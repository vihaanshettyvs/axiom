"""engine.py -- deterministic minute-by-minute simulation engine; writes a RunLog.

    python engine.py --mode both --seed 42        # runs BRAIN ON and BRAIN OFF, writes out/*.json

Per minute:  physics+plume step -> sensors observe -> estimator predict/update ->
             risk calc (conjunctions) -> triage brain -> apply actions -> collisions ->
             record events + Frame.
The frontend must ONLY replay the RunLog; it never calls anything in this project.
"""
from __future__ import annotations

import argparse
import copy
import importlib
import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import config
from contracts import (CELL_KM, CONTRACT_VERSION, GRID_N, Action, ActionType, Asset, Conjunction, Decision,
                       Frame, Hazard, Observation, PendingItem, RunLog, Satellite, Status, WorldView, dist,
                       make_rng, to_jsonable)
import mocks
import scenario_data
from brain.leakhunter import footprint_weights


# --------------------------------------------------------------------------- #
def build_platforms() -> List[Satellite]:
    """Identical initial conditions for every run (no randomness here)."""
    sp = config.SENSOR_SPECS
    out: List[Satellite] = []
    for d in config.SATELLITES:
        s = sp["SAT"]
        out.append(Satellite(
            id=d["id"], kind="SAT", pos=tuple(d["A"]), status=Status.ACTIVE.value, fuel_kg=d["fuel"],
            fuel_capacity_kg=config.SAT_FUEL_CAPACITY, health=d["health"], sensor_confidence=s["pd"],
            sensor_radius_km=s["radius"], slew_km=s["slew"], sigma_km=s["sigma"], fp_rate=s["fp"],
            cloud_sensitivity=s["cloud"], mission_importance=d["importance"],
            orbit=dict(A=tuple(d["A"]), B=tuple(d["B"]), period=d["period"], phase=d["phase"],
                       degrade_rate=d["degrade"], base_conf=s["pd"])))
    h = sp["HAPS"]
    out.append(Satellite(id="HAPS-1", kind="HAPS", pos=config.HAPS_START, status=Status.ACTIVE.value, fuel_kg=5.0,
                         fuel_capacity_kg=5.0, sensor_confidence=h["pd"], sensor_radius_km=h["radius"],
                         sigma_km=h["sigma"], fp_rate=h["fp"], cloud_sensitivity=h["cloud"],
                         mission_importance=0.8, in_view=True))
    dr = sp["DRONE"]
    out.append(Satellite(id="DRONE-1", kind="DRONE", pos=config.DRONE_BASE, status=Status.IDLE.value, fuel_kg=70.0,
                         fuel_capacity_kg=70.0, sensor_confidence=dr["pd"], sensor_radius_km=dr["radius"],
                         sigma_km=dr["sigma"], fp_rate=dr["fp"], cloud_sensitivity=dr["cloud"],
                         mission_importance=0.8, in_view=True))
    out.append(Satellite(id="TUG-1", kind="TUG", pos=(0.0, -30.0), status=Status.IDLE.value, fuel_kg=10.0,
                         fuel_capacity_kg=10.0, orbit={"park": (0.0, -30.0)}))
    return out


def _import_obj(path: str):
    mod, name = path.split(":")
    return getattr(importlib.import_module(mod), name)


class Guarded:
    """Fault-isolating proxy around a module.

    If a call into the real module raises, the proxy permanently swaps in the mock fallback, reports the failure
    (-> a MODULE_FALLBACK event in the RunLog) and retries the same call on the fallback, so one broken or missing
    module never crashes the simulation.
    """

    def __init__(self, name: str, impl: Any, fallback_factory, report, is_mock: bool) -> None:
        self.__dict__.update(_name=name, _impl=impl, _fb=fallback_factory, _report=report, _is_mock=is_mock,
                             swapped=False)

    @property
    def status(self) -> str:
        return "fallback" if self.swapped else ("mock" if self._is_mock else "real")

    def __getattr__(self, attr: str):
        target = getattr(self.__dict__["_impl"], attr)          # AttributeError propagates (hasattr() works)
        if not callable(target):
            return target

        def call(*a, **k):
            try:
                return getattr(self._impl, attr)(*a, **k)
            except Exception as e:                               # noqa: BLE001 - isolate any module failure
                if self._is_mock:
                    raise                                        # the mock itself failed: nothing left to fall back to
                self._report(self._name, f"{attr}() raised {type(e).__name__}: {e}")
                self.__dict__["_impl"] = self._fb()
                self.__dict__["_is_mock"] = True
                self.__dict__["swapped"] = True
                return getattr(self._impl, attr)(*a, **k)
        return call


