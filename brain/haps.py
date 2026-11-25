"""brain/haps.py -- HAPS waypoint planning, drone escalation rule, planner benchmark.

AdaptiveHAPSPlanner : moves toward high-probability and high-uncertainty cells, discounts
                      confirmed locations, penalises travel time, uses hysteresis.
LawnmowerPlanner    : fixed boustrophedon sweep (the brain-OFF baseline).
should_dispatch_drone : escalation rule for ground-level confirmation.
compare_planners    : offline A/B of the two planners on the same plume.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np

import config
from brain.leakhunter import LeakHunter, binary_entropy
from brain.plume import PlumeModel, edge_weight
from contracts import (AREA_KM, Asset, Estimate, Observation, Satellite, Vec2, dist, grid_xy, make_rng)


class LawnmowerPlanner:
    """Serpentine rows spaced so footprints just touch."""

    def __init__(self, radius: float = None) -> None:
        r = radius or config.SENSOR_SPECS["HAPS"]["radius"]
        spacing = 1.8 * r
        ys = list(np.arange(spacing / 2, AREA_KM, spacing))
        self.wps: List[Vec2] = []
        for i, y in enumerate(ys):
            xs = (5.0, AREA_KM - 5.0) if i % 2 == 0 else (AREA_KM - 5.0, 5.0)
            self.wps += [(xs[0], float(y)), (xs[1], float(y))]
        self.i = 0

    def next_waypoint(self, pos: Vec2) -> Tuple[Vec2, bool]:
        """Returns (waypoint, changed)."""
        changed = False
        if dist(pos, self.wps[self.i]) < 1.0 and self.i < len(self.wps) - 1:
            self.i += 1
            changed = True
        return self.wps[self.i], changed


class AdaptiveHAPSPlanner:
    LATTICE = 5.0

    def __init__(self, radius: float = None, speed: float = None) -> None:
        sp = config.SENSOR_SPECS["HAPS"]
        self.r = radius or sp["radius"]
        self.speed = speed or sp["speed"]
        self.pd = sp["pd"]
        c = np.arange(self.LATTICE, AREA_KM, self.LATTICE)
        self.cand = np.array([(x, y) for y in c for x in c], dtype=float)           # (M, 2)
        X, Y = grid_xy()
        d = np.sqrt((self.cand[:, 0:1] - X.ravel()[None, :]) ** 2 + (self.cand[:, 1:2] - Y.ravel()[None, :]) ** 2)
        self.W = edge_weight(d, self.r)                                              # (M, 2500)
        self.cur: Optional[Vec2] = None
        self._t_set = -1e9
        self.cur_score = 0.0
        self._X, self._Y = X, Y
        self._prox: Optional[np.ndarray] = None

    def _asset_proximity(self, assets) -> np.ndarray:
        if self._prox is None:
            P = np.zeros_like(self._X)
            for a in assets or []:
                P = np.maximum(P, a.weight * np.exp(-np.sqrt((self._X - a.pos[0]) ** 2 + (self._Y - a.pos[1]) ** 2) / 20.0))
            self._prox = P
        return self._prox

    def value_map(self, D: np.ndarray, ests: List[Estimate], now: float = 0.0, assets=None) -> np.ndarray:
        """Cell value: uncertainty + likelihood.  Locations that are already confirmed (drone) or tightly
        localised and freshly seen are switched off, and come back as their data goes stale."""
        V = (binary_entropy(D) + config.GAIN_MASS_W * D) * (1.0 + config.HAPS_ASSET_BIAS * self._asset_proximity(assets))
        for e in ests:
            tight = e.existence >= 0.9 and e.uncertainty_km <= 2.5
            if e.confirmed or tight:
                stale = 60.0 if e.last_obs_t < 0 else now - e.last_obs_t
                ttl = 50.0 if e.confirmed else 25.0
                f = 0.05 + 0.95 * min(1.0, stale / ttl)
                near = np.sqrt((self._X - e.pos[0]) ** 2 + (self._Y - e.pos[1]) ** 2) <= 6.0
                V = np.where(near, V * f, V)
        return V

    def plan(self, haps_pos: Vec2, D: np.ndarray, ests: List[Estimate], now: float = 0.0,
             assets=None) -> Tuple[Vec2, float, bool]:
        """Returns (waypoint, score, changed)."""
        V = self.value_map(D, ests, now, assets).ravel()
        travel = np.sqrt(((self.cand - np.array(haps_pos)) ** 2).sum(1)) / self.speed
        score = self.pd * (self.W @ V) / (1.0 + travel / 25.0)
        k = int(np.argmax(score))
        best = (float(self.cand[k, 0]), float(self.cand[k, 1]))
        changed = False
        if self.cur is None:
            changed = True
        else:
            cur_travel = dist(haps_pos, self.cur) / self.speed
            cur_score = self.pd * float(
                edge_weight(np.sqrt(((np.array([self._X.ravel(), self._Y.ravel()]).T - np.array(self.cur)) ** 2).sum(1)),
                            self.r) @ V) / (1.0 + cur_travel / 25.0)
            arrived = dist(haps_pos, self.cur) < 2.0
            dwell = (now - self._t_set) < 10.0
            if arrived or score[k] > (2.5 if dwell else 1.35) * max(cur_score, 1e-9):
                changed = best != self.cur
            else:
                best, k = self.cur, None
                return self.cur, cur_score, False
        if best != self.cur:
            self._t_set = now
        self.cur, self.cur_score = best, float(score[k])
        return best, float(score[k]), changed


def should_dispatch_drone(est: Estimate, haps: Satellite, drone: Satellite, now: float) -> Tuple[bool, str]:
    """Escalate to a ground-level drone when remote sensing cannot settle the question.

    Rules (all must hold):
      1. drone idle with enough battery to fly there,
      2. estimate is probably real (existence >= 0.6) but NOT yet confirmed,
      3. an aerial look is available (HAPS observed near it in the last 40 min) so the
         position is tight (uncertainty <= 4 km) -- send the drone to a good target,
      4. ground truth matters: fire is intense (>= 0.5) or evidence conflicts (a single
         detection while later scans were negative).
    """
    if drone.status not in ("IDLE",) or drone.fuel_kg < 10.0:
        return False, "drone unavailable"
    if est.confirmed:
        return False, "already confirmed on the ground"
    if est.existence < 0.6:
        return False, "existence too low to justify a dispatch"
    if est.uncertainty_km > 4.0:
        return False, "position too uncertain for a drone; keep refining aerially"
    if est.last_obs_t < 0 or now - est.last_obs_t > 40 or haps.status == "DEAD":
        return False, "no recent aerial observation"
    conflicting = est.n_pos <= 2 and est.existence < 0.85
    if est.intensity_est >= 0.5 or conflicting:
        why = "high intensity requires ground-level perimeter check" if est.intensity_est >= 0.5 \
            else "conflicting evidence needs ground truth"
        eta = dist(drone.pos, est.pos) / config.SENSOR_SPECS["DRONE"]["speed"]
        if eta * 1.2 + 8 <= drone.fuel_kg:
            return True, f"{why} (ETA {eta:.0f} min)"
        return False, "drone battery insufficient for the trip"
    return False, "remote sensing is sufficient"


def compare_planners(seed: int = config.SEED, minutes: int = 240) -> Dict[str, Dict[str, float]]:
    """HAPS-only A/B test: adaptive vs lawnmower on the same plume, same initial satellite cue."""
    out: Dict[str, Dict[str, float]] = {}
    assets = [Asset(a['name'], tuple(a['pos']), a['weight']) for a in config.ASSETS]
    for name in ("adaptive", "lawnmower"):
        plume, lh = PlumeModel(seed), LeakHunter(seed)
        haps = Satellite(id="HAPS-1", kind="HAPS", pos=config.HAPS_START, health=1.0,
                         sensor_confidence=config.SENSOR_SPECS["HAPS"]["pd"],
                         sensor_radius_km=config.SENSOR_SPECS["HAPS"]["radius"],
                         sigma_km=config.SENSOR_SPECS["HAPS"]["sigma"], fp_rate=config.SENSOR_SPECS["HAPS"]["fp"],
                         cloud_sensitivity=config.SENSOR_SPECS["HAPS"]["cloud"])
        planner = AdaptiveHAPSPlanner() if name == "adaptive" else LawnmowerPlanner()
        wp, speed, path, found, errs = haps.pos, config.SENSOR_SPECS["HAPS"]["speed"], 0.0, {}, []
        for t in range(minutes):
            plume.step(t, 1.0)
            lh.predict(1.0)
            if t == 5:   # one noisy satellite cue near the east fire, identical for both planners
                cue = plume.observe(Satellite(id="CUE", kind="SAT", sensor_confidence=0.95, sensor_radius_km=14,
                                              sigma_km=1.5, fp_rate=0.0),
                                    plume.hazards()[0].pos, 5, "cue")
                cue.source = "SAT"
                lh.update(cue, t)
            ests = lh.estimates(t)
            if name == "adaptive":
                wp, _, _ = planner.plan(haps.pos, lh.grid(), ests, t, assets)
            else:
                wp, _ = planner.next_waypoint(haps.pos)
            d = dist(haps.pos, wp)
            if d > 1e-6:
                step = min(speed, d)
                haps.pos = (haps.pos[0] + (wp[0] - haps.pos[0]) / d * step, haps.pos[1] + (wp[1] - haps.pos[1]) / d * step)
                path += step
            obs = plume.observe(haps, haps.pos, t, f"h{t}")
            obs.source = "HAPS"
            lh.update(obs, t)
            for h in plume.hazards():
                if h.active and h.id not in found:
                    e = [x for x in lh.estimates(t) if dist(x.pos, h.pos) < 8 and x.existence >= 0.8]
                    if e:
                        found[h.id] = float(t)
            for h in plume.hazards():
                if h.active:
                    e = lh.estimates(t)
                    errs.append(min([dist(x.pos, h.pos) for x in e if x.existence >= 0.3] + [25.0]))
        out[name] = {"time_to_find_mean_min": float(np.mean(list(found.values()))) if found else float("inf"),
                     "hazards_found": float(len(found)), "mean_loc_error_km": float(np.mean(errs)),
                     "path_km": float(path)}
        for hid, tt in found.items():
            out[name]["t_" + hid] = tt
    return out
