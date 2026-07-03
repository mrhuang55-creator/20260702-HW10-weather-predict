import os
import logging
from datetime import datetime
# pyrefly: ignore [missing-import]
from openai import OpenAI
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
import weather  # 導入 weather.py 用於快取

load_dotenv()
logger = logging.getLogger("weather_module.ai")
_DISABLE_SSL = os.getenv("DISABLE_SSL_VERIFY", "false").lower() == "true"

def _get_openai_client(api_key, base_url=None):
    import httpx
    from openai import OpenAI
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    if _DISABLE_SSL:
        kwargs["http_client"] = httpx.Client(verify=False)
    return OpenAI(**kwargs)

def call_custom_api(provider, api_key, prompt, system_instruction):
    """
    自訂 API 呼叫的中央調度函式
    """
    import requests
    if provider == "Gemini":
        # 修正端點為 Gemini 3.5: gemini-3.5-flash
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 800
            }
        }
        response = requests.post(url, headers=headers, json=payload, timeout=15, verify=not _DISABLE_SSL)
        response.raise_for_status()
        res_data = response.json()
        return res_data['candidates'][0]['content']['parts'][0]['text']
    elif provider == "Codex":
        # 使用 OpenAI 客戶端連線，預設對接 gpt-4o-mini 或代碼模型
        client = _get_openai_client(api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=800
        )
        return response.choices[0].message.content.strip()
    elif provider == "Opencode":
        # 連接 Opencode 自訂相容端點
        client = _get_openai_client(api_key, base_url="https://api.opencode.ai/v1")
        response = client.chat.completions.create(
            model="opencode-model",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=800
        )
        if isinstance(response, str):
            return response.strip()
        elif isinstance(response, dict):
            try:
                return response['choices'][0]['message']['content'].strip()
            except (KeyError, TypeError):
                return str(response)
        else:
            return response.choices[0].message.content.strip()
    else:
        raise ValueError(f"不支援的 API 服務商: {provider}")


