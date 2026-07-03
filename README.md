# AI 智慧天氣分析預報儀表板

這是一個基於 **Flask** 框架與 **SQLite** 資料庫建置的台灣縣市天氣預報系統。此系統不僅能自「交通部中央氣象署 (CWA) 開放資料平台」擷取最新的今明 36 小時預報數據，更能整合 **OpenAI GPT-4o-mini** 模型，為台灣 22 個縣市量身打造口吻溫馨且極具實用價值的穿搭與生活建議（若無 API 金鑰，系統會自動切換至內建規則引擎生成建議）。

---

## 📂 專案檔案結構

本專案結構如下：

```text
f:\HW10-20260702-天氣預報/
├── .vscode/
│   └── settings.json       # VS Code 工作區設定檔（配置自動排版及 Python 解釋器）
├── templates/
│   └── index.html          # 前端網頁模板（採用毛玻璃與暗夜系高質感漸層 CSS 設計）
├── logs/
│   └── weather.log         # 系統日誌檔（記錄爬蟲狀態、API 連線及 SQLite 操作）
├── .env                    # 環境變數設定檔（儲存 CWA 與 OpenAI 金鑰，不上傳至 Git）
├── app.py                  # Flask 主程式（負責指揮官調度與 API 路由註冊）
├── weather.py              # 資料同步與 SQLite 資料庫操作模組
├── ai_helper.py            # OpenAI API 請求與本地規則 fallback 建議引擎
├── requirements.txt        # 環境相依套件清單
├── weather.db              # SQLite 資料庫（執行後產生，快取氣象與 AI 建議）
└── README.md               # 專案說明文檔（本檔案）
```

---

## 🛠️ 安裝與設定步驟

### 1. 安裝環境相依套件
確保您已啟動專案的虛擬環境 (`venv`)，然後執行以下指令安裝或更新套件：
```bash
.\venv\Scripts\pip install -r requirements.txt
```

### 2. 配置環境變數（雙層金鑰保護機制）

本專案採用**雙環境檔案**設計，確保真實 API Key 永不外洩：

| 檔案 | 用途 | 是否上傳 GitHub |
|:--|:--|:--|
| `env.private` | 本機私有設定，存放真實 API Key | ❌ **絕不上傳**（.gitignore 保護） |
| `.env` | 公開範本，只有佔位符 | ✅ 可安全上傳 |

**程式讀取優先序：`env.private` → `.env`（fallback）**

#### 本機執行設定步驟：

1. 在專案根目錄建立 `env.private` 檔案：
```ini
# 中央氣象署 (CWA) 開放資料授權碼
# 請至 https://opendata.cwa.gov.tw 申請後填入
CWA_API_KEY=你的真實CWA授權碼

# OpenAI API Key（若要使用 OpenAI 智慧分析，請在此填入您的 API Key）
OPENAI_API_KEY=你的真實OpenAI_Key

# Flask 設定
FLASK_ENV=development
FLASK_DEBUG=True
PORT=5000

# SSL 驗證（僅限開發環境設為 true；正式環境應設為 false）
DISABLE_SSL_VERIFY=true
```

2. `env.private` 已加入 `.gitignore`，**不會被 `git add` 追蹤**，可安心填入真實金鑰。

> 💡 **若無 OpenAI Key 亦可正常執行**：AI 建議欄位會自動切換至系統內建規則引擎生成。

---

## 💾 資料庫結構 (Database Schema)

本系統使用 SQLite 資料庫 (`weather.db`) 進行兩層式快取，以節省 API 呼叫次數與 Token 成本：

### 1. 天氣預報表 `weather_forecasts`
| 欄位名稱 | 型態 | 說明 |
| :--- | :--- | :--- |
| `id` | INTEGER | 流水號 (主鍵) |
| `location_name` | TEXT | 縣市名稱 (例如: 臺北市) |
| `start_time` | TEXT | 預報開始時間 (`YYYY-MM-DD HH:MM:SS`) |
| `end_time` | TEXT | 預報結束時間 (`YYYY-MM-DD HH:MM:SS`) |
| `wx_desc` | TEXT | 天氣現象描述 (例如: 多雲時晴) |
| `wx_value` | TEXT | 天氣現象代碼 (用於前端對應天氣圖示) |
| `pop` | INTEGER | 降雨機率 (%) |
| `min_t` | INTEGER | 最低溫度 (°C) |
| `max_t` | INTEGER | 最高溫度 (°C) |
| `ci` | TEXT | 舒適度指數 |
| `updated_at` | TEXT | 資料同步時間 |

### 2. 一週天氣預報表 `weekly_forecasts`
| 欄位名稱 | 型態 | 說明 |
| :--- | :--- | :--- |
| `id` | INTEGER | 流水號 (主鍵) |
| `location_name` | TEXT | 縣市名稱 (例如: 臺北市) |
| `start_time` | TEXT | 時段開始時間 (`YYYY-MM-DD HH:MM:SS`) |
| `end_time` | TEXT | 時段結束時間 (`YYYY-MM-DD HH:MM:SS`) |
| `wx_desc` | TEXT | 天氣現象描述 (例如: 多雲時晴) |
| `wx_value` | TEXT | 天氣現象代碼 |
| `min_t` | INTEGER | 最低溫度 (°C) |
| `max_t` | INTEGER | 最高溫度 (°C) |
| `pop` | INTEGER | 12小時降雨機率 (%) |
| `uv_index` | TEXT | 紫外線指數描述 (例如: "10 (過量級)") |
| `ci` | TEXT | 舒適度描述 |
| `wind` | TEXT | 風向與風速描述 |
| `updated_at` | TEXT | 資料同步時間 |


