def calculate_credits(retired, debris, fuel_pct=0.0, bw_pct=0.0):
    s = (retired * 100.0) - (debris * 250.0)
    s += 0.25 * max(0.0, min(100.0, fuel_pct)) + 0.25 * max(0.0, min(100.0, bw_pct))
    return round(s, 2)