def generate_weather_advice(location_name, forecasts, use_custom=False, provider="Gemini", api_key=""):
    """
    根據氣象預報資料，生成 AI 生活天氣建議。
    如果未設定 OpenAI API Key，將自動降級為規則式生成，並提示使用者。
    """
    if use_custom:
        if not api_key:
            return "⚠️ 已啟用自訂 AI 設定，但未輸入對應的 API 金鑰！"
        logger.info(f"使用自訂 AI 服務商 ({provider}) 生成 {location_name} 的建議...")
        try:
            # 建立預報詳細資料字串
            forecast_details = []
            for f in forecasts:
                forecast_details.append({
                    "時間段": f"{f['start_time']} 至 {f['end_time']}",
                    "天氣現象": f["wx_desc"],
                    "氣溫區間": f"{f['min_t']}°C - {f['max_t']}°C",
                    "降雨機率": f"{f['pop']}%",
                    "舒適度": f["ci"]
                })
            system_instruction = "你是一位親切、幽默且專業的台灣氣象主播，善於給予細緻的生活關懷建議。"
            prompt = f"請針對「{location_name}」未來 36 小時的天氣預報資料提供一份精美的生活氣象分析。預報資料如下：\n{forecast_details}\n請以 Markdown 格式撰寫，內容必須包含今日與明日天氣概況、穿衣與雨具穿搭指南、戶外活動與出行建議、貼心小叮嚀。"
            return call_custom_api(provider, api_key, prompt, system_instruction)
        except Exception as e:
            logger.error(f"自訂 API ({provider}) 呼叫失敗: {e}")
            return f"❌ 自訂 AI ({provider}) 連線失敗：{str(e)}"

    # 檢查是否有快取，且比對快取生成時間與天氣資料更新時間
    cached = weather.get_ai_summary(location_name)
    if cached and forecasts:
        latest_weather_update = forecasts[0].get("updated_at")
        cache_gen_time = cached.get("generated_at")
        if latest_weather_update and cache_gen_time:
            try:
                dt_weather = datetime.strptime(latest_weather_update, "%Y-%m-%d %H:%M:%S")
                dt_cache = datetime.strptime(cache_gen_time, "%Y-%m-%d %H:%M:%S")
                if dt_cache >= dt_weather:
                    logger.info(f"從快取中讀取 {location_name} 的 AI 建議（快取時間：{cache_gen_time}，天氣更新時間：{latest_weather_update}）。")
                    return cached["summary_text"]
                else:
                    logger.info(f"{location_name} 的 AI 建議已過期（快取時間：{cache_gen_time} < 天氣更新時間：{latest_weather_update}），將重新生成。")
            except Exception as e:
                logger.error(f"比對快取時間與天氣更新時間時發生錯誤: {e}")
                # 發生錯誤時，保險起見使用快取
                return cached["summary_text"]

    api_key = os.getenv("OPENAI_API_KEY")
    
    # 判斷是否為無效的 API Key 占位符
    is_key_invalid = not api_key or api_key == "your_openai_api_key_here" or api_key.strip() == ""
    
    if is_key_invalid:
        logger.warning("未偵測到有效的 OPENAI_API_KEY，將啟用系統規則生成模擬建議。")
        advice = generate_mock_advice(location_name, forecasts)
        # 儲存模擬建議到資料庫，避免重複警示
        weather.save_ai_summary(location_name, advice)
        return advice

    # 組合預報資訊給 OpenAI
    forecast_details = []
    for f in forecasts:
        forecast_details.append({
            "時間段": f"{f['start_time']} 至 {f['end_time']}",
            "天氣現象": f["wx_desc"],
            "氣溫區間": f"{f['min_t']}°C - {f['max_t']}°C",
            "降雨機率": f"{f['pop']}%",
            "舒適度": f["ci"]
        })

    prompt = f"""
你是一位貼心且專業的台灣氣象主播。請針對「{location_name}」未來 36 小時的天氣預報資料，提供一份精美、溫馨且實用的生活氣象分析。

天氣預報資料如下：
{forecast_details}

請以 Markdown 格式撰寫，內容必須包含以下幾點：
1. **今日與明日天氣概況**：用親切的口吻總結這 36 小時的天氣變化趨勢。
2. **穿衣與雨具穿搭指南**：根據溫度高低與降雨機率，建議民眾如何穿衣（如洋蔥式穿法、防風外套）及是否需要攜帶雨具。
3. **戶外活動與出行建議**：評估是否適合戶外運動、洗車、曬衣，或是有哪些交通安全注意事項（如大雨路滑、山區防坍方）。
4. **貼心小叮嚀**：簡短而溫馨的關懷話語。

注意事項：
- 請適度使用豐富的表情符號（如 ☀️, 🌧️, 🌡️, 🧥, 🚗）讓排版更為生動活潑。
- 使用繁體中文回答。
"""

    try:
        # 使用最新的 OpenAI SDK 初始化
        client = _get_openai_client(api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "你是一位親切、幽默且專業的台灣氣象主播，善於給予細緻的生活關懷建議。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=800
        )
        
        advice = response.choices[0].message.content.strip()
        # 存入快取
        weather.save_ai_summary(location_name, advice)
        logger.info(f"成功為 {location_name} 生成 OpenAI 天氣建議。")
        return advice

    except Exception as e:
        logger.error(f"呼叫 OpenAI API 發生錯誤: {e}，將降級使用規則式生成模擬建議。")
        advice = generate_mock_advice(location_name, forecasts, error_msg=str(e))
        weather.save_ai_summary(location_name, advice)
        return advice

