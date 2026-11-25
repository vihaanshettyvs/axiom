import streamlit as st


def render_retire_lab(satellites: list[dict], eval_no_retire: dict, eval_with_retire: dict, brain_on: bool):
    st.subheader("Retirement Lab")
    st.caption("Simulate satellite failures live without resetting the current timestep.")

    retired_set: set[str] = st.session_state.retired_sats

    if retired_set:
        before_cov = eval_no_retire["metrics"]["targets_covered_pct"]
        after_cov = eval_with_retire["metrics"]["targets_covered_pct"]
        drop = round(after_cov - before_cov, 1)

        if brain_on:
            st.warning(
                f"{len(retired_set)} satellite(s) retired. Coverage impact: **{drop:+.1f}%** "
                f"(Brain ON is re-tasking active satellites to cover gaps)."
            )
        else:
            st.error(
                f"{len(retired_set)} satellite(s) retired. Coverage impact: **{drop:+.1f}%** "
                f"(Turn Brain ON to see automatic re-tasking)."
            )

        if st.button("Restore All Satellites", key="restore_all_btn"):
            st.session_state.retired_sats = set()
            st.rerun()

    for sat in satellites:
        sid = sat["id"]
        is_retired = sid in retired_set
        col_info, col_btn = st.columns([3, 1.4])

        with col_info:
            status_label = "RETIRED" if is_retired else f"{sat.get('status', 'ACTIVE')} | Batt {sat.get('battery', 0)}%"
            st.markdown(f"**{sid}** — {sat.get('name', '')}  \n`{status_label}`")

        with col_btn:
            if is_retired:
                if st.button("Restore", key=f"restore_{sid}"):
                    st.session_state.retired_sats.discard(sid)
                    st.rerun()
            else:
                if st.button("Retire", key=f"retire_{sid}"):
                    st.session_state.retired_sats.add(sid)
                    st.rerun()
