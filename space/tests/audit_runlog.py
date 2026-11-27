"""Audit RunLog JSON files produced by the integrated engine for physics-side problems.

Read-only: it does not simulate anything. Usage (repo root), one file per run:
    python -m space.tests.audit_runlog out/runlog_seed1.json out/runlog_seed2.json out/runlog_seed3.json
Exit code 1 if any hard check fails. It reads only contract fields (RunLog.to_dict): frames[].satellites[],
decisions[], events[], metrics; satellite fields status/fuel_kg/health/pos/orbit.
"""
import json
import sys
from collections import Counter, defaultdict

ACTIVE_STATES = ("ACTIVE", "DEGRADED")
DONE_STATES = ("RETIRING", "RETIRED", "DEAD", "LOST")


def audit(path: str) -> dict:
    log = json.load(open(path))
    frames = log["frames"]
    fails, notes = [], []
    sats0 = [s for s in frames[0]["satellites"] if s.get("kind") == "SAT"]
    ids = [s["id"] for s in sats0]

    # 1 movement / coverage
    moved = {i: set() for i in ids}
    ever_in_view = Counter()
    for f in frames:
        for s in f["satellites"]:
            if s["id"] in moved:
                moved[s["id"]].add(tuple(s["pos"]))
                ever_in_view[s["id"]] += bool(s.get("in_view"))
    still = [i for i, p in moved.items() if len(p) < 2]
    if still:
        fails.append(f"satellites that never moved: {still}")
    notes.append(f"satellites {len(ids)}, with view time: {sum(1 for i in ids if ever_in_view[i])}")

    # negative resources, status lifecycle, servicing overlap
    first_done, repeated_retire = {}, Counter()
    prev = {}
    for f in frames:
        t = f["t"]
        servicing = [s["id"] for s in f["satellites"] if s.get("status") == "SERVICING"]
        if len(servicing) > 1:
            fails.append(f"t={t}: tug servicing {servicing} simultaneously")
        for s in f["satellites"]:
            if s.get("kind") != "SAT":
                continue
            o = s.get("orbit", {})
            for k, v in (("fuel_kg", s.get("fuel_kg")), ("health", s.get("health")), ("battery", o.get("battery"))):
                if v is not None and v < -1e-9:
                    fails.append(f"t={t} {s['id']}: negative {k}={v}")
            if s.get("health", 0) > 1.0 + 1e-9:
                fails.append(f"t={t} {s['id']}: health>1")
            if s["status"] in DONE_STATES and s["id"] not in first_done:
                first_done[s["id"]] = (t, s["status"])
            if s["id"] in prev and prev[s["id"]] in ("RETIRED", "DEAD", "LOST") and s["status"] in ACTIVE_STATES:
                fails.append(f"t={t} {s['id']}: came back to life ({prev[s['id']]} -> {s['status']})")
            prev[s["id"]] = s["status"]

    # decisions
    acts_after = []
    by_frame_actor = defaultdict(set)
    prev_status = {}
    for f in frames:
        for d in f.get("decisions", []):
            a = d["action"]
            typ, actor = a["type"], a["actor_id"]
            if not str(d.get("reason", "")).strip():
                fails.append(f"t={f['t']}: decision {typ} by {actor} has empty reason")
            if typ == "RETIRE":
                repeated_retire[actor] += 1
            elif prev_status.get(actor) in DONE_STATES and typ in (
                    "OBSERVE", "DODGE", "DOWNLINK", "HANDOFF", "REQUEST_TUG"):
                # A satellite that is RETIRING may still drain its data buffer in ground contact (last breath).
                if not (typ == "DOWNLINK" and prev_status.get(actor) == "RETIRING"):
                    acts_after.append((f["t"], actor, typ))
            by_frame_actor[(f["t"], actor)].add(typ)
        prev_status = {s["id"]: s["status"] for s in f["satellites"]}
    for (t, actor), types in by_frame_actor.items():
        if "DODGE" in types and "OBSERVE" in types:
            notes.append(f"t={t} {actor}: DODGE and OBSERVE in the same minute (check for contradiction)")
    if acts_after:
        fails.append(f"actions after retirement/death: {acts_after[:5]}")
    rep = {k: v for k, v in repeated_retire.items() if v > 1}
    if rep:
        fails.append(f"repeated RETIRE decisions: {rep}")

    # dodge, handoff, tug requests
    kinds = Counter(d["action"]["type"] for f in frames for d in f.get("decisions", []))
    notes.append("decision counts: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    maneuvers = sum(len(s.get("orbit", {}).get("maneuvers", [])) for s in frames[-1]["satellites"])
    if kinds.get("DODGE") and not maneuvers:
        notes.append("LIMITATION: DODGE decisions exist but no orbit['maneuvers'] logged "
                     "(engine does not call physics.execute_dodge, so the route is unchanged)")

    # last breath / telemetry / tug timeline
    verdicts = defaultdict(list)
    tug_windows = []
    for f in frames:
        for s in f["satellites"]:
            lb = s.get("orbit", {}).get("last_breath")
            if lb and (not verdicts[s["id"]] or verdicts[s["id"]][-1][1] != lb["verdict"]):
                verdicts[s["id"]].append((f["t"], lb["verdict"]))
                if not lb.get("reason"):
                    fails.append(f"t={f['t']} {s['id']}: last_breath without reason")
            o = s.get("orbit", {})
            if "tug_arrival_t" in o:
                w = (o["tug_arrival_t"], o["tug_done_t"], s["id"])
                if w not in tug_windows:
                    tug_windows.append(w)
    tug_windows.sort()
    for a, b in zip(tug_windows, tug_windows[1:]):
        if b[0] < a[1]:
            fails.append(f"tug windows overlap: {a} and {b}")
    notes.append("last_breath transitions: " + "; ".join(f"{k}: {'>'.join(v for _, v in x)}" for k, x in verdicts.items() if len(x) > 1))
    notes.append(f"tug services: {[(w[2], w[0], w[1]) for w in tug_windows]}")
    lab = log.get("scenario", {}).get("retirement_lab")
    notes.append("retirement_lab present: %s; space_weather meta: %s" % (bool(lab), log.get("meta", {}).get("space_weather")))
    notes.append("final statuses: " + ", ".join(f"{s['id']}={s['status']}" for s in frames[-1]["satellites"] if s.get("kind") == "SAT"))
    return {"path": path, "fails": fails, "notes": notes}


def main(paths):
    bad = 0
    for p in paths:
        r = audit(p)
        print(f"\n== {r['path']}: {'FAIL' if r['fails'] else 'OK'}")
        for n in r["notes"]:
            print("  -", n)
        for f in r["fails"][:20]:
            print("  !!", f)
        bad += bool(r["fails"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