class Engine:
    def __init__(self, mode: str = "on", seed: Optional[int] = None, duration: Optional[int] = None,
                 use_real: Optional[Dict[str, bool]] = None, space_weather: Optional[float] = None,
                 weather_schedule: Optional[Dict[int, float]] = None) -> None:
        assert mode in ("on", "off")
        self._weather0 = space_weather
        self.weather_schedule = dict(weather_schedule or {})      # {minute: w} for scripted storms
        self.mode = mode
        self.seed = config.SEED if seed is None else seed
        self.duration = config.DURATION_MIN if duration is None else duration
        self.use_real = dict(config.USE_REAL if use_real is None else use_real)
        self._build()

    # ------------------------------------------------------------------ #
    def _report(self, name: str, msg: str) -> None:
        self._ev("MODULE_FALLBACK", name, f"Module '{name}' failed ({msg}); switched to the mock implementation.")

    def _module(self, name: str, real_factory, mock_factory):
        """Build a module guarded against failures; a broken import/constructor falls back to the mock."""
        if self.use_real.get(name) and real_factory is not None:
            try:
                return Guarded(name, real_factory(), mock_factory, self._report, False)
            except Exception as e:                               # noqa: BLE001
                self._report(name, f"could not load: {type(e).__name__}: {e}")
        return Guarded(name, mock_factory(), mock_factory, self._report, True)

    def _build(self) -> None:
        ur = self.use_real
        self.t, self.events = 0.0, []
        self.hazard_specs, self.hazard_source, warns = scenario_data.build_hazard_specs()
        for w in warns:
            self._ev("DATA_FALLBACK", "scenario", w + " -- using the next data source.")
        sats0 = build_platforms()

        def mock_phys():
            m = mocks.MockPhysics()
            m.adopt(self.seed, getattr(self, "sats", None) or sats0)
            return m

        def mock_plume():
            m = mocks.MockPlume(self.seed, self.hazard_specs)
            try:                                                 # keep the world continuous if the real plume dies
                m._h = [copy.copy(h) for h in self.plume.hazards()]
            except Exception:                                    # noqa: BLE001
                pass
            return m

        from brain.plume import PlumeModel
        from brain.leakhunter import MultiKindLeakHunter
        self.physics = self._module("physics", lambda: _import_obj(config.PHYSICS_REAL_PATH)(), mock_phys)
        self.plume = self._module("plume", lambda: PlumeModel(self.seed, self.hazard_specs),
                                  lambda: mocks.MockPlume(self.seed, self.hazard_specs))
        self.lh = self._module("leakhunter", lambda: MultiKindLeakHunter(self.seed),
                               lambda: mocks.MockLeakHunter(self.seed))
        if self.mode == "on":
            from brain.triage import TriageBrain
            self.triage = self._module("triage", lambda: TriageBrain(self.physics, use_adaptive_haps=bool(ur.get("haps"))),
                                       mocks.MockTriage)
        else:
            from brain.triage import BaselinePolicy
            self.triage = Guarded("triage", BaselinePolicy(self.physics), mocks.MockTriage, self._report, False)

        if self._weather0 is not None:
            self.set_space_weather(self._weather0)
        self.sats = self.physics.reset(self.seed, sats0)
        self.plume.reset()
        self.lh.reset()
        self._load_extensions()
        self.assets = [Asset(a["name"], tuple(a["pos"]), a["weight"]) for a in config.ASSETS]
        self.obs_store: Dict[str, Observation] = {}
        self.pending: Dict[str, List[PendingItem]] = {s.id: [] for s in self.sats if s.kind == "SAT"}
        self.aims: Dict[str, Tuple[float, float]] = {}
        self.dodged: Dict[Tuple[str, str], float] = {}
        self.resolved: set = set()
        self.t = 0.0
        self._obs_n = 0
        self.m = dict(fuel_used_kg=0.0, bandwidth_mb=0.0, alerts=0, sats_lost=0, uncontrolled_dead=0, retired=0,
                      serviced=0, expected_sat_loss=0.0, dodges=0, loc_error_km=25.0, observations=0,
                      downlinked_scans=0, dropped_scans=0)
        self.latencies: List[float] = []
        self.loc_errs: List[float] = []
        self.t_detect: Dict[str, float] = {}
        self.t_localize: Dict[str, float] = {}
        self.false_tracks: set = set()
        self._alerted: set = set()
        self._confirmed_seen: set = set()
        self._prev_status = {s.id: s.status for s in self.sats}
        self._last_ests: List[Any] = []
        self._last_handoff_ev: Dict[str, float] = {}
        self._observer: Dict[str, Tuple[str, float]] = {}      # hazard/estimate id -> (satellite, last minute it was assigned)
        self._last_dodge: Dict[str, float] = {}
        self._reassigned: Dict[Tuple[str, str], float] = {}
        self._boot_events, self.events = self.events, []          # load-time events appear in frame 0
        self.log = RunLog(meta=self._meta(), scenario=self._scenario())
        self.log.scenario["retirement_lab"] = self._retirement_lab()

    # ------------------------------------------------------------------ #
    def _meta(self) -> Dict[str, Any]:
        return dict(contract_version=CONTRACT_VERSION, project="ORBITAL TRIAGE", mode=f"BRAIN_{self.mode.upper()}",
                    seed=self.seed, duration_min=self.duration, step_min=config.STEP_MIN, grid_n=GRID_N,
                    cell_km=CELL_KM, area_km=100.0, use_real=self.use_real, hazard_source=self.hazard_source,
                    n_satellites=sum(1 for s in self.sats if s.kind == "SAT"),
                    space_weather=getattr(self.physics, "space_weather", None))

    def _scenario(self) -> Dict[str, Any]:
        return dict(assets=to_jsonable(self.assets),
                    satellites=[dict(id=s.id, A=s.orbit["A"], B=s.orbit["B"], period=s.orbit["period"],
                                     phase=s.orbit["phase"], importance=s.mission_importance)
                                for s in self.sats if s.kind == "SAT"],
                    hazard_ids=[h["id"] for h in self.hazard_specs],
                    hazards=[dict(id=h["id"], kind=h.get("kind", "wildfire"), t_start=h["t_start"],
                                  source=("NASA_FIRMS" if (self.hazard_source.startswith("firms") and h.get("kind", "wildfire") == "wildfire")
                                          else "SIMULATED")) for h in self.hazard_specs],
                    hazard_source=self.hazard_source, hazard_source_note=self._source_note(), haps_start=config.HAPS_START,
                    drone_base=config.DRONE_BASE, sensor_specs=config.SENSOR_SPECS,
                    conjunctions=[dict(sat=a, debris=b, tca=c, p=d) for a, b, c, d in config.CONJUNCTIONS])

    def set_space_weather(self, w: float) -> bool:
        """Live knob (0..1, 0.5 nominal). Returns False if the physics has no weather model (mock)."""
        f = getattr(self.physics, "set_space_weather", None)
        if f is None:
            return False
        f(w)
        return True

    def _retirement_lab(self) -> Dict[str, Any]:
        """Frontend-ready Retirement Lab rows per satellite at quiet / nominal / storm space weather (P2 physics)."""
        lab = getattr(self.physics, "retirement_lab", None)
        if lab is None:
            return {}
        keep = getattr(self.physics, "space_weather", 0.5)
        out: Dict[str, Any] = {}
        for s in self.sats:
            if s.kind == "SAT":
                out[s.id] = {}
                for w in (0.0, 0.25, 0.5, 0.75, 1.0):
                    self.physics.set_space_weather(w)
                    out[s.id][f"{w:.2f}"] = lab(s, 0.0)
        self.physics.set_space_weather(keep)
        return out

    def _source_note(self) -> str:
        if self.hazard_source.startswith("firms"):
            return (f"Wildfires: {config.FIRMS_CREDIT}; 100x100 km window centred at lat/lon "
                    f"{scenario_data.FIRMS_REGION_USED}, read with {scenario_data.FIRMS_READER_USED}. "
                    f"Methane leaks, debris and satellites are SIMULATED.")
        return "All hazards, debris and satellites are SIMULATED (no real FIRMS data loaded)."

    def sat(self, sid: str) -> Satellite:
        return next(s for s in self.sats if s.id == sid)

    def _ev(self, typ: str, actor: str, msg: str) -> None:
        self.events.append(dict(t=self.t, type=typ, actor=actor, msg=msg))

    # -- optional extensions (e.g. P4 telemetry) ----------------------------- #
    # An extension is any class with OPTIONAL methods  on_reset(meta)  on_step(frame)  on_end(summary).
    # It can observe the run but cannot change engine state. A failing/missing extension is disabled, never fatal.
    def _load_extensions(self) -> None:
        self.extensions: Dict[str, Any] = {}
        for name, path in (config.EXTENSIONS or {}).items():
            try:
                self.extensions[name] = _import_obj(path)()
            except Exception as e:                               # noqa: BLE001
                self._ev("EXTENSION_DISABLED", name, f"Extension '{name}' could not load ({type(e).__name__}: {e}).")

    def _ext(self, hook: str, arg: Any) -> None:
        for name in list(self.extensions):
            fn = getattr(self.extensions[name], hook, None)
            if fn is None:
                continue
            try:
                fn(arg)
            except Exception as e:                               # noqa: BLE001
                del self.extensions[name]
                msg = f"Extension '{name}'.{hook} raised {type(e).__name__}: {e}; disabled."
                self._boot_events.append(dict(t=self.t, type="EXTENSION_DISABLED", actor=name, msg=msg))   # lands in the next frame
                self.log.meta.setdefault("warnings", []).append(msg)

    # ------------------------------------------------------------------ #
    def run(self) -> RunLog:
        self._ext("on_reset", self.log.meta)
        completed = True
        for k in range(self.duration):
            self.t = float(k)
            try:
                self.step()
            except Exception as e:                               # noqa: BLE001 - even the mock failed: stop cleanly
                completed = False
                self.log.meta["error"] = f"step {k}: {type(e).__name__}: {e}"
                break
        self.log.meta["completed"] = completed
        self.log.meta["frames_recorded"] = len(self.log.frames)
        self.log.meta["modules"] = {n: getattr(self, n).status for n in ("physics", "plume", "lh", "triage")}
        self.log.meta["extensions"] = sorted(self.extensions)
        if self.log.frames:
            self.log.summary = self._summary()
        self.log.summary["completed"] = completed
        self._ext("on_end", self.log.summary)
        return self.log

    def step(self) -> None:
        t, dt = self.t, config.STEP_MIN
        self.events, self._boot_events = self._boot_events, []
        if int(t) in self.weather_schedule:
            self.set_space_weather(self.weather_schedule[int(t)])
            self._ev("SPACE_WEATHER", "ENV", f"Space-weather index set to {self.weather_schedule[int(t)]:.2f}.")
        self.aims_now: Dict[str, Tuple[float, float]] = {}
        # 1. world advances
        self.sats = self.physics.step(self.sats, t, dt)
        self.plume.step(t, dt)
        self._move_flyers()
        self._track_status_changes()
        # 2. sensors observe
        self.lh.predict(dt)
        new_obs = self._observe()
        # 3. direct-link observations reach the estimator immediately
        for o in new_obs:
            if o.source != "SAT":
                self._deliver(o)
        # 4. risks / 5. brain
        view = self._view()
        decisions = [d for d in (self.triage.decide(view) or []) if isinstance(d, Decision)]
        # 6. apply actions (one bad decision must not stop the world)
        for d in decisions:
            try:
                self._apply(d)
            except Exception as e:                               # noqa: BLE001
                self._ev("ACTION_FAILED", d.action.actor_id, f"{d.action.type.value} failed: {type(e).__name__}: {e}")
        # 7. collisions
        self._resolve_collisions()
        self._track_status_changes()
        # 8. estimates + metrics + frame
        ests = self.lh.estimates(t)
        self._last_ests = ests
        self._update_metrics(ests)
        fr = self._frame(new_obs, decisions, ests)
        self.log.frames.append(fr)
        self._ext("on_step", fr)

    # ------------------------------------------------------------------ #
    def _move_flyers(self) -> None:
        for p in self.sats:
            if p.kind not in ("HAPS", "DRONE") or p.status == Status.DEAD.value:
                continue
            speed = config.SENSOR_SPECS[p.kind]["speed"]
            if p.kind == "DRONE" and p.status == Status.ACTIVE.value and p.target is not None:
                near = [e for e in self._last_ests if e.existence >= 0.3 and dist(e.pos, p.target) < 15.0]
                if near:                                           # follow the (moving) hazard estimate
                    p.target = min(near, key=lambda e: dist(e.pos, p.target)).pos
                if p.fuel_kg <= 0:
                    p.status, p.target = Status.IDLE.value, None
                    self._ev("DRONE_DONE", p.id, f"{p.id} battery exhausted; returning idle.")
                    continue
            if p.target is not None:
                d = dist(p.pos, p.target)
                step = min(speed, d)
                if d > 1e-9:
                    p.vel = ((p.target[0] - p.pos[0]) / d * step, (p.target[1] - p.pos[1]) / d * step)
                    p.pos = (p.pos[0] + p.vel[0], p.pos[1] + p.vel[1])
                else:
                    p.vel = (0.0, 0.0)
                if p.kind == "HAPS":
                    p.fuel_kg = max(0.0, p.fuel_kg - config.HAPS_BURN_PER_KM * step)
                elif p.status == Status.ACTIVE.value:
                    p.fuel_kg = max(0.0, p.fuel_kg - (1.0 if step > 0 else 0.2))
                if p.kind == "DRONE" and d <= speed:
                    p.orbit["hover"] = p.orbit.get("hover", 0) + 1
                    if p.orbit["hover"] > 6:                    # mission complete -> idle in place
                        p.status, p.target, p.orbit["hover"] = Status.IDLE.value, None, 0
                        self._ev("DRONE_DONE", p.id, f"{p.id} finished its ground check and holds position.")

    def _observe(self) -> List[Observation]:
        out: List[Observation] = []
        for s in self.sats:
            aim = None
            if s.kind == "SAT" and s.operational and s.in_view:
                if self.mode == "off":
                    aim = s.pos
                elif s.id in self.aims:
                    a = self.aims[s.id]
                    d = dist(a, s.pos)
                    aim = a if d <= s.slew_km else (s.pos[0] + (a[0] - s.pos[0]) / d * s.slew_km,
                                                    s.pos[1] + (a[1] - s.pos[1]) / d * s.slew_km)
            elif s.kind == "HAPS" and s.status == Status.ACTIVE.value:
                aim = s.pos
            elif s.kind == "DRONE" and s.status == Status.ACTIVE.value:
                aim = s.pos
            s.aim = aim
            if aim is None:
                continue
            self._obs_n += 1
            o = self.plume.observe(s, aim, self.t, f"OBS-{self._obs_n:05d}")
            self.obs_store[o.id] = o
            out.append(o)
            self.m["observations"] += 1
            if s.kind == "SAT":
                w = footprint_weights(aim, s.sensor_radius_km)
                self.pending[s.id].append(PendingItem(o.id, s.id, self.t, o.detected, o.size_raw_mb, o.size_comp_mb,
                                                      float((w * self.lh.grid()).sum()), aim, s.sensor_radius_km))
        self.aims = {}
        for s in self.sats:
            if s.kind == "SAT":
                s.buffer_mb = sum((i.size_raw_mb if self.mode == "off" else i.size_comp_mb) for i in self.pending[s.id])
        return out

    def _deliver(self, o: Observation, via_mb: Optional[float] = None) -> None:
        o.delivered_t = self.t
        self.lh.update(o, self.t)
        if o.detected:
            self.latencies.append(self.t - o.t)
            if self.mode == "off":
                self.m["alerts"] += len(o.detections)          # operator must read every raw detection
        if o.source != "SAT":
            self.m["bandwidth_mb"] += o.size_raw_mb if self.mode == "off" else o.size_comp_mb

    def _view(self) -> WorldView:
        conj = {s.id: self.physics.upcoming_conjunctions(s, self.t, config.CONJ_FORECAST_MIN)
                for s in self.sats if s.kind == "SAT" and s.status not in (Status.LOST.value, Status.RETIRED.value)}
        return WorldView(self.t, self.sats, self.lh.estimates(self.t), self.lh.grid().copy(), self.assets, conj,
                         {k: list(v) for k, v in self.pending.items()}, self.physics.tug_status(self.t),
                         list(self.dodged.keys()), config.LINK_MB_PER_MIN, self.seed)

    # ------------------------------------------------------------------ #
    def _apply(self, d: Decision) -> None:
        a, t = d.action, self.t
        s = self.sat(a.actor_id)
        if a.type == ActionType.OBSERVE:
            if a.target is not None:
                self.aims[s.id] = a.target
            self._burn(s, a.fuel_cost)
            if a.target_id:
                prev = self._observer.get(a.target_id)
                td = self._last_dodge.get(prev[0], -99.0) if prev else -99.0
                if (prev and prev[0] != s.id and prev[1] - 3.0 <= td <= t and t - td <= 30.0
                        and t - self._reassigned.get((a.target_id, s.id), -99.0) >= 15.0):
                    self._reassigned[(a.target_id, s.id)] = t
                    self._ev("REASSIGN", s.id, f"Observation of {a.target_id} passes from {prev[0]} (busy dodging debris) "
                                               f"to {s.id}, which takes over the watch. {d.reason}")
                self._observer[a.target_id] = (s.id, t)
        elif a.type == ActionType.DOWNLINK:
            self._downlink(s, a)
        elif a.type == ActionType.HANDOFF:
            dst = self.sat(a.params["dst"])
            ids = set(a.params["item_ids"])
            moved = [i for i in self.pending[s.id] if i.id in ids]
            self.pending[s.id] = [i for i in self.pending[s.id] if i.id not in ids]
            self.pending[dst.id] += moved
            self.m["bandwidth_mb"] += sum(i.size_comp_mb for i in moved)
            if self.t - self._last_handoff_ev.get(s.id, -99.0) >= 10.0:
                self._last_handoff_ev[s.id] = self.t
                self._ev("HANDOFF", s.id, d.reason)
        elif a.type == ActionType.DODGE:
            lead = a.params.get("lead", 0.0)
            cost = self.physics.dodge_fuel_cost(s, lead)
            if s.fuel_kg >= cost:
                self.dodged[(s.id, a.target_id)] = self.physics.dodge_effectiveness(s, lead)
                self._burn(s, cost)
                self._last_dodge[s.id] = t
                shift = getattr(self.physics, "execute_dodge", None)      # P2: route change; fuel already debited here
                if shift:
                    try:
                        shift(s, t, a.target_id, debit_fuel=False)
                    except Exception as ex:                              # optional hook, never fatal
                        self._ev("MODULE_WARNING", "ENGINE", f"execute_dodge unavailable: {ex}")
                self.m["dodges"] += 1
                self._ev("DODGE", s.id, d.reason)
            else:
                self._ev("DODGE_FAILED", s.id, f"{s.id} lacked fuel to dodge {a.target_id}.")
        elif a.type == ActionType.RETIRE:
            s.status = Status.RETIRING.value
            s.orbit["retire_done_t"] = t + a.params["duration_min"]
            self._burn(s, a.params["fuel_kg"])
            self._ev("RETIRE", s.id, d.reason)
        elif a.type == ActionType.REQUEST_TUG:
            r = self.physics.request_tug(s, t)
            self._ev("TUG_REQUEST" if r["accepted"] else "TUG_DENIED", s.id, d.reason if r["accepted"] else
                     f"Tug unavailable for {s.id}.")
        elif a.type == ActionType.DISPATCH_HAPS:
            s.target = a.target
            if self.mode == "on":
                self._ev("DISPATCH_HAPS", s.id, d.reason)
        elif a.type == ActionType.DISPATCH_DRONE:
            s.target, s.status = a.target, Status.ACTIVE.value
            s.orbit["hover"] = 0
            self._ev("DISPATCH_DRONE", s.id, d.reason)

    def _burn(self, s: Satellite, kg: float) -> None:
        s.fuel_kg = max(0.0, s.fuel_kg - kg)
        self.m["fuel_used_kg"] += kg

    def _downlink(self, s: Satellite, a: Action) -> None:
        if not s.in_contact:
            return
        compress = a.params.get("compress", False)
        ids = a.params.get("item_ids", [])
        drop = set(a.params.get("drop_ids", []))
        by_id = {i.id: i for i in self.pending[s.id]}
        budget, sent = config.LINK_MB_PER_MIN, set()
        for iid in ids:
            it = by_id.get(iid)
            if it is None:
                continue
            size = it.size_comp_mb if compress else it.size_raw_mb
            if size > budget:
                break
            budget -= size
            self.m["bandwidth_mb"] += size
            self.m["downlinked_scans"] += 1
            self._deliver(self.obs_store[iid])
            sent.add(iid)
        self.m["dropped_scans"] += len(drop & set(by_id))
        self.pending[s.id] = [i for i in self.pending[s.id] if i.id not in sent and i.id not in drop]

    def _resolve_collisions(self) -> None:
        for s in self.sats:
            if s.kind != "SAT" or s.status in (Status.LOST.value, Status.RETIRED.value):
                continue
            for c in self.physics.upcoming_conjunctions(s, self.t, config.STEP_MIN):
                key = (s.id, c.debris_id)
                if key in self.resolved:
                    continue
                self.resolved.add(key)
                p_eff = c.probability * (1.0 - self.dodged.get(key, 0.0))
                self.m["expected_sat_loss"] += p_eff
                if make_rng(self.seed, "col", s.id, c.debris_id).random() < p_eff:
                    s.status = Status.LOST.value
                    self._ev("COLLISION", s.id, f"{s.id} was destroyed by {c.debris_id} (p={p_eff:.3f}).")

    def _track_status_changes(self) -> None:
        for s in self.sats:
            prev = self._prev_status.get(s.id)
            if s.status != prev:
                if s.status == Status.LOST.value:
                    self.m["sats_lost"] += 1
                    self.m["alerts"] += 1
                elif s.status == Status.DEAD.value:
                    self.m["uncontrolled_dead"] += 1
                    self.m["alerts"] += 1
                    self._ev("DEAD", s.id, f"{s.id} died uncontrolled and is now debris.")
                elif s.status == Status.RETIRED.value:
                    self.m["retired"] += 1
                    self._ev("RETIRED", s.id, f"{s.id} completed a graceful de-orbit.")
                elif s.status == Status.SERVICING.value:
                    self._ev("SERVICING", s.id, f"Tug docked with {s.id}.")
                elif prev == Status.SERVICING.value and s.status == Status.ACTIVE.value:
                    self.m["serviced"] += 1
                    self._ev("SERVICED", s.id, f"{s.id} serviced: fuel {s.fuel_kg:.2f} kg, health {s.health:.2f}.")
                self._prev_status[s.id] = s.status

    # ------------------------------------------------------------------ #
    def _update_metrics(self, ests) -> None:
        truth = [h for h in self.plume.hazards() if h.active]
        errs = []
        for h in truth:
            real = [e for e in ests if e.existence >= 0.3 and e.kind == h.kind]
            errs.append(min([dist(e.pos, h.pos) for e in real] + [25.0]))     # capped at 25 km (also when the only estimates are far off)
            for e in (x for x in ests if x.kind == h.kind):
                d = dist(e.pos, h.pos)
                if d < 10 and e.existence >= 0.5:
                    self.t_detect.setdefault(h.id, self.t)
                if d < 6 and e.existence >= 0.8 and e.uncertainty_km <= 4.0:
                    self.t_localize.setdefault(h.id, self.t)
        if errs:
            self.m["loc_error_km"] = float(np.mean(errs))
            self.loc_errs.append(self.m["loc_error_km"])
        for e in ests:
            if e.existence >= 0.6:
                same = [h for h in truth if h.kind == e.kind]
                if truth and min([dist(e.pos, h.pos) for h in same] or [99.0]) > 10:
                    self.false_tracks.add(e.id)
                if self.mode == "on" and e.id not in self._alerted:
                    self._alerted.add(e.id)
                    self.m["alerts"] += 1
                    self._ev("ALERT", e.id, f"Hazard {e.id} confirmed likely at ({e.pos[0]:.0f}, {e.pos[1]:.0f}) km.")
            if e.confirmed and e.id not in self._confirmed_seen:
                self._confirmed_seen.add(e.id)
                self._ev("CONFIRMED", e.id, f"{e.id} confirmed by ground-level drone.")
                if self.mode == "on":
                    self.m["alerts"] += 1

    def _frame(self, obs, decisions, ests) -> Frame:
        sats = []
        for s in self.sats:
            c = copy.copy(s)
            c.orbit = {k: v for k, v in s.orbit.items() if k in ("serviced", "last_breath", "tug_arrival_t", "tug_done_t",
                                                                  "retire_done_t", "telemetry", "maneuvers",
                                                                  "failure_mode", "battery")}
            sats.append(c)
        hz = [copy.copy(h) for h in self.plume.hazards()]
        D = self.lh.grid()
        belief = np.rint(np.clip(D, 0, 1) * 1000).astype(int).tolist()
        return Frame(self.t, sats, hz, list(obs), list(decisions), ests, belief, round(self.lh.entropy_bits(), 3),
                     round(self.lh.uncertainty(ests), 4), list(self.events),
                     {k: round(float(v), 4) for k, v in self.m.items()},
                     belief_by_kind={k: np.rint(np.clip(g, 0, 1) * 1000).astype(int).tolist()
                                     for k, g in getattr(self.lh, "grids", lambda: {})().items()})

    def _summary(self) -> Dict[str, Any]:
        ids = [h["id"] for h in self.hazard_specs]
        lat = float(np.mean(self.latencies)) if self.latencies else float("nan")
        cap = float(self.duration)
        td = [self.t_detect.get(i, cap) - self.hazard_specs[k]["t_start"] for k, i in enumerate(ids)]
        tl = [self.t_localize.get(i, cap) - self.hazard_specs[k]["t_start"] for k, i in enumerate(ids)]
        return dict(mode=self.log.meta["mode"], seed=self.seed,
                    mean_loc_error_km=float(np.mean(self.loc_errs)) if self.loc_errs else 25.0,
                    time_to_detect_min={i: self.t_detect.get(i) for i in ids},
                    mean_time_to_detect_min=float(np.mean(td)),
                    time_to_localize_min={i: self.t_localize.get(i) for i in ids},
                    mean_time_to_localize_min=float(np.mean(tl)),
                    mean_detection_latency_min=lat, false_alarm_tracks=len(self.false_tracks),
                    fuel_used_kg=self.m["fuel_used_kg"], bandwidth_mb=self.m["bandwidth_mb"],
                    attention_alerts=self.m["alerts"], sats_lost=self.m["sats_lost"],
                    expected_sat_loss=self.m["expected_sat_loss"], uncontrolled_dead=self.m["uncontrolled_dead"],
                    retired=self.m["retired"], serviced=self.m["serviced"], dodges=self.m["dodges"],
                    observations=self.m["observations"], final_entropy_bits=self.log.frames[-1].entropy_bits)


