import math
import plotly.graph_objects as go


STATUS_COLORS = {
    "ACTIVE": ("rgba(0, 212, 255, 0.22)", "#00D4FF"),
    "TASKED": ("rgba(255, 179, 0, 0.28)", "#FFB300"),
    "RETIRED": ("rgba(255, 75, 75, 0.08)", "#FF4B4B"),
}


def make_footprint_circle(lat: float, lon: float, radius_km: float, num_points: int = 40):
    earth_r = 6371.0
    ang = radius_km / earth_r
    lat_r = math.radians(lat)
    lon_r = math.radians(lon)
    lats, lons = [], []

    for i in range(num_points + 1):
        brg = 2.0 * math.pi * i / num_points
        sin_p = math.sin(lat_r) * math.cos(ang) + math.cos(lat_r) * math.sin(ang) * math.cos(brg)
        p_lat = math.asin(max(-1.0, min(1.0, sin_p)))
        p_lon = lon_r + math.atan2(
            math.sin(brg) * math.sin(ang) * math.cos(lat_r),
            math.cos(ang) - math.sin(lat_r) * math.sin(p_lat),
        )
        lats.append(math.degrees(p_lat))
        lons.append(((math.degrees(p_lon) + 540.0) % 360.0) - 180.0)

    return lats, lons


def build_map_figure(satellites: list[dict], targets: list[dict], covered_ids: set[str]) -> go.Figure:
    fig = go.Figure()

    for sat in satellites:
        status = sat.get("status", "ACTIVE")
        fill_rgba, line_hex = STATUS_COLORS.get(status, STATUS_COLORS["ACTIVE"])

        if status == "RETIRED":
            radius = sat.get("radius_km", 1500)
            lats, lons = make_footprint_circle(sat["lat"], sat["lon"], radius)
            crosses_date_line = (max(lons) - min(lons)) > 180
            fig.add_trace(go.Scattergeo(
                lat=lats,
                lon=lons,
                mode="lines",
                line=dict(color=line_hex, width=1.5, dash="dot"),
                fill=None if crosses_date_line else "toself",
                fillcolor=fill_rgba,
                hoverinfo="skip",
                showlegend=False,
            ))
            continue

        radius = sat.get("effective_radius_km", sat.get("radius_km", 1500))
        lats, lons = make_footprint_circle(sat["lat"], sat["lon"], radius)
        crosses_date_line = (max(lons) - min(lons)) > 180
        fig.add_trace(go.Scattergeo(
            lat=lats,
            lon=lons,
            mode="lines",
            line=dict(color=line_hex, width=1.5),
            fill=None if crosses_date_line else "toself",
            fillcolor=fill_rgba,
            hoverinfo="skip",
            showlegend=False,
        ))

    for is_cov, label, color, symbol in [
        (True, "Target (Covered)", "#00E676", "diamond"),
        (False, "Target (Uncovered Gap)", "#FF5252", "x"),
    ]:
        subset = [t for t in targets if (t["id"] in covered_ids) == is_cov]
        if subset:
            fig.add_trace(go.Scattergeo(
                lat=[t["lat"] for t in subset],
                lon=[t["lon"] for t in subset],
                text=[f"{t['name']} ({t.get('priority', 'MED')})" for t in subset],
                mode="markers",
                name=label,
                marker=dict(size=10, color=color, symbol=symbol, line=dict(width=1, color="#FFFFFF")),
                hovertemplate="<b>%{text}</b><br>Lat: %{lat:.2f}, Lon: %{lon:.2f}<extra></extra>",
            ))

    for status, label in [
        ("ACTIVE", "Satellite (Active)"),
        ("TASKED", "Satellite (Brain Re-Tasked)"),
        ("RETIRED", "Satellite (Retired)"),
    ]:
        subset = [s for s in satellites if s.get("status", "ACTIVE") == status]
        if subset:
            _, line_hex = STATUS_COLORS[status]
            fig.add_trace(go.Scattergeo(
                lat=[s["lat"] for s in subset],
                lon=[s["lon"] for s in subset],
                text=[
                    f"{s['id']} ({s.get('name', '')})<br>Status: {status}<br>Battery: {s.get('battery', 0)}%"
                    for s in subset
                ],
                mode="markers+text",
                textposition="top center",
                textfont=dict(size=10, color=line_hex),
                name=label,
                marker=dict(
                    size=11,
                    color=line_hex,
                    symbol="circle" if status != "RETIRED" else "circle-open",
                    line=dict(width=2, color="#0E1117"),
                ),
                hovertemplate="%{text}<extra></extra>",
            ))

    fig.update_layout(
        geo=dict(
            projection_type="natural earth",
            showland=True,
            landcolor="#1E2430",
            showocean=True,
            oceancolor="#0E1117",
            showcountries=True,
            countrycolor="#333C4D",
            coastlinecolor="#465269",
            bgcolor="#0E1117",
        ),
        paper_bgcolor="#0E1117",
        plot_bgcolor="#0E1117",
        margin=dict(l=0, r=0, t=10, b=0),
        height=490,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=0.01,
            xanchor="center",
            x=0.5,
            font=dict(color="#E6EDF3", size=11),
            bgcolor="rgba(14, 17, 23, 0.75)",
        ),
    )
    return fig
