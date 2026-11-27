from __future__ import annotations
import streamlit as st
def render_kpi_cards(active_eval: dict, baseline_eval: dict, brain_on: bool):
    m = active_eval["metrics"]
    b = baseline_eval["metrics"]
    c1, c2, c3, c4 = st.columns(4)
    cov_delta = round(m["targets_covered_pct"] - b["targets_covered_pct"], 1)
    lat_delta = round(m["avg_response_min"] - b["avg_response_min"], 1)
    bat_delta = round(m["fleet_battery_pct"] - b["fleet_battery_pct"], 1)
    tri_delta = round(m["triage_score"] - b["triage_score"], 1)
    with c1:
        st.metric(label="Targets Covered", value=f"{m['targets_covered_pct']}% ({m['targets_covered_count']}/{m['targets_total']})", delta=f"{cov_delta:+.1f}% vs Brain OFF" if brain_on else "Baseline (Brain OFF)", delta_color="normal" if brain_on else "off")
    with c2:
        st.metric(label="Avg Response Time", value=f"{m['avg_response_min']} min", delta=f"{lat_delta:+.1f} min vs Brain OFF" if brain_on else "Baseline (Brain OFF)", delta_color="inverse" if brain_on else "off")
    with c3:
        st.metric(label="Fleet Battery / Health", value=f"{m['fleet_battery_pct']}%", delta=f"{bat_delta:+.1f}% vs Brain OFF" if brain_on else "Baseline (Brain OFF)", delta_color="normal" if brain_on else "off")
    with c4:
        st.metric(label="Triage Score", value=f"{m['triage_score']} / 100", delta=f"{tri_delta:+.1f} pts vs Brain OFF" if brain_on else "Baseline (Brain OFF)", delta_color="normal" if brain_on else "off")
    sim_m = active_eval.get("sim_metrics") or {}
    if sim_m:
        r1, r2, r3, r4 = st.columns(4)
        with r1:
            st.metric(label="Fuel Used (kg)", value=f"{sim_m.get('fuel_used_kg', 0.0):.3f} kg")
        with r2:
            st.metric(label="Downlink Bandwidth", value=f"{sim_m.get('bandwidth_mb', 0.0):.1f} MB")
        with r3:
            st.metric(label="Uncontrolled Dead Sats", value=f"{int(sim_m.get('uncontrolled_dead', 0))}")
        with r4:
            st.metric(label="Mean Loc Error", value=f"{sim_m.get('loc_error_km', 0.0):.2f} km")
def render_target_table(active_eval: dict):
    st.subheader("Ground Target & Hazard Coverage")
    st.dataframe(active_eval["target_rows"], hide_index=True, width="stretch")
def render_events_feed(frames: list[dict], current_idx: int):
    st.subheader("Live Brain Decisions & Mission Events")
    recent_events = []
    for fr in frames[: current_idx + 1]:
        for ev in (fr.get("events") or []):
            recent_events.append({"t (min)": int(ev.get("t", fr.get("t", 0))), "Type": ev.get("type", "EVENT"), "Actor": ev.get("actor", "-"), "Reason / Log": ev.get("msg", "")})
        if not (fr.get("events") or []):
            for dec in (fr.get("decisions") or []):
                act = dec.get("action") or {}
                recent_events.append({"t (min)": int(dec.get("t", fr.get("t", 0))), "Type": act.get("type", "DECISION"), "Actor": act.get("actor_id", "-"), "Reason / Log": dec.get("reason", "")})
    if recent_events:
        st.dataframe(list(reversed(recent_events[-12:])), hide_index=True, width="stretch")
    else:
        st.caption("No discrete crisis events triggered up to this timestep.")
