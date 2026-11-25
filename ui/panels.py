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
        st.metric(
            label="Targets Covered",
            value=f"{m['targets_covered_pct']}% ({m['targets_covered_count']}/{m['targets_total']})",
            delta=f"{cov_delta:+.1f}% vs Brain OFF" if brain_on else "Baseline (Brain OFF)",
            delta_color="normal" if brain_on else "off",
        )

    with c2:
        st.metric(
            label="Avg Response Time",
            value=f"{m['avg_response_min']} min",
            delta=f"{lat_delta:+.1f} min vs Brain OFF" if brain_on else "Baseline (Brain OFF)",
            delta_color="inverse" if brain_on else "off",
        )

    with c3:
        st.metric(
            label="Fleet Battery",
            value=f"{m['fleet_battery_pct']}%",
            delta=f"{bat_delta:+.1f}% vs Brain OFF" if brain_on else "Baseline (Brain OFF)",
            delta_color="normal" if brain_on else "off",
        )

    with c4:
        st.metric(
            label="Triage Score",
            value=f"{m['triage_score']} / 100",
            delta=f"{tri_delta:+.1f} pts vs Brain OFF" if brain_on else "Baseline (Brain OFF)",
            delta_color="normal" if brain_on else "off",
        )


def render_target_table(active_eval: dict):
    st.subheader("Ground Target Coverage")
    st.dataframe(active_eval["target_rows"], hide_index=True, width="stretch")
