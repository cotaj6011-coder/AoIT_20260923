# AIoT DIC-2 工作流程
## Taiwan Weather GIS — CWA Open Data × GIS × GitHub × Vercel

## 1. 專案目標

建立一個以中央氣象署 CWA Open Data 為主要資料來源的台灣氣象 GIS Web App，整合氣象資料、地理位置資訊與互動式地圖，並透過 GitHub 進行版本管理、Vercel 進行正式部署。

第一版以可完成、可展示、可部署為優先，不一次加入過多功能。

---

## 2. MVP 範圍

第一版至少完成以下功能：

- 取得 CWA Open Data 氣象資料。
- 解析並正規化 CWA JSON。
- 顯示台灣 GIS 地圖。
- 在地圖上顯示各地區氣溫 Marker。
- 支援日期或預報時段切換。
- 點擊地圖 Marker 顯示氣象詳細資料。
- 顯示氣溫趨勢圖。
- 顯示基本氣象資料表。
- 將程式碼上傳 GitHub。
- 部署至 Vercel。
- CWA API Key 不可暴露於前端或 GitHub。

MVP 建議先使用：

- Temperature
- Min Temperature
- Max Temperature
- Probability of Precipitation
- Weather Description
- Latitude / Longitude

---

## 3. 系統工作流程

```text
CWA Open Data API
        │
        ▼
Weather API Client
        │
        ▼
JSON Parsing
        │
        ▼
Data Normalization
        │
        ├───────────────┐
        ▼               ▼
Weather Data        GIS Location Data
        │               │
        └───────┬───────┘
                ▼
          Backend API
                │
                ▼
        Taiwan GIS Web App
                │
       ┌────────┼────────┐
       ▼        ▼        ▼
      Map      Chart    Table
                │
                ▼
             GitHub
                │
                ▼
             Vercel
```

---

## 4. 建議技術架構

| Layer | Technology |
|---|---|
| Data Source | CWA Open Data |
| Data Format | JSON |
| Frontend | Next.js / React |
| Backend API | Next.js API Route / Vercel Function |
| GIS | Leaflet |
| Basemap | OpenStreetMap |
| Chart | Recharts / Chart.js |
| GIS Data | Latitude / Longitude / GeoJSON |
| Database | 第一版可不使用 |
| Optional DB | Supabase PostgreSQL |
| Version Control | Git + GitHub |
| Deployment | Vercel |

SQLite 可保留在本機實驗或教學用途，但不建議作為 Vercel 正式環境的主要持久化資料庫。

---

# 5. Phase 1 — CWA API 驗證

## Goal

確認 CWA API 可以取得真實資料，並掌握 JSON 結構。

## Tasks

1. 建立 CWA API Key。
2. 將 API Key 存入 `.env.local`。
3. 建立 `.env.example`。
4. `.gitignore` 排除 `.env.local`。
5. 呼叫指定 CWA Dataset。
6. 保存一份真實 JSON Sample。
7. 確認 Response Status。
8. 確認資料更新時間。
9. 確認需要的欄位 JSON Path。
10. 記錄 API Dataset ID 與資料來源。

## Deliverable

```text
docs/
└── cwa-api.md

tests/
└── fixtures/
    └── cwa-weather.json
```

## Acceptance Criteria

- HTTP Request 成功。
- JSON 可正常解析。
- 已確認 Temperature / MinT / MaxT / PoP / Wx 欄位位置。
- API Key 未 Commit。

---

# 6. Phase 2 — Weather Data Normalization

不要讓 Frontend 直接依賴 CWA 原始 JSON 結構。

建立統一的 Weather DTO。

例如：

```json
{
  "locationId": "taichung",
  "locationName": "臺中市",
  "latitude": 24.1477,
  "longitude": 120.6736,
  "forecastTime": "2026-09-24T12:00:00+08:00",
  "minTemp": 24,
  "maxTemp": 31,
  "temperature": 29,
  "rainProbability": 30,
  "weather": "多雲短暫陣雨"
}
```

## Tasks

1. 建立 CWA API Client。
2. 建立 Raw CWA Model。
3. 建立 Weather DTO。
4. 建立 Parser / Mapper。
5. 處理 Nullable 欄位。
6. 處理無效溫度資料。
7. 處理 API Timeout。
8. 處理 CWA API Failure。
9. 加入基本 Unit Test。

## Acceptance Criteria

- Frontend 不需要知道 CWA JSON 原始結構。
- 不同地區輸出格式一致。
- API 發生錯誤時不造成整個網站 Crash。

---

