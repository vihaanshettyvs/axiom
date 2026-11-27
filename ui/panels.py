import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_loader import metric_series, timeline_events
from theme import PAL, esc, sparkline

# (label, metrics key, format, lower_is_better, spark color)
KPIS = [
    ("Observations", "observations", "{:,.0f}", False, PAL["cyan"]),
    ("Alerts raised", "alerts", "{:,.0f}", True, PAL["amber"]),
    ("Bandwidth MB", "bandwidth_mb", "{:,.0f}", True, PAL["violet"]),
    ("Fuel used kg", "fuel_used_kg", "{:.2f}", True, PAL["fire"]),
    ("Dodges", "dodges", "{:,.0f}", False, PAL["green"]),
    ("Location error km", "loc_error_km", "{:.1f}", True, PAL["methane"]),
]
TYPE_COLOR = {
    "DODGE": PAL["amber"], "RETIRE": PAL["red"], "RETIRED": PAL["grey"], "REQUEST_TUG": PAL["violet"], "TUG_REQUEST": PAL["violet"],
    "SERVICING": PAL["violet"], "SERVICED": PAL["green"], "ALERT": PAL["red"], "CONFIRMED": PAL["green"],
    "HANDOFF": "#9FB4D9", "DOWNLINK": PAL["cyan"], "DISPATCH_HAPS": PAL["green"], "DISPATCH_DRONE": PAL["green"],
    "DRONE_DONE": PAL["green"], "OBSERVE": PAL["cyan"],
}


def render_hero(meta: dict, frame: dict, label: str):
    mode_cls = "on" if "ON" in label.upper() else "off"
    clock = int(frame["t"])
    active = sum(1 for h in frame.get("hazards", []) if h.get("active", True))
    st.markdown(f"""
<div class="hero"><div>
  <h1>ORBITA · Orbital Triage Mission Replay</h1>
  <div class="sub"><span class="badge {mode_cls} dot">{esc(label.upper())}</span>
  seed {esc(meta.get('seed'))} · {esc(meta.get('n_satellites'))} satellites · {active} active hazards ·
  physics {esc(meta.get('modules', {}).get('physics', '?'))} · hazards {esc(meta.get('hazard_source'))}</div></div>
  <div class="clock"><small>MISSION CLOCK</small>T+{clock // 60:02d}:{clock % 60:02d}</div></div>""", unsafe_allow_html=True)


def render_kpis(log: dict, key: str, t: int, other: dict | None, other_key: str, other_label: str):
    cards = []
    for label, metric, fmt, lower_better, color in KPIS:
        series = metric_series(log, key, metric)
        v = series[min(t, len(series) - 1)]
        delta_html = '<div class="dl flat">&nbsp;</div>'
        if other is not None:
            ov = metric_series(other, other_key, metric)
            ov = ov[min(t, len(ov) - 1)]
            diff = v - ov
            good = (diff < 0) == lower_better if diff else None
            cls = "flat" if not diff else ("good" if good else "bad")
            arrow = "▲" if diff > 0 else "▼" if diff < 0 else "•"
            delta_html = f'<div class="dl {cls}">{arrow} {abs(diff):,.1f} vs {esc(other_label)}</div>'
        cards.append(f'<div class="kpi"><div class="lab">{label}</div><div class="val">{fmt.format(v)}</div>{delta_html}'
                     f'{sparkline(series[: t + 1][::2] or series[:1], color)}</div>')
    st.markdown(f'<div class="kpis">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_status_strip(frame: dict):
    counts: dict[str, int] = {}
    for s in frame["satellites"]:
        if s["kind"] == "SAT":
            counts[s["status"]] = counts.get(s["status"], 0) + 1
    chips = " ".join(f'<span class="badge" style="color:{PAL["cyan"]};border-color:#38E1FF55">{n} {k}</span>'
                     for k, n in sorted(counts.items()))
    st.markdown(f'{chips} <span class="mono" style="color:{PAL["muted"]};font-size:.75rem">entropy {frame.get("entropy_bits", 0):.1f} bits · '
                f'uncertainty {frame.get("uncertainty", 0):.2f}</span>', unsafe_allow_html=True)


def _feed(items: list[dict], empty: str):
    if not items:
        st.info(empty)
        return
    rows = []
    for k, it in enumerate(items):
        c = TYPE_COLOR.get(it["type"], PAL["cyan"])
        rows.append(f'<div class="item" style="--c:{c};animation-delay:{min(k, 12) * 30}ms"><div class="t">T+{int(it["t"])}</div>'
                    f'<div><span class="chip">{esc(it["type"])}</span><span class="who">{esc(it["actor"])}</span>'
                    f'<div class="why">{esc(it["why"])}</div></div></div>')
    st.markdown(f'<div class="feed">{"".join(rows)}</div>', unsafe_allow_html=True)


def render_decisions(rows: list[dict]):
    _feed([{"t": r["t"], "type": r["Action"], "actor": r["Actor"], "why": r["Why"]} for r in rows], "No decisions yet at this time.")


def render_events(rows: list[dict]):
    _feed([{"t": r["t"], "type": r["Type"], "actor": r["Actor"], "why": r["Message"]} for r in rows], "No events yet at this time.")


def render_satellite_table(frame: dict):
    rows = []
    for s in frame["satellites"]:
        lb = (s.get("orbit") or {}).get("last_breath") or {}
        rows.append({
            "ID": s["id"], "Kind": s["kind"], "Status": s["status"], "Fuel kg": round(s["fuel_kg"], 2),
            "Health": round(s["health"], 2), "RUL min": None if s["rul_min"] > 1e8 else round(s["rul_min"]),
            "In view": s["in_view"], "Contact": s["in_contact"], "Buffer MB": s.get("buffer_mb", 0),
            "Verdict": lb.get("verdict", ""), "Why": lb.get("reason", ""),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"Health": st.column_config.ProgressColumn("Health", min_value=0, max_value=1, format="%.2f"),
                                "Fuel kg": st.column_config.ProgressColumn("Fuel kg", min_value=0, max_value=2, format="%.2f")})


def render_summary(log_on: dict | None, log_off: dict | None):
    s_on, s_off = (log_on or {}).get("summary"), (log_off or {}).get("summary")
    if not (s_on and s_off):
        st.info("Load both a Brain ON and a Brain OFF RunLog to compare final results.")
        return
    skip = {"mode", "seed", "completed", "time_to_detect_min", "time_to_localize_min"}
    rows = [{"Metric": k, "Brain OFF": str(s_off[k]), "Brain ON": str(s_on[k])} for k in s_on if k not in skip and k in s_off]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    hz = sorted(s_on.get("time_to_detect_min", {}))
    fig = go.Figure()
    for name, s, col in (("Brain OFF", s_off, PAL["amber"]), ("Brain ON", s_on, PAL["green"])):
        vals = [s["time_to_detect_min"].get(h) for h in hz]
        fig.add_bar(name=name, x=hz, y=[v if v is not None else 0 for v in vals], marker_color=col,
                    text=[f"{v:.0f}" if v is not None else "never" for v in vals], textposition="outside")
    fig.update_layout(title="Time to detect (min) — lower is better", barmode="group", height=320,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=PAL["text"]),
                      yaxis=dict(gridcolor="#1C2740"), margin=dict(t=48, b=10))
    st.plotly_chart(fig, width="stretch")


