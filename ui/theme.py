"""Visual theme: palette, CSS and small HTML helpers (all rendering stays inside Streamlit)."""
import html

import streamlit as st

PAL = {
    "bg": "#070B14", "panel": "#0D1424", "line": "#1C2740", "text": "#E6ECF5", "muted": "#7F8EA8",
    "cyan": "#38E1FF", "amber": "#FFB547", "fire": "#FF7A2F", "methane": "#E066FF", "green": "#3DF5A5",
    "red": "#FF5470", "violet": "#A78BFA", "grey": "#64718A",
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
html, body, [class*="css"], .stApp { font-family: 'Inter', sans-serif; }
.stApp { background: radial-gradient(1200px 600px at 75% -10%, #12204a55, transparent 60%),
                     radial-gradient(900px 500px at 0% 100%, #2a124a40, transparent 60%), #070B14; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stSidebar"] { background: #0A101F; border-right: 1px solid #1C2740; }
.block-container { padding-top: 1.6rem; max-width: 1500px; }
h1, h2, h3 { letter-spacing: -0.02em; }
.mono { font-family: 'JetBrains Mono', monospace; }

.hero { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:18px 24px; margin-bottom:14px;
        border:1px solid #1C2740; border-radius:18px;
        background: linear-gradient(120deg, #0D1424 0%, #101A33 55%, #1a1240 100%); box-shadow: 0 0 40px #38e1ff10 inset; }
.hero h1 { margin:0; font-size:1.55rem; font-weight:700; background:linear-gradient(90deg,#fff,#38E1FF 70%);
           -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.hero .sub { color:#7F8EA8; font-size:.82rem; margin-top:4px; }
.clock { font-family:'JetBrains Mono',monospace; font-size:1.9rem; font-weight:600; color:#38E1FF;
         text-shadow:0 0 18px #38E1FF80; text-align:right; }
.clock small { display:block; font-size:.62rem; color:#7F8EA8; letter-spacing:.18em; text-shadow:none; }
.badge { display:inline-block; padding:3px 11px; border-radius:999px; font-size:.7rem; font-weight:600; letter-spacing:.08em;
         border:1px solid; margin-right:6px; }
.badge.on  { color:#3DF5A5; border-color:#3DF5A580; background:#3DF5A512; }
.badge.off { color:#FFB547; border-color:#FFB54780; background:#FFB54712; }
.badge.dot::before { content:''; display:inline-block; width:7px; height:7px; border-radius:50%; background:currentColor;
         margin-right:7px; animation: pulse 1.6s infinite; }
@keyframes pulse { 0%{box-shadow:0 0 0 0 currentColor;} 70%{box-shadow:0 0 0 7px transparent;} 100%{box-shadow:0 0 0 0 transparent;} }

.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(135px,1fr)); gap:12px; margin:6px 0 14px; }
.kpi { position:relative; overflow:hidden; padding:14px 16px 8px; border-radius:14px; border:1px solid #1C2740;
       background:linear-gradient(160deg,#0f1830cc,#0b1222cc); backdrop-filter:blur(6px);
       transition:transform .2s, border-color .2s, box-shadow .2s; animation: rise .5s ease both; }
.kpi:hover { transform:translateY(-3px); border-color:#38E1FF80; box-shadow:0 8px 28px #38e1ff22; }
.kpi .lab { color:#7F8EA8; font-size:.64rem; letter-spacing:.05em; text-transform:uppercase; white-space:nowrap; }
.kpi .val { font-family:'JetBrains Mono',monospace; font-size:1.65rem; font-weight:600; margin:2px 0; color:#E6ECF5; }
.kpi .dl { font-size:.72rem; font-weight:600; }
.kpi .dl.good { color:#3DF5A5; } .kpi .dl.bad { color:#FF5470; } .kpi .dl.flat { color:#7F8EA8; }
.kpi svg { display:block; width:100%; height:34px; margin-top:4px; }
@keyframes rise { from {opacity:0; transform:translateY(8px);} to {opacity:1; transform:none;} }

.card { border:1px solid #1C2740; border-radius:14px; padding:14px 16px; background:#0D1424cc; }
.feed { display:flex; flex-direction:column; gap:8px; max-height:380px; overflow-y:auto; padding-right:4px; }
.item { display:flex; gap:12px; align-items:flex-start; padding:10px 12px; border-radius:12px; border:1px solid #1C2740;
        background:#0D1424; border-left:3px solid var(--c); animation: slidein .45s ease both; }
.item:hover { background:#111b33; }
.item .t { font-family:'JetBrains Mono',monospace; color:#7F8EA8; font-size:.74rem; min-width:46px; padding-top:2px; }
.item .chip { font-size:.64rem; font-weight:700; letter-spacing:.08em; padding:2px 8px; border-radius:6px;
              color:var(--c); background:color-mix(in srgb, var(--c) 14%, transparent); white-space:nowrap; }
.item .who { font-weight:600; font-size:.82rem; margin:0 6px; }
.item .why { color:#AEB9CE; font-size:.8rem; margin-top:4px; line-height:1.4; }
@keyframes slidein { from {opacity:0; transform:translateX(-14px);} to {opacity:1; transform:none;} }

.opts { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:12px; }
.opt { padding:14px; border-radius:14px; border:1px solid #1C2740; background:#0D1424; transition:.2s; }
.opt:hover { transform:translateY(-3px); border-color:#A78BFA90; box-shadow:0 8px 24px #a78bfa22; }
.opt h4 { margin:0 0 6px; font-size:.95rem; } .opt .note { color:#7F8EA8; font-size:.72rem; margin-top:8px; }
.bar { height:6px; border-radius:99px; background:#1C2740; margin:3px 0 9px; overflow:hidden; }
.bar > i { display:block; height:100%; border-radius:99px; animation: grow .9s ease both; }
@keyframes grow { from {width:0;} }
.opt .l { font-size:.68rem; color:#7F8EA8; display:flex; justify-content:space-between; }

[data-testid="stTabs"] button { font-weight:600; }
[data-testid="stPlotlyChart"] { border:1px solid #1C2740; border-radius:16px; overflow:hidden; }
div.stButton > button { border-radius:10px; border:1px solid #1C2740; background:#0D1424; }
div.stButton > button:hover { border-color:#38E1FF; color:#38E1FF; }
</style>
"""


def inject():
    st.markdown(CSS, unsafe_allow_html=True)


def esc(x) -> str:
    return html.escape(str(x))


def sparkline(values: list[float], color: str, cursor_frac: float = 1.0) -> str:
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    n = len(values)
    pts = [(i / (n - 1) * 100, 28 - (v - lo) / span * 24) for i, v in enumerate(values)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"0,32 {line} 100,32"
    gid = f"g{abs(hash(color + str(n))) % 99999}"
    return (f'<svg viewBox="0 0 100 32" preserveAspectRatio="none"><defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{color}" stop-opacity=".35"/><stop offset="1" stop-color="{color}" stop-opacity="0"/>'
            f'</linearGradient></defs><polygon points="{area}" fill="url(#{gid})"/>'
            f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="1.6" vector-effect="non-scaling-stroke"/>'
            f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="2.2" fill="{color}"/></svg>')