# 7. Phase 3 — GIS 基礎地圖

## Goal

建立 Taiwan Weather GIS 主畫面。

## Tasks

1. 安裝 Leaflet。
2. 建立 Taiwan Map Component。
3. 使用 OpenStreetMap Basemap。
4. 設定台灣為預設 Map Center。
5. 加入 Zoom。
6. 建立 Weather Marker。
7. Marker 綁定 Latitude / Longitude。
8. Marker Popup 顯示基本氣象資料。

## Marker Example

```text
臺中市

Temperature: 29°C
Min: 24°C
Max: 31°C
Rain: 30%
Weather: 多雲短暫陣雨
```

## Acceptance Criteria

- 台灣地圖正常載入。
- Marker 座標正確。
- Marker 可點擊。
- Popup 可顯示對應氣象資料。

---

# 8. Phase 4 — Weather GIS Visualization

將氣象資料視覺化，而不是只放普通 Marker。

第一版可以先依溫度分類。

| Temperature | Display |
|---|---|
| < 20°C | Cold |
| 20–25°C | Cool |
| 25–30°C | Warm |
| > 30°C | Hot |

## Tasks

1. 建立 Temperature Style Rule。
2. Marker 顯示目前氣溫。
3. 不同溫度套用不同視覺狀態。
4. 建立 Legend。
5. Marker Popup 顯示完整資料。
6. 加入資料最後更新時間。

## Acceptance Criteria

使用者不需要逐一點擊 Marker，也能大致看出台灣各地溫度分布。

---

# 9. Phase 5 — Forecast Date / Time

## Goal

讓 GIS 不只顯示單一時間點。

## UI

```text
Forecast Date

[ 2026-09-23 ▼ ]
```

或：

```text
Today | Tomorrow | +2 Days | +3 Days
```

## Tasks

1. 整理 Forecast Date List。
2. 建立 Date Selector。
3. Date Change 時更新 Marker。
4. Date Change 時更新 Chart。
5. Date Change 時更新 Table。
6. 確認所有 Component 使用同一份選定日期 State。

## Acceptance Criteria

切換日期後：

```text
Map
Chart
Table
```

必須同步更新。

---

# 10. Phase 6 — Chart

建立選定地區的溫度趨勢圖。

## Example

```text
Temperature Forecast — 臺中市

32 ┤
31 ┤       ●
30 ┤   ●       ●
29 ┤
28 ┤ ●
   └────────────────
     Day1 Day2 Day3
```

## Tasks

1. 選擇 Chart Library。
2. 建立 Weather Chart Component。
3. 顯示 MinT。
4. 顯示 MaxT。
5. 可選擇地區。
6. Tooltip 顯示日期及溫度。

## Acceptance Criteria

Chart 與 Map 使用相同資料來源。

---

# 11. Phase 7 — Weather Table

提供可直接閱讀與驗證的資料表。

建議欄位：

| Location | Date | Min | Max | Rain | Weather |
|---|---|---:|---:|---:|---|
| 臺中市 | 2026-09-23 | 24 | 31 | 30% | 多雲 |

## Tasks

1. 建立 Weather Table。
2. 支援 Date Filter。
3. 支援 Location Filter。
4. 與 Map / Chart 共用 Weather DTO。

---

# 12. Phase 8 — GIS Layer

完成 MVP 後，再增加 Layer Control。

例如：

```text
Layers

☑ Temperature
☐ Rainfall
☐ Weather Stations
☐ AQI
```

第一版先完成 Temperature。

第二版再增加：

- Rainfall
- Weather Stations
- AQI
- GeoJSON Boundary
- Heatmap

---

# 13. Phase 9 — Open Data Integration

如果課程要求強調 Open Data，可以增加第二個政府資料來源。

候選：

- EPA AQI
- CWA Rainfall
- CWA Weather Stations
- Flood Warning
- River Water Level
- UV Index

架構：

```text
CWA Weather
     │
     ├── Temperature
     ├── Rain
     └── Weather

Other Open Data
     │
     └── AQI

          ↓

       GIS Layers
```

此階段不是 MVP 必要功能。

---

# 14. Phase 10 — Backend API

不要讓 Browser 直接帶 CWA API Key 呼叫 CWA。

正確流程：

```text
Browser
   │
   ▼
/api/weather
   │
   ▼
Server / Vercel Function
   │
   ▼
CWA Open Data API
```

錯誤做法：

```text
Browser
   │
   ▼
CWA API + API Key
```

## Tasks