def generate_mock_advice(location_name, forecasts, error_msg=None):
    """當 API Key 缺失或呼叫出錯時，藉由氣象邏輯產生在地化天氣建議"""
    if not forecasts:
        return "⚠️ 目前無該縣市的天氣預報資料，無法生成建議。"
        
    # 分析預報數值
    max_pop = max(f["pop"] for f in forecasts)
    min_temp = min(f["min_t"] for f in forecasts)
    max_temp = max(f["max_t"] for f in forecasts)
    primary_wx = forecasts[0]["wx_desc"]
    
    # 建立 Markdown 內容
    lines = []
    lines.append(f"### 🤖 智慧生活天氣建議 ({location_name})")
    
    if error_msg:
        lines.append(f"> ⚠️ **系統提示：** 呼叫 OpenAI API 時發生錯誤 (`{error_msg[:60]}`)。以下為系統分析規則產生的天氣建議。")
    else:
        lines.append("> 💡 **系統提示：** 偵測到尚未在 `.env` 中設定有效的 `OPENAI_API_KEY`。此建議由系統內建規則引擎生成，若想體驗更聰明的智慧對話，請在 `.env` 填入您的 OpenAI Key。")
        
    lines.append("")
    lines.append(f"#### 🌡️ 天氣概況摘要")
    lines.append(f"- 目前 **{location_name}** 最新的天氣現象為「**{primary_wx}**」。")
    lines.append(f"- 未來 36 小時預估氣溫區間在 **{min_temp}°C 至 {max_temp}°C** 之間。")
    lines.append(f"- 整體降雨機率最高來到 **{max_pop}%**，出門請隨時留意天空變化。")
    lines.append("")
    
    lines.append("#### 🧥 穿衣與雨具指南")
    # 降雨建議
    if max_pop >= 70:
        lines.append("- 🌧️ **雨具必備：** 降雨機率極高，出門請務必攜帶折疊傘或雨衣，建議穿著防水或易乾的鞋襪。")
    elif max_pop >= 30:
        lines.append("- 🌂 **雨具備用：** 有局部短暫陣雨的機會，出門建議在包包中放把備用傘以防萬一。")
    else:
        lines.append("- ☀️ **晴空朗朗：** 降雨機率低，不需攜帶雨具，非常適合戶外曬衣服！")
        
    # 溫度建議
    if min_temp < 15:
        lines.append("- ❄️ **防寒保暖：** 氣溫偏低，體感較冷，出門請務必穿著厚大衣、發熱衣，並注意頭部與四肢的保暖。")
    elif min_temp < 20:
        lines.append("- 🧥 **涼意提醒：** 早晚體感稍有寒意，建議採用洋蔥式穿法，內穿短袖或薄長袖，外搭一件防風外套。")
    elif max_temp > 30:
        lines.append("- 👕 **清爽排汗：** 天氣炎熱，建議穿著寬鬆、透氣排汗的短袖衣物，並注意防曬。")
    else:
        lines.append("- 👌 **舒適穿搭：** 溫度適中，穿著一般長袖襯衫或薄帽 T 即可，十分舒適。")
        
    lines.append("")
    lines.append("#### 🏃 戶外活動與出行建議")
    if max_pop >= 50:
        lines.append("- 🏠 **建議室內活動：** 降雨機率偏高，戶外運動（如慢跑、打球）可能會受阻，建議改在室內進行健身或休閒活動。")
        lines.append("- 🚗 **行車安全：** 下雨易導致視線不佳與路面濕滑，駕駛汽機車請減速慢行，注意保持安全距離。")
    else:
        lines.append("- 🌳 **適合戶外運動：** 天氣狀況良好，非常適合到公園散步、慢跑或安排單車郊遊！")
        lines.append("- 🚗 **洗車好時機：** 天氣晴朗穩定，是動手清洗愛車、整理家務的好日子。")
        
    lines.append("")
    lines.append("#### 💙 貼心小叮嚀")
    if max_temp - min_temp >= 8:
        lines.append(f"- ⚠️ **日夜溫差大：** 溫差達 {max_temp - min_temp}°C，早出晚歸的朋友一定要多帶件衣物，避免感冒喔！")
    else:
        lines.append("- 😊 天氣多變化，隨時關注最新氣象資訊，保持愉快的心情迎接每一天！")
        
    return "\n".join(lines)

