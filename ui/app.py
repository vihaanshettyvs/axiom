import sys
import time
from pathlib import Path
import plotly.graph_objects as go
import streamlit as st
sys.path.insert(0, str(Path(__file__).resolve().parent))
from charts import build_mission_timeline
from data_loader import evaluate_frame, list_json_files, load_mock_runlog, load_runlog_from_bytes, load_runlog_from_path
from map_view import build_map_figure
from panels import render_kpi_cards, render_target_table
from retire_lab import render_retire_lab
st.set_page_config(page_title="Orbital Triage Mission Control", layout="wide")
if "t_idx" not in st.session_state:
    st.session_state.t_idx = 0
if "is_playing" not in st.session_state:
    st.session_state.is_playing = False
if "retired_sats" not in st.session_state:
    st.session_state.retired_sats = set()
with st.sidebar:
    st.title("Mission Controls")
    brain_on = st.toggle("Brain ON (Triage AI)", value=True)
    st.divider()
    st.subheader("RunLog Data Source")
    data_mode = st.radio("Source", ["Mock Data", "Real RunLog JSON"], index=0)
    runlog = None
    if data_mode == "Real RunLog JSON":
        json_files = list_json_files()
        if json_files:
            selected_file = st.selectbox("Select JSON from data/", options=json_files, format_func=lambda p: p.name)
            runlog = load_runlog_from_path(selected_file)
        else:
            st.info("No .json files found in data/ yet. Upload one below:")
        uploaded = st.file_uploader("Or upload RunLog JSON", type=["json"])
        if uploaded is not None:
            runlog = load_runlog_from_bytes(uploaded)
    if runlog is None:
        runlog = load_mock_runlog()
    source_label = runlog.get("meta", {}).get("source", "RunLog")
    st.caption(f"Source: **{source_label}**")
    st.caption(f"Retired satellites: **{len(st.session_state.retired_sats)}**")
frames = runlog.get("frames", [])
targets = runlog.get("targets", [])
num_frames = len(frames)
if num_frames == 0:
    st.title("Orbital Triage - Policy Comparison")
    raw_data = runlog.get("raw") if isinstance(runlog.get("raw"), dict) else {}
    metrics_map = raw_data.get("metrics") if isinstance(raw_data.get("metrics"), dict) else {}
    if metrics_map:
        top_keys = ["mean_time_to_detect_min", "mean_time_to_localize_min", "mean_detection_latency_min", "bandwidth_mb"]
        cols = st.columns(4)
        for idx, k in enumerate(top_keys):
            entry = metrics_map.get(k)
            if isinstance(entry, dict):
                b_on = entry.get("brain_on", "-")
                imp = entry.get("improvement_pct")
                with cols[idx]:
                    st.metric(label=k.replace("_", " ").title(), value=f"{b_on:.2f}" if isinstance(b_on, (int, float)) else str(b_on), delta=f"{imp:+.1f}% improvement" if isinstance(imp, (int, float)) else None)
        comp_rows = []
        bar_metrics, bar_on, bar_off = [], [], []
        for metric_name, vals in metrics_map.items():
            if isinstance(vals, dict):
                on_v = vals.get("brain_on")
                off_v = vals.get("brain_off")
                imp_v = vals.get("improvement_pct")
                comp_rows.append({"Metric": metric_name, "Brain ON": round(on_v, 4) if isinstance(on_v, float) else on_v, "Brain OFF": round(off_v, 4) if isinstance(off_v, float) else off_v, "Improvement (%)": round(imp_v, 2) if isinstance(imp_v, float) else imp_v})
                if isinstance(on_v, (int, float)) and isinstance(off_v, (int, float)):
                    bar_metrics.append(metric_name)
                    bar_on.append(on_v)
                    bar_off.append(off_v)
        if bar_metrics:
            bar_fig = go.Figure()
            bar_fig.add_trace(go.Bar(name="Brain ON", x=bar_metrics, y=bar_on))
            bar_fig.add_trace(go.Bar(name="Brain OFF", x=bar_metrics, y=bar_off))
            bar_fig.update_layout(barmode="group", height=340, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(bar_fig)
        if comp_rows:
            st.subheader("All Benchmark Metrics")
            st.dataframe(comp_rows, hide_index=True, width="stretch")
    else:
        st.warning("No frame or benchmark data found in this JSON.")
    st.stop()
st.session_state.t_idx = min(st.session_state.t_idx, num_frames - 1)
st.title("Orbital Triage Dashboard")
p1, p2, p3, p4 = st.columns([1.2, 1.0, 1.4, 5.4])
with p1:
    play_label = "Pause" if st.session_state.is_playing else "Play"
    if st.button(play_label, width="stretch"):
        st.session_state.is_playing = not st.session_state.is_playing
        st.rerun()
with p2:
    if st.button("Reset", width="stretch"):
        st.session_state.is_playing = False
        st.session_state.t_idx = 0
        st.rerun()
with p3:
    speed = st.selectbox("Speed", ["1x", "2x", "5x"], index=0, label_visibility="collapsed")
with p4:
    slider_val = st.slider("Simulation Timestep", min_value=0, max_value=num_frames - 1, value=st.session_state.t_idx, label_visibility="collapsed")
    if slider_val != st.session_state.t_idx:
        st.session_state.t_idx = slider_val
current_frame = frames[st.session_state.t_idx]
ts = current_frame.get("timestamp", "")
st.caption(f"Frame **{st.session_state.t_idx + 1} / {num_frames}** - `{ts}`")
active_mode = "brain_on" if brain_on else "brain_off"
retired_set = st.session_state.retired_sats
active_eval = evaluate_frame(current_frame, targets, active_mode, retired_set)
baseline_eval = evaluate_frame(current_frame, targets, "brain_off", retired_set)
no_retire_eval = evaluate_frame(current_frame, targets, active_mode, set())
render_kpi_cards(active_eval, baseline_eval, brain_on)
st.divider()
map_col, lab_col = st.columns([2.6, 1.2])
with map_col:
    fig = build_map_figure(satellites=active_eval["satellites"], targets=targets, covered_ids=active_eval["covered_ids"])
    st.plotly_chart(fig)
    render_target_table(active_eval)
with lab_col:
    render_retire_lab(satellites=active_eval["satellites"], eval_no_retire=no_retire_eval, eval_with_retire=active_eval, brain_on=brain_on)
st.divider()
timeline_fig = build_mission_timeline(frames=frames, targets=targets, retired_sats=retired_set, current_idx=st.session_state.t_idx)
st.plotly_chart(timeline_fig)
if st.session_state.is_playing:
    delay_map = {"1x": 0.6, "2x": 0.3, "5x": 0.12}
    time.sleep(delay_map[speed])
    st.session_state.t_idx = (st.session_state.t_idx + 1) % num_frames
    st.rerun()
