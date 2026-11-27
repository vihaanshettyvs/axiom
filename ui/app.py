import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import theme
from data_loader import (decisions_upto, events_upto, frame_at, list_runlogs, load_bytes, load_path, pick_default)
from map_view import build_map
from panels import (render_decisions, render_events, render_hero, render_kpis, render_retirement_lab,
                    render_satellite_table, render_status_strip, render_summary, render_timeline)

st.set_page_config(page_title="ORBITA Mission Control", page_icon="🛰️", layout="wide")
theme.inject()

st.session_state.setdefault("t_slider", 0)
st.session_state.setdefault("last_click", None)


def key_of(log: dict) -> str:
    return f"{log.get('_name', '')}|{log['meta'].get('mode')}"


def pick_log(label: str, mode: str):
    paths = list_runlogs()
    log = None
    if paths:
        i = st.selectbox(f"{label} RunLog", range(len(paths)), index=pick_default(paths, mode),
                         format_func=lambda k: paths[k].name, key=f"sel_{mode}")
        log = load_path(str(paths[i]))
    up = st.file_uploader(f"Or upload {label} RunLog", type=["json"], key=f"up_{mode}")
    if up is not None:
        log = load_bytes(up.getvalue(), up.name)
    return log


with st.sidebar:
    st.markdown("### 🛰️ Mission Controls")
    view = st.radio("View", ["Brain ON", "Brain OFF", "Side by side"], index=0)
    belief = st.toggle("Show brain belief heatmap", value=False, help="Where the agent believes hazards are (adds data to the animation).")
    weather = st.slider("Space weather (retirement lab)", 0.0, 1.0, 0.5, 0.25)
    st.divider()
    try:
        log_on = pick_log("Brain ON", "BRAIN_ON")
        log_off = pick_log("Brain OFF", "BRAIN_OFF")
    except Exception as e:
        st.error(str(e))
        st.stop()

if log_on is None and log_off is None:
    st.error("No RunLog found. Put runlog_*.json files in data/runlogs/ or upload them in the sidebar.")
    st.stop()

if view == "Side by side" and not (log_on and log_off):
    st.warning("Side by side needs both logs; showing the one that is loaded.")
    view = "Brain ON"
primary = log_on if view != "Brain OFF" else log_off
primary = primary or log_on or log_off
secondary = log_off if primary is log_on else log_on
primary_label = "Brain ON" if primary is log_on else "Brain OFF"
secondary_label = "Brain OFF" if primary is log_on else "Brain ON"
n_frames = min(len(l["frames"]) for l in (log_on, log_off) if l)
st.session_state.t_slider = min(st.session_state.t_slider, n_frames - 1)

# Minute control: slider (or click on the timeline below).
sc1, sc2 = st.columns([1, 14])
with sc1:
    if st.button("⟲", width="stretch", help="Reset to minute 0"):
        st.session_state.t_slider = 0
        st.rerun()
with sc2:
    t = st.slider("Snapshot minute", 0, n_frames - 1, key="t_slider", label_visibility="collapsed")

frame = frame_at(primary, t)
render_hero(primary["meta"], frame, primary_label)
render_kpis(primary, key_of(primary), t, secondary if secondary is not primary else None,
            key_of(secondary) if secondary else "", secondary_label)

if view == "Side by side":
    a, b = st.columns(2)
    a.plotly_chart(build_map(log_on, t, "Brain ON", belief), width="stretch", key="map_on")
    b.plotly_chart(build_map(log_off, t, "Brain OFF", belief), width="stretch", key="map_off")
else:
    st.plotly_chart(build_map(primary, t, primary_label, belief), width="stretch", key="map_main")
st.caption("Press ▶ Play on the map for smooth playback. The slider above sets the snapshot used by the cards and panels; "
           "click a marker on the timeline to jump to that moment.")
render_status_strip(frame)

st.markdown("##### Event timeline")
clicked = render_timeline(primary, key_of(primary), t)
if clicked is not None and clicked != st.session_state.last_click:
    st.session_state.last_click = clicked
    st.session_state.t_slider = min(clicked, n_frames - 1)
    st.rerun()

tab_dec, tab_ev, tab_sat, tab_lab, tab_sum = st.tabs(
    ["Decisions", "Events", "Satellites", "Retirement Lab", "Final comparison"])
with tab_dec:
    st.caption("Why the agent acted (routine OBSERVE actions hidden).")
    render_decisions(decisions_upto(primary, t))
with tab_ev:
    render_events(events_upto(primary, t))
with tab_sat:
    render_satellite_table(frame)
with tab_lab:
    render_retirement_lab(primary, frame, weather)
with tab_sum:
    render_summary(log_on, log_off)