def generate_weekly_weather_advice(location_name, weekly_forecasts, use_custom=False, provider="Gemini", api_key=""):
    """
    根據一週天氣預報資料，生成 AI 生活天氣週報建議。
    如果未設定 OpenAI API Key，將自動降級為規則式生成，並提示使用者。
    """
    if use_custom:
        if not api_key:
            return "⚠️ 已啟用自訂 AI 設定，但未輸入對應的 API 金鑰！"
        logger.info(f"使用自訂 AI 服務商 ({provider}) 生成 {location_name} 的一週建議...")
        try:
            forecast_details = []
            for f in weekly_forecasts:
                forecast_details.append({
                    "時間段": f"{f['start_time']} 至 {f['end_time']}",
                    "天氣現象": f["wx_desc"],
                    "氣溫區間": f"{f['min_t']}°C - {f['max_t']}°C",
                    "降雨機率": f"{f.get('pop', 0)}%",
                    "紫外線指數": f.get('uv_index', '-'),
                    "體感舒適度": f.get('ci', '-'),
                    "風力風向": f.get('wind', '-')
                })
            system_instruction = "你是一位親切、幽默且專業的台灣氣象主播，善於給予細緻的生活關懷建議。"
            prompt = f"請針對「{location_name}」未來一週的天氣預報資料提供一份精美的生活氣象週報分析。預報資料如下：\n{forecast_details}\n請以 Markdown 格式撰寫，內容必須包含未來一週天氣走勢分析、本週戶外/家務建議、週末出行規劃提示、本週貼心叮嚀。"
            return call_custom_api(provider, api_key, prompt, system_instruction)
        except Exception as e:
            logger.error(f"自訂 API ({provider}) 呼叫失敗: {e}")
            return f"❌ 自訂 AI ({provider}) 連線失敗：{str(e)}"

    cache_key = f"{location_name}_weekly"
    cached = weather.get_ai_summary(cache_key)
    if cached and weekly_forecasts:
        latest_weather_update = weekly_forecasts[0].get("updated_at")
        cache_gen_time = cached.get("generated_at")
        if latest_weather_update and cache_gen_time:
            try:
                dt_weather = datetime.strptime(latest_weather_update, "%Y-%m-%d %H:%M:%S")
                dt_cache = datetime.strptime(cache_gen_time, "%Y-%m-%d %H:%M:%S")
                if dt_cache >= dt_weather:
                    logger.info(f"從快取中讀取 {location_name} 的 AI 週報建議（快取時間：{cache_gen_time}，天氣更新時間：{latest_weather_update}）。")
                    return cached["summary_text"]
                else:
                    logger.info(f"{location_name} 的 AI 週報建議已過期（快取時間：{cache_gen_time} < 天氣更新時間：{latest_weather_update}），將重新生成。")
            except Exception as e:
                logger.error(f"比對快取時間與天氣更新時間時發生錯誤: {e}")
                return cached["summary_text"]

    api_key = os.getenv("OPENAI_API_KEY")
    is_key_invalid = not api_key or api_key == "your_openai_api_key_here" or api_key.strip() == ""
    
    if is_key_invalid:
        logger.warning("未偵測到有效的 OPENAI_API_KEY，將啟用系統規則生成模擬週報建議。")
        advice = generate_mock_weekly_advice(location_name, weekly_forecasts)
        weather.save_ai_summary(cache_key, advice)
        return advice

    # 組合一週預報資訊給 OpenAI
    forecast_details = []
    for f in weekly_forecasts:
        forecast_details.append({
            "時間段": f"{f['start_time']} 至 {f['end_time']}",
            "天氣現象": f["wx_desc"],
            "氣溫區間": f"{f['min_t']}°C - {f['max_t']}°C",
            "降雨機率": f"{f.get('pop', 0)}%",
            "紫外線指數": f.get('uv_index', '-'),
            "體感舒適度": f.get('ci', '-'),
            "風力風向": f.get('wind', '-')
        })

    prompt = f"""
你是一位貼心且專業的台灣氣象主播。請針對「{location_name}」未來一週的天氣預報資料，提供一份精美、溫馨且實用的生活氣象週報分析。

一週天氣預報資料如下：
{forecast_details}

請以 Markdown 格式撰寫，內容必須包含以下幾點：
1. **未來一週天氣走勢分析**：用溫暖貼心的口吻描述這星期的氣溫升降、降雨趨勢與天氣變化特徵。
2. **本週戶外/家務建議**：如哪幾天適合曬衣服、洗車、戶外運動，或哪幾天建議安排室內行程。
3. **週末出行規劃提示**：特別針對即將到來的週末給予旅遊或外出的穿搭與防範指南。
4. **本週貼心叮嚀**：結合天氣特徵給予健康或生活上的溫馨小關懷。

注意事項：
- 請適度使用豐富的表情符號（如 ☀️, 🌧️, 🌡️, 🧥, 🚗）。
- 使用繁體中文回答。
"""

    try:
        client = _get_openai_client(api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "你是一位親切、幽默且專業的台灣氣象主播，善於給予細緻的生活關懷建議。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=800
        )
        
        advice = response.choices[0].message.content.strip()
        weather.save_ai_summary(cache_key, advice)
        logger.info(f"成功為 {location_name} 生成 OpenAI 天氣週報。")
        return advice

    except Exception as e:
        logger.error(f"呼叫 OpenAI API 發生錯誤: {e}，將降級使用規則式生成模擬週報。")
        advice = generate_mock_weekly_advice(location_name, weekly_forecasts, error_msg=str(e))
        weather.save_ai_summary(cache_key, advice)
        return advice