# --------------------------------------------------------------------------- #
def run(mode: str, seed: Optional[int] = None, duration: Optional[int] = None,
        use_real: Optional[Dict[str, bool]] = None) -> RunLog:
    return Engine(mode, seed, duration, use_real).run()


def compare(seed: Optional[int] = None, duration: Optional[int] = None, out_dir: Optional[str] = None,
            use_real: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    on = run("on", seed, duration, use_real)
    off = run("off", seed, duration, use_real)
    keys = ["mean_loc_error_km", "mean_time_to_detect_min", "mean_time_to_localize_min", "mean_detection_latency_min",
            "false_alarm_tracks", "fuel_used_kg", "bandwidth_mb", "attention_alerts", "sats_lost",
            "expected_sat_loss", "uncontrolled_dead"]
    table = {}
    for k in keys:
        a, b = on.summary[k], off.summary[k]
        table[k] = dict(brain_on=a, brain_off=b, improvement_pct=(100.0 * (b - a) / b) if b else 0.0)
    comp = dict(seed=on.summary["seed"], metrics=table)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        on.save(os.path.join(out_dir, "runlog_brain_on.json"))
        off.save(os.path.join(out_dir, "runlog_brain_off.json"))
        with open(os.path.join(out_dir, "comparison.json"), "w") as fh:
            json.dump(to_jsonable(comp), fh, indent=2)
        try:                                                  # P4's analysis report (optional: a missing/broken module is only a warning)
            from sensing.report import generate_p4_report
            rep = generate_p4_report(to_jsonable(on.to_dict()), to_jsonable(off.to_dict()))
            with open(os.path.join(out_dir, "p4_report.json"), "w") as fh:
                json.dump(to_jsonable(rep), fh, indent=2)
        except Exception as ex:                               # noqa: BLE001
            print(f"[warning] P4 report skipped: {type(ex).__name__}: {ex}")
    comp["_logs"] = (on, off)
    return comp


def _print(comp: Dict[str, Any]) -> None:
    print(f"{'metric':32s}{'BRAIN ON':>12s}{'BRAIN OFF':>12s}{'better by':>11s}")
    for k, v in comp["metrics"].items():
        print(f"{k:32s}{v['brain_on']:12.3f}{v['brain_off']:12.3f}{v['improvement_pct']:10.0f}%")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="both", choices=["on", "off", "both"])
    ap.add_argument("--seed", type=int, default=config.SEED)
    ap.add_argument("--duration", type=int, default=config.DURATION_MIN)
    ap.add_argument("--out", default=config.OUT_DIR)
    ap.add_argument("--mock-all", action="store_true", help="run with every module mocked")
    a = ap.parse_args()
    ur = {k: False for k in config.USE_REAL} if a.mock_all else None
    if a.mode == "both":
        _print(compare(a.seed, a.duration, a.out, ur))
        print(f"wrote {a.out}/runlog_brain_on.json, runlog_brain_off.json, comparison.json")
    else:
        lg = run(a.mode, a.seed, a.duration, ur)
        os.makedirs(a.out, exist_ok=True)
        lg.save(os.path.join(a.out, f"runlog_brain_{a.mode}.json"))
        print(json.dumps(to_jsonable(lg.summary), indent=2))
