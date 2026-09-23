# Taiwan Weather GIS — Weather Dashboard

## Live Demo Website

**[開啟 Taiwan Weather Dashboard](http://127.0.0.1:8501)**

目前為本機展示網站，啟動 Streamlit 後可開啟；此連結僅適用於執行網站的電腦，尚未提供公開部署網址。

Python 3.11+ 天氣預報專案，包含 CWA 資料層、SQLite、Streamlit Dashboard 與 Folium 天氣地圖。

在此 repository 根目錄執行（Windows PowerShell）：

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
# 僅首次建立；已有 .env.local 時不要覆寫。
Copy-Item .env.example .env.local
# 在本機編輯 .env.local，填入自己的 CWA_API_KEY。
.venv/Scripts/python -X utf8 validate_cwa.py --env-file .env.local
.venv/Scripts/python -X utf8 -m unittest discover -s tests -v
```

Linux/macOS 請將 `.venv/Scripts/python` 換成 `.venv/bin/python`。已設定 process environment 的使用者可省略 `--env-file`。

- [CWA API、欄位對應、錯誤處理與限制](docs/cwa-api.md)
- [真實 Fixture 來源與更新方式](tests/fixtures/README.md)
- [完整專案規劃](AIoT_DIC2_Taiwan_Weather_GIS_Workflow.md)
- [換電腦還原清單：API Key、環境與本地資料庫](docs/local-setup.md)

`.env.local` 位於專案內，但已被 `.gitignore` 排除；不會隨 Git 傳遞。預設驗證輸出到被忽略的 `.local/`，不會覆寫固定測試 Fixture。

## Phase 2 — Data Processing

以 Phase 1 固定真實 Fixture 驗證 MinT／MaxT、時間配對與正規化，不需要網路或 API Key：

```powershell
.venv/Scripts/python -X utf8 validate_processing.py
```

詳見 [Data Processing：欄位、缺值政策、時間配對與測試](docs/data-processing.md)。

## Phase 3 — Data Storage

使用固定 Fixture 完成 Parser → SQLite → Query 驗收。預設建立並自動清除暫存資料庫，不需 API Key 或網路：

```powershell
.venv/Scripts/python -X utf8 validate_storage.py
```

詳見 [Data Storage：Schema、UPSERT、Transaction 與查詢](docs/data-storage.md)。

## Phase 4 — Web App

```powershell
.venv/Scripts/python -m pip install -r requirements.txt
# 明確匯入既有真實 Fixture（歷史 Snapshot），不呼叫 API。
.venv/Scripts/python -X utf8 seed_dashboard.py
.venv/Scripts/python -m streamlit run app.py --server.address=127.0.0.1 --server.headless=true --browser.gatherUsageStats=false
```

開啟 <http://127.0.0.1:8501>。首頁呈現深色全臺同時段天氣地圖；點選標記或使用縣市選單更新摘要，展開下方明細查看圖表與表格。
預設唯讀使用 `.local/weather.sqlite3`；指定其他既有 DB 可設定 `WEATHER_DATABASE`。

```powershell
.venv/Scripts/python -X utf8 validate_webapp.py
```

詳見 [Web App：資料流程、篩選、測試與錯誤狀態](docs/web-app.md)。

## Phase 5 — GIS

更新依賴後，沿用 `streamlit run app.py`。Map 顯示所選時段全部地區；圖表、表格顯示所選縣市的相同時段。數字標記突出預報最高溫，最低溫以小字呈現。

```powershell
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -X utf8 validate_gis.py
```

驗證預設使用真實 Fixture 與暫存 SQLite，不需網路或 API Key。實際瀏覽地圖的底圖與 JavaScript 資源需網路。
詳見 [GIS：座標來源、Marker、篩選與驗證](docs/gis.md)。

最新介面與互動規格見 [深色地圖改版](docs/ui-design.md)。更動 `.streamlit/config.toml` 後若主題未更新，請重新啟動 Streamlit。
