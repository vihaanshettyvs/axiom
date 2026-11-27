"""Animated km-plane map. All frames are built once (cached) and played client-side by Plotly, so playback is smooth."""
import copy
import math
import random

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from theme import PAL

STATUS_COLOR = {
    "ACTIVE": PAL["cyan"], "DEGRADED": PAL["amber"], "SERVICING": PAL["violet"], "RETIRING": "#FF8A65",
    "RETIRED": PAL["grey"], "DEAD": PAL["red"], "LOST": PAL["red"], "IDLE": "#5C6B7A",
}
HAZ = {"wildfire": (PAL["fire"], "255,122,47"), "methane": (PAL["methane"], "224,102,255")}
KIND_SYMBOL = {"SAT": "circle", "HAPS": "square", "DRONE": "triangle-up", "TUG": "diamond"}
RING_COLOR = {"DODGE": PAL["amber"], "RETIRE": PAL["red"], "REQUEST_TUG": PAL["violet"], "DISPATCH_HAPS": PAL["green"],
              "DISPATCH_DRONE": PAL["green"], "SERVICING": PAL["violet"], "SERVICED": PAL["green"],
              "ALERT": PAL["red"], "CONFIRMED": PAL["green"], "RETIRED": PAL["grey"]}
RING_TYPES = set(RING_COLOR)
TRAIL = 28


def _poly(cx, cy, r, n=28):
    xs = [round(cx + r * math.cos(2 * math.pi * i / n), 2) for i in range(n + 1)]
    ys = [round(cy + r * math.sin(2 * math.pi * i / n), 2) for i in range(n + 1)]
    return xs, ys


def _gap():
    return [None], [None]


def _log_key(log: dict) -> str:
    return f"{log.get('_name', '')}|{log['meta'].get('mode')}|{len(log['frames'])}"


def _ring_events(log: dict) -> dict[int, list]:
    """frame index -> [(type, actor)] for decisions/events worth a visual burst."""
    out: dict[int, list] = {}
    for i, f in enumerate(log["frames"]):
        for d in f.get("decisions", []):
            if d["action"]["type"] in RING_TYPES:
                out.setdefault(i, []).append((d["action"]["type"], d["action"]["actor_id"]))
        for e in f.get("events", []):
            if e["type"] in RING_TYPES and e["type"] not in ("DODGE", "REQUEST_TUG"):
                out.setdefault(i, []).append((e["type"], e.get("actor", "")))
    return out