def generate_mock_weekly_advice(location_name, weekly_forecasts, error_msg=None):
    """當 API Key 缺失或呼叫出錯時，藉由氣象邏輯產生一週天氣模擬週報"""
    if not weekly_forecasts:
        return "⚠️ 目前無該縣市的一週天氣預報資料，無法生成週報。"
        
    min_temp = min(f["min_t"] for f in weekly_forecasts)
    max_temp = max(f["max_t"] for f in weekly_forecasts)
    
    # 統計下雨與晴天日期
    rainy_days = []
    sunny_days = []
    uv_warnings = []
    windy_days = []
    
    for f in weekly_forecasts:
        desc = f["wx_desc"]
        try:
            date_part = f["start_time"].split(" ")[0].split("-")
            time_label = f"{date_part[1]}/{date_part[2]}"
        except IndexError:
            time_label = f["start_time"]
            
        if "雨" in desc:
            if time_label not in rainy_days:
                rainy_days.append(time_label)
        else:
            if time_label not in sunny_days and time_label not in rainy_days:
                sunny_days.append(time_label)
                
        # 檢查紫外線指數
        uv = f.get("uv_index", "-")
        if uv != "-" and any(lvl in uv for lvl in ["過量", "危險", "8", "9", "10", "11"]):
            if time_label not in uv_warnings:
                uv_warnings.append(time_label)
                
        # 檢查強風
        wind = f.get("wind", "-")
        if wind != "-" and any(kw in wind for kw in ["強風", "陣風", "6 級", "7 級", "8 級"]):
            if time_label not in windy_days:
                windy_days.append(time_label)
                
    # 建立 Markdown 內容
    lines = []
    lines.append(f"### 🤖 智慧生活天氣週報 ({location_name})")
    
    if error_msg:
        lines.append(f"> ⚠️ **系統提示：** 呼叫 OpenAI API 時發生錯誤 (`{error_msg[:60]}`)。以下為系統分析一週氣象規則生成的週報建議。")
    else:
        lines.append("> 💡 **系統提示：** 偵測到尚未在 `.env` 中設定有效的 `OPENAI_API_KEY`。此週報由系統內建規則引擎生成，若想體驗更聰明的智慧對話，請在 `.env` 填入您的 OpenAI Key。")
        
    lines.append("")
    lines.append(f"#### 🌡️ 未來一週天氣概況")
    lines.append(f"- 預估未來 7 天氣溫介於 **{min_temp}°C 至 {max_temp}°C** 之間。")
    if rainy_days:
        lines.append(f"- 本週預估有降雨可能的日期包含：**{', '.join(rainy_days)}**，出門請多加留意。")
    else:
        lines.append("- 未來一週整體天氣穩定，並無明顯降雨訊號。")
        
    if uv_warnings:
        lines.append(f"- ☀️ **防曬警示：** 預估 **{', '.join(uv_warnings)}** 紫外線指數偏高（過量或危險級），戶外活動請做好防曬，避免曬傷。")
        
    if windy_days:
        lines.append(f"- 💨 **強風提醒：** 預估 **{', '.join(windy_days)}** 風力較大，騎車出行或戶外活動請注意安全，防範風大掉落物。")
        
    lines.append("")
    lines.append("#### 👕 家務與曬衣指南")
    if sunny_days:
        lines.append(f"- 🧺 **曬衣好日子：** 本週天氣相對晴朗的日期為 **{', '.join(sunny_days[:3])}**，請把握機會清洗與晾曬大件被單！")
    else:
        lines.append("- 🧺 **曬衣注意：** 本週雲量偏多或有雨，晾曬衣物建議選擇通風良好處，或配合除濕機、烘衣機使用。")
        
    lines.append("")
    lines.append("#### 🚗 週末出行指南")
    lines.append("- 🗺️ **週末規劃：** 請密切注意氣候變化。若有雨天，建議安排密室逃脫、美術館、或特色咖啡廳等室內靜態行程。若天氣晴朗，則非常適合進行郊外踏青或野餐活動。")
    
    lines.append("")
    lines.append("#### 💙 本週貼心小叮嚀")
    if max_temp - min_temp >= 10:
        lines.append(f"- 🧣 **溫差警示：** 本週高低溫差達 {max_temp - min_temp}°C，提醒您採洋蔥式穿法，早出晚歸多備一件薄外套，預防傷風感冒。")
    else:
        lines.append("- 💧 **補充水分：** 氣溫多變，出門在外請記得定時補充水分，並保持良好規律的生活作息喔！")
        
    return "\n".join(lines)
