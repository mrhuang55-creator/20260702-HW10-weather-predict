import os
import sqlite3
import logging
import argparse
import urllib3
import requests
from datetime import datetime
from dotenv import load_dotenv

# ── 環境變數優先讀取順序 ──────────────────────────────────
# 1. env.private（本機私有設定，含真實 API Key，已加入 .gitignore，不上傳）
# 2. .env（公開範本，佔位符，可安全上傳 GitHub）
_private_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), "env.private")
if os.path.exists(_private_env):
    _backup_port = os.getenv("PORT")
    load_dotenv(_private_env, override=True)
    if _backup_port:
        os.environ["PORT"] = _backup_port
else:
    load_dotenv()  # fallback 到 .env

# SSL 驗證開關：開發環境可設 DISABLE_SSL_VERIFY=true 繞過 Windows 本地憑證問題
# 正式部署應設為 false（預設即 false，僅限明確啟用才停用驗證）
_DISABLE_SSL = os.getenv("DISABLE_SSL_VERIFY", "false").lower() == "true"
if _DISABLE_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    logging.getLogger("weather_module").warning(
        "SSL 驗證已停用（DISABLE_SSL_VERIFY=true）。請勿在正式環境使用此設定！"
    )

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
logger = logging.getLogger("weather_module")

DB_FILE = "weather.db"
CWA_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001"
CWA_WEEKLY_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-091"

