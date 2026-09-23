# Phase 2 — Data Processing

## Purpose / Phase 1 dependency check

將 Phase 1 真實 CWA JSON 轉為可重用的 `WeatherForecast` DTO。本階段沒有新增套件、DB、SQL、GIS、UI、Chart 或網路資料來源。

- Dataset：`F-C0032-001`，沿用 Phase 1。
- 真實 Fixture：`tests/fixtures/cwa_weather.json`，未修改。
- Source：Phase 1 Python Client 取得的 HTTP 200 Response；取得時間 `2026-09-23T11:51:43.304831+00:00`，詳見相鄰 metadata。
- SHA-256：`1235d181608be07e9f0b22f0a095e16afdaab5f2ca6e13c135370abdd45bf750`。
- Phase 1 已有 Client、環境設定、Parser、DTO、85 個通過的測試與 [API 文件](cwa-api.md)。實作 Phase 2 前再次執行真實 Integration，HTTP 200 / PASS。
- 不需補外部資料；Phase 2 預設執行不需 Key 或網路。

## Input format / 實際 JSON Paths

沿用 `parse_response(body: bytes)` 與 `parse_forecasts(data: dict[str, Any])` 兩個公開入口，回傳 `list[WeatherForecast]`。

根節點為 object，`success="true"`（兼容 boolean true）、`result.resource_id="F-C0032-001"`。資料位於 `records.location`，不是 `records.locations[0].location`。

下表 `L` 代表 `$.records.location[*]`，`E` 代表 `L.weatherElement[*]`。

| 語意 | 實際路徑 |
|---|---|
| Location collection | `$.records.location` |
| Location name | `L.locationName` |
| Weather elements | `L.weatherElement` |
| Element name | `E.elementName` |
| MinT | `L.weatherElement[?(@.elementName=='MinT')].time[*].parameter.parameterName` |
| MaxT | `L.weatherElement[?(@.elementName=='MaxT')].time[*].parameter.parameterName` |
| Start | `E.time[*].startTime` |
| End | `E.time[*].endTime` |
| Unit | `E.time[*].parameter.parameterUnit` |

逐一走訪全部 22 縣市：每個縣市的 Wx／PoP／MinT／CI／MaxT 均有 3 個時段，各元素的完整起訖時間集合在此 Fixture **完全相同**。MinT／MaxT unit 為 `C`，PoP 為 `百分比`，Wx／CI 無 unit。值來自 `parameterName`，不是 `parameterValue`。

Fixture 沒有獨立 Forecast Date／發布時間欄位。`forecast_date` 由正規化後的 `start_time.date()` 計算；metadata 擷取時間不是資料發布時間。22／66 是 Snapshot 驗證結果，不是 production parser 的限制。

## Parsing flow / 單一責任

```text
Raw JSON bytes
  → decode_json（既有嚴格 JSON 檢查）
  → parse_forecasts（確認 envelope、Dataset、Location）
  → _index_elements（elementName → element）
  → _index_periods（(start, end) → 原始值）
  → _parse_location（區間聯集、建立 DTO）
  → WeatherForecast（沿用數值正規化及 sanity validation）
  → validate_forecasts（全體 DTO 不變量）
```

所有 CWA dictionary traversal、element lookup、time mapping 都留在 `parser.py`。Model 只理解 application 欄位；沿用 Phase 1 的共用 numeric conversion，不複製另一套轉換。下游只使用 DTO，不重新走訪原始 CWA JSON。

## Time alignment strategy

唯一 forecast key 為 `(location_name, start_time, end_time)`。先在每個縣市內依元素名稱建立索引，再對完整 `(start, end)` 建立索引，最後對所有保留元素的區間做 **full outer join（聯集）**。

