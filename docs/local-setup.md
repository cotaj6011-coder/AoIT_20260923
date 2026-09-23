# 換電腦／重新 Clone 的還原清單

## 不會隨 Git 帶走的項目

| 項目 | 需要做什麼 | 何時需要 |
|---|---|---|
| `.env.local` / `CWA_API_KEY` | 複製 `.env.example` 為 `.env.local`，填入自己的 Key | 真實呼叫 CWA；離線展示不用 |
| `.venv/` | 建立虛擬環境並安裝 requirements.txt | 執行 Python、測試或網站 |
| Python | 安裝 Python 3.11+；本專案驗證環境為 3.14 | 新電腦 |
| `.local/weather.sqlite3` | 用 seed_dashboard.py 從已提交 Fixture 重建 | 啟動網站前 |
| 自行累積的 SQLite 歷史資料 | 若要保留完整歷史，另行備份並還原 DB | Fixture 只能還原固定 snapshot，不能還原自有歷史 |
| `.local/` 下載、結構分析與 logs | 重新執行驗證即可產生；一般不用搬移 | 需要新的 API snapshot 或除錯資料時 |
| `WEATHER_DATABASE` | 若使用非預設 DB 路徑，在新環境重設 process environment | 自訂 DB 才需要 |
| `SSL_CERT_FILE`／公司憑證 | 依新環境重新設定可信 PEM 憑證路徑 | 公司代理或特別憑證需求才需要 |
| GitHub 登入／Git author | 在新電腦設定 Git 認證及 user.name、user.email | 要提交／推送時 |

程式碼、requirements.txt、`.env.example`、Streamlit 深色設定、座標表、測試、真實 Fixture、文件及 `.agents/skills/` 都會隨 Git 傳遞。個人 `~/.codex/skills` 不在此 repository 內；本 repo 已保留 grilling/grill-me 的專案版本，是否自動載入取決於使用的 coding agent。

## 最短還原流程（PowerShell）

```powershell
git clone https://github.com/cotaj6011-coder/AoIT_20260923.git
cd AoIT_20260923
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -X utf8 seed_dashboard.py
.venv/Scripts/python -m streamlit run app.py --server.address=127.0.0.1 --server.headless=true --browser.gatherUsageStats=false
```

開啟 http://127.0.0.1:8501 。上述展示使用固定歷史 Fixture，不需要 CWA Key；底圖和地圖前端資源仍需要網路。

## 取得最新 CWA 資料

```powershell
# 僅在 .env.local 尚不存在時執行，避免覆寫自己的 Key。
Copy-Item .env.example .env.local
# 在本機編輯 .env.local：CWA_API_KEY=自己的金鑰
.venv/Scripts/python -X utf8 validate_cwa.py --env-file .env.local
.venv/Scripts/python -X utf8 seed_dashboard.py --fixture .local/cwa_weather.json
```

僅執行 validate_cwa.py 不會更新 SQLite；須成功取得／驗證資料後再匯入。UPSERT 保留舊時段，不會刪除已有歷史資料。UI 本身不自動呼叫 API。若環境本身已設定 CWA_API_KEY，該值優先於 env file。

## 尚未提供的項目

- Live Demo 目前是本機網址，不是公開部署；Git push 不會自動部署或啟動 Streamlit。
- README 的實際網站截圖尚待取得，尚無可隨 Git 還原的截圖。
- 不需要 Supabase、資料庫服務、Vercel 或額外地圖 API Key。
- 不要將 `.env.local`、金鑰或 runtime DB 強制加入 Git。