@st.cache_resource(show_spinner="Building animation...")
def _build(_log: dict, key: str, belief: bool):
    log = _log
    area = float(log["meta"].get("area_km", 100.0))
    frames_raw = log["frames"]
    sat_ids = [s["id"] for s in frames_raw[0]["satellites"] if s["kind"] == "SAT"]
    haz = log["scenario"].get("hazards", [])
    rings = _ring_events(log)
    rnd = random.Random(7)
    lo, hi = -65, area + 65
    stars = [(rnd.uniform(lo, hi), rnd.uniform(lo, hi), rnd.uniform(.15, .7), rnd.choice([2, 2, 3, 4])) for _ in range(160)]

    static = [
        go.Scatter(x=[s[0] for s in stars], y=[s[1] for s in stars], mode="markers", hoverinfo="skip", showlegend=False,
                   marker=dict(size=[s[3] for s in stars], color="#BFD4FF", opacity=[s[2] for s in stars])),
    ]
    assets = log["scenario"].get("assets", [])
    if assets:
        static.append(go.Scatter(
            x=[a["pos"][0] for a in assets], y=[a["pos"][1] for a in assets], mode="markers+text", name="Protected asset",
            text=[a["name"] for a in assets], textposition="bottom center", textfont=dict(color=PAL["text"], size=10),
            marker=dict(symbol="star", size=15, color="#FFD740", line=dict(width=1, color=PAL["bg"]))))
    n_static = len(static)

    def dyn(i: int) -> list:
        f = frames_raw[i]
        t = f["t"]
        d = []
        if belief and f.get("belief_permille"):
            z = (np.array(f["belief_permille"], dtype=float) / 1000.0).round(3)
            cell = float(log["meta"].get("cell_km", 2.0))
            d.append(go.Heatmap(z=z, x0=cell / 2, dx=cell, y0=cell / 2, dy=cell, showscale=False, hoverinfo="skip",
                                colorscale=[[0, "rgba(56,225,255,0)"], [0.25, "rgba(56,225,255,0.18)"], [1, "rgba(61,245,165,0.75)"]],
                                zmin=0, zmax=1, name="Brain belief"))
        else:
            d.append(go.Heatmap(z=[[0]], showscale=False, hoverinfo="skip", opacity=0))
        hz_by = {h["id"]: h for h in f.get("hazards", [])}
        for pass_, scale, alpha in (("glow", 1.9, 0.10), ("core", 1.0, 0.36)):
            for h0 in haz:
                h = hz_by.get(h0["id"])
                if h and h.get("active", True):
                    r = max(h["radius_km"], 1.0) * scale
                    xs, ys = _poly(h["pos"][0], h["pos"][1], r)
                    rgb = HAZ.get(h["kind"], HAZ["wildfire"])[1]
                    tr = go.Scatter(x=xs, y=ys, mode="lines", fill="toself", fillcolor=f"rgba({rgb},{alpha})", showlegend=False,
                                    line=dict(color=f"rgba({rgb},{0.0 if pass_ == 'glow' else 0.9})", width=1.2),
                                    hoverinfo="skip" if pass_ == "glow" else "text",
                                    text=f"{h['id']} · {h['kind']} · intensity {h['intensity']:.2f}")
                else:
                    tr = go.Scatter(x=[None], y=[None], showlegend=False, hoverinfo="skip")
                d.append(tr)
        by = {s["id"]: s for s in f["satellites"]}
        for sid in sat_ids:                                     # sensor footprints (only while viewing)
            s = by[sid]
            if s.get("in_view") and s["status"] in ("ACTIVE", "DEGRADED"):
                xs, ys = _poly(s["pos"][0], s["pos"][1], s["sensor_radius_km"])
                d.append(go.Scatter(x=xs, y=ys, mode="lines", fill="toself", fillcolor="rgba(56,225,255,0.09)",
                                    line=dict(color="rgba(56,225,255,0.55)", width=1), showlegend=False, hoverinfo="skip"))
            else:
                d.append(go.Scatter(x=[None], y=[None], showlegend=False, hoverinfo="skip"))
        bx, by_ = [], []                                        # aim lines + handoff crosslinks
        for s in f["satellites"]:
            if s.get("aim"):
                bx += [s["pos"][0], s["aim"][0], None]
                by_ += [s["pos"][1], s["aim"][1], None]
        for dec in f.get("decisions", []):
            a = dec["action"]
            if a["type"] == "HANDOFF" and a.get("target_id") in by and a["actor_id"] in by:
                p, q = by[a["actor_id"]]["pos"], by[a["target_id"]]["pos"]
                bx += [p[0], q[0], None]
                by_ += [p[1], q[1], None]
        d.append(go.Scatter(x=bx or [None], y=by_ or [None], mode="lines", showlegend=False, hoverinfo="skip",
                            line=dict(color="rgba(230,236,245,0.55)", width=1, dash="dot")))
        tx, ty, to, tc = [], [], [], []                          # fading comet trails
        for k in range(max(0, i - TRAIL), i + 1):
            age = i - k
            for s in frames_raw[k]["satellites"]:
                if s["kind"] == "SAT":
                    tx.append(round(s["pos"][0], 1)); ty.append(round(s["pos"][1], 1))
                    to.append(round(max(0.04, 0.6 * (1 - age / (TRAIL + 1))), 2))
                    tc.append(STATUS_COLOR.get(frames_raw[i]["satellites"][sat_ids.index(s["id"])]["status"], PAL["cyan"]))
        d.append(go.Scatter(x=tx, y=ty, mode="markers", showlegend=False, hoverinfo="skip",
                            marker=dict(size=4, color=tc, opacity=to)))
        sats = f["satellites"]
        cols = [STATUS_COLOR.get(s["status"], PAL["cyan"]) for s in sats]
        d.append(go.Scatter(x=[s["pos"][0] for s in sats], y=[s["pos"][1] for s in sats], mode="markers", hoverinfo="skip",
                            showlegend=False, marker=dict(size=24, color=cols, opacity=0.16)))          # halo
        d.append(go.Scatter(
            x=[s["pos"][0] for s in sats], y=[s["pos"][1] for s in sats], mode="markers+text", showlegend=False,
            text=[s["id"] for s in sats], textposition="top center", textfont=dict(size=9, color=PAL["muted"]),
            marker=dict(size=10, color=cols, symbol=[KIND_SYMBOL.get(s["kind"], "circle") for s in sats],
                        line=dict(width=1.5, color=PAL["bg"])),
            customdata=[[s["id"], s["kind"], s["status"], s["fuel_kg"], s["health"], s.get("buffer_mb", 0)] for s in sats],
            hovertemplate="<b>%{customdata[0]}</b> · %{customdata[1]}<br>%{customdata[2]}<br>fuel %{customdata[3]:.2f} kg"
                          "<br>health %{customdata[4]:.2f}<br>buffer %{customdata[5]:.1f} MB<extra></extra>"))
        est = f.get("estimates", [])
        d.append(go.Scatter(
            x=[e["pos"][0] for e in est] or [None], y=[e["pos"][1] for e in est] or [None], mode="markers",
            name="Brain estimate", marker=dict(symbol="x-thin", size=12, color=PAL["green"], line=dict(width=2, color=PAL["green"])),
            text=[f"{e['id']} ({e['kind']}) conf {e['confidence']:.2f} ±{e['uncertainty_km']:.1f} km" for e in est],
            hovertemplate="%{text}<extra></extra>"))
        rx, ry, rs, ro, rc = [], [], [], [], []                  # expanding event rings (last 4 frames)
        for age in range(0, 4):
            for typ, actor in rings.get(i - age, []):
                if actor in by:
                    rx.append(by[actor]["pos"][0]); ry.append(by[actor]["pos"][1])
                    rs.append(16 + age * 9); ro.append(1 - age * 0.25); rc.append(RING_COLOR[typ])
        d.append(go.Scatter(x=rx or [None], y=ry or [None], mode="markers", showlegend=False, hoverinfo="skip",
                            marker=dict(size=rs or [1], color="rgba(0,0,0,0)", opacity=ro or [0],
                                        line=dict(width=2, color=rc or ["#fff"]))))
        return d

    def title(i):
        return dict(text=f"T+{int(frames_raw[i]['t']):03d} min", font=dict(color=PAL["cyan"], size=13, family="JetBrains Mono"),
                    x=0.02, y=0.97)

    frames = []
    for i in range(len(frames_raw)):
        data = dyn(i)
        frames.append(go.Frame(name=str(i), data=data, traces=list(range(n_static, n_static + len(data))), layout=dict(title=title(i))))
    steps = [dict(method="animate", label=str(i), args=[[str(i)], dict(mode="immediate", frame=dict(duration=0, redraw=True),
              transition=dict(duration=0))]) for i in range(len(frames_raw))]
    shapes = [dict(type="rect", x0=0, y0=0, x1=area, y1=area, line=dict(color="rgba(56,225,255,0.35)", width=1.2, dash="dot"),
                   fillcolor="rgba(56,225,255,0.03)", layer="below")]
    shapes += [dict(type="circle", x0=-r, y0=-r + area / 2, x1=r, y1=r + area / 2, xref="x", yref="y", layer="below",
                    line=dict(color="rgba(120,160,255,0.05)", width=1)) for r in (70, 110)]
    layout = dict(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#060913", height=640, margin=dict(l=8, r=8, t=36, b=8),
        xaxis=dict(range=[lo, hi], showgrid=True, gridcolor="rgba(120,160,255,0.06)", zeroline=False, color=PAL["muted"],
                   constrain="domain", tickfont=dict(size=9)),
        yaxis=dict(range=[lo, hi], showgrid=True, gridcolor="rgba(120,160,255,0.06)", zeroline=False, color=PAL["muted"],
                   scaleanchor="x", scaleratio=1, constrain="domain", tickfont=dict(size=9)),
        shapes=shapes, showlegend=True,
        legend=dict(orientation="h", x=0.5, xanchor="center", y=0.02, font=dict(color=PAL["text"], size=10), bgcolor="rgba(0,0,0,0)"),
        updatemenus=[dict(type="buttons", direction="left", x=0.02, y=-0.02, xanchor="left", yanchor="top", pad=dict(t=8),
                          bgcolor="#0D1424", bordercolor="#1C2740", font=dict(color=PAL["cyan"]),
                          buttons=[dict(label="▶  Play", method="animate",
                                        args=[None, dict(frame=dict(duration=70, redraw=True), fromcurrent=True,
                                                         transition=dict(duration=0), mode="immediate")]),
                                   dict(label="❚❚  Pause", method="animate",
                                        args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate",
                                                           transition=dict(duration=0))])])],
        sliders=[dict(active=0, steps=steps, x=0.16, len=0.82, y=-0.02, pad=dict(t=8, b=0),
                      currentvalue=dict(visible=False), tickcolor="rgba(0,0,0,0)", font=dict(color="rgba(0,0,0,0)"),
                      bgcolor="#1C2740", bordercolor="#1C2740", activebgcolor=PAL["cyan"])],
    )
    return static, frames, layout, n_static


def build_map(log: dict, t_idx: int, label: str, belief: bool = False) -> go.Figure:
    static, frames, layout, _ = _build(log, _log_key(log) + f"|{belief}", belief)
    t_idx = min(t_idx, len(frames) - 1)
    lay = copy.deepcopy(layout)
    lay["sliders"][0]["active"] = t_idx
    lay["title"] = frames[t_idx].layout.title.to_plotly_json()
    return go.Figure(data=list(static) + list(frames[t_idx].data), layout=lay, frames=frames)