def get_db_connection():
    """建立資料庫連線"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化 SQLite 資料庫表"""
    logger.info("正在初始化資料庫...")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 建立天氣預報表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS weather_forecasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            location_name TEXT,
            start_time TEXT,
            end_time TEXT,
            wx_desc TEXT,
            wx_value TEXT,
            pop INTEGER,
            min_t INTEGER,
            max_t INTEGER,
            ci TEXT,
            updated_at TEXT
        )
    """)
    
    # 檢查 weekly_forecasts 表是否已存在且包含新欄位
    cursor.execute("PRAGMA table_info(weekly_forecasts)")
    columns = [row[1] for row in cursor.fetchall()]
    if columns and "pop" not in columns:
        logger.info("檢測到舊版 weekly_forecasts 表，正在升級表格結構...")
        cursor.execute("DROP TABLE weekly_forecasts")
        
    # 建立一週天氣預報表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS weekly_forecasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            location_name TEXT,
            start_time TEXT,
            end_time TEXT,
            wx_desc TEXT,
            wx_value TEXT,
            min_t INTEGER,
            max_t INTEGER,
            pop INTEGER,
            uv_index TEXT,
            ci TEXT,
            wind TEXT,
            updated_at TEXT
        )
    """)
    
    # 建立 AI 建議快取表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_summaries (
            location_name TEXT PRIMARY KEY,
            summary_text TEXT,
            generated_at TEXT
        )
    """)
    
    conn.commit()
    conn.close()
    logger.info("資料庫初始化完成！")

def sync_weekly_data_internal(cursor, api_key, updated_at):
    """內部輔助函式：同步一週天氣預報 (使用 F-D0047-091)"""
    params = {
        "Authorization": api_key,
        "format": "JSON"
    }
    logger.info("開始從中央氣象署 API 同步一週天氣資料...")
    try:
        response = requests.get(CWA_WEEKLY_URL, params=params, timeout=15, verify=not _DISABLE_SSL)
        response.raise_for_status()
        data = response.json()
        
        if not data.get("success") == "true":
            logger.error("CWA 一週天氣 API 回傳成功標記為 false")
            return False
            
        locations_list = data.get("records", {}).get("Locations", [])
        if not locations_list:
            logger.warning("未取得任何一週天氣 records.Locations 資料")
            return False
            
        location_arr = locations_list[0].get("Location", [])
        if not location_arr:
            logger.warning("未取得任何一週天氣 records.Locations[0].Location 資料")
            return False
            
        for loc in location_arr:
            location_name = loc.get("LocationName")
            if location_name:
                location_name = location_name.replace("台", "臺")
                
            weather_elements = loc.get("WeatherElement", [])
            elements = {el.get("ElementName"): el.get("Time", []) for el in weather_elements}
            
            times_count = len(elements.get("天氣現象", []))
            if times_count == 0:
                continue
                
            # 清除舊的一週預報
            cursor.execute("DELETE FROM weekly_forecasts WHERE location_name = ?", (location_name,))
            
            for i in range(times_count):
                try:
                    time_item_wx = elements["天氣現象"][i]
                    start_time = time_item_wx.get("StartTime")
                    end_time = time_item_wx.get("EndTime")
                    
                    if start_time and "T" in start_time:
                        start_time = start_time.replace("T", " ").split("+")[0]
                    if end_time and "T" in end_time:
                        end_time = end_time.replace("T", " ").split("+")[0]
                    
                    wx_desc = ""
                    wx_value = ""
                    wx_vals = time_item_wx.get("ElementValue", [])
                    if wx_vals:
                        wx_desc = wx_vals[0].get("Weather", "")
                        wx_value = wx_vals[0].get("WeatherCode", "")
                    
                    min_t_val = "0"
                    min_t_vals = elements.get("最低溫度", [{}])[i].get("ElementValue", [])
                    if min_t_vals:
                        min_t_val = min_t_vals[0].get("MinTemperature", "0")
                    min_t = int(min_t_val) if min_t_val.replace("-", "").isdigit() else 0
                    
                    max_t_val = "0"
                    max_t_vals = elements.get("最高溫度", [{}])[i].get("ElementValue", [])
                    if max_t_vals:
                        max_t_val = max_t_vals[0].get("MaxTemperature", "0")
                    max_t = int(max_t_val) if max_t_val.replace("-", "").isdigit() else 0
                    
                    # 12小時降雨機率 (14個時段對應)
                    pop = 0
                    if "12小時降雨機率" in elements and i < len(elements["12小時降雨機率"]):
                        pop_vals = elements["12小時降雨機率"][i].get("ElementValue", [])
                        if pop_vals:
                            pop_str = pop_vals[0].get("ProbabilityOfPrecipitation", "0")
                            pop = int(pop_str) if pop_str.isdigit() else 0
                            
                    # 體感舒適度 CI (14個時段對應)
                    ci = ""
                    if "最大舒適度指數" in elements and i < len(elements["最大舒適度指數"]):
                        ci_vals = elements["最大舒適度指數"][i].get("ElementValue", [])
                        if ci_vals:
                            ci = ci_vals[0].get("MaxComfortIndexDescription", "")
                            
                    # 紫外線指數 (僅白天，需以 StartTime 比對)
                    uv_index = "-"
                    uv_times = elements.get("紫外線指數", [])
                    for uv_time in uv_times:
                        if uv_time.get("StartTime") == time_item_wx.get("StartTime"):
                            uv_vals = uv_time.get("ElementValue", [])
                            if uv_vals:
                                uv_val = uv_vals[0].get("UVIndex", "-")
                                uv_desc = uv_vals[0].get("UVExposureLevel", "")
                                uv_index = f"{uv_val} ({uv_desc})" if uv_desc else uv_val
                            break
                            
                    # 風力與風向
                    wind_dir = ""
                    if "風向" in elements and i < len(elements["風向"]):
                        wd_vals = elements["風向"][i].get("ElementValue", [])
                        if wd_vals:
                            wind_dir = wd_vals[0].get("WindDirection", "")
                            
                    wind_speed = ""
                    beaufort_scale = ""
                    if "風速" in elements and i < len(elements["風速"]):
                        ws_vals = elements["風速"][i].get("ElementValue", [])
                        if ws_vals:
                            wind_speed = ws_vals[0].get("WindSpeed", "")
                            beaufort_scale = ws_vals[0].get("BeaufortScale", "")
                            
                    if wind_dir or wind_speed:
                        parts = []
                        if wind_dir:
                            parts.append(wind_dir)
                        if wind_speed:
                            parts.append(f"{wind_speed} m/s")
                        if beaufort_scale:
                            parts.append(f"(風力 {beaufort_scale} 級)")
                        wind = " ".join(parts)
                    else:
                        wind = "-"
                    
                    cursor.execute("""
                        INSERT INTO weekly_forecasts (
                            location_name, start_time, end_time, wx_desc, wx_value, min_t, max_t, pop, uv_index, ci, wind, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (location_name, start_time, end_time, wx_desc, wx_value, min_t, max_t, pop, uv_index, ci, wind, updated_at))
                    
                except (IndexError, KeyError) as e:
                    logger.warning(f"解析縣市 {location_name} 一週預報的第 {i} 個時段資料時出錯: {e}")
                    
        logger.info("一週天氣資料同步成功！")
        return True
    except Exception as e:
        logger.error(f"與 CWA 一週天氣 API 同步時發生錯誤: {e}")
        return False

