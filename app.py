import os
import logging
import threading
from datetime import datetime, timedelta
# pyrefly: ignore [missing-import]
from flask import Flask, jsonify, render_template, request
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

import weather
import ai_helper

# 載入環境變數
load_dotenv()

# 設定 Flask
app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

# 設定日誌
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/weather.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("app_commander")

# 台灣 22 縣市清單 (對齊中央氣象署命名，皆使用「臺」字)
TAIWAN_COUNTIES = [
    "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市",
    "基隆市", "新竹市", "新竹縣", "苗栗縣", "彰化縣", "南投縣",
    "雲林縣", "嘉義市", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣",
    "臺東縣", "澎湖縣", "金門縣", "連江縣"
]

# 背景同步錦標：避免多個請求同時觸發重複同步
_sync_lock = threading.Lock()
_sync_in_progress = False


def _run_sync_in_background(cwa_key=None):
    """在独立執行緒執行資料同步，避免陰塞 Flask 請求"""
    global _sync_in_progress
    with _sync_lock:
        if _sync_in_progress:
            return  # 已有同步在執行中，跳過
        _sync_in_progress = True
    try:
        weather.sync_weather_data(cwa_key=cwa_key)
    except Exception as e:
        logger.error(f"背景同步發生未預期錯誤: {e}")
    finally:
        _sync_in_progress = False


def check_and_auto_sync(location_name, cwa_key=None):
    """
    自動同步檢查：
    - 資料庫全無資料 → 同步執行（首次啟動必要）
    - 資料過期（超過 1 小時）→ 啟動背景執行緒，立即返回現有快取資料（零延遲）
    - 資料仍有效 → 直接返回快取
    """
    forecasts = weather.get_forecasts(location_name)

    if not forecasts:
        # 首次入站：資料庫為空，必須同步等待（第一次載入）
        logger.info(f"資料庫中無 {location_name} 的氣象資料，將同步執行內容。")
        weather.sync_weather_data(cwa_key=cwa_key)
        forecasts = weather.get_forecasts(location_name)
    else:
        # 檢查資料新鮮度
        last_updated_str = forecasts[0]["updated_at"]
        try:
            last_updated = datetime.strptime(last_updated_str, "%Y-%m-%d %H:%M:%S")
            if datetime.now() - last_updated > timedelta(hours=1):
                # 資料過期：啟動背景同步，不造成請求阻塞
                logger.info(
                    f"{location_name} 資料過期（{last_updated_str}），已在背景啟動同步任務。"
                )
                thread = threading.Thread(target=_run_sync_in_background, args=(cwa_key,), daemon=True)
                thread.start()
        except ValueError:
            # 時間格式異常：同樣背景更新
            thread = threading.Thread(target=_run_sync_in_background, args=(cwa_key,), daemon=True)
            thread.start()

    return forecasts

@app.route("/")
def index():
    """渲染天氣儀表板首頁"""
    return render_template("index.html")

@app.route("/api/counties", methods=["GET"])
def get_counties():
    """取得台灣縣市清單"""
    return jsonify({
        "success": True,
        "counties": TAIWAN_COUNTIES
    })

@app.route("/api/weather", methods=["GET"])
def get_weather():
    """
    取得特定縣市的天氣預報。
    參數: ?location=臺北市
    """
    location = request.args.get("location", "臺北市")
    
    if location not in TAIWAN_COUNTIES:
        return jsonify({
            "success": False,
            "message": f"無效的縣市名稱。可接受範圍為：{', '.join(TAIWAN_COUNTIES)}"
        }), 400
        
    try:
        # 自動同步或查詢
        use_custom_cwa = request.args.get("use_custom_cwa", "false").lower() == "true"
        cwa_key = request.args.get("cwa_key", "").strip() if use_custom_cwa else None
        forecasts = check_and_auto_sync(location, cwa_key=cwa_key)
        
        if not forecasts:
            return jsonify({
                "success": False,
                "message": "無法取得氣象資料，請檢查 API 金鑰設定或網路連線。"
            }), 500
            
        updated_at = forecasts[0]["updated_at"]
        
        return jsonify({
            "success": True,
            "location": location,
            "updated_at": updated_at,
            "forecasts": forecasts,
            "is_syncing": _sync_in_progress
        })
        
    except Exception as e:
        logger.error(f"取得天氣 API 發生錯誤: {e}")
        return jsonify({
            "success": False,
            "message": f"伺服器錯誤: {str(e)}"
        }), 500

