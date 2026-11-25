import streamlit as st
import pandas as pd

def render_retire_lab():
    st.subheader("Retirement Lab: Space Weather & Deorbit Tradeoffs")
    st.caption("Simulated drag model — move the Space-Weather Index to see how solar activity changes re-entry time and credits.")

    kp = st.slider("Space-Weather Index (Solar Activity / Drag)", min_value=1, max_value=9, value=4)
    drag_factor = 1.0 + (kp - 1) * 0.22

    data = [
        {"Option": "Controlled Burn", "Est. Re-entry (Days)": round(30 / drag_factor, 1), "Fuel Needed (%)": 18, "Orbital Credits": round(80 + kp * 2, 1)},
        {"Option": "Drag Sail", "Est. Re-entry (Days)": round(180 / drag_factor, 1), "Fuel Needed (%)": 2, "Orbital Credits": round(95 + kp * 3, 1)},
        {"Option": "Electrodynamic Tether", "Est. Re-entry (Days)": round(90 / drag_factor, 1), "Fuel Needed (%)": 0, "Orbital Credits": round(110 + kp * 4, 1)},
        {"Option": "Do Nothing (Uncontrolled)", "Est. Re-entry (Days)": round(1800 / drag_factor, 1), "Fuel Needed (%)": 0, "Orbital Credits": -50.0},
    ]
    st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
