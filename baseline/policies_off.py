def _dec(c, aid, act, tgt, rsn):
    if c and hasattr(c, "Decision"):
        try: return c.Decision(actor_id=aid, action=act, target=tgt, reason=rsn)
        except TypeError: pass
    return {"actor_id": aid, "action": act, "target": tgt, "reason": rsn}

def decide_off(state, contracts=None):
    out = []
    sats = getattr(state, "satellites", [])
    haps = getattr(state, "haps", None)
    t = int(getattr(state, "time_min", getattr(state, "t", 0)))
    if haps is not None:
        r = (t // 10) % 5
        x = float((t % 10) * 5)
        if r % 2 == 1: x = 50.0 - x
        out.append(_dec(contracts, getattr(haps, "id", "haps_1"), "MOVE_HAPS", (x, 5.0 + r * 10.0), "Lawnmower"))
    for s in sats:
        sid = getattr(s, "id", "sat")
        if getattr(s, "collision_prob", 0.0) > 0.05: out.append(_dec(contracts, sid, "DODGE", None, "Dodge"))
        elif getattr(s, "has_detection", False): out.append(_dec(contracts, sid, "DOWNLINK_RAW", None, "Raw"))
        else: out.append(_dec(contracts, sid, "IDLE", None, "Idle"))
    return out