### 3. AI 建議快取表 `ai_summaries`
| 欄位名稱 | 型態 | 說明 |
| :--- | :--- | :--- |
| `location_name` | TEXT | 縣市名稱 (主鍵，36h 預報為「縣市名」，週報為「縣市名_weekly」) |
| `summary_text` | TEXT | AI 生成的 Markdown 格式建議內容 |
| `generated_at` | TEXT | 建議生成時間 |

---

## 🌐 核心 API 路由說明

| 請求方法 | API 端點 | 參數說明 | 描述 |
| :--- | :--- | :--- | :--- |
| **GET** | `/` | 無 | 渲染並返回天氣儀表板主頁面。 |
| **GET** | `/api/counties` | 無 | 獲取台灣 22 縣市的標準命名清單。 |
| **GET** | `/api/weather` | `?location=縣市名` | 獲取特定縣市最新 36 小時預報。若資料過期（超過 1 小時）會自動在背景觸發同步，並於回傳 JSON 中附加 `"is_syncing": true`。 |
| **GET** | `/api/weekly_weather` | `?location=縣市名` | 獲取特定縣市最新一週（7天）天氣預報。若資料過期（超過 1 小時）會自動在背景觸發同步，並於回傳 JSON 中附加 `"is_syncing": true`。 |
| **GET** | `/api/ai_advice` | `?location=縣市名&type=36h&force_refresh=true` | 獲取特定縣市之 AI 天氣生活建議。`type` 參數可選 `36h`（預設）或 `weekly`。具備快取過期檢測功能（當天氣更新時間晚於快取生成時間時會自動更新）。 |
| **POST** | `/api/sync` | 無 | 手動觸發中央氣象署所有縣市最新天氣資料同步（含 36 小時及一週預報）。 |

---

## 🚀 執行與測試

本系統支援 **「直接啟動、自初始化與自動背景同步」**。不需要手動執行命令列的資料庫建立或同步指令。

### 1. 啟動網頁伺服器
執行 `app.py` 啟動主服務：
```bash
# 啟動應用程式 (系統會自動在背景建表並拉取氣象資料)
.\venv\Scripts\python.exe app.py
```
啟動後，請使用瀏覽器開啟以下網址進入天氣儀表板首頁：
👉 **[http://127.0.0.1:5000](http://127.0.0.1:5000)**

*(註：若您是在 Render 雲端平台部署，同樣只需將啟動命令設為 `gunicorn app:app` 或 `python app.py`，伺服器便會在啟動時自行在背景建立資料表並同步最新氣象資料。)*

---

## 🛡️ 容錯與安全設計
- **金鑰安全與前端自訂設定**：除了支援本機私有設定檔外，系統前端特別新增了**自訂 API 設定面板**：
  - **自訂 AI 金鑰**：已極簡化為單一的「啟用自訂 AI API」勾選開關與單一的「API 金鑰」密碼輸入框。系統後端會自動根據輸入的金鑰首碼進行智慧偵測與端點分流（以 `AIzaSy` 開頭判定為 Gemini 3.5 Flash，以 `sk-` 開頭判定為 Codex/OpenAI，其餘則判定為 Opencode），以最乾淨簡潔的 UI 提供最高度的彈性。
  - **自訂氣象局金鑰**：支援在前端輸入 CWA 授權碼，勾選即可讓前台查詢與手動同步均繞過本機設定，改用您輸入的金鑰執行。
- **氣象署 (CWA) 官方 API 端點驗證**：
  - 今明 36 小時預報：`https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001`
  - 未來一週天氣預報：`https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-091`
- **SSL 驗證環境開關**：透過 `.env` 中的 `DISABLE_SSL_VERIFY` 環境變數控制 SSL 驗證行為。開發環境預設為 `true`（停用），以解決 Windows 本地環境因憑證鏈不完整造成的 SSL 錯誤；正式部署環境應將此值設為 `false` 以恢復完整驗證。
- **非阻塞式背景同步與前端輪詢**：資料同步改為背景執行緒（`threading.Thread`）執行。當快取資料過期時，API 端點立即返回現有快取並帶上 `is_syncing: true`。前端檢測到此旗標時會開啟自動輪詢（每 3 秒），同步完成後無重整更新 UI。
- **AI 建議快取自動過期比對**：`ai_helper.py` 載入建議快取時會比對資料庫天氣更新時間 `updated_at` 與 AI 快取生成時間 `generated_at`。若天氣已被同步更新，則舊的 AI 建議快取會自動失效並觸發重新計算，確保資料一致性。
- **Windy 即時雷達與定位連動**：前端首頁下方整合了 Windy 氣象觀測動態地圖，配置台灣 22 縣市經緯度座標字典。當使用者切換觀測縣市時，前端會動態變更 Windy Iframe 網址重新定位，提供流暢的即時雷達、降雨與風場觀測。
- **OpenAI 降級容錯**：`ai_helper.py` 具備自動降級機制。當偵測到環境變數中未填入 API 金鑰或 API 呼叫失敗時，系統會調用本地規則引擎，根據該地區的最高/最低氣溫、降雨機率及舒適度，組裝出同樣精美的 Markdown 排版建議，確保展示功能無懈可擊。


