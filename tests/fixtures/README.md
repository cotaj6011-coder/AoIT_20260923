# 真實 CWA Fixture

- `cwa_weather.json`：由本機 Python CWA Client 真實 HTTPS Request 取得；不是 mock。
- Dataset：`F-C0032-001`，今明 36 小時縣市預報。
- 取得日期：2026-09-23，精確 UTC 時間見 `cwa_weather.metadata.json` 的 `retrieved_at`。
- HTTP：200；`success="true"`；22 縣市、每縣市 3 時段，共 66 DTO。
- 保留完整 JSON 根結構、所有縣市、全部氣象元素與時段。
- 經過敏感資訊清理程序：redact 授權碼／token 等欄位與 echoed API key；不保存 request URL、HTTP headers 或 Key。真實回應沒有需要保留的授權資訊。
- `cwa_weather.metadata.json`：來源、Dataset、時間、sanitization、SHA-256、Parser 驗證狀態。
- `cwa_weather.structure.json`：由實際回應走訪產生的 path/type 清單，不含額外推測。
- Unit tests 的 mutation 與 inline JSON 是 **synthetic edge cases**，不宣稱來自 CWA；不修改這份 fixture。

日常 `validate_cwa.py` 寫入忽略的 `.local/`。要刻意更新固定 fixture：

```powershell
.venv/Scripts/python -X utf8 validate_cwa.py --env-file .env.local --output tests/fixtures/cwa_weather.json
```

更新後檢查真實值，調整 `test_parser.py`、`test_validation.py` 中的 snapshot expectations，重跑全部 tests。不要編造 Response 填補網路／授權失敗。