def sync_weather_data(cwa_key=None):
    """從中央氣象署 API 同步天氣資料至 SQLite"""
    api_key = cwa_key or os.getenv("CWA_API_KEY")
    if not api_key:
        logger.error("未找到 CWA_API_KEY，同步失敗！")
        return False
        
    # 清洗可能帶有變數名稱的前綴（例如 "CWA_API_KEY=CWA-xxx" -> "CWA-xxx"）
    api_key = api_key.strip()
    if "=" in api_key:
        parts = api_key.split("=", 1)
        if parts[0].strip().upper() in ["CWA_API_KEY", "CWA_TOKEN"]:
            api_key = parts[1].strip()
        
    logger.info("開始從中央氣象署 API 同步天氣資料...")
    params = {
        "Authorization": api_key,
        "format": "JSON"
    }
    
    conn = None
    try:
        response = requests.get(CWA_API_URL, params=params, timeout=15, verify=not _DISABLE_SSL)
        response.raise_for_status()
        data = response.json()
        
        if not data.get("success") == "true":
            logger.error("CWA API 回傳成功標記為 false")
            return False
            
        locations = data.get("records", {}).get("location", [])
        if not locations:
            logger.warning("未取得任何縣市天氣資料")
            return False
            
        conn = get_db_connection()
        cursor = conn.cursor()
        updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        for loc in locations:
            location_name = loc.get("locationName")
            weather_elements = loc.get("weatherElement", [])
            
            # 將 element 轉為字典以便提取
            elements = {el.get("elementName"): el.get("time", []) for el in weather_elements}
            
            # 取得時間段數量，通常是3個 (今明36小時)
            times_count = len(elements.get("Wx", []))
            if times_count == 0:
                continue
                
            # 同步前先清除該地區的舊預報
            cursor.execute("DELETE FROM weather_forecasts WHERE location_name = ?", (location_name,))
            
            for i in range(times_count):
                try:
                    start_time = elements["Wx"][i].get("startTime")
                    end_time = elements["Wx"][i].get("endTime")
                    
                    wx_desc = elements["Wx"][i].get("parameter", {}).get("parameterName", "")
                    wx_value = elements["Wx"][i].get("parameter", {}).get("parameterValue", "")
                    
                    pop_val = elements.get("PoP", [{}])[i].get("parameter", {}).get("parameterName", "0")
                    pop = int(pop_val) if pop_val.isdigit() else 0
                    
                    min_t_val = elements.get("MinT", [{}])[i].get("parameter", {}).get("parameterName", "0")
                    min_t = int(min_t_val) if min_t_val.isdigit() else 0
                    
                    max_t_val = elements.get("MaxT", [{}])[i].get("parameter", {}).get("parameterName", "0")
                    max_t = int(max_t_val) if max_t_val.isdigit() else 0
                    
                    ci = elements.get("CI", [{}])[i].get("parameter", {}).get("parameterName", "")
                    
                    cursor.execute("""
                        INSERT INTO weather_forecasts (
                            location_name, start_time, end_time, wx_desc, wx_value, pop, min_t, max_t, ci, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (location_name, start_time, end_time, wx_desc, wx_value, pop, min_t, max_t, ci, updated_at))
                    
                except (IndexError, KeyError) as e:
                    logger.warning(f"解析縣市 {location_name} 的第 {i} 個時段資料時出錯: {e}")
                    
        # 2. 同步一週天氣預報資料
        sync_weekly_data_internal(cursor, api_key, updated_at)
        
        conn.commit()
        logger.info(f"天氣與一週預報資料同步成功！共更新 {len(locations)} 個縣市。")
        return True
    except Exception as e:
        logger.error(f"與 CWA API 同步時發生錯誤: {e}")
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return False
    finally:
        if conn:
            conn.close()

def get_forecasts(location_name):
    """查詢指定縣市的天氣預報"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM weather_forecasts 
        WHERE location_name = ? 
        ORDER BY start_time ASC
    """, (location_name,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_weekly_forecasts(location_name):
    """查詢指定縣市的一週天氣預報"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM weekly_forecasts 
        WHERE location_name = ? 
        ORDER BY start_time ASC
    """, (location_name,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def save_ai_summary(location_name, summary_text):
    """儲存 AI 建議到快取"""
    conn = get_db_connection()
    cursor = conn.cursor()
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT OR REPLACE INTO ai_summaries (location_name, summary_text, generated_at)
        VALUES (?, ?, ?)
    """, (location_name, summary_text, generated_at))
    conn.commit()
    conn.close()

def get_ai_summary(location_name):
    """取得快取的 AI 建議"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ai_summaries WHERE location_name = ?", (location_name,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="氣象資料獲取與資料庫模組")
    parser.add_argument("--init-db", "--init.db", action="store_true", help="初始化 SQLite 資料庫")
    parser.add_argument("--sync", action="store_true", help="自中央氣象署 API 同步資料")
    args = parser.parse_args()
    
    # 預設如果資料庫檔案不存在，自動初始化
    if not os.path.exists(DB_FILE) or args.init_db:
        init_db()
        
    if args.sync:
        sync_weather_data()
