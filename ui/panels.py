import streamlit as st
import pandas as pd

def render_top_metrics(frame: dict):
    sats = frame["satellites"]
    avg_fuel = sum(s["fuel"] for s in sats) / len(sats)
    active_watch = sum(1 for s in sats if "Watching" in s["status"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Avg Fleet Fuel", f"{avg_fuel:.1f}%")
    c2.metric("Downlink Used", f"{frame['bytes_used_mb']} MB")
    c3.metric("Satellites On-Task", f"{active_watch} / {len(sats)}")
    c4.metric("Orbital Credits", f"{frame['credits']}")

    st.caption("Data Labels: 🔥 **Wildfire** = Real Data (NASA FIRMS) | 🛰️ **Orbits, Methane Plume, Debris, Failures** = Simulated")

def render_decisions_feed(frames_so_far: list):
    st.subheader("Brain Decisions & Reasons")
    all_decisions = [d for f in frames_so_far for d in f["decisions"]]
    if not all_decisions:
        st.info("No major triage interventions yet at this minute.")
    else:
        for d in reversed(all_decisions):
            st.markdown(f"**t = {d['time']} min | {d['actor']} → `{d['action']}`**: {d['reason']}")

def render_satellite_table(frame: dict):
    st.subheader("Satellite Health & Status")
    df = pd.DataFrame(frame["satellites"])[["id", "status", "fuel", "health"]]
    df.columns = ["Satellite", "Status", "Fuel (%)", "Health (%)"]
    st.dataframe(df, use_container_width=True, hide_index=True)
