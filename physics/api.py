"""physics/api.py - RealPhysics: P2's implementation of contracts.PhysicsAPI.

Thin facade over space/{orbits,debris,degradation,lastbreath,retire,tug}.py.
Set config.USE_REAL["physics"] = True (config.PHYSICS_REAL_PATH = "physics.api:RealPhysics").

Extras beyond PhysicsAPI (optional for P1/P3/P5):
  RealPhysics.space_weather / set_space_weather(w)   0..1, 0.5 nominal (Retirement Lab slider)
  retirement_lab(sat, t)        3-way comparison + do-nothing, frontend-ready rows
  conjunction_reports(sat, t)   Pc, miss distance, consequence, risk per upcoming conjunction
  tug_rank(requests)            competing tug requests -> chosen + reason
  sat.orbit["last_breath"]      {verdict, reason, rul_min, point_of_no_return_min, urgency, ...}
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import config
from contracts import Conjunction, Satellite, Status
from space import NOMINAL_WEATHER, clamp01, debris, degradation, lastbreath, orbits, retire, tug

_LIVE = (Status.ACTIVE.value, Status.DEGRADED.value, Status.SERVICING.value, Status.RETIRING.value)


class RealPhysics:
    def __init__(self) -> None:
        self.seed = config.SEED
        self.space_weather = clamp01(getattr(config, "SPACE_WEATHER", NOMINAL_WEATHER))
        self.enc: Dict[str, List[dict]] = {}
        self.tug_free_at = 0.0
        self.tug_fuel = tug.TUG_FUEL_KG

    def set_space_weather(self, w: float) -> None:
        self.space_weather = clamp01(w)

    # -- PhysicsAPI -------------------------------------------------------- #
    def reset(self, seed: int, sats: List[Satellite]) -> List[Satellite]:
        self.seed = seed
        self.enc = debris.build_encounters(seed, config.CONJUNCTIONS)
        self.tug_free_at = 0.0
        self.tug_fuel = tug.TUG_FUEL_KG
        self._tug_display_kg = next((s.fuel_kg for s in sats if s.kind == "TUG"), None)
        for s in sats:
            if s.kind == "SAT":
                orbits.init_orbit(s.orbit, s.id)
                s.orbit.setdefault("battery", s.health)
        return self.step(sats, 0.0, 0.0)

    def step(self, sats: List[Satellite], t: float, dt: float) -> List[Satellite]:
        w = self.space_weather
        for s in sats:
            if s.kind == "TUG":
                self._step_tug(s, sats, t)
                continue
            if s.kind != "SAT":
                continue
            o = s.orbit
            p0 = s.pos
            orbits.apply_due_route_changes(o, t)
            s.pos = orbits.pos_at(o, t)
            s.vel = (s.pos[0] - p0[0], s.pos[1] - p0[1]) if dt > 0 else (0.0, 0.0)
            tug.update_servicing(s, o, t)
            if s.status == Status.RETIRING.value and t >= o.get("retire_done_t", 1e18):
                s.status = Status.RETIRED.value
            if s.status in _LIVE and dt > 0:
                degradation.step(s, o, self.seed, t, dt, w)
            s.sensor_confidence = degradation.sensor_confidence(s, o)
            s.rul_min = lastbreath.rul_min(s, o, w)
            reach = s.sensor_radius_km + s.slew_km
            s.in_view = orbits.in_view_at(o, t, reach)
            comm_ok = o.get("comm_ok", True)
            s.in_contact = orbits.in_contact_at(o, t) and comm_ok
            s.view_left_min, s.next_view_min = orbits.view_times(o, t, reach, s.in_view)
            s.next_contact_min = orbits.next_contact_min(o, t) if comm_ok else 999.0
            s.debris_risk = debris.instantaneous_risk(self.enc.get(s.id, []), t, config.CONJ_PEAK_WIDTH)
            o["last_breath"] = lastbreath.assess(s, o, w, retire.engine_options(s, o))
            o["failure_prob_60m"] = o["last_breath"]["failure_prob_60m"]
            o["telemetry"] = degradation.telemetry(s, o)
        return sats

    def coverage_windows(self, sat: Satellite, t: float, horizon_min: float) -> List[Tuple[float, float]]:
        return orbits.coverage_windows(sat.orbit, t, horizon_min, sat.sensor_radius_km + sat.slew_km)

    def upcoming_conjunctions(self, sat: Satellite, t: float, horizon_min: float) -> List[Conjunction]:
        return debris.upcoming(self.enc, sat.id, t, horizon_min)

    def dodge_fuel_cost(self, sat: Satellite, lead_min: float) -> float:
        return debris.dodge_fuel_cost(lead_min)

    def dodge_effectiveness(self, sat: Satellite, lead_min: float) -> float:
        return debris.dodge_effectiveness(lead_min) if sat.orbit.get("prop_ok", True) else 0.0

    def retirement_options(self, sat: Satellite, t: float) -> List[Dict[str, Any]]:
        return retire.engine_options(sat, sat.orbit)

    def tug_status(self, t: float) -> Dict[str, Any]:
        return {"available": t >= self.tug_free_at, "eta_min": config.TUG["eta_min"],
                "service_min": config.TUG["service_min"], "free_at": self.tug_free_at,
                "fuel_kg": self.tug_fuel}

    def request_tug(self, sat: Satellite, t: float) -> Dict[str, Any]:
        if t < self.tug_free_at or not tug.can_accept(sat):
            return {"accepted": False, "arrival_t": -1.0, "complete_t": -1.0}
        ops = tug.plan_ops(sat, sat.orbit)
        cost = tug.fuel_cost(ops)
        if cost > self.tug_fuel + 1e-9:
            return {"accepted": False, "arrival_t": -1.0, "complete_t": -1.0, "reason": "tug propellant exhausted"}
        self.tug_fuel -= cost
        arr = t + config.TUG["eta_min"]
        done = arr + tug.service_minutes(ops)
        sat.orbit.update(tug_arrival_t=arr, tug_done_t=done, tug_target=sat.id, tug_ops=ops)
        self.tug_free_at = done + config.TUG["cooldown_min"]
        return {"accepted": True, "arrival_t": arr, "complete_t": done, "ops": ops, "tug_fuel_cost_kg": cost}

    # -- extras ------------------------------------------------------------ #
    # -- threats, recommendations, manoeuvres (standalone sim / scenario setup) ---- #
    def inject_threat(self, sat: Satellite, t: float, level: str = "HIGH") -> Dict[str, Any]:
        """Add an approaching debris object aimed at `sat`. Deterministic per (seed, sat, level, serial).
        NOT called by the engine: its scripted config.CONJUNCTIONS stay the single source of truth."""
        serial = sum(len(v) for v in self.enc.values())
        e = debris.generate_threat(self.seed, sat.id, t, level, serial)
        self.enc.setdefault(sat.id, []).append(e)
        return e

    def recommend_dodge(self, sat: Satellite, t: float) -> List[Dict[str, Any]]:
        """One recommendation per upcoming encounter on `sat` (risk, dodge yes/no, fuel cost, reason)."""
        return [debris.recommend(e, sat, t) for e in self.enc.get(sat.id, []) if e["tca"] >= t
                and e["debris_id"] not in sat.orbit.get("dodged", [])]

    def execute_dodge(self, sat: Satellite, t: float, debris_id: str, debit_fuel: bool = False) -> Dict[str, Any]:
        """Perform an avoidance manoeuvre: log it, shift the orbit phase, record the residual likelihood.
        debit_fuel=False by default because the engine already debits fuel for DODGE actions; set True in a
        standalone sim. Does NOT alter upcoming_conjunctions() output (it must stay deterministic)."""
        e = next((x for x in self.enc.get(sat.id, []) if x["debris_id"] == debris_id), None)
        if e is None:
            return {"executed": False, "reason": "unknown debris id"}
        lead = max(0.0, e["tca"] - t)
        cost = debris.dodge_fuel_cost(lead)
        if not sat.orbit.get("prop_ok", True) or sat.fuel_kg < cost:
            return {"executed": False, "reason": "propulsion failed or insufficient fuel", "fuel_needed_kg": cost}
        eff = debris.dodge_effectiveness(lead)
        if debit_fuel:
            sat.fuel_kg -= cost
        # along-track phasing: ~3*dv*t displacement, expressed as a timing shift of the ground track
        shift_km = debris.DODGE_SHIFT_M / 1000.0 * eff
        orbits.apply_route_change(sat.orbit, t, dphase_min=shift_km / 456.0, kind="collision_avoidance",
                                  note=f"dodge {debris_id}")
        sat.orbit.setdefault("dodged", []).append(debris_id)
        return {"executed": True, "debris_id": debris_id, "lead_min": lead, "fuel_kg": cost,
                "effectiveness": eff, "residual_likelihood": e["p"] * (1.0 - eff)}

    def plan_route_change(self, sat: Satellite, t_exec: float, dphase_min: float = 0.0, dcross_km: float = 0.0) -> None:
        """Queue a planned route change (applied by step() at t >= t_exec). Propellant is the caller's concern."""
        orbits.schedule_route_change(sat.orbit, t_exec, dphase_min, dcross_km)

    def observation_opportunities(self, sats: List[Satellite], target_xy, t: float, horizon_min: float):
        return orbits.observation_opportunities(sats, target_xy, t, horizon_min)

    def debris_state(self, sat: Satellite, t: float) -> List[Dict[str, Any]]:
        return [debris.relative_state(e, t) for e in self.enc.get(sat.id, [])]

    def retirement_lab(self, sat: Satellite, t: float) -> List[Dict[str, Any]]:
        return retire.lab(sat, sat.orbit, self.space_weather)

    def conjunction_reports(self, sat: Satellite, t: float, horizon_min: float = 1e9) -> List[Dict[str, Any]]:
        return [debris.assess(e, sat.mission_importance, sat.health, t) for e in self.enc.get(sat.id, [])
                if t <= e["tca"] < t + horizon_min]

    def tug_rank(self, requests: List[dict]) -> Dict[str, Any]:
        return tug.rank_requests(requests)

    # -- cosmetic tug animation (position only) ----------------------------- #
    def _step_tug(self, tg: Satellite, sats: List[Satellite], t: float) -> None:
        tgt = next((s for s in sats if s.kind == "SAT" and "tug_arrival_t" in s.orbit), None)
        park = tg.orbit.get("park", (0.0, -30.0))
        if getattr(self, "_tug_display_kg", None):          # show remaining tug propellant in the shared state
            tg.fuel_kg = self._tug_display_kg * self.tug_fuel / tug.TUG_FUEL_KG
        if tgt is None:
            tg.status, tg.target, tg.pos = Status.IDLE.value, None, park
            return
        tg.status, tg.target = Status.ACTIVE.value, tgt.pos
        a = tgt.orbit["tug_arrival_t"]
        if t >= a:
            tg.pos = tgt.pos
        else:
            f = 1.0 - (a - t) / config.TUG["eta_min"]
            tg.pos = (park[0] + (tgt.pos[0] - park[0]) * f, park[1] + (tgt.pos[1] - park[1]) * f)
