# Phase 3 — Data Storage

沿用 Phase 2 `WeatherForecast`、Parser 與 Phase 1 真實 Fixture；新增 Python 標準函式庫 `sqlite3` repository，無第三方依賴、ORM、其他資料來源或 UI。

## Schema

Table：`weather_forecasts`。SQL 集中於 `weather_data/storage_sql.py`，repository 不拼接 SQL。

| Column | SQLite type | 規則 |
|---|---|---|
| id | INTEGER PRIMARY KEY | SQLite 產生；UPSERT 保留 |
| location_name | TEXT NOT NULL | 非空字串 |
| start_time | TEXT NOT NULL | ISO 8601，固定 microseconds、UTC+08:00 |
| end_time | TEXT NOT NULL | ISO 8601，同上；start < end |
| min_temperature | REAL / NULL | 純數值，沿用 -90～60°C 防呆 |
| max_temperature | REAL / NULL | 純數值；兩者有值時 min ≤ max |
| rain_probability | REAL / NULL | 0～100 |
| weather_description | TEXT / NULL | 保留 Phase 2 值 |
| created_at | TEXT NOT NULL | UTC ISO 8601，首次寫入時間 |
| updated_at | TEXT NOT NULL | UTC ISO 8601，最後一次 UPSERT 時間 |

Natural key：`UNIQUE(location_name, start_time, end_time)`。另有 `(start_time, end_time)` index 協助時間查詢。

例：`2026-09-23T18:00:00.000000+08:00`。統一 offset 和精度後，文字比較即為時間順序；相同 instant 即使由其他 timezone 傳入，也轉成相同 key。保留 microseconds，不依賴 SQLite 的預設 datetime adapter。沒有把 naive datetime 當成已知時區。

Schema 用 NOT NULL、CHECK、UNIQUE 防止基本錯誤；寫入前沿用 Phase 2 DTO validation。`None` 直接 bind 為 SQL NULL，0 仍保存為 0.0；不存入 `24°C` 之類 display string。

## Repository API

`WeatherForecastRepository(database)` 擁有一個 connection。未指定路徑時預設 `:memory:`；使用 `with` 或呼叫 `close()` 釋放。父目錄需事先存在，不自動建立任意目錄。

| Method | 行為 |
|---|---|
| initialize_database() | 可重複執行的 CREATE TABLE / INDEX，不清空資料 |
| save_forecast(forecast) | 單筆 UPSERT，回傳 None |
| save_forecasts(iterable) | 原子批次 UPSERT；回傳處理筆數，不是新增 row 數 |
| get_forecasts() | 所有 DTO |
| get_forecasts_by_location(name) | 精確匹配地名 |
| get_forecasts_by_time_range(start, end) | 與 `[start, end)` 重疊的 forecast |
| get_forecast(name, start, end) | 完整 natural key，回傳 DTO 或 None |
| get_locations() | Distinct 地名，排序後回傳 |
| count_forecasts() | DB row count |
| count_duplicate_keys() | 重複 key 群組數，正常為 0 |
| check_integrity() | SQLite integrity_check 與 DTO 不變量檢查 |

所有查詢結果固定依 `location_name → start_time → end_time` 排序。Storage 排序與 Phase 2 原始縣市順序不同；不修改 Parser 排序契約。Repository 回傳原有 DTO，id / audit columns 僅是儲存 metadata。

時間範圍規則：`forecast.start < query.end AND forecast.end > query.start`。僅接觸端點不算重疊；要求 aware datetime 且 query.start < query.end。完整相等期間請用 `get_forecast`。

## Write / transaction semantics

- 每個 repository 一個 connection，每次 batch 一次明確 BEGIN；成功 COMMIT。
- 批次裡出現 SQLite error、DTO validation error 或輸入 generator 例外，一律透過 connection context ROLLBACK 全批。
- 沒有 DELETE + INSERT，也沒有 `INSERT OR REPLACE`。使用 `INSERT ... ON CONFLICT ... DO UPDATE`。
- 重複 key 更新氣象欄位及 updated_at；保留 id、created_at。相同 batch 內同 key 多次出現時最後一筆生效，包括 None 覆蓋舊數值。
- 同批使用一個 UTC audit timestamp；updated_at 代表匯入時間，不是 CWA 發布時間。重匯相同值仍更新 updated_at。
- 空 batch 回傳 0，無資料變更。
- SQLite errors 轉為 `WeatherDataError(code='DATABASE_ERROR')`，提供操作與 SQLite error name，不洩漏 SQL 參數、原始 DB 路徑或敏感本文。輸入 generator 自身的例外 rollback 後原樣傳出，沒有 silent catch。
- `with WeatherForecastRepository(...)` 僅管理生命週期；各 save call 獨立 commit，不構成跨多個方法的外層 transaction。
- 使用單執行緒 connection、5 秒 lock timeout；未新增跨執行緒 pool、migration framework 或重試策略。

## 使用範例

```python
from pathlib import Path
from weather_data.parser import parse_response
from weather_data.storage import WeatherForecastRepository

forecasts = parse_response(Path('tests/fixtures/cwa_weather.json').read_bytes())
with WeatherForecastRepository('weather.sqlite3') as repository:
    repository.initialize_database()
    repository.save_forecasts(forecasts)
    rows = repository.get_forecasts()
    locations = repository.get_locations()
    repository.check_integrity()
```

此範例會建立本地持久化檔案；自動測試與驗收**不執行此範例**，只使用隔離的 memory / temporary DB。

## Validation / Tests

在 repository 目錄執行：

```powershell
# 暫存 SQLite，Fixture → Parser → Save → Query → Integrity → 自動清理
.venv/Scripts/python -X utf8 validate_storage.py

# Storage 單元與 Fixture integration tests
.venv/Scripts/python -X utf8 -m unittest tests.test_storage tests.test_storage_integration -v

# 全部回歸測試
.venv/Scripts/python -X utf8 -m unittest discover -s tests -v

# 語法編譯
.venv/Scripts/python -m compileall -q weather_data validate_cwa.py validate_processing.py validate_storage.py tests
```

驗收可用 `--fixture path/to/response.json` 指定輸入；預設 Fixture 相對腳本位置，不受工作目錄影響。不提供 production DB 參數，避免驗收污染正式資料。

驗收不僅比對筆數，也逐筆比較所有 DTO 欄位與 timestamp、查詢 location / time range / exact key、重複匯入、檢查 duplicate groups，並執行「已更新及新增後刻意中斷」驗證 rollback。任何必要檢查失敗都 exit 1 / FAIL；通過 exit 0 / PASS。TemporaryDirectory 在正常及失敗流程都清除檔案，connection 先關閉再清理。

Fixture 預期：Parsed 66、Stored 66、Queried 66、Locations 22、Duplicate Keys 0。此數字僅屬固定 Snapshot 測試，production repository 未 hard-code 筆數或地區。

## Git / limitations

`.gitignore` 排除 `*.db`、`*.sqlite`、`*.sqlite3` 及對應 WAL / SHM / journal sidecar。不提交本地 DB；Fixture 與 Phase 1/2 source 維持原狀。

本版建立新 schema，不自動遷移既有不相容 DB；若提供外部自行建立的 DB，需先確保 schema 相符。所有正式資料讀寫應走 repository；不支援任意外部 SQL 寫入後自動修復資料。不新增 DB deployment、GIS、Chart、UI、Supabase 或 AI。
