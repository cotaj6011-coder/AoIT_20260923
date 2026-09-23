# 地圖優先的深色介面

依使用者確認的五項決策實作：保留 Streamlit/Folium、地圖為主、全臺同時段、MaxT 大字與色彩、點選 Marker 同步縣市明細。

視覺參考：[Taiwan Weather Map](https://taiwan-weather-map.vercel.app/)。參考其深藍黑配色、半透明面板、地圖主導與圖例；不是複製即時觀測產品，不新增觀測 API、雷達、雨量或颱風資料。

## 版面

- 頁首：繁體中文標題與簡短預報說明。
- 控制列：全臺共用完整起訖時段、縣市明細選單。
- 摘要：所選縣市、最高溫、最低溫、降雨機率。
- 主地圖：填滿瀏覽器視窗（100vw × 100dvh），可縮放與拖曳；數字 Marker 顯示最高溫與次要最低溫。
- 下方明細：預設收合，圖表及表格使用與地圖完全相同的預報時段。单一時段以散點呈現兩個溫度，不製造不存在的趨勢線。
- 頁尾：資料庫匯入時間；明確區分 CWA 發布時間。

`.streamlit/config.toml` 提供原生深色主題；`weather_data/dashboard.css` 管理滿版容器與浮動卡片；Folium 樣式集中在 gis.py。左上為標題與摘要、右上為篩選、左下為可展開明細與資料來源說明、右下為圖例。地圖 iframe 與內部 Leaflet 容器同步使用 viewport 高度，580px 僅為元件初始 fallback。明細面板限制高度並內部捲動。手機採兩個緊湊上方角落面板與底部明細，保留右下圖例及底圖出處；不是參考站的 bottom sheet 複製。

底圖沿用 OpenStreetMap，以 CSS 僅處理 tile pane 為深色；標籤、圖例與出處不被反色。不需要新的地圖 API Key。需網路載入底圖與前端資源；地名密集時可放大地圖選取。

## 資料與時段

`Repository → DataFrame → 同一 interval 的全臺資料 → Map`。
`全臺資料 → selected location → 摘要 / Chart / Table`。

完整起訖時段選單同時提供日期及時間，沒有 All intervals，防止跨時段比較最高溫。預設選擇目前仍有效的時段；尚未開始時選下一筆；全部過期時選最後一筆並顯示歷史預報提示。時段改變後，若所選縣市缺資料，選單重設為有效地區。缺測地區不捏造 Marker。

MaxT 控制色彩：<20 藍、20–<25 綠、25–<30 黃、≥30 粉紅；缺值灰色，UI 數值以「—」、Popup 以 N/A 呈現。所有值是預報；PoP 是降雨機率，不是雨量。沒有修改 Phase 1–3 或 Fixture。

## 互動

`streamlit-folium==0.27.4` 回傳 `last_object_clicked` 與 `last_object_clicked_count`。點擊位置必須精確匹配本時段有效 Marker，任意底圖點擊／無效座標不改變選取。事件消費後以 pending selection 在下一次 rerun 建立選單之前更新值；重複回傳的舊事件不覆寫手動選取。

Map 內容只依全臺時段資料生成，切換明細縣市不改變 Map component ID，避免重設縮放與點擊計數。時段切換才更新地圖。顯示選取狀態的來源為縣市選單與摘要卡。

## 驗證與限制

```powershell
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -X utf8 -m unittest discover -s tests -v
.venv/Scripts/python -X utf8 validate_webapp.py
.venv/Scripts/python -X utf8 validate_gis.py
.venv/Scripts/python -m streamlit run app.py --server.address=127.0.0.1 --server.headless=true --browser.gatherUsageStats=false
```

AppTest 解析真實 component payload，檢查全臺 Marker 時段、Popup、表格、圖表、地圖 identity 穩定。點擊事件以元件回傳契約模擬，涵蓋選單／摘要／表格同步、舊事件不覆寫選單，以及再次點擊。純函式測試驗證目前／未來／歷史時段選擇與無效事件。

環境無可用瀏覽器時，驗證僅能涵蓋 AppTest、元件輸出、Map 生成和 Server 啟動；不能宣稱已目視確認實際桌面／手機排版或瀏覽器端點擊。瀏覽器後續人工檢查：全臺標記顯示、選縣市、點另一標記、再用選單切換、切換時段、展開明細、縮小視窗檢查控制列。
