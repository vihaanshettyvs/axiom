"""brain/triage.py -- the autonomous triage brain and the brain-OFF baseline.

Every candidate action is scored with the same ledger (see config weights):

    expected_benefit = INFO_VALUE * urgency * importance * info_gain * health_factor   (information value)
                     + LOSS_VALUE * satellite_value * risk_reduction                     (loss avoided)
                     - FUEL_VALUE * fuel_cost - BW_VALUE * bandwidth_cost - other costs

so a dodge, a downlink and a drone dispatch can be compared on one scale.  The brain only
looks at WorldView (estimates, belief grid, platform states) -- never at ground truth.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import config
from brain.haps import AdaptiveHAPSPlanner, LawnmowerPlanner, should_dispatch_drone
from brain.leakhunter import binary_entropy, expected_gain, footprint_weights
from contracts import (Action, ActionType, Decision, Estimate, PendingItem, Satellite, Status, Vec2,
                       WorldView, dist)


# --------------------------------------------------------------------------- #
def region_name(pos: Vec2) -> str:
    dx, dy = pos[0] - 50.0, pos[1] - 50.0
    if abs(dx) < 15 and abs(dy) < 15:
        return "central"
    ns = "northern" if dy > 15 else ("southern" if dy < -15 else "")
    ew = "eastern" if dx > 15 else ("western" if dx < -15 else "")
    return (ns + "-" + ew).strip("-") if ns and ew else (ns or ew)


def _clip(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def urgency_of(e: Estimate, now: float) -> float:
    stale = 60.0 if e.last_obs_t < 0 else now - e.last_obs_t
    unsettled = 1.0 - abs(2.0 * e.existence - 1.0)            # 1 when the track is a coin-flip, 0 when settled either way
    return _clip(0.30 * e.intensity_est + 0.25 * _clip(e.growth_est * 5.0) + 0.25 * min(1.0, stale / 30.0)
                 + 0.20 * e.existence + config.URGENCY_CONFIRM_W * unsettled)


def importance_of(e: Estimate, assets) -> float:
    a = max([x.weight * math.exp(-dist(x.pos, e.pos) / 25.0) for x in assets] or [0.0])
    return _clip(0.3 + 0.5 * a + 0.3 * e.intensity_est)


def _mk(t, action, u, imp, g, fuel, bw, rr, hf, ben, reason, alts=None) -> Decision:
    action.fuel_cost, action.bandwidth_cost = float(fuel), float(bw)
    return Decision(t, action, round(u, 4), round(imp, 4), round(g, 4), round(fuel, 5), round(bw, 3),
                    round(rr, 5), round(hf, 4), round(ben, 4), reason, alts or [])


class TriageBrain:
    """BRAIN ON policy."""

    def __init__(self, physics, use_adaptive_haps: bool = True) -> None:
        self.physics = physics
        self.haps_planner = AdaptiveHAPSPlanner() if use_adaptive_haps else LawnmowerPlanner()
        self.adaptive = use_adaptive_haps
        self._tug_requested: set = set()
        self._last_aim: Dict[str, Vec2] = {}

    # ------------------------------------------------------------------ #
    def decide(self, view: WorldView) -> List[Decision]:
        t = view.t
        ests = [e for e in view.estimates if e.existence >= 0.15]
        UI = {e.id: (urgency_of(e, t), importance_of(e, view.assets)) for e in ests}
        decisions: List[Decision] = []
        decisions += self._observe(view, ests, UI)
        decisions += self._downlink_and_handoff(view, ests, UI)
        bus = self._bus_actions(view)
        decisions += bus
        decisions += self._haps(view, ests, UI)
        decisions += self._drone(view, ests, UI)
        # a satellite that is burning (DODGE / RETIRE) this minute does not also re-point its sensor
        burning = {d.action.actor_id for d in bus
                   if d.action.type in (ActionType.DODGE, ActionType.RETIRE)}
        if burning:
            decisions = [d for d in decisions
                         if not (d.action.type == ActionType.OBSERVE and d.action.actor_id in burning)]
        decisions.sort(key=lambda d: -d.expected_benefit)
        return decisions

    # ------------------------------------------------------------------ #
    def _ui_at(self, pos: Vec2, radius: float, ests, UI) -> Tuple[float, float, Optional[Estimate]]:
        best, be = (0.30, 0.40), None                      # exploration baseline
        bv = best[0] * best[1]
        for e in ests:
            if dist(pos, e.pos) < radius + 3.0:
                u, i = UI[e.id]
                if u * i * (0.5 + 0.5 * e.existence) > bv:
                    best, bv, be = (u, i), u * i * (0.5 + 0.5 * e.existence), e
        return best[0], best[1], be

    def _aims(self, s: Satellite, ests: List[Estimate]) -> List[Vec2]:
        aims = [s.pos]
        for e in ests:
            v = (e.pos[0] - s.pos[0], e.pos[1] - s.pos[1])
            d = math.hypot(*v)
            if d <= s.slew_km:
                aims.append(e.pos)
            elif d > 1e-9:
                aims.append((s.pos[0] + v[0] / d * s.slew_km, s.pos[1] + v[1] / d * s.slew_km))
        for k in range(8):
            a = k * math.pi / 4
            aims.append((s.pos[0] + 0.9 * s.slew_km * math.cos(a), s.pos[1] + 0.9 * s.slew_km * math.sin(a)))
        return aims

    # -- OBSERVE ------------------------------------------------------- #
    def _observe(self, view: WorldView, ests, UI) -> List[Decision]:
        sats = [s for s in view.satellites if s.kind == "SAT" and s.operational and s.in_view
                and (s.orbit.get("telemetry") or {}).get("comm_ok", True)]      # no command link -> cannot be re-tasked
        Dw = view.belief.copy()
        out: List[Decision] = []
        remaining = list(sats)
        looks: Dict[str, int] = {}                      # looks already assigned to each estimate this minute
        while remaining:
            HbD = binary_entropy(Dw)
            best = None
            per_sat: Dict[str, List[Tuple[float, Any]]] = {}
            for s in remaining:
                hf = _clip(s.sensor_confidence / 0.8) * (0.5 + 0.5 * s.health)
                for aim in self._aims(s, ests):
                    held = self._last_aim.get(s.id)
                    fuel = 0.0 if (held is not None and dist(held, aim) < 3.0) else config.SLEW_FUEL_PER_KM * dist(aim, s.pos)
                    if fuel > 0 and s.fuel_kg - fuel < config.FUEL_RESERVE_KG:
                        continue
                    g, _, _ = expected_gain(Dw, aim, s.sensor_radius_km, s.sensor_confidence, HbD)
                    u, imp, e = self._ui_at(aim, s.sensor_radius_km, ests, UI)
                    if e is not None:                   # diminishing returns: a 2nd/3rd satellite on the same hazard adds little
                        u *= config.REPEAT_LOOK_DECAY ** looks.get(e.id, 0)
                    fpen = config.FUEL_VALUE * fuel * (1.0 + 2.0 * max(0.0, 1.0 - s.fuel_kg / 0.5))
                    ben = config.INFO_VALUE * u * imp * g * hf - fpen
                    cand = (ben, s, aim, g, u, imp, e, fuel, hf)
                    per_sat.setdefault(s.id, []).append((ben, cand))
                    if best is None or ben > best[0]:
                        best = cand
            if best is None or best[0] <= 0:
                break
            ben, s, aim, g, u, imp, e, fuel, hf = best
            alts = []
            nad = [c for b, c in per_sat[s.id] if c[2] == s.pos]
            if nad and aim != s.pos:
                alts.append({"action": "OBSERVE nadir", "benefit": round(nad[0][0], 3)})
            slew = dist(aim, s.pos)
            if e is not None:
                what = "methane leak" if e.kind == "methane" else "wildfire"
                why = (f"{s.id} is assigned to observe the {region_name(e.pos)} {what} ({e.id}, "
                       f"{e.existence:.0%} likely, +/-{e.uncertainty_km:.1f} km) because its sensor confidence "
                       f"is {s.sensor_confidence:.2f} and its fuel reserve ({s.fuel_kg:.2f} kg) is sufficient "
                       f"for the {slew:.1f} km re-pointing; expected information gain {g:.2f}.")
            else:
                why = (f"{s.id} surveys the {region_name(aim)} sector (belief uncertainty is highest there) "
                       f"because it is the best use of its pass: sensor confidence {s.sensor_confidence:.2f}, "
                       f"fuel {s.fuel_kg:.2f} kg, re-pointing {slew:.1f} km, expected information gain {g:.2f}.")
            self._last_aim[s.id] = aim
            if e is not None:
                looks[e.id] = looks.get(e.id, 0) + 1
            a = Action(ActionType.OBSERVE, s.id, target=aim, target_id=e.id if e else None)
            out.append(_mk(view.t, a, u, imp, g, fuel, 0.0, 0.0, hf, ben, why, alts))
            w = footprint_weights(aim, s.sensor_radius_km)
            Dw = Dw * (1.0 - 0.5 * s.sensor_confidence * w)          # coordinate: avoid duplicate looks
            remaining = [r for r in remaining if r.id != s.id]
        return out

    # -- DOWNLINK / HANDOFF -------------------------------------------- #
    @staticmethod
    def _item_value(it: PendingItem) -> float:
        return 2.0 if it.has_detection else 0.2 + 2.0 * it.prior_mass

    def _select_items(self, items: List[PendingItem]) -> Tuple[List[PendingItem], List[PendingItem]]:
        """Information-aware selection: keep detections + the newest scan per area, drop stale duplicates."""
        keep: List[PendingItem] = []
        newest: Dict[Tuple[int, int], PendingItem] = {}
        for it in sorted(items, key=lambda i: i.t):
            if it.has_detection:
                keep.append(it)
            else:
                newest[(round(it.aim[0] / 6), round(it.aim[1] / 6))] = it
        keep += list(newest.values())
        dropped = [i for i in items if i not in keep]
        keep.sort(key=lambda i: -self._item_value(i) / max(i.size_comp_mb, 0.01))
        return keep, dropped

    def _ui_items(self, items, ests, UI) -> Tuple[float, float]:
        best = (0.3, 0.4)
        for it in items:
            u, i, _ = self._ui_at(it.aim, it.radius_km, ests, UI)
            if u * i > best[0] * best[1]:
                best = (u, i)
        return best

    def _downlink_and_handoff(self, view: WorldView, ests, UI) -> List[Decision]:
        out: List[Decision] = []
        sats = {s.id: s for s in view.satellites if s.kind == "SAT"}
        for sid, items in view.pending.items():
            s = sats.get(sid)
            if s is None or not items or s.status in (Status.LOST.value, Status.DEAD.value, Status.RETIRED.value):
                continue
            if s.in_contact:
                keep, dropped = self._select_items(items)
                budget, chosen = view.link_mb_per_min, []
                for it in keep:
                    if it.size_comp_mb <= budget:
                        chosen.append(it)
                        budget -= it.size_comp_mb
                if not chosen and not dropped:
                    continue
                mb = sum(i.size_comp_mb for i in chosen)
                v = sum(self._item_value(i) for i in chosen)
                u, imp = self._ui_items(chosen, ests, UI)
                g = 1.0 - math.exp(-v / 3.0)
                ben = config.INFO_VALUE * u * imp * g - config.BW_VALUE * mb
                npos = sum(1 for i in chosen if i.has_detection)
                raw_mb = sum(i.size_raw_mb for i in items)
                why = (f"{sid} is in ground contact and downlinks {len(chosen)} compressed scan(s) "
                       f"({npos} with detections, {mb:.1f} MB instead of {raw_mb:.0f} MB raw) because they carry the "
                       f"most information per MB; {len(dropped)} redundant empty scan(s) are discarded.")
                a = Action(ActionType.DOWNLINK, sid, params={"item_ids": [i.id for i in chosen], "compress": True,
                                                              "drop_ids": [i.id for i in dropped]})
                out.append(_mk(view.t, a, u, imp, g, 0.0, mb, 0.0, s.health, ben, why))
            else:
                pos_items = [i for i in items if i.has_detection]
                partners = [p for p in sats.values() if p.id != sid and p.operational
                            and p.next_contact_min < s.next_contact_min - 10]
                if pos_items and partners and s.next_contact_min > 15:
                    p = min(partners, key=lambda q: (q.next_contact_min, q.buffer_mb))
                    mb = sum(i.size_comp_mb for i in pos_items)
                    u, imp = self._ui_items(pos_items, ests, UI)
                    g = 1.0 - math.exp(-sum(self._item_value(i) for i in pos_items) / 3.0)
                    saved = s.next_contact_min - p.next_contact_min
                    ben = config.INFO_VALUE * u * imp * g * _clip(saved / 60.0) - config.BW_VALUE * mb
                    when = "is in ground contact now" if p.next_contact_min <= 0 else \
                        f"reaches ground contact in {p.next_contact_min:.0f} min"
                    why = (f"{sid} hands {len(pos_items)} detection report(s) over the crosslink to {p.id}, which {when}, "
                           f"because {sid}'s own contact is {s.next_contact_min:.0f} min away and the reports are "
                           f"time-critical (saves ~{saved:.0f} min).")
                    a = Action(ActionType.HANDOFF, sid, target_id=p.id,
                               params={"item_ids": [i.id for i in pos_items], "dst": p.id})
                    out.append(_mk(view.t, a, u, imp, g, 0.0, mb, 0.0, s.health, ben, why))
        return [d for d in out if d.expected_benefit > 0]

    # -- DODGE / RETIRE / TUG ------------------------------------------ #
    def _bus_actions(self, view: WorldView) -> List[Decision]:
        out: List[Decision] = []
        tug = view.tug
        tug_bids: Dict[str, float] = {}
        if tug.get("available"):
            span = tug["eta_min"] + tug["service_min"]
            for q in view.satellites:
                if q.kind != "SAT" or not q.operational or q.orbit.get("serviced") or q.id in self._tug_requested:
                    continue
                nd = 0.5 * (1.0 - q.fuel_kg / q.fuel_capacity_kg) + 0.5 * (1.0 - q.health)
                if q.rul_min > span + 10 and q.mission_importance >= 0.6 and nd >= 0.40:
                    b = config.SERVICE_VALUE * q.mission_importance * nd - config.TUG_COST \
                        - 0.5 * tug["service_min"] * q.mission_importance
                    if b > 0:
                        tug_bids[q.id] = b
        tug_winner = max(tug_bids, key=tug_bids.get) if tug_bids else None
        for s in view.satellites:
            if s.kind != "SAT" or not s.operational:
                continue
            cands: List[Decision] = []
            sat_val = (0.4 + 0.6 * s.mission_importance) * s.health
            # DODGE
            # Collision Avoidance 2.0: P2 may supply a per-encounter assessment (miss distance before/after the burn,
            # risk tier, feasibility). Absent on mock physics -> the original economics below apply unchanged.
            assess_fn = getattr(self.physics, "assess_conjunction", None)
            asm: Dict[str, Dict[str, Any]] = {}
            if callable(assess_fn):
                try:
                    asm = {x["debris_id"]: x for x in assess_fn(s, view.t)}
                except Exception:                                    # noqa: BLE001 - advisory data only
                    asm = {}
            ahead = {cc.debris_id for cc in view.conjunctions.get(s.id, [])}
            for c in view.conjunctions.get(s.id, []):
                if (s.id, c.debris_id) in view.dodged:
                    continue
                lead = c.tca - view.t
                cost = self.physics.dodge_fuel_cost(s, lead)
                eff = self.physics.dodge_effectiveness(s, lead)
                if s.fuel_kg < cost + config.FUEL_RESERVE_KG:
                    continue
                av = asm.get(c.debris_id)
                if av is not None:
                    if not av["feasible"] or not av["projected_improved"]:
                        continue                   # propulsion lost, no fuel margin, or the burn would not move the miss distance
                    # propellant is finite: do not spend it on this encounter if a riskier one still ahead needs it
                    held = sum(o["dodge_fuel_kg"] for k, o in asm.items() if k != c.debris_id and k in ahead
                               and (s.id, k) not in view.dodged and o["feasible"] and o["risk_score"] > av["risk_score"])
                    if s.fuel_kg < cost + config.FUEL_RESERVE_KG + held:
                        continue
                rr = c.probability * eff
                rf = 0.2 + 0.8 * _clip((s.rul_min - lead) / 150.0)
                ben = config.LOSS_VALUE * sat_val * rf * rr - config.FUEL_VALUE * cost
                if ben > 0:
                    why = (f"{s.id} dodges {c.debris_id} now ({lead:.0f} min before closest approach) because the "
                           f"{c.probability:.1%} collision risk outweighs the {cost:.3f} kg burn, and acting early "
                           f"removes {eff:.0%} of the risk at the lowest fuel price.")
                    prm = {"lead": lead, "eff": eff}
                    if av is not None:
                        why += (f" Risk tier {av['risk_tier']} (score {av['risk_score']:.3f}); predicted miss "
                                f"{av['predicted_miss_km']:.1f} km -> {av['predicted_miss_after_km']:.1f} km after the burn "
                                f"(projected: {av['projected_outcome'].lower()}).")
                        prm.update(risk_tier=av["risk_tier"], risk_score=av["risk_score"],
                                   miss_km=av["predicted_miss_km"], miss_after_km=av["predicted_miss_after_km"],
                                   projected_outcome=av["projected_outcome"])
                    a = Action(ActionType.DODGE, s.id, target_id=c.debris_id, params=prm)
                    cands.append(_mk(view.t, a, _clip(c.probability / 0.05), s.mission_importance, 0.0, cost, 0.0,
                                     rr, s.health, ben, why))
                else:
                    pass  # not worth it -> deliberately accepted (see ASSUMPTIONS.md)
            # RETIRE  (Last Breath verdict RETIRE or the brain's own RUL rule; method chosen by cost/risk/time score)
            lab = getattr(self.physics, "retirement_lab", None)      # P2: controlled_deorbit / drag_sail / edt_tether rows
            raw = (lab(s, view.t) if callable(lab) else None) or (self.physics.retirement_options(s, view.t) or [])
            opts = [dict(o, name=o.get("name", o.get("option"))) for o in raw
                    if o.get("feasible", True) and o.get("name", o.get("option")) not in (None, "do_nothing")
                    and o["fuel_kg"] <= s.fuel_kg - config.FUEL_RESERVE_KG]
            verdict = (s.orbit.get("last_breath") or {}).get("verdict")
            if opts and (verdict == "RETIRE" or s.rul_min < config.RETIRE_RUL_MIN or s.health < 0.12):
                def _score(x):
                    return config.FUEL_VALUE * x["fuel_kg"] + config.RETIRE_RISK_W * x.get("risk", 0.0) \
                        + config.RETIRE_TIME_W * x.get("duration_min", 0.0)
                ranked = sorted(opts, key=_score)
                o = ranked[0]
                nm = lambda x: x.get("name", x.get("option"))
                death = _clip(1.0 - s.rul_min / 60.0)
                ben = config.DEBRIS_PENALTY * death - _score(o) - 20.0 * s.mission_importance * s.health
                if ben > 0:
                    cmp = "; ".join(f"{nm(x)}: {x['fuel_kg']:.2f} kg, risk {x.get('risk', 0):.2f}, "
                                    f"{x.get('duration_min', 0):.0f} min" for x in ranked)
                    why = (f"{s.id} is retired via {nm(o)} (Last Breath verdict {verdict or 'n/a'}; remaining life "
                           f"{s.rul_min:.0f} min, health {s.health:.2f}). Options compared -> {cmp}. {nm(o)} has the "
                           f"lowest combined fuel/risk/time cost, so it avoids leaving uncontrolled debris at the best price.")
                    o = dict(o); o["name"] = nm(o)
                    a = Action(ActionType.RETIRE, s.id, params=o)
                    cands.append(_mk(view.t, a, death, s.mission_importance, 0.0, o["fuel_kg"], 0.0, death,
                                     s.health, ben, why))
            # TUG (only the best-ranked requester this minute; the others are queued behind it)
            if tug.get("available") and not s.orbit.get("serviced") and s.id not in self._tug_requested:
                span = tug["eta_min"] + tug["service_min"]
                need = 0.5 * (1.0 - s.fuel_kg / s.fuel_capacity_kg) + 0.5 * (1.0 - s.health)
                if s.rul_min > span + 10 and s.mission_importance >= 0.6 and need >= 0.40:
                    ben = config.SERVICE_VALUE * s.mission_importance * need - config.TUG_COST \
                        - 0.5 * tug["service_min"] * s.mission_importance
                    if ben > 0 and s.id == tug_winner:
                        rivals = ", ".join(f"{k} ({v:.1f})" for k, v in sorted(tug_bids.items(), key=lambda kv: -kv[1])
                                           if k != s.id)
                        queue = (f" It outranks {rivals} (benefit {ben:.1f}); they queue behind it." if rivals else "")
                        why = (f"{s.id} requests the servicing tug because its fuel is {s.fuel_kg:.2f}/"
                               f"{s.fuel_capacity_kg:.1f} kg and health {s.health:.2f} while its mission importance is "
                               f"{s.mission_importance:.1f}; it will survive the {span:.0f} min rendezvous and regain capability."
                               + queue)
                        a = Action(ActionType.REQUEST_TUG, s.id)
                        cands.append(_mk(view.t, a, need, s.mission_importance, 0.0, 0.0, 0.0, need, s.health,
                                         ben, why))
            if cands:
                cands.sort(key=lambda d: -d.expected_benefit)
                win = cands[0]
                win.alternatives = [{"action": c.action.type.value, "benefit": c.expected_benefit} for c in cands[1:]]
                out.append(win)
                if win.action.type == ActionType.REQUEST_TUG:
                    self._tug_requested.add(s.id)
                    tug = dict(tug, available=False)
        return out

    # -- HAPS ------------------------------------------------------------ #
    def _haps(self, view: WorldView, ests, UI) -> List[Decision]:
        haps = next((s for s in view.satellites if s.kind == "HAPS" and s.status != Status.DEAD.value), None)
        if haps is None:
            return []
        if not self.adaptive:
            wp, changed = self.haps_planner.next_waypoint(haps.pos)
            if not changed and haps.target is not None:
                return []
            a = Action(ActionType.DISPATCH_HAPS, haps.id, target=wp)
            return [_mk(view.t, a, 0.3, 0.4, 0.3, 0.0, 0.0, 0.0, 1.0, 1.0, f"{haps.id} follows its sweep to {wp}.")]
        wp, score, changed = self.haps_planner.plan(haps.pos, view.belief, ests, view.t, view.assets)
        if not changed and haps.target is not None:
            return []
        g, _, _ = expected_gain(view.belief, wp, haps.sensor_radius_km, haps.sensor_confidence)
        u, imp, e = self._ui_at(wp, haps.sensor_radius_km, ests, UI)
        trav = dist(haps.pos, wp)
        fuel = config.HAPS_BURN_PER_KM * trav
        ben = config.INFO_VALUE * u * imp * g - config.FUEL_VALUE * fuel
        if e is not None:
            why = (f"{haps.id} is dispatched to the {region_name(wp)} sector ({wp[0]:.0f}, {wp[1]:.0f}) km to "
                   f"refine {e.id} (existence {e.existence:.0%}, +/-{e.uncertainty_km:.1f} km): high hazard probability "
                   f"and uncertainty there outweigh the {trav / config.SENSOR_SPECS['HAPS']['speed']:.0f} min transit.")
        else:
            why = (f"{haps.id} is dispatched to the {region_name(wp)} sector ({wp[0]:.0f}, {wp[1]:.0f}) km because it "
                   f"is the most uncertain reachable region and no hazard there is confirmed yet.")
        a = Action(ActionType.DISPATCH_HAPS, haps.id, target=wp, target_id=e.id if e else None)
        return [_mk(view.t, a, u, imp, g, fuel, 0.0, 0.0, haps.health, ben, why)]

    # -- DRONE ----------------------------------------------------------- #
    def _drone(self, view: WorldView, ests, UI) -> List[Decision]:
        haps = next((s for s in view.satellites if s.kind == "HAPS"), None)
        drone = next((s for s in view.satellites if s.kind == "DRONE"), None)
        if haps is None or drone is None:
            return []
        for e in sorted(ests, key=lambda x: -x.existence):
            ok, why = should_dispatch_drone(e, haps, drone, view.t)
            if ok:
                u, imp = UI[e.id]
                a = Action(ActionType.DISPATCH_DRONE, drone.id, target=e.pos, target_id=e.id)
                ben = config.INFO_VALUE * u * imp
                return [_mk(view.t, a, u, imp, 1.0, dist(drone.pos, e.pos) * 0.01, 0.0, 0.0, drone.health, ben,
                            f"{drone.id} is dispatched to {e.id} in the {region_name(e.pos)} sector: {why}.")]
        return []


# --------------------------------------------------------------------------- #
class BaselinePolicy:
    """BRAIN OFF: fixed lawnmower, raw FIFO downlink, last-minute independent collision avoidance."""

    def __init__(self, physics) -> None:
        self.physics = physics
        self.planner = LawnmowerPlanner()

    def decide(self, view: WorldView) -> List[Decision]:
        t, out = view.t, []
        for s in view.satellites:
            if s.kind != "SAT" or s.status in (Status.LOST.value, Status.DEAD.value, Status.RETIRED.value):
                continue
            items = view.pending.get(s.id, [])
            if s.in_contact and items:
                mb = sum(i.size_raw_mb for i in items)
                a = Action(ActionType.DOWNLINK, s.id, params={"item_ids": [i.id for i in items], "compress": False,
                                                              "drop_ids": []})
                out.append(_mk(t, a, 0.0, 0.0, 0.0, 0.0, min(mb, view.link_mb_per_min), 0.0, s.health, 0.0,
                               f"{s.id} dumps its buffer in FIFO order, raw ({mb:.0f} MB queued) -- no prioritisation."))
            if s.operational and s.debris_risk >= config.BASELINE_DODGE_RISK:
                cs = [c for c in view.conjunctions.get(s.id, []) if c.tca >= t and (s.id, c.debris_id) not in view.dodged]
                if cs:
                    c = max(cs, key=lambda c: c.probability * math.exp(-((t - c.tca) / config.CONJ_PEAK_WIDTH) ** 2))
                    lead = c.tca - t
                    cost = self.physics.dodge_fuel_cost(s, lead)
                    if s.fuel_kg >= cost:
                        a = Action(ActionType.DODGE, s.id, target_id=c.debris_id,
                                   params={"lead": lead, "eff": self.physics.dodge_effectiveness(s, lead)})
                        out.append(_mk(t, a, 1.0, 0.0, 0.0, cost, 0.0, c.probability, s.health, 0.0,
                                       f"{s.id} dodges {c.debris_id} independently because instantaneous risk "
                                       f"{s.debris_risk:.1%} exceeded the fixed threshold ({lead:.0f} min to go)."))
        haps = next((s for s in view.satellites if s.kind == "HAPS"), None)
        if haps is not None:
            wp, changed = self.planner.next_waypoint(haps.pos)
            if changed or haps.target is None:
                a = Action(ActionType.DISPATCH_HAPS, haps.id, target=wp)
                out.append(_mk(t, a, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0,
                               f"{haps.id} continues its fixed lawnmower sweep to ({wp[0]:.0f}, {wp[1]:.0f})."))
        return out
