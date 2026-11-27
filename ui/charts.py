from __future__ import annotations
import plotly.graph_objects as go
from data_loader import evaluate_frame
def build_mission_timeline(frames: list[dict], targets: list[dict], retired_sats: set[str], current_idx: int) -> go.Figure:
    steps = list(range(1, len(frames) + 1))
    on_cov, off_cov, on_score = [], [], []
    for frame in frames:
        ev_on = evaluate_frame(frame, targets, "brain_on", retired_sats)
        ev_off = evaluate_frame(frame, targets, "brain_off", retired_sats)
        on_cov.append(ev_on["metrics"]["targets_covered_pct"])
        off_cov.append(ev_off["metrics"]["targets_covered_pct"])
        on_score.append(ev_on["metrics"]["triage_score"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=steps, y=on_cov, mode="lines+markers", name="Brain ON - Coverage %", line=dict(color="#10b981", width=3)))
    fig.add_trace(go.Scatter(x=steps, y=off_cov, mode="lines", name="Brain OFF - Coverage %", line=dict(color="#f59e0b", width=2, dash="dash")))
    fig.add_trace(go.Scatter(x=steps, y=on_score, mode="lines", name="Brain ON - Triage Score", line=dict(color="#38bdf8", width=2, dash="dot")))
    fig.add_vline(x=current_idx + 1, line_width=2, line_dash="solid", line_color="#e2e8f0", annotation_text=f"Frame {current_idx + 1}", annotation_position="top right")
    fig.update_layout(title="Full-Mission Performance: Brain ON vs. Brain OFF", xaxis_title="Simulation Frame", yaxis_title="Score / Coverage (%)", yaxis=dict(range=[0, 105]), height=320, margin=dict(l=20, r=20, t=45, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig
