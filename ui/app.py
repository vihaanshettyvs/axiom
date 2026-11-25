import streamlit as st
from mock_data import get_mock_runlog
from map_view import render_map
from panels import render_top_metrics, render_decisions_feed, render_satellite_table
from retire_lab import render_retire_lab

st.set_page_config(page_title="Orbital Triage + Disaster Watch", layout="wide")
st.title("🛰️ Orbital Triage + Disaster Watch")

# Sidebar Controls
st.sidebar.header("Simulation Controls")
brain_on = st.sidebar.toggle("Triage Brain ON", value=True)
frames = get_mock_runlog(brain_on=brain_on)

t = st.sidebar.slider("Simulation Time (minutes)", min_value=0, max_value=len(frames) - 1, value=0)
current_frame = frames[t]

# Tabs
tab1, tab2 = st.tabs(["🗺️ Mission Control", "🧪 Retirement Lab"])

with tab1:
    render_top_metrics(current_frame)
    col_map, col_feed = st.columns([2, 1])
    with col_map:
        st.plotly_chart(render_map(current_frame), use_container_width=True)
    with col_feed:
        render_decisions_feed(frames[: t + 1])
        render_satellite_table(current_frame)

with tab2:
    render_retire_lab()