- 不使用固定元素陣列位置或 `zip`。
- MinT／MaxT 的原始順序、筆數可以不同。
- 缺一個元素或一個時段，該區間對應值為 `None`。
- 相同 start、不同 end 是不同區間；互相重疊也不推估或合併。
- 例如 MinT 08:00–18:00、MaxT 18:00–翌日06:00 會輸出兩筆，各缺另一侧溫度；不跨時段配成一筆。
- PoP／Wx 保留相同配對規則；只有它們提供的區間也保留，MinT／MaxT 為 `None`。
- 同一元素重複完整區間、反向／空區間明確報錯。

**Ordering 沿用 Phase 1**：縣市依輸入第一次出現順序，各縣市內依 start → end 排序。元素或 time array 重新排列不改結果；Location array 改順序時，輸出縣市順序相應改變，這是既有公開契約。

## Time normalization

真實 Fixture 使用 `YYYY-MM-DD HH:MM:SS`，沒有 timezone suffix；指定台灣 UTC+08:00。

Phase 2 額外支援完整 ISO 秒級時間 `YYYY-MM-DDTHH:MM:SS+08:00`、`Z`、其他合法 `±HH:MM` offset。保留其代表的 instant，統一轉為 UTC+08:00 aware datetime 再配對。這是相容性擴充，測試為合成 mutation，**不宣稱 Fixture 原本就含 ISO offset**。

僅日期、錯誤日曆日期、非法 offset、不完整時間會回報 `INVALID_TIME`。不支援小數秒、timezone 名称或日光節約時間名稱。台灣 offset 以標準函式庫 fixed-offset 表示，不引入 tzdata 依賴。

## Temperature conversion / invalid data policy

沿用 Phase 1 `optional_number`：

| 輸入／情況 | 結果 |
|---|---|
| int / float / numeric string / 外圍空白 | 有限 `float` |
| 0、合理負溫 | 保留，不當成缺值 |
| null / 空字串 / 空白 / 缺少 parameterName | `None` |
| ABC / N/A / bool / NaN / Infinity / 不合法型別 | `None` |
| 溫度超出 -90～60°C | `None`，沿用應用防呆政策 |
| 缺少整個 MinT／MaxT | 其他元素區間中的該值 `None` |
| MinT > MaxT | `INVALID_FORECAST`，整次解析失敗，不交換值 |
| Missing/empty locationName | `INVALID_SCHEMA`，含 Location 位置 |
| Duplicate locationName（trim 後） | `INVALID_SCHEMA`；此縣市預報資料集不接受重複 location |
| Duplicate element | `INVALID_SCHEMA` |
| Invalid time | `INVALID_TIME` |
| 反向／重複 element interval | `TIME_ALIGNMENT_ERROR` |
| 必要 container 型別不符或錯誤溫度單位 | `INVALID_SCHEMA` |
| 空 location list | Parser 回傳 `[]`；驗收入口 FAIL |
| 空 body、空 root `{}`、非法 JSON | 沿用 `EMPTY_RESPONSE` / `INVALID_JSON` 等錯誤，不造資料 |
| 非 object root | `INVALID_ROOT`（bytes 入口）或 `INVALID_SCHEMA`（dict 入口） |

`-99/-999/-9999` 的合成測試因溫度範圍而回傳 None；Phase 1 真實 Fixture 未出現 missing code，因此不聲稱這些數字已由官方／真實資料確認為特殊代碼。

沒有設置 logging，也不新增每筆 info log。可容忍的缺值以 DTO 的 `None` 呈現；malformed data 則使用既有 `WeatherDataError`。Parser 錯誤包含 Location、Element、Time（時間無法解析時提供 `time[n]` 與欄位名），不印原始非法值或整份 JSON。Location 中 credential-shaped 文字會先遮蔽。

## Output Weather Model / invariants

`WeatherForecast` 仍為 frozen dataclass，欄位不變：

| 欄位 | 型別 |
|---|---|
| location_name | str |
| start_time | aware datetime，UTC+08:00 |
| end_time | aware datetime，UTC+08:00 |
| min_temperature | float 或 None |
| max_temperature | float 或 None |
| rain_probability | float 或 None |
| weather_description | str 或 None |
| forecast_date | 衍生 date property |

