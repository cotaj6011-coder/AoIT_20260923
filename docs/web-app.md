# Phase 4 — Weather Dashboard

> 本文件記錄 Phase 4 初版。後續已改為全臺單一時段地圖、縣市明細、預設收合圖表／表格；目前只有時段與縣市兩個選單，Validation 的 Filtered Records 為 1。現行介面、互動與測試以 [深色地圖改版](ui-design.md) 為準；以下舊版 All dates / All intervals 及未加入 GIS 的敘述僅供階段紀錄。

## Architecture

`SQLite → Phase 3 WeatherForecastRepository → WeatherForecast → Pandas → shared filter → Streamlit Chart/Table`。

入口 `app.py` 不含 SQL、JSON parser 或 CWA Client。`weather_data/dashboard.py` 提供 DataFrame 與篩選純函式。Phase 3 只新增 keyword-only `read_only=False` 開啟選項及 `get_last_updated()`；舊用法與寫入交易不變，SQL 仍集中於 `storage_sql.py`。

## Install / launch

Web App 依賴 Python 3.11+、`streamlit==1.64.0`、`pandas==3.0.6`；本次使用 Python 3.14。圖表使用 Streamlit 原生 API，沒有另裝 chart framework；Altair / Arrow 等由 Streamlit 自身依賴帶入。

```powershell
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -X utf8 seed_dashboard.py
.venv/Scripts/python -m streamlit run app.py --server.address=127.0.0.1 --server.headless=true --browser.gatherUsageStats=false
```

開啟 `http://127.0.0.1:8501`。本地服務只 bind loopback，未部署。

`seed_dashboard.py` 為獨立、明確執行的初始化命令，透過既有 Parser/Repository 將真實 Fixture UPSERT 到 `.local/weather.sqlite3`；不是最新 API 抓取，也不由 UI 自動觸發。可指定 `--fixture` / `--database`。它不刪除已有 DB 內其他期間的資料，重新執行只依 Natural Key 更新。

UI 預設讀取專案 `.local/weather.sqlite3`，或使用 process environment `WEATHER_DATABASE` 指定既有檔案。SQLite 以 `mode=ro` 開啟，UI 不初始化、不寫入 DB。DB 不存在時顯示錯誤，絕不默默建立空 DB。

## DataFrame / filters

DataFrame 固定欄位：location_name、start_time、end_time、min_temperature、max_temperature、rain_probability、weather_description。

- 時間保留 timezone-aware，統一 `Asia/Taipei`（UTC+08:00）。
- 數值使用 Pandas nullable Float64，SQL NULL 轉為缺值，不補成 0。
- 載入排序為地區 → start → end。表格和圖表依 start → end 排序。
- Location 精確匹配；預報日期依台灣當地 **start_time 日期**，跨午夜時段歸起始日。
- 完整時段依 start + end 同時比對，可選 All dates / All intervals。
- 地區切換造成原日期／時段不再有效時，選項重設為 All，避免殘留條件。
- Chart/Table 共用同一個 filtered DataFrame；Chart 不重新查 DB 或解析 JSON。
- 多時段用折線；僅一個時段用原生 scatter 顯示兩個溫度點，避免單點折線不可見。
- NULL 不插值；全部溫度缺失時顯示訊息，表格仍可查看。

Chart 軸為 Forecast Time / Temperature (°C)，包含 MinT 與 MaxT。native temporal chart 由瀏覽器按本地時區呈現，使用其他時區瀏覽器時請以表格的 UTC+08:00 timestamp 為準。

摘要顯示 DB 總筆數、縣市數與 `MAX(updated_at)`。Last imported 是 **SQLite 匯入時間**，不是 CWA 發布時間；預設 Fixture 是 2026-09-23 的歷史資料。每次 Streamlit rerun 重新唯讀查詢，沒有過期 cache；目前沒有自動刷新或背景抓 API。

## Empty / error states

- Missing DB：顯示建立／選擇資料庫提示。
- Empty DB：`No forecast data available`，不繪圖。
- SQL / schema / corrupt DB：可理解 UI error，伺服器 logger 保留 exception 與錯誤代碼供除錯。
- 無符合地區／日期／時段資料：顯示 filter empty 訊息。
- 全部 NULL 溫度：顯示 Temperature data unavailable，保留表格。
- UI 不直接顯示 traceback；不讀取或顯示 CWA_API_KEY。

## Validation / tests

```powershell
# 預設：真實 Fixture → temporary SQLite → Repository → Pandas；自動清除暫存 DB
.venv/Scripts/python -X utf8 validate_webapp.py

# 驗證既有 DB，唯讀、不改寫
.venv/Scripts/python -X utf8 validate_webapp.py --database .local/weather.sqlite3

# 純函式、SQLite integration、Streamlit AppTest
.venv/Scripts/python -X utf8 -m unittest tests.test_dashboard tests.test_app -v

# 全部回歸測試
.venv/Scripts/python -X utf8 -m unittest discover -s tests -v

# 語法檢查
.venv/Scripts/python -m compileall -q weather_data app.py seed_dashboard.py validate_webapp.py tests
```

預設 validation 不需網路／API Key。检查 DB 可讀、DataFrame、地區及日期/完整時段篩選、時間排序、chart/table 非空及有效 MinT ≤ MaxT；成功 exit 0、失敗 exit 1。固定 Fixture：Records 66、Locations 22、Selected Location 南投縣、Filtered Records 3。

AppTest 直接操作實際頁面的 selectors，並解碼 Streamlit chart 的 Arrow dataset，比對它與 table 的時間／溫度值；不是只有 mock UI 函式。另涵蓋 missing/corrupt/empty DB、全 NULL／部分 NULL、filter empty、stale selector reset。所有 tests 使用 temporary DB，並檢查讀取前後 DB hash 不變。

## Smoke test / limitations

本次本地 Streamlit Server 啟動成功，首頁與 `/_stcore/health` 都回傳 HTTP 200，無 startup error。工具環境無可用瀏覽器，因此依任務允許的 fallback，以真實 Server 啟動及官方 AppTest 操作驗證；未宣稱已完成實際瀏覽器目視檢查。

Streamlit AppTest 在一般 unittest process 可能出現 `missing ScriptRunContext` 提示；測試結果與頁面 exception 檢查均正常。生產服務 startup log 無 exception。

未新增 GIS、Map、部署、Supabase、AI、AQI 或其他資料源。未修改 Phase 1/2 Parser、Model、Fixture。`.local/` 與 SQLite runtime 檔案已忽略，不能提交。