1. 建立 `/api/weather`。
2. Server 端讀取 `CWA_API_KEY`。
3. API 呼叫 CWA。
4. Parse CWA JSON。
5. 回傳 Weather DTO。
6. 加入錯誤處理。
7. Optional Cache。

---

# 15. Phase 11 — GitHub

Repository 建議：

```text
aiot-dic2-weather-gis/

├── app/
│   ├── page.tsx
│   └── api/
│       └── weather/
│
├── components/
│   ├── WeatherMap.tsx
│   ├── WeatherMarker.tsx
│   ├── WeatherChart.tsx
│   └── WeatherTable.tsx
│
├── lib/
│   ├── cwa.ts
│   ├── weather.ts
│   └── gis.ts
│
├── public/
│   └── geojson/
│
├── tests/
│
├── docs/
│
├── .env.example
├── .gitignore
├── README.md
└── package.json
```

## README 至少包含

- Project Overview
- Screenshot
- Architecture
- Data Source
- CWA Dataset
- GIS
- Installation
- Environment Variables
- Run Locally
- Deployment
- Demo URL

---

# 16. Phase 12 — Vercel Deployment

## Flow

```text
Local Development
       │
       ▼
     Git
       │
       ▼
    GitHub
       │
       ▼
    Vercel
       │
       ▼
Production URL
```

## Tasks

1. GitHub Repository 建立完成。
2. Vercel Import GitHub Repository。
3. 設定 Framework。
4. 設定 `CWA_API_KEY`。
5. Production Build。
6. 執行 Smoke Test。
7. 驗證 API。
8. 驗證 GIS。
9. 驗證 Chart。
10. 驗證手機 / Desktop 基本版面。

## Acceptance Criteria

GitHub Push 後可以自動 Deployment。

---

# 17. Phase 13 — Testing

至少建立以下測試：

## API

- CWA API 正常。
- CWA API Timeout。
- Unauthorized。
- Invalid JSON。
- Empty Dataset。

## Parser

- MinT。
- MaxT。
- Rain Probability。
- Weather Description。
- Missing Field。

## GIS

- Latitude / Longitude 存在。
- Location 與座標對應正確。

## UI

- Map 可以 Render。
- Date Selector 可切換。
- Marker 正確更新。
- Chart 正確更新。

---

# 18. Phase 14 — Optional AI Feature

AI 不列入第一版必要功能。

完成 GIS MVP 後再加入。

可考慮：

## Weather Activity Recommendation

Input：

```text
Temperature
Humidity
Rain
Wind
```

Output：

```text
Outdoor Activity

Suitable
Moderate
Not Recommended
```

第一版甚至可以先使用 Rule-based Engine，未來再替換成 AI / ML。

---

# 19. 最終 Demo 流程

上台展示建議依下列順序：

1. 開啟 GitHub Repository。
2. 簡單展示 README 與 Architecture。
3. 開啟 Vercel Production URL。
4. 展示 Taiwan GIS。
5. 展示不同地區 Temperature Marker。
6. 點擊臺中市 Marker。
7. 展示 Weather Popup。
8. 切換 Forecast Date。
9. GIS Marker 自動更新。
10. 展示 Temperature Chart。
11. 展示 Weather Table。
12. 說明資料來自 CWA Open Data。
13. 說明 API Key 保存在 Vercel Environment Variable。
14. Optional：切換 Rainfall / AQI GIS Layer。

---

# 20. 建議開發順序

```text
01 CWA API
      ↓
02 JSON Validation
      ↓
03 Weather DTO
      ↓
04 Backend API
      ↓
05 GIS Map
      ↓
06 Weather Marker
      ↓
07 Date Selector
      ↓
08 Chart
      ↓
09 Table
      ↓
10 GIS Layer
      ↓
11 GitHub
      ↓
12 Vercel
      ↓
13 Testing
      ↓
14 Optional Open Data
      ↓
15 Optional AI
```

---

# 21. Definition of Done

DIC-2 第一版完成的最低標準：

- CWA 真實資料可取得。
- CWA JSON 已正確解析。
- Weather DTO 結構固定。
- 台灣 GIS 可以正常顯示。
- 至少有 Temperature Marker。
- Marker 可以查看氣象資料。
- 可以切換 Forecast Date。
- 有氣溫 Chart。
- 有 Weather Table。
- GitHub Repository 可正常 Clone / Build。
- API Key 沒有暴露。
- Vercel Production Deployment 成功。
- README 有架構、資料來源與操作說明。
- Demo 可以從頭到尾完整操作。

完成上述內容後，再增加 AQI、Rainfall、Heatmap 或 AI，避免第一版 Scope 過大。