@app.route("/api/ai_advice", methods=["GET"])
def get_ai_advice():
    """
    取得該縣市的 AI 生活建議。
    參數: ?location=臺北市&force_refresh=true&type=36h (或 weekly)
    """
    location = request.args.get("location", "臺北市")
    force_refresh = request.args.get("force_refresh", "false").lower() == "true"
    advice_type = request.args.get("type", "36h").lower()
    
    if location not in TAIWAN_COUNTIES:
        return jsonify({
            "success": False,
            "message": "無效的縣市名稱。"
        }), 400
        
    try:
        # 取得自訂氣象局金鑰並同步 (確保資料庫有資料)
        use_custom_cwa = request.args.get("use_custom_cwa", "false").lower() == "true"
        cwa_key = request.args.get("cwa_key", "").strip() if use_custom_cwa else None
        check_and_auto_sync(location, cwa_key=cwa_key)
        
        # 取得自訂 AI 參數
        use_custom = request.args.get("use_custom", "false").lower() == "true"
        custom_key = request.args.get("api_key", "").strip()
        
        # 自動判別端點
        custom_provider = "Opencode"
        if custom_key.startswith("AIzaSy"):
            custom_provider = "Gemini"
        elif custom_key.startswith("sk-"):
            custom_provider = "Codex"
        
        cache_key = location
        if advice_type == "weekly":
            cache_key = f"{location}_weekly"
            
        # 若強制更新且未使用自訂 AI API，清除資料庫中的 AI 快取紀錄
        if force_refresh and not use_custom:
            logger.info(f"使用者強制更新 {location} 的 AI 建議快取 ({advice_type})。")
            conn = weather.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ai_summaries WHERE location_name = ?", (cache_key,))
            conn.commit()
            conn.close()
            
        if advice_type == "weekly":
            weekly_forecasts = weather.get_weekly_forecasts(location)
            advice = ai_helper.generate_weekly_weather_advice(
                location, 
                weekly_forecasts, 
                use_custom=use_custom, 
                provider=custom_provider, 
                api_key=custom_key
            )
        else:
            forecasts = weather.get_forecasts(location)
            advice = ai_helper.generate_weather_advice(
                location, 
                forecasts, 
                use_custom=use_custom, 
                provider=custom_provider, 
                api_key=custom_key
            )
        
        return jsonify({
            "success": True,
            "location": location,
            "advice": advice
        })
        
    except Exception as e:
        logger.error(f"取得 AI 建議 API 發生錯誤: {e}")
        return jsonify({
            "success": False,
            "message": f"伺服器錯誤: {str(e)}"
        }), 500

@app.route("/api/weekly_weather", methods=["GET"])
def get_weekly_weather():
    """
    取得特定縣市的一週天氣預報。
    參數: ?location=臺北市
    """
    location = request.args.get("location", "臺北市")
    
    if location not in TAIWAN_COUNTIES:
        return jsonify({
            "success": False,
            "message": "無效的縣市名稱。"
        }), 400
        
    try:
        # 自動同步或查詢
        use_custom_cwa = request.args.get("use_custom_cwa", "false").lower() == "true"
        cwa_key = request.args.get("cwa_key", "").strip() if use_custom_cwa else None
        check_and_auto_sync(location, cwa_key=cwa_key)
        weekly_forecasts = weather.get_weekly_forecasts(location)
        
        if not weekly_forecasts:
            return jsonify({
                "success": False,
                "message": "無法取得一週預報資料。"
            }), 500
            
        updated_at = weekly_forecasts[0]["updated_at"]
        
        return jsonify({
            "success": True,
            "location": location,
            "updated_at": updated_at,
            "forecasts": weekly_forecasts,
            "is_syncing": _sync_in_progress
        })
        
    except Exception as e:
        logger.error(f"取得一週天氣 API 發生錯誤: {e}")
        return jsonify({
            "success": False,
            "message": f"伺服器錯誤: {str(e)}"
        }), 500


@app.route("/api/sync", methods=["POST"])
def manual_sync():
    """手動同步中央氣象署資料"""
    cwa_key = None
    use_custom_cwa = request.args.get("use_custom_cwa", "false").lower() == "true"
    cwa_key = request.args.get("cwa_key", "").strip() if use_custom_cwa else None
    
    if not cwa_key and request.is_json:
        req_data = request.json or {}
        if req_data.get("use_custom_cwa"):
            cwa_key = req_data.get("cwa_key", "").strip()
            
    try:
        success = weather.sync_weather_data(cwa_key=cwa_key)
        if success:
            return jsonify({
                "success": True,
                "message": "所有縣市天氣資料已成功同步更新！"
            })
        else:
            return jsonify({
                "success": False,
                "message": "資料同步失敗，請檢查日誌以獲取更多資訊。"
            }), 500
    except Exception as e:
        logger.error(f"手動同步發生錯誤: {e}")
        return jsonify({
            "success": False,
            "message": f"伺服器錯誤: {str(e)}"
        }), 500

# 啟動時自動初始化資料庫並自動背景同步
with app.app_context():
    try:
        weather.init_db()
        logger.info("應用程式啟動：資料庫檢查與初始化成功。")
        # 背景非阻塞式進行首次全縣市同步，避免主執行緒阻塞
        thread = threading.Thread(target=_run_sync_in_background, args=(None,), daemon=True)
        thread.start()
        logger.info("已於背景啟動首次全縣市天氣同步任務。")
    except Exception as e:
        logger.critical(f"應用程式啟動時初始化或同步失敗: {e}")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "True").lower() == "true"
    logger.info(f"正在啟動 Flask 天氣伺服器，Port: {port}, Debug: {debug}")
    app.run(host="0.0.0.0", port=port, debug=debug)
