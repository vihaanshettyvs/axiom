import numpy as np

def get_mock_runlog(brain_on: bool = True, num_frames: int = 20):
    rng = np.random.default_rng(42)
    frames = []
    haps_path = []

    for t in range(num_frames):
        # 50x50 methane probability grid (0 to 100 km)
        x = np.linspace(0, 100, 50)
        y = np.linspace(0, 100, 50)
        X, Y = np.meshgrid(x, y)
        spread = max(4.0, 18.0 - t * 0.7) if brain_on else 16.0
        grid = np.exp(-((X - 65) ** 2 + (Y - 40) ** 2) / (2 * spread ** 2))

        # HAPS path: adaptive toward landfill (65,40) if Brain ON, lawnmower if OFF
        if brain_on:
            hx = 20 + (65 - 20) * (t / max(1, num_frames - 1))
            hy = 20 + (40 - 20) * (t / max(1, num_frames - 1))
        else:
            hx = 15 + (t % 5) * 18
            hy = 15 + (t // 5) * 20
        haps_path.append((round(hx, 1), round(hy, 1)))

        # 4 sample satellites
        sats = [
            {"id": "SAT-1", "x": (10 + t * 4) % 100, "y": 42, "fuel": max(10, 90 - t * (1.2 if brain_on else 2.5)), "health": 98, "status": "Dodging" if (t == 6) else "Watching Leak"},
            {"id": "SAT-2", "x": (30 + t * 3) % 100, "y": 72, "fuel": max(15, 85 - t * 0.8), "health": 95, "status": "Watching Fire"},
            {"id": "SAT-3", "x": (70 - t * 2) % 100, "y": 25, "fuel": max(5, 35 - t * 1.5), "health": max(10, 60 - t * 2.5), "status": "Retiring" if (brain_on and t >= 12) else ("Lost" if (not brain_on and t >= 15) else "Degrading")},
            {"id": "SAT-4", "x": (50 + t * 2) % 100, "y": 55, "fuel": 88 - t * 0.5, "health": 99, "status": "Standby"},
        ]

        # Decisions with one-line reasons
        decisions = []
        if t == 6:
            decisions.append({"time": t, "actor": "SAT-1", "action": "DODGE", "reason": "Debris risk high; handing landfill watch to HAPS." if brain_on else "Independent dodge (no handoff)."})
        if t == 12 and brain_on:
            decisions.append({"time": t, "actor": "SAT-3", "action": "RETIRE", "reason": "Battery below threshold; initiating controlled deorbit before point of no return."})
        if t == 14 and brain_on:
            decisions.append({"time": t, "actor": "DRONE-1", "action": "DISPATCH", "reason": "Leak probability > 85% at landfill; dispatching drone to confirm."})

        frames.append({
            "time_min": t,
            "prob_grid": grid.tolist(),
            "landfill": {"x": 65, "y": 40},
            "wildfire": {"x": 30, "y": 75, "radius": 4 + t * 0.4},
            "satellites": sats,
            "haps_path": list(haps_path),
            "drone_dispatched": brain_on and t >= 14,
            "bytes_used_mb": round((t + 1) * (2.4 if brain_on else 18.5), 1),
            "credits": round((t + 1) * (12.5 if brain_on else 3.0), 1),
            "decisions": decisions,
        })
    return frames
