# 📝 專案完整開發日誌 (log.md)

本文件完整記錄了「AI 智慧天氣預報系統」專案自開始期（2026 年 7 月 2 日）至今的所有開發歷程、技術決策、系統當機/錯誤除錯以及今日（2026 年 7 月 3 日）的最新分析進度。

---

## 📅 專案開發歷程紀錄 (July 2, 2026 - Present)

### 🚀 第一階段：系統基礎架構與快取建立 (2026-07-02)
*   **核心目標**：建立基礎 Flask 後端與今明 36 小時氣象同步，並設計雙層快取以降低 API Token 與連線次數。
*   **關鍵技術與決策**：
    - **專案指揮官**：建立 [app.py](file:///f:/HW10-20260702-天氣預報/app.py) 作為 Flask 後端主體。
    - **SQLite 雙層快取**：於 [weather.py](file:///f:/HW10-20260702-天氣預報/weather.py) 中設計 `weather_forecasts`（天氣數據快取）與 `ai_summaries`（AI 生活建議分析快取）雙表，有效降低 API 負載。
    - **毛玻璃 GUI 前端**：在 [index.html](file:///f:/HW10-20260702-天氣預報/templates/index.html) 設計 Glassmorphism 配合暗色系霓虹漸層，提升視覺高級感。
*   **除錯歷程**：
    - ⚠️ **當機問題**：執行同步時遭遇 Windows 本地環境的 `SSLCertVerificationError` 證書校驗失敗。
    - ✅ **對策**：引入 `urllib3` 並對 `requests.get` 設定 `verify=False`，成功豁免 SSL 驗證完成同步。

---

### 🔄 第二階段：一週預報整合與背景非阻塞式同步 (2026-07-02)
*   **核心目標**：擴充未來一週天氣預報，並解決同步 API 時造成的前端 Pending 延遲。
*   **關鍵技術與決策**：
    - **一週資料庫與 API 改進**：
      - 經歷從誤用代碼 `F-C0032-005` 修正為正確的 `F-D0047-091` API 呼叫。
      - 因應氣象署週報 API 中文欄位與 TitleCase（`Locations`, `天氣現象`）特殊格式，重新設計解析器入庫 `weekly_forecasts`。
    - **非阻塞式同步機制 (Multi-threading)**：
      - 由於資料過期時向氣象署 API 重新同步需耗時 3-8 秒，會造成前端 Pending。
      - 引入 Python `threading.Thread`（daemon 執行緒）非同步處理同步任務。
      - 搭配 `threading.Lock()` 全域鎖定旗標 `_sync_in_progress`，防止並發請求重複發起同步競態。
    - **頁籤切換 Tab**：前端整合「今明36h/未來一週」雙頁籤卡片與可滾動的七日預報 UI。

---

### 🎨 第三階段：主題視覺、金鑰安全防護與自訂 API 智能辨識 (2026-07-02)
*   **核心目標**：更換夏日主題、增強金鑰隱私安全防洩漏，並簡化使用者自訂 API 輸入界面。
*   **關鍵技術與決策**：
    - **夏日海邊主題**：以 `generate_image` 生成涼爽夏日海邊背景圖片，加入暗色遮罩優化文字易讀性。
    - **金鑰安全與防崩潰防護**：
      - 建立 `env.private` 儲存本機真實金鑰並寫入 `.gitignore` 防止洩漏。
      - 建立範本 `.env` 使用佔位符，並修改後端載入順序（優先讀取 `env.private`，無則 Fallback 讀取 `.env`），保證外部測試不因變數缺失而崩潰。
    - **自訂 AI 智能端點判別**：
      - 簡化 UI 為單一啟用勾選框與金鑰輸入框。
      - 後端依金鑰前綴自動分流判別：以 `AIzaSy` 開頭判定為 Gemini 3.5，以 `sk-` 開頭判定為 Codex，其餘判定為 Opencode。
      - 整合 Windy 即時氣象雷達，並建立 22 縣市座標對照表（`COUNTY_COORDINATES`）實現地圖自動定位。

---

### 📊 第四階段：當機診斷與優化功能實作完成 (2026-07-03)
*   **核心工作**：
    - 針對昨日發生的所有異常日誌（CWA 404, OpenAI 429 額度超限，以及 Opencode `AttributeError` 程式缺陷）完成當機分析，並產出 [crash_analysis.md](file:///C:/Users/admin/.gemini/antigravity-ide/brain/237c2f34-3f4d-4d1b-9a67-a73507d928d5/crash_analysis.md)。
    - **第四階段功能已完整實作部署**：
      1. **一週天氣預報數據完整解析入庫**：已在 [weather.py](file:///f:/HW10-20260702-天氣預報/weather.py) 升級 `weekly_forecasts` 表結構，並在 `init_db()` 加入安全重建邏輯。在 `sync_weekly_data_internal()` 中完整解析 `12h降雨機率`、`紫外線指數`、`體感舒適度` 與 `風向風速` 並同步入庫。
      2. **AI 模組 SSL 驗證豁免控制**：在 [ai_helper.py](file:///f:/HW10-20260702-天氣預報/ai_helper.py) 整合 `DISABLE_SSL_VERIFY` 環境變數開關，跳過 Gemini REST 與 OpenAI 的 SSL 憑證校驗，解決 Windows 環境當機問題；同時將紫外線、舒適度、降雨機率等指標加入提問詞，並優化內建規則模擬週報引擎以發布強風與防曬警報。
      3. **前端 Chart.js 溫度趨勢折線圖**：在前端引入 Chart.js 庫，在雙頁籤上方渲染高質感的溫差折線圖，並支援分頁/縣市動畫切換。
      4. **Windy 多功能圖層切換**：在 Windy 雷達標題旁新增「風場」、「雷達」、「溫度」、「雲量」等即時觀測切換按鈕，實現非同步圖層更新。
      5. **一週天氣卡片展示擴展**：前端卡片升級，完整渲染出降雨機率、體感舒適度、紫外線指數、風向風速等精細氣象指標。
*   **驗證成果**：
    - 完成了 SQLite 表格升級、CLI 資料同步驗證、API 路由輸出驗證。
    - 使用自動化測試瀏覽器（Browser Subagent）執行完整的前台點擊與圖表動畫檢驗，產出驗證報告 [walkthrough.md](file:///C:/Users/admin/.gemini/antigravity-ide/brain/237c2f34-3f4d-4d1b-9a67-a73507d928d5/walkthrough.md)。

---

## 🎉 目前狀態 (Current Status)
*   **狀態**：第四階段優化與當機診斷已全部順利開發並驗證完成，系統在 Windows 本地開發環境下運作非常流暢穩定。