`validate_forecasts(rows)` 可由下游重用：確認 DTO 型別、非空地名、aware 時間、start < end、合理有限數值、MinT ≤ MaxT（兩者均存在時）及無重複 key。成功回傳 `None`，異常 raise `WeatherDataError`。不變量函式不要求有資料；驗收入口另將空結果判 FAIL。

```python
from pathlib import Path
from weather_data.parser import parse_response
from weather_data.model import validate_forecasts

rows = parse_response(Path("tests/fixtures/cwa_weather.json").read_bytes())
validate_forecasts(rows)
for row in rows:
    print(row.location_name, row.start_time.isoformat(), row.min_temperature)
```

## Validation / test commands

在 repository 根目錄執行：

```powershell
# 固定 Fixture；不發送 HTTP、不讀 API Key、不寫檔
.venv/Scripts/python -X utf8 validate_processing.py

# 可另指定待驗證 JSON
.venv/Scripts/python -X utf8 validate_processing.py --fixture path/to/response.json

# 全部離線測試（Phase 1 + Phase 2）
.venv/Scripts/python -X utf8 -m unittest discover -s tests -v

# Phase 2 regression / alignment / missing / conversion / invariant / CLI tests
.venv/Scripts/python -X utf8 -m unittest tests.test_processing -v

# 語法編譯
.venv/Scripts/python -m compileall -q weather_data validate_cwa.py validate_processing.py tests
```

預設 fixture 路徑相對於腳本位置，可從其他工作目錄呼叫。成功 exit 0，驗證失敗 exit 1（CLI 參數錯誤為 2）。不額外加入 `--live`；Phase 1 的獨立驗證入口仍可取得最新資料。

**Parser 可容忍缺值；Phase 2 acceptance CLI 比 Parser 更嚴格**：每個輸出區間必須同時有有效 MinT／MaxT 才標記完整驗收 PASS。缺值／錯開區間會得到 `INCOMPLETE_TEMPERATURES`，而非印出誤導的 `[PASS] Time aligned`。此檢查不聲稱某個完全沒有提供任何元素時段的 location 有完整覆蓋。

固定 Snapshot 結果：22 locations、66 records、MinT range 22–27°C、MaxT range 26–33°C。範圍僅供 sanity check；production validation 不 hard-code 數字或地區。

## 本次驗收結果（2026-09-23）

- Status：COMPLETE。
- 全部 unit tests：120 passed、0 failed、0 skipped；含原有 85 個測試與新增 35 個 Phase 2 測試。
- Phase 2 groups：Regression/Normal 5、Alignment/Order 8、Missing 6、Invalid/Conversion 6、Invariants 4、Offline CLI 6。
- Compileall：PASS。Repository 未設定 formatter/linter，未為本階段新增工具或依賴。
- 預設離線驗證：6 項 PASS，22 縣市、66 筆，無 duplicate key。
- 真實 Fixture 與 metadata/structure 未變更；SHA-256 符合 Phase 1。
- 僅修改／新增 README、此文件、Parser、Model、Phase 2 tests 與驗證入口共 6 檔。Git 可見檔案 secret scan 與 diff whitespace check 通過；未 commit、未 push。

## Known limitations

- 不自動合併重疊區間、推算缺值、改寫 MinT／MaxT 或統一地名異體字。
- 完全沒有任何保留元素時段的縣市不產生 forecast，延續 Phase 1；不憑空建立期間。
- UTC+08:00 策略僅針對本台灣預報 Dataset，非通用國際時區解析器。
- 數值界線沿用 Phase 1；若未來 dataset 引入新的有意義數值或 missing code，需依新證據調整。
- Fixture 是固定歷史 Snapshot，測試不評估是否為最新天氣。
- 無行政區代碼、座標、資料庫 schema 或其他 Phase 功能。
