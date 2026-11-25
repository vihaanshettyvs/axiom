import sys
import time
from pathlib import Path
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_loader import (
    evaluate_frame,
    list_json_files,
    load_mock_runlog,
    load_runlog_from_bytes,
    load_runlog_from_path,
)
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
            selected_file = st.selectbox(
                "Select JSON from data/",
                options=json_files,
                format_func=lambda p: p.name,
            )
            runlog = load_runlog_from_path(selected_file)
        else:
            st.info("No .json files found in data/ yet. Upload one below:")

        uploaded = st.file_uploader("Or upload RunLog JSON", type=["json"])
        if uploaded is not None:
            runlog = load_runlog_from_bytes(uploaded)

    if runlog is None:
        runlog = load_mock_runlog()

    st.caption(f"Loaded: **{runlog['meta'].get('scenario', 'RunLog')}**")
    st.caption(f"Retired satellites: **{len(st.session_state.retired_sats)}**")

frames = runlog.get("frames", [])
targets = runlog.get("targets", [])
num_frames = len(frames)

if num_frames == 0:
    st.title("Orbital Triage — Summary / Comparison View")
    raw_data = runlog.get("raw")
    if isinstance(raw_data, dict) and raw_data:
        st.info(
            f"`{runlog['meta'].get('source', 'JSON')}` is a summary file (no timestep frames). "
            "Displaying comparison metrics below:"
        )
        flat_items = {k: v for k, v in raw_data.items() if not isinstance(v, (dict, list))}
        nested_dicts = {k: v for k, v in raw_data.items() if isinstance(v, dict)}

        if flat_items:
            st.subheader("Overview")
            st.dataframe(
                [{"Metric": k, "Value": str(v)} for k, v in flat_items.items()],
                hide_index=True,
                width="stretch",
            )

        if nested_dicts:
            st.subheader("Policy / Run Comparison")
            all_keys = list(dict.fromkeys(k for d in nested_dicts.values() for k in d.keys()))
            rows = []
            for key in all_keys:
                row = {"Metric": key}
                for group_name, group_dict in nested_dicts.items():
                    val = group_dict.get(key, "—")
                    row[group_name] = str(val) if isinstance(val, (dict, list)) else val
                rows.append(row)
            st.dataframe(rows, hide_index=True, width="stretch")

        with st.expander("View Raw JSON"):
            st.json(raw_data)
    else:
        st.warning("Loaded JSON has 0 frames and no summary metrics to display.")
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
    slider_val = st.slider(
        "Simulation Timestep",
        min_value=0,
        max_value=num_frames - 1,
        value=st.session_state.t_idx,
        label_visibility="collapsed",
    )
    if slider_val != st.session_state.t_idx:
        st.session_state.t_idx = slider_val

current_frame = frames[st.session_state.t_idx]
st.caption(f"Frame **{st.session_state.t_idx + 1} / {num_frames}** — `{current_frame.get('timestamp', '')}`")

active_mode = "brain_on" if brain_on else "brain_off"
retired_set = st.session_state.retired_sats

active_eval = evaluate_frame(current_frame, targets, active_mode, retired_set)
baseline_eval = evaluate_frame(current_frame, targets, "brain_off", retired_set)
no_retire_eval = evaluate_frame(current_frame, targets, active_mode, set())

render_kpi_cards(active_eval, baseline_eval, brain_on)
st.divider()

map_col, lab_col = st.columns([2.6, 1.2])

with map_col:
    fig = build_map_figure(
        satellites=active_eval["satellites"],
        targets=targets,
        covered_ids=active_eval["covered_ids"],
    )
    st.plotly_chart(fig)
    render_target_table(active_eval)

with lab_col:
    render_retire_lab(
        satellites=active_eval["satellites"],
        eval_no_retire=no_retire_eval,
        eval_with_retire=active_eval,
        brain_on=brain_on,
    )

if st.session_state.is_playing:
    delay_map = {"1x": 0.6, "2x": 0.3, "5x": 0.12}
    time.sleep(delay_map[speed])
    st.session_state.t_idx = (st.session_state.t_idx + 1) % num_frames
    st.rerun()
