# Phase 1 — CWA Weather Data

## 範圍與架構

狀態：**COMPLETE**（2026-09-23 真實 API 與離線測試驗證；詳細結果見下方）。

原始 repository 只有規劃文件和已暫存的技能，沒有 Python/Node.js 程式、套件或測試。工作區 `PHASE.md` 規劃 Python；repository workflow 提出未實作的 Next.js 全專案構想。本階段採 Python 3.10+，無 Web 框架，不修改既有規劃與技能。

```text
Environment / explicit local env file
  → CwaConfig
  → CwaClient (HTTPS, native trust, timeout, bounded response)
  → decode_json (raw dict; strict UTF-8 JSON)
  → parse_forecasts (dataset-specific validation + period join)
  → list[WeatherForecast] (application DTO)
```

`validate_cwa.py` 串接上述流程，清理敏感資料、保存 Response/metadata/structure、印出一筆摘要。一般 unit tests 全部離線，HTTP 使用 mock。

## 資料來源與 Dataset

- 中央氣象署氣象資料開放平臺：[官方網站](https://opendata.cwa.gov.tw/)。
- Dataset：[`F-C0032-001` — 一般天氣預報／今明 36 小時天氣預報](https://opendata.cwa.gov.tw/dataset/all/F-C0032-001)。
- Endpoint：`https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001`。
- Method：`GET`；query：`Authorization=<環境變數值>`、`format=JSON`。
- Base URL / Dataset ID / 15 秒 socket timeout / 5 MiB response 上限集中於 `weather_data/config.py`。
- [CWA 官方 Swagger](https://opendata.cwa.gov.tw/dist/opendata-swagger.html)、[原始 API 規格](https://opendata.cwa.gov.tw/apidoc/v1)。官方規格確認 query 與元素名稱；JSON 路徑則直接由本次真實 Response 確認。
- 官方標示每 6 小時更新。實際擷取時間寫入 Fixture metadata；**不將擷取時間當成資料發布／更新時間**。

## API Key 與 TLS

在 CWA 開放平臺申請會員並取得個人授權碼。本程式只使用 `CWA_API_KEY`，缺少或空白時回報 `MISSING_API_KEY`，不發送請求。

方法 A：由執行環境／CI secret 注入 `CWA_API_KEY`，直接執行驗證入口。

方法 B：將 `.env.example` 複製為 `.env.local`，在本機編輯後使用 `--env-file .env.local`。這是明確指定的本地環境設定檔，不會自動搜尋其他專案的 secret。Process environment 優先於檔案；process 中刻意設定空字串也不會回退使用檔案。

Env reader 支援 UTF-8、BOM、空行、整行註解、簡單 `KEY=value` 與成對單／雙引號。只讀 `CWA_API_KEY`、`SSL_CERT_FILE`；不执行 shell、不展開變數、不支援 inline comment 或多行值。請勿把註解放在 Key 值後方。

`.env`、`.env.*` 被 Git 忽略，只有空白樣板 `.env.example` 可納入版本控制。Key 不出現在設定 repr、錯誤訊息、Response repr、驗證摘要或 Fixture。CWA 要求授權碼放 query，因此 Client 不記錄 URL，也不轉傳 urllib 的原始 exception/body；不追隨 redirect。不要在外部除錯工具開啟完整請求 URL 紀錄。

本機 Python 原生 HTTPS 曾回報 `CERTIFICATE_VERIFY_FAILED`，而 Windows HTTPS 可成功驗證。使用唯一額外依賴 [`truststore==0.10.4`](https://truststore.readthedocs.io/en/latest/) 建立原生 OS trust context 後，Python Client 成功取得 HTTP 200。未停用 TLS 或 hostname verification。若公司網路有自訂 CA，可設定 `SSL_CERT_FILE` 為受信任的 PEM 憑證檔；不能藉此使用不受信任的憑證。

## 已觀察的真實 JSON 結構

本次 2026-09-23 HTTP 200 回應：根物件有 `success`、`result`、`records`；`success` 是字串 `"true"`。

```text
$ (object)
├── success (string "true")
├── result (object)
│   ├── resource_id ("F-C0032-001")
│   └── fields[] (id, type)
└── records (object)
    ├── datasetDescription (string)
    └── location[] (22 counties/cities)
        ├── locationName (string)
        └── weatherElement[]
            ├── elementName (Wx / PoP / MinT / CI / MaxT)
            └── time[]
                ├── startTime ("YYYY-MM-DD HH:MM:SS")
                ├── endTime ("YYYY-MM-DD HH:MM:SS")
                └── parameter
                    ├── parameterName (string)
                    ├── parameterValue (Wx code, when present)
                    └── parameterUnit (numeric elements, when present)
```

完整實測路徑／型別保存在 `tests/fixtures/cwa_weather.structure.json`。這不是 `records.locations[0].location`。

## Weather fields mapping

以下 JSONPath 用於文件描述；Python 使用明確 dict/list 存取，不依賴 JSONPath 套件。

| Application field | 實測 JSON Path / 來源 | 語意 |
|---|---|---|
| location_name | `$.records.location[*].locationName` | 縣市名；保留「臺」等原文 |
| start_time | `$.records.location[*].weatherElement[*].time[*].startTime` | 該氣象元素的時段起點 |
| end_time | `$.records.location[*].weatherElement[*].time[*].endTime` | 該氣象元素的時段終點 |
| forecast_date | `start_time.date()` | 起點的台灣當地日期，非另造 API 欄位 |
| min_temperature | `$.records.location[*].weatherElement[?(@.elementName=='MinT')].time[*].parameter.parameterName` | °C；回應 `parameterUnit="C"` |
| max_temperature | `$.records.location[*].weatherElement[?(@.elementName=='MaxT')].time[*].parameter.parameterName` | °C |
| rain_probability | `$.records.location[*].weatherElement[?(@.elementName=='PoP')].time[*].parameter.parameterName` | 0–100；回應 `parameterUnit="百分比"` |
| weather_description | `$.records.location[*].weatherElement[?(@.elementName=='Wx')].time[*].parameter.parameterName` | 天氣文字，例如「晴時多雲」 |

Parser 以 **縣市＋完整 `(startTime, endTime)`** 配對所有元素，依時段排序；不以 weatherElement 或 time 的陣列索引配對。實測每縣市 3 個時段，共 66 筆 DTO，但 production parser 不把 22 或 66 寫死。

原始 timestamp 沒有 timezone suffix；本 dataset 是台灣當地預報，Application 明確轉成 UTC+08:00 的 aware datetime。跨午夜時段不拆成日資料。`success` 額外容許布林 `true`；其他成功值拒絕。`result.resource_id` 必須吻合設定。

`$.result.resource_id` 是 **資料集 ID，不是縣市 ID**。此 Response 沒有縣市行政代碼、經緯度或發布時間。`locationName` 可供未來另行核對縣市資料；不自行生成行政區 identifier。`Wx.parameterValue` 是天氣代碼，不是地理 identifier；`CI` 是舒適度，Phase 1 DTO 不收錄。

## 缺值與結構錯誤政策

- 氣象值 `null`、空字串、非數字、bool、NaN、Infinity、超出範圍值 → `None`。數值 0 與合理負溫保留。
- Application 合理值範圍：溫度 -90～60°C、降雨機率 0～100%。這是**本專案防呆政策**，不是宣稱 CWA 的官方 missing-code 定義。
- 合成邊界測試包含 `-99`、`-999`、`-9999`；均因越界轉 `None`。本次真實回應未觀察到這些缺值代碼，不冒稱已由 live data 證實。
- 某元素／parameter／parameterName 缺失：對應 DTO 欄位 `None`，不填入 0。沒有任何有效元素時段的 location 不生成 DTO。
- 空 `location` → 空 list；驗證入口將空資料集／完全沒有時段的縣市判為 FAIL。
- 非 object/array 的必要容器、空地名、無效時間、反向時段、重複縣市／元素／時段、溫度單位不是 C、MinT > MaxT → 可理解的 application error，不猜測如何修復。
- 空 body、無效 UTF-8/JSON、非 object root、重複 JSON key、非標準 JSON 數值會拒絕。存檔與檢查限制 JSON 深度 40。
- Live 驗證至少要求一筆六個必要欄位完整的資料，每個回傳縣市均有時段；其他 DTO 的缺值仍保留 `None`，不假造數值。PASS 不代表每個時段都無缺值。

## HTTP 與錯誤處理

| 情況 | 處理 |
|---|---|
| 200 | 讀取有上限的 body，再驗證 JSON / success / Dataset / 時段 |
| 400 | Request 參數錯誤 |
| 401 / 403 | 授權碼或存取權限錯誤 |
| 404 | Dataset endpoint 不存在 |
| 429 | Rate limit，提示稍後重試 |
| 5xx | CWA 服務失敗，提示稍後重試 |
| Timeout | `TIMEOUT`，15 秒 socket timeout |
| DNS / connection / partial response | `CONNECTION_ERROR` |
| SSL verification / CA file | `TLS_ERROR` / `TLS_CONFIG` |
| Redirect 或其他 HTTP status | 拒絕，不把授權碼轉往其他 URL |

不自動重試，避免放大配額消耗；呼叫者可在稍後重新執行。15 秒是 socket 操作 timeout，不是整個命令的絕對總秒數上限。HTTP errors 保留狀態碼，但不保存敏感 URL、request headers 或服務端錯誤本文。

## 執行、測試與 Build

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt

# 真實網路驗證（需要自己的 key；不屬於預設 unit tests）
.venv/Scripts/python -X utf8 validate_cwa.py --env-file .env.local

# 離線 unit tests
.venv/Scripts/python -X utf8 -m unittest discover -s tests -v

# Python 語法編譯檢查
.venv/Scripts/python -m compileall -q weather_data validate_cwa.py tests
```

Live command exit code：成功 `0`、失敗 `1`（CLI 參數用錯為 argparse 的 `2`）。預設寫入 `.local/cwa_weather.json`、`.metadata.json`、`.structure.json`，被 Git 忽略。Schema/資料驗證失敗的 JSON 存成 `.unverified.json` 與其 metadata/structure，不覆盖成功 Fixture；HTTP 錯誤本文與非 JSON 內容不保存。

固定 fixture 是真實擷取，取得日期、SHA-256、清理政策與 verification status 記錄在 metadata；不是 synthetic。Unit tests 對 fixture 使用固定預期值。需要更換時明確指定 `--output tests/fixtures/cwa_weather.json`，並依新資料調整對應 snapshot assertions；日常 validation 不會覆寫它。

本次驗證結果：HTTP 200、22 縣市、66 筆；樣本嘉義縣 `2026-09-23T18:00:00+08:00`～`2026-09-24T06:00:00+08:00`，MinT=25、MaxT=29、PoP=10、Wx=晴時多雲。

2026-09-23 離線測試：85 passed / 0 failed（Configuration 8、HTTP Client 21、Parser 30、JSON/Fixture 12、DTO 6、Validation CLI 8）。Compileall 與 `pip check` 均成功。真實 Integration Validation 最後一次執行 1 passed / 0 failed；不計入 unit test 數量。

`.gitattributes` 將 Fixture JSON 固定為 LF，確保 Windows/Linux checkout 後 metadata SHA-256 仍吻合。Git 可見檔案未找到真實 API Key；`.env.local` 未追蹤，未 commit 或 push。

## Known limitations / 下一階段

- 只有今明 36 小時縣市預報，不代表鄉鎮／山區所有地點的天氣。
- Dataset does not provide point temperature (`Temperature`), latitude/longitude or an administrative location ID in the verified response. Future phase requires another dataset or verified geographic reference for those fields.
- 未新增 GIS、UI、Chart、Database、部署、AI 或第二個資料來源。
- 沒有追溯更新時間或 stale-cache 偵測；metadata 的 retrieved_at 僅代表擷取時間。
- 未建立快取、排程或 retry framework；HTTP API 變更將明確失敗而非猜測新 schema。
- 下一階段直接使用 `CwaClient(config).fetch()` + `parse_response(response.body)` 取得 DTO，再於各自階段消費資料，UI 不需理解原始 CWA JSON。
