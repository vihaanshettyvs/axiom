from __future__ import annotations
from typing import Optional
import streamlit as st
def render_retire_lab(satellites: list[dict], eval_no_retire: dict, eval_with_retire: dict, brain_on: bool, retire_lab_data: Optional[dict] = None):
    st.subheader("Retirement Lab")
    st.caption("Adjust space weather to compare deorbit options, reentry days & mission credits.")
    sw_val = st.select_slider("Space-Weather Index", options=[0.0, 0.25, 0.5, 0.75, 1.0], value=0.5)
    sw_key = f"{sw_val:.2f}"
    if isinstance(retire_lab_data, dict) and retire_lab_data:
        sat_ids = sorted(retire_lab_data.keys())
        default_idx = sat_ids.index("SAT-05") if "SAT-05" in sat_ids else 0
        chosen_sat = st.selectbox("Inspect Satellite Disposal Plan", options=sat_ids, index=default_idx)
        options_list = retire_lab_data.get(chosen_sat, {}).get(sw_key) or []
        if options_list:
            opt_rows = []
            for opt in options_list:
                risk_v = float(opt.get("risk", 0.0))
                eff_v = float(opt.get("effectiveness", 0.0))
                fuel_v = float(opt.get("fuel_kg", 0.0))
                credits = round(100.0 * eff_v - 40.0 * risk_v - 15.0 * fuel_v, 1)
                opt_rows.append({"Method": opt.get("option", "-"), "Reentry (days)": opt.get("reentry_days", "-"), "Fuel (kg)": fuel_v, "Risk": risk_v, "Credits": credits, "Feasible": "Yes" if opt.get("feasible") else "No"})
            st.dataframe(opt_rows, hide_index=True, width="stretch")
    st.divider()
    retired_set: set[str] = st.session_state.retired_sats
    if retired_set:
        before_cov = eval_no_retire["metrics"]["targets_covered_pct"]
        after_cov = eval_with_retire["metrics"]["targets_covered_pct"]
        drop = round(after_cov - before_cov, 1)
        if brain_on:
            st.warning(f"{len(retired_set)} satellite(s) retired. Coverage impact: **{drop:+.1f}%** (Brain ON re-tasking active fleet).")
        else:
            st.error(f"{len(retired_set)} satellite(s) retired. Coverage impact: **{drop:+.1f}%** (Turn Brain ON to re-task).")
        if st.button("Restore All Satellites", key="restore_all_btn"):
            st.session_state.retired_sats = set()
            st.rerun()
    for sat in satellites:
        sid = sat["id"]
        is_retired = sid in retired_set
        lb = sat.get("last_breath") if isinstance(sat.get("last_breath"), dict) else {}
        verdict = lb.get("verdict", "SAVE")
        col_info, col_btn = st.columns([3, 1.4])
        with col_info:
            status_label = "RETIRED" if is_retired else f"{sat.get('status', 'ACTIVE')} | Verdict: {verdict} | Batt {sat.get('battery', 0)}%"
            st.markdown(f"**{sid}** - `{status_label}`")
        with col_btn:
            if is_retired:
                if st.button("Restore", key=f"restore_{sid}"):
                    st.session_state.retired_sats.discard(sid)
                    st.rerun()
            else:
                if st.button("Retire", key=f"retire_{sid}"):
                    st.session_state.retired_sats.add(sid)
                    st.rerun()