def _bar(label: str, frac: float, text: str, color: str) -> str:
    return (f'<div class="l"><span>{label}</span><span class="mono">{esc(text)}</span></div>'
            f'<div class="bar"><i style="width:{max(0.0, min(1.0, frac)) * 100:.0f}%;background:{color}"></i></div>')


def render_retirement_lab(log: dict, frame: dict, weather: float):
    lab = log["scenario"].get("retirement_lab", {})
    sat_ids = [s["id"] for s in frame["satellites"] if s["kind"] == "SAT" and s["id"] in lab]
    if not sat_ids:
        st.info("This RunLog has no retirement_lab data.")
        return
    sid = st.selectbox("Satellite", sat_ids, key="lab_sat")
    levels = sorted(lab[sid], key=float)
    level = min(levels, key=lambda k: abs(float(k) - weather))
    st.caption(f"Disposal options for {sid} at space-weather level {level} (from the physics module).")
    cards = []
    for o in lab[sid][level]:
        days = o["reentry_days"]
        cards.append(f'<div class="opt"><h4>{esc(o["option"].replace("_", " ").title())}</h4>'
                     + _bar("Effectiveness", o["effectiveness"], f'{o["effectiveness"]:.0%}', PAL["green"])
                     + _bar("Risk", o["risk"], f'{o["risk"]:.0%}', PAL["red"])
                     + _bar("Fuel", o["fuel_kg"] / 0.5, f'{o["fuel_kg"]:.2f} kg', PAL["amber"])
                     + f'<div class="l"><span>Re-entry</span><span class="mono">{days:,.1f} d</span></div>'
                     f'<div class="l"><span>Duration</span><span class="mono">{o["duration_min"]:.0f} min</span></div>'
                     f'<div class="note">{esc(o["resource_cost"])} · {esc(o["note"])}</div></div>')
    st.markdown(f'<div class="opts">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_timeline(log: dict, key: str, t: int):
    """Clickable event strip; returns the clicked minute or None."""
    ev = timeline_events(log, key)
    fig = go.Figure()
    fig.add_vrect(x0=0, x1=t, fillcolor="rgba(56,225,255,0.07)", line_width=0)
    fig.add_vline(x=t, line_color=PAL["cyan"], line_width=2)
    kinds = sorted({e["type"] for e in ev})
    for lane, k in enumerate(kinds):
        pts = [e for e in ev if e["type"] == k]
        fig.add_scatter(x=[e["t"] for e in pts], y=[lane] * len(pts), mode="markers", name=k.replace("_", " "),
                        marker=dict(size=11, color=TYPE_COLOR.get(k, PAL["cyan"]), line=dict(width=1, color=PAL["bg"])),
                        customdata=[[e["actor"], e["msg"][:110]] for e in pts],
                        hovertemplate="T+%{x:.0f} · <b>%{customdata[0]}</b><br>%{customdata[1]}<extra></extra>")
    fig.update_layout(height=150, margin=dict(l=4, r=4, t=4, b=4), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(range=[0, len(log["frames"])], gridcolor="#1C2740", color=PAL["muted"]),
                      yaxis=dict(visible=False, range=[-0.7, max(len(kinds) - 0.3, 0.7)]), clickmode="event+select",
                      legend=dict(orientation="h", y=1.25, font=dict(size=10, color=PAL["text"])), dragmode="select")
    sel = st.plotly_chart(fig, width="stretch", on_select="rerun", selection_mode="points", key=f"tl_{key}")
    pts = (sel or {}).get("selection", {}).get("points", []) if sel else []
    return int(pts[0]["x"]) if pts else None
