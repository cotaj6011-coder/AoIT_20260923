# Phase 5 — Taiwan Weather Map

> 以下記錄 Phase 5 初版。現行 UI 已改用 `streamlit-folium==0.27.4` 雙向互動元件，取代 `st.iframe`；全臺地圖使用單一時段，點擊更新所選縣市明細。深色數字標籤、預設時段與目前流程見 [深色地圖改版](ui-design.md)。底層 prepare_markers 仍支援多時段，故此處的離線 GIS validation 仍使用完整 66 筆 Fixture。

## Architecture

`SQLite → Phase 3 Repository → Phase 4 DataFrame/shared filter → prepare_markers → Folium → Streamlit st.iframe`。

只新增 Folium 0.20.0；沿用 Streamlit 1.64.0 的 `st.iframe`（安裝版本提供 HTML string 嵌入），不使用已淘汰的 `components.v1.html`，也不另加 streamlit-folium。UI 不解析 CWA、不呼叫 API、不寫 DB。

## Coordinate source

`weather_data/location_coordinates.json` 集中保存 22 縣市定位點；每點包含 latitude、longitude、station_id、station_name。來源為 [中央氣象署測站一覽表](https://hdps.cwa.gov.tw/static/state.html)，於 2026-09-23 核對；精確擷取時間保存在 JSON 的 retrieved_at。直接摘錄官方表的經緯度與所屬城市，沒有猜測座標、沒有自動地理編碼。資料以固定靜態對照表隨程式保存，執行時不下載測站資料，也不新增另一個氣象資料 API。

這些點只是**縣市顯示定位點**，不是縣市中心、行政邊界或預報站點。顯示值始終是既有 F-C0032-001 縣市預報，不是該測站觀測值。例如南投縣使用日月潭、新竹市使用新竹市東區、新竹縣使用新竹站，避免將位於竹北的新竹站錯歸新竹市。屏東縣使用恆春站作定位，不能解讀為恆春的單點預報。Popup 與頁面均有縣市預報說明。

更新對照表時須逐項核對官方站碼、所屬城市、緯度與經度；不可依序號匹配。未知地區不嘗試推測。經緯度須為有限數值，本專案位置檢查範圍緯度 21–27、經度 118–123，含臺灣與離島；不是全球地理資料驗證器。

## Markers / popup / style

- 每個已篩選地區一個 Marker，避免同座標多時段重疊。Popup 保留**所有已選時段**，依開始、結束时间排序，各自顯示 Location、Start/End（+08:00）、MinT、MaxT、Rain、Weather。
- Tooltip 顯示地區與時段數；Popup HTML 對外部文字 escape，嵌於 Folium IFrame；Tooltip 另處理 JavaScript template 特殊字元。
- Marker DTO 的 min_temperature/max_temperature 是所選範圍的最低 MinT／最高 MaxT，用於摘要及顏色；不是將不同時段當成單筆原始預報。精確時段值仍在 Popup 逐筆呈現。
- 顏色依選取時段的最高有效 MaxT：`<20` 藍、`20≤T<25` 綠、`25≤T<30` 橙、`≥30` 紅；全缺值為灰。界線集中在 gis.py。NULL 顯示 N/A，不補 0；部分缺值在摘要中略過，Popup 保留缺值。
- 初始中心位於臺灣，視野包含臺灣本島、澎湖、金門、馬祖；使用 Folium 原生 Marker、Popup、Tooltip 與 OpenStreetMap 底圖，保留出處標示。可縮放、拖曳、點選。

## Filter integration / errors

沿用單一 Location selector；地圖只顯示目前選取的縣市。日期依當地 start_time 日期，完整時段同時比對 start/end，完全沿用 Phase 4。Chart、Table、Map 使用同一份 filtered DataFrame，不各自重新查詢。

無資料時沿用 Phase 4 訊息。缺座標或無效座標：每個受影響地區記錄 warning、跳過 Marker、UI 顯示計數，絕不使用 (0,0)。沒有任何有效 Marker 時顯示訊息，表格與圖表仍存在。Map rendering 失敗記錄 traceback 到伺服器，UI 顯示簡短錯誤並保留其他資料。

## Commands

在 repository 根目錄執行：

```powershell
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -X utf8 validate_gis.py
.venv/Scripts/python -X utf8 validate_gis.py --database .local/weather.sqlite3
.venv/Scripts/python -X utf8 -m unittest tests.test_gis tests.test_app -v
.venv/Scripts/python -X utf8 -m unittest discover -s tests -v
.venv/Scripts/python -m streamlit run app.py --server.address=127.0.0.1 --server.headless=true --browser.gatherUsageStats=false
```

預設 validation：固定真實 Fixture → 自動清理的暫存 SQLite → Repository → DataFrame → 22 Marker / 66 forecasts → Folium HTML。`--database` 唯讀既有 DB。顯示 missing/invalid **地區數**，任一缺漏或檢查失敗 exit 1；全部通過 exit 0。UI 可部分顯示，但驗收採完整覆蓋政策。

測試包含座標覆蓋、臺北／離島確切值、未知與無效座標、NULL、色彩邊界、Popup escape、順序穩定、日期／時段／地區篩選、SQLite 唯讀整合。AppTest 操作真實 selectors，解碼 Folium Popup 並將時段與溫度逐項比對頁面表格，檢查地圖故障／未知地區不影響 Chart/Table。

## Limitations / smoke test

測試與 validation 不需網路，網站上的 Leaflet JavaScript、樣式、圖示與 OpenStreetMap tiles 需要瀏覽器可連網；不加入離線 tile cache。固定 Fixture 是歷史預報，不代表即時天氣。沒有 Heatmap、GeoJSON 邊界、其他氣象來源或部署功能。

若環境沒有可用瀏覽器，依任務允許的方式以 Streamlit Server HTTP health、AppTest 與實際 Folium Map/Popup HTML 生成驗收，並在最終回報說明未完成瀏覽器目視檢查。
