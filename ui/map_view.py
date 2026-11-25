import plotly.graph_objects as go
import numpy as np

def render_map(frame: dict):
    fig = go.Figure()

    # 1. 50x50 Methane Probability Heatmap (Simulated)
    z = np.array(frame["prob_grid"])
    axis = np.linspace(0, 100, 50)
    fig.add_trace(go.Heatmap(
        x=axis, y=axis, z=z,
        colorscale="YlOrRd", opacity=0.45,
        showscale=False, name="Methane Probability (Sim)"
    ))

    # 2. Landfill Marker (Simulated)
    lf = frame["landfill"]
    fig.add_trace(go.Scatter(
        x=[lf["x"]], y=[lf["y"]], mode="markers+text",
        marker=dict(size=14, color="purple", symbol="triangle-up"),
        text=["Landfill (Sim)"], textposition="bottom center", name="Landfill"
    ))

    # 3. Wildfire Marker (Real Data - NASA FIRMS)
    wf = frame["wildfire"]
    fig.add_trace(go.Scatter(
        x=[wf["x"]], y=[wf["y"]], mode="markers+text",
        marker=dict(size=16 + wf["radius"], color="rgba(255,69,0,0.6)", line=dict(color="red", width=2)),
        text=["Wildfire (REAL DATA)"], textposition="top center", name="Wildfire (Real)"
    ))

    # 4. HAPS Flight Path
    hx = [p[0] for p in frame["haps_path"]]
    hy = [p[1] for p in frame["haps_path"]]
    fig.add_trace(go.Scatter(
        x=hx, y=hy, mode="lines+markers",
        line=dict(color="cyan", width=3), marker=dict(size=6),
        name="HAPS Path"
    ))

    # 5. Drone Marker (when dispatched)
    if frame["drone_dispatched"]:
        fig.add_trace(go.Scatter(
            x=[lf["x"] + 2], y=[lf["y"] + 2], mode="markers+text",
            marker=dict(size=13, color="lime", symbol="star"),
            text=["Drone Dispatched"], textposition="top right", name="Drone"
        ))

    # 6. Satellites & Coverage Footprints
    sats = frame["satellites"]
    fig.add_trace(go.Scatter(
        x=[s["x"] for s in sats], y=[s["y"] for s in sats],
        mode="markers+text",
        marker=dict(size=12, color="dodgerblue", symbol="diamond"),
        text=[s["id"] for s in sats], textposition="top center",
        name="Satellites"
    ))

    fig.update_layout(
        xaxis=dict(title="East-West (km)", range=[0, 100]),
        yaxis=dict(title="North-South (km)", range=[0, 100]),
        height=520, margin=dict(l=20, r=20, t=20, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02)
    )
    return fig
