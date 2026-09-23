"""Map-first county forecast dashboard backed by the existing repository."""
from datetime import datetime, timezone
import logging
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from weather_data.dashboard import DEFAULT_DATABASE, chart_data, filter_forecasts, load_dashboard, table_data
from weather_data.errors import WeatherDataError
from weather_data.gis import create_map, prepare_markers
from weather_data.presentation import clicked_location, default_interval, forecast_intervals, interval_label, temperature_label

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent


def main() -> None:
    st.set_page_config(page_title="臺灣天氣地圖", page_icon="🌤️", layout="wide")
    st.html('<style>' + (ROOT / 'weather_data/dashboard.css').read_text(encoding='utf-8') + '</style>')
    try:
        frame, updated = load_dashboard(Path(os.environ.get("WEATHER_DATABASE", str(DEFAULT_DATABASE))))
    except WeatherDataError as exc:
        LOGGER.exception("Dashboard repository read failed [%s]", exc.code)
        st.error("找不到天氣資料庫，請先匯入資料。" if exc.code == "DATABASE_MISSING" else "無法讀取天氣資料，請檢查資料庫。")
        return
    except Exception:
        LOGGER.exception("Unexpected dashboard data loading failure")
        st.error("天氣資料載入失敗，請稍後重試。")
        return
    if frame.empty:
        st.info("目前沒有預報資料。")
        return

    periods = forecast_intervals(frame)
    now = datetime.now(timezone.utc)
    if st.session_state.get('interval') not in periods:
        st.session_state.interval = default_interval(periods, now)
    controls = st.container(key='corner_controls')
    with controls:
        interval = st.selectbox("預報時段", periods, key='interval', format_func=interval_label)
    nationwide = filter_forecasts(frame, interval=interval)
    locations = sorted(nationwide.location_name.unique())
    if not locations:
        st.info("此時段沒有預報資料。")
        return
    pending = st.session_state.pop('_pending_location', None)
    if pending in locations:
        st.session_state.location = pending
    if st.session_state.get('location') not in locations:
        st.session_state.location = locations[0]
    with controls:
        location = st.selectbox("縣市明細（也可點選地圖）", locations, key='location')
    filtered = filter_forecasts(nationwide, location)
    row = filtered.iloc[0]
    with st.container(key='corner_summary'):
        st.html('<div class="eyebrow">TAIWAN WEATHER</div>')
        st.title("臺灣天氣地圖")
        summary = st.columns(2)
        summary[0].metric("選取縣市", location)
        summary[1].metric("預報最高溫", temperature_label(row.max_temperature))
        summary = st.columns(2)
        summary[0].metric("預報最低溫", temperature_label(row.min_temperature))
        summary[1].metric("降雨機率", "—" if pd.isna(row.rain_probability) else f"{row.rain_probability:g}%")
        st.caption(f"{row.weather_description or '天氣描述未提供'} · {interval_label(interval)}")
        if datetime.fromisoformat(interval[1]) <= now:
            st.caption("◷ 歷史預報 · 所選時段已結束，非目前天氣。")

    try:
        data = prepare_markers(nationwide)
        if data.missing_locations or data.invalid_locations:
            st.warning(f"已略過無有效座標地區：缺少 {len(data.missing_locations)}、無效 {len(data.invalid_locations)}。")
        if data.markers:
            map_key = 'weather-map-' + interval[0] + interval[1]
            # Keep map identity stable when only the detail location changes.
            with st.container(key='map_canvas'):
                event = st_folium(create_map(data), key=map_key, height=580, use_container_width=True,
                                  returned_objects=['last_object_clicked', 'last_object_clicked_count'])
            selected = clicked_location(event, data)
            if selected is None:
                st.session_state._handled_map_click = None
            token = (map_key, selected, event.get('last_object_clicked_count')) if isinstance(event, dict) else None
            if selected and token != st.session_state.get('_handled_map_click'):
                st.session_state._handled_map_click = token
                if selected != location:
                    st.session_state._pending_location = selected
                    st.rerun()
        else:
            st.info("所選時段沒有可顯示的地圖標記，仍可查看下方資料。")
    except Exception:
        LOGGER.exception("Weather map rendering failed")
        st.error("地圖暫時無法顯示，預報明細仍可使用。")

    with st.container(key='corner_details'):
        st.caption(f"全臺 {len(nationwide)} 個縣市預報 · 座標僅供縣市定位，不代表測站觀測。")
        with st.expander(f"{location} · 溫度圖與預報明細", expanded=False):
            st.caption("與地圖使用相同預報時段；更換上方時段可查看其他預報。")
            chart = chart_data(filtered)
            if chart[['min_temperature', 'max_temperature']].notna().any().any():
                st.scatter_chart(chart.rename(columns={'min_temperature': '最低溫', 'max_temperature': '最高溫'}),
                                 x='start_time', y=['最低溫', '最高溫'], x_label='預報時間', y_label='溫度 °C',
                                 color=['#60a5fa', '#fb7185'], height=240)
            else:
                st.info("此時段未提供溫度資料；缺值不會當成 0°C。")
            st.dataframe(table_data(filtered), hide_index=True, column_config={
                'location_name': '縣市', 'start_time': '開始時間 (+08:00)', 'end_time': '結束時間 (+08:00)',
                'min_temperature': '最低溫 °C', 'max_temperature': '最高溫 °C',
                'rain_probability': '降雨機率 %', 'weather_description': '天氣',
            })
        stamp = updated.astimezone(row.start_time.tzinfo).strftime('%Y/%m/%d %H:%M') if updated else '未提供'
        st.caption(f"資料庫匯入：{stamp} · 非 CWA 發布時間 · 地圖來源標示見右下角")



if __name__ == '__main__':
    main()
