from eval.credits import calculate_credits

def compute_metrics(run_log):
    frames = getattr(run_log, "frames", [])
    leak_t, fire_t, b_tot, f0, f1, deb, ret = -1, -1, 0, 0.0, 0.0, 0, 0
    for i, fr in enumerate(frames):
        t = getattr(fr, "time_min", getattr(fr, "t", i))
        sats = getattr(fr, "satellites", [])
        if i == 0: f0 = sum(getattr(s, "fuel", 0.0) for s in sats)
        if i == len(frames) - 1:
            f1 = sum(getattr(s, "fuel", 0.0) for s in sats)
            for s in sats:
                st = str(getattr(s, "status", "")).lower()
                if "debris" in st or "dead" in st: deb += 1
                elif "retired" in st or "deorbited" in st: ret += 1
        b_tot += getattr(fr, "bytes_sent", 0)
        if leak_t == -1 and getattr(fr, "leak_localized", False): leak_t = t
        if fire_t == -1 and getattr(fr, "fire_detected", False): fire_t = t
    fu = max(0.0, f0 - f1)
    cr = calculate_credits(ret, deb, (f1 / f0 * 100.0) if f0 > 0 else 0.0)
    return {"leak_localization_min": leak_t, "uncontrolled_debris": deb, "controlled_retirements": ret, "total_fuel_used": round(fu, 2), "total_bytes_sent": b_tot, "fire_response_min": fire_t, "credits": cr}
