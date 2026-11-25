"""mocks.py -- plausible stand-ins so the engine/frontend run before real modules exist.

MockPhysics  : interim stand-in for P2's physics (same PhysicsAPI). Not a duplicate:
               when USE_REAL["physics"] is True the engine never touches it.
MockPlume, MockLeakHunter, MockTriage : trivial but contract-compliant.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

import numpy as np

import config
from contracts import (AREA_KM, GRID_N, Action, ActionType, Conjunction, Decision, Detection,
                       Estimate, Hazard, Observation, Satellite, Status, Vec2, WorldView, dist,
                       grid_xy, make_rng)


# --------------------------------------------------------------------------- #
class MockPhysics:
    """Linear ground tracks, scripted conjunctions, linear degradation, one tug."""

    def __init__(self) -> None:
        self.seed = config.SEED
        self.conj: Dict[str, List[Conjunction]] = {}
        self.tug_free_at = 0.0

    # -- geometry ---------------------------------------------------------- #
    @staticmethod
    def _s(o: Dict[str, Any], t: float) -> float:
        return ((t + o["phase"]) % o["period"]) / o["period"]

    def _pos_at(self, o: Dict[str, Any], t: float) -> Vec2:
        s = self._s(o, t)
        return (o["A"][0] + (o["B"][0] - o["A"][0]) * s, o["A"][1] + (o["B"][1] - o["A"][1]) * s)

    @staticmethod
    def _view(pos: Vec2, reach: float) -> bool:
        cx = min(max(pos[0], 0.0), AREA_KM)
        cy = min(max(pos[1], 0.0), AREA_KM)
        return dist(pos, (cx, cy)) < reach

    def _contact(self, o: Dict[str, Any], t: float) -> bool:
        lo, hi = config.CONTACT_S_RANGE
        return lo <= self._s(o, t) <= hi

    # -- PhysicsAPI -------------------------------------------------------- #
    def adopt(self, seed: int, sats: List[Satellite]) -> None:
        """Take over mid-run (fallback from a failed real physics): rebuild schedules, keep satellite state."""
        self.seed = seed
        self.conj = {s.id: [] for s in sats}
        for sid, deb, tca, p in config.CONJUNCTIONS:
            if sid in self.conj:
                self.conj[sid].append(Conjunction(sid, deb, float(tca), float(p)))
        for s in sats:
            s.orbit.setdefault("base_conf", config.SENSOR_SPECS["SAT"]["pd"])

    def reset(self, seed: int, sats: List[Satellite]) -> List[Satellite]:
        self.seed = seed
        self.conj = {s.id: [] for s in sats}
        for sid, deb, tca, p in config.CONJUNCTIONS:
            if sid in self.conj:
                self.conj[sid].append(Conjunction(sid, deb, float(tca), float(p)))
        self.tug_free_at = 0.0
        return self.step(sats, 0.0, 0.0)

    def step(self, sats: List[Satellite], t: float, dt: float) -> List[Satellite]:
        for s in sats:
            if s.kind == "TUG":
                self._step_tug(s, sats, t)
                continue
            if s.kind != "SAT":
                continue
            o = s.orbit
            p0 = s.pos
            s.pos = self._pos_at(o, t)
            s.vel = (s.pos[0] - p0[0], s.pos[1] - p0[1]) if dt > 0 else (0.0, 0.0)
            # servicing timeline (owned by physics)
            if "tug_arrival_t" in o:
                if o["tug_arrival_t"] <= t < o["tug_done_t"]:
                    s.status = Status.SERVICING.value
                elif t >= o["tug_done_t"]:
                    s.fuel_kg = min(s.fuel_capacity_kg, s.fuel_kg + config.TUG["fuel_gain_kg"])
                    s.health = min(1.0, s.health + config.TUG["health_gain"])
                    o["degrade_rate"] *= 0.5
                    s.status = Status.ACTIVE.value
                    o["serviced"] = True
                    del o["tug_arrival_t"], o["tug_done_t"]
            if s.status == Status.RETIRING.value and t >= o.get("retire_done_t", 1e18):
                s.status = Status.RETIRED.value
            live = s.status in (Status.ACTIVE.value, Status.DEGRADED.value, Status.SERVICING.value,
                                Status.RETIRING.value)
            if live and dt > 0:
                rng = make_rng(self.seed, "deg", s.id, int(t))
                s.health -= o["degrade_rate"] * dt
                if rng.random() < config.SHOCK_PROB:
                    s.health -= rng.uniform(0.03, 0.10)
                s.health = max(0.0, s.health)
                if s.health <= 0.02 and s.status in (Status.ACTIVE.value, Status.DEGRADED.value):
                    s.status = Status.DEAD.value
                elif s.status == Status.ACTIVE.value and s.health < 0.5:
                    s.status = Status.DEGRADED.value
                elif s.status == Status.DEGRADED.value and s.health >= 0.5:
                    s.status = Status.ACTIVE.value
            s.sensor_confidence = o["base_conf"] * (0.55 + 0.45 * s.health)
            s.rul_min = s.health / (o["degrade_rate"] + config.SHOCK_PROB * 0.065 + 1e-9)
            # derived coverage fields
            reach = s.sensor_radius_km + s.slew_km
            s.in_view = self._view(s.pos, reach)
            s.in_contact = self._contact(o, t)
            s.view_left_min, s.next_view_min = self._view_times(s, t, reach)
            s.next_contact_min = self._contact_time(o, t)
            s.debris_risk = max([c.probability * math.exp(-((t - c.tca) / config.CONJ_PEAK_WIDTH) ** 2)
                                 for c in self.conj.get(s.id, [])] or [0.0])
        return sats

    def _view_times(self, s: Satellite, t: float, reach: float) -> Tuple[float, float]:
        o = s.orbit
        if s.in_view:
            k = 0
            while k < 240 and self._view(self._pos_at(o, t + k + 1), reach):
                k += 1
            return float(k + 1), 0.0
        k = 0
        while k < 240 and not self._view(self._pos_at(o, t + k + 1), reach):
            k += 1
        return 0.0, float(k + 1)

    def _contact_time(self, o: Dict[str, Any], t: float) -> float:
        if self._contact(o, t):
            return 0.0
        k = 0
        while k < 240 and not self._contact(o, t + k + 1):
            k += 1
        return float(k + 1)

    def coverage_windows(self, sat: Satellite, t: float, horizon_min: float) -> List[Tuple[float, float]]:
        reach = sat.sensor_radius_km + sat.slew_km
        out, start = [], None
        for k in range(int(horizon_min) + 1):
            v = self._view(self._pos_at(sat.orbit, t + k), reach)
            if v and start is None:
                start = t + k
            if not v and start is not None:
                out.append((start, t + k))
                start = None
        if start is not None:
            out.append((start, t + horizon_min))
        return out

    def upcoming_conjunctions(self, sat: Satellite, t: float, horizon_min: float) -> List[Conjunction]:
        return [c for c in self.conj.get(sat.id, []) if t <= c.tca < t + horizon_min]

    def dodge_fuel_cost(self, sat: Satellite, lead_min: float) -> float:
        return 0.04 + 0.22 * math.exp(-max(lead_min, 0.0) / 25.0)

    def dodge_effectiveness(self, sat: Satellite, lead_min: float) -> float:
        return 1.0 - math.exp(-max(lead_min, 0.0) / 9.0)

    def retirement_options(self, sat: Satellite, t: float) -> List[Dict[str, Any]]:
        opts = [{"name": "controlled_deorbit", "fuel_kg": 0.30, "duration_min": 15.0},
                {"name": "graveyard_orbit", "fuel_kg": 0.18, "duration_min": 25.0}]
        return [o for o in opts if sat.fuel_kg >= o["fuel_kg"] + 0.02]

    def tug_status(self, t: float) -> Dict[str, Any]:
        return {"available": t >= self.tug_free_at, "eta_min": config.TUG["eta_min"],
                "service_min": config.TUG["service_min"], "free_at": self.tug_free_at}

    def request_tug(self, sat: Satellite, t: float) -> Dict[str, Any]:
        if t < self.tug_free_at or sat.kind != "SAT":
            return {"accepted": False, "arrival_t": -1.0, "complete_t": -1.0}
        arr = t + config.TUG["eta_min"]
        done = arr + config.TUG["service_min"]
        sat.orbit["tug_arrival_t"], sat.orbit["tug_done_t"] = arr, done
        sat.orbit["tug_target"] = sat.id
        self.tug_free_at = done + config.TUG["cooldown_min"]
        return {"accepted": True, "arrival_t": arr, "complete_t": done}

    def _step_tug(self, tug: Satellite, sats: List[Satellite], t: float) -> None:
        tgt = next((s for s in sats if s.kind == "SAT" and "tug_arrival_t" in s.orbit), None)
        if tgt is None:
            tug.status, tug.target = Status.IDLE.value, None
            tug.pos = tug.orbit.get("park", (0.0, -30.0))
            return
        a, d = tgt.orbit["tug_arrival_t"], tgt.orbit["tug_done_t"]
        tug.status = Status.ACTIVE.value
        tug.target = tgt.pos
        if t >= a:
            tug.pos = tgt.pos
        else:
            f = 1.0 - (a - t) / config.TUG["eta_min"]
            park = tug.orbit.get("park", (0.0, -30.0))
            tug.pos = (park[0] + (tgt.pos[0] - park[0]) * f, park[1] + (tgt.pos[1] - park[1]) * f)


# --------------------------------------------------------------------------- #
class MockPlume:
    """Hazards drift linearly; sensors see everything inside the footprint, no noise."""

    def __init__(self, seed: int = config.SEED, hazard_specs=None) -> None:
        self.seed = seed
        self.specs = list(hazard_specs or config.HAZARDS)
        self._h: List[Hazard] = []
        self.reset()

    def reset(self) -> None:
        self._h = [Hazard(id=h["id"], kind=h.get("kind", "wildfire"), pos=tuple(h["pos"]), vel=tuple(h["wind"]),
                          radius_km=h["radius0"], intensity=h["int0"], t_start=h["t_start"]) for h in self.specs]

    def step(self, t: float, dt: float) -> None:
        for h in self._h:
            h.active = t >= h.t_start
            if h.active and dt > 0:
                h.pos = (h.pos[0] + h.vel[0] * dt, h.pos[1] + h.vel[1] * dt)
                h.radius_km = min(8.0, h.radius_km + 0.03 * dt)

    def hazards(self) -> List[Hazard]:
        return self._h

    def observe(self, sensor: Satellite, aim: Vec2, t: float, obs_id: str) -> Observation:
        spec = config.SENSOR_SPECS[sensor.kind]
        dets = [Detection(h.pos, h.intensity, False, h.id, h.kind) for h in self._h
                if h.active and dist(aim, h.pos) < sensor.sensor_radius_km]
        return Observation(obs_id, t, sensor.id, sensor.kind, aim, sensor.sensor_radius_km, dets,
                           sensor.sigma_km, sensor.sensor_confidence, sensor.fp_rate,
                           spec["raw_mb"], spec["comp_pos_mb"] if dets else spec["comp_neg_mb"])


class MockLeakHunter:
    """Gaussian blob at the last positive detection that fades with time."""

    def __init__(self, seed: int = config.SEED) -> None:
        self.reset()

    def reset(self) -> None:
        self._centres: List[List[float]] = []     # x, y, strength, last_t
        self._D = np.full((GRID_N, GRID_N), config.LH_PRIOR)
        self.confirmed: List[Tuple[Vec2, float]] = []

    def predict(self, dt: float) -> None:
        for c in self._centres:
            c[2] *= 0.995

    def update(self, obs: Observation, now: float) -> None:
        for d in obs.detections:
            self._centres.append([d.pos[0], d.pos[1], 0.8, now])
        self._centres = self._centres[-6:]

    def grid(self) -> np.ndarray:
        X, Y = grid_xy()
        D = np.full((GRID_N, GRID_N), config.LH_PRIOR)
        for x, y, s, _ in self._centres:
            D += s * np.exp(-((X - x) ** 2 + (Y - y) ** 2) / (2 * 3.0 ** 2)) / 8.0
        return np.clip(D, 0, 1)

    def estimates(self, now: float, max_n: int = 4) -> List[Estimate]:
        return [Estimate(f"EST-{i + 1:02d}", (c[0], c[1]), min(1.0, c[2]), min(1.0, c[2]) * 0.7, 3.0,
                         0.5, 0.0, False, c[3], 1) for i, c in enumerate(self._centres[-max_n:])]

    def entropy_bits(self) -> float:
        D = np.clip(self.grid(), 1e-6, 1 - 1e-6)
        return float(-(D * np.log2(D) + (1 - D) * np.log2(1 - D)).sum())

    def uncertainty(self, ests: List[Estimate]) -> float:
        return 1.0 if not ests else float(1 - np.mean([e.confidence for e in ests]))


class MockTriage:
    """Everything in view observes nadir; everything in contact downlinks raw."""

    def decide(self, view: WorldView) -> List[Decision]:
        out: List[Decision] = []
        for s in view.satellites:
            if s.kind != "SAT" or not s.operational:
                continue
            if s.in_view:
                a = Action(ActionType.OBSERVE, s.id, target=s.pos)
                out.append(Decision(view.t, a, 0.5, 0.5, 0.5, 0.0, 0.0, 0.0, s.health, 1.0,
                                    f"[mock] {s.id} observes nadir because it is in view."))
            items = view.pending.get(s.id, [])
            if s.in_contact and items:
                a = Action(ActionType.DOWNLINK, s.id, params={"item_ids": [i.id for i in items], "compress": False})
                out.append(Decision(view.t, a, 0.3, 0.3, 0.3, 0.0, sum(i.size_raw_mb for i in items), 0.0,
                                    s.health, 0.5, f"[mock] {s.id} dumps its buffer raw."))
        return out
