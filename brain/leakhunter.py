"""brain/leakhunter.py -- Bayesian hazard localisation on a 50 x 50 grid.

Method: a grid version of the PHD / "expected number of hazards per cell" filter.
D[c] ~= P(a hazard centre lies in cell c)  (sum over the grid ~= number of hazards).

predict : diffuse (hazards drift) + relax toward the prior (old information goes stale)
update  :
  * NEGATIVE scan  -> D[c] *= 1 - trust * pd * w(c)   inside the footprint
  * POSITIVE scan  -> for each detection k at m_k:
        D'[c] = (1 - pd w) D[c] + sum_k  pd w G(m_k; c, sigma_eff) D[c] / (kappa + sum_c pd w G D)
    kappa = clutter (false-positive) density, so a lone detection is only ~70% believed,
    a second consistent one makes it ~99%.  A false positive that is never repeated
    fades away because the following negative scans erode it.
  * sigma_eff grows with the age of delayed observations (hazards moved since).
Nothing assumes a reading is true: sensor quality, false positives, missed detections
and untrusted negatives are all in the likelihood.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np

import config
from brain.plume import edge_weight
from contracts import (CELL_KM, GRID_N, Estimate, Observation, Vec2, dist, grid_xy, pos_to_cell)


def binary_entropy(p: np.ndarray) -> np.ndarray:
    q = np.clip(p, 1e-9, 1 - 1e-9)
    return -(q * np.log2(q) + (1 - q) * np.log2(1 - q))


def footprint_weights(aim: Vec2, radius: float) -> np.ndarray:
    X, Y = grid_xy()
    return edge_weight(np.sqrt((X - aim[0]) ** 2 + (Y - aim[1]) ** 2), radius)


def expected_gain(D: np.ndarray, aim: Vec2, radius: float, pd: float,
                  HbD: Optional[np.ndarray] = None) -> Tuple[float, float, float]:
    """Return (info_gain_0_1, entropy_term, mass_term) for scanning at `aim`.

    entropy_term: binary entropy of the belief inside the footprint (uncertainty to resolve)
    mass_term   : belief mass inside the footprint (hazard likely to be seen)
    """
    w = footprint_weights(aim, radius)
    Hb = binary_entropy(D) if HbD is None else HbD
    ent = float((w * Hb).sum())
    mass = float((w * D).sum())
    raw = pd * (ent + config.GAIN_MASS_W * mass)
    return 1.0 - math.exp(-raw / config.GAIN_K), ent, mass


def _box_sum(A: np.ndarray, k: int) -> np.ndarray:
    """Sum over a (2k+1)^2 window, zero padded."""
    P = np.pad(A, k + 1)
    C = P.cumsum(0).cumsum(1)
    n = 2 * k + 1
    return C[n:, n:][:GRID_N, :GRID_N] - C[:-n, n:][:GRID_N, :GRID_N] \
        - C[n:, :-n][:GRID_N, :GRID_N] + C[:-n, :-n][:GRID_N, :GRID_N]


class LeakHunter:
    def __init__(self, seed: int = config.SEED, prefix: str = "EST", diffuse: Optional[float] = None,
                 relax: Optional[float] = None, kind: str = "wildfire") -> None:
        self.X, self.Y = grid_xy()
        self.prefix, self.kind = prefix, kind
        self.diffuse = config.LH_DIFFUSE if diffuse is None else diffuse
        self.relax = config.LH_RELAX if relax is None else relax
        self.reset()

    def reset(self) -> None:
        self.D = np.full((GRID_N, GRID_N), config.LH_PRIOR)
        self.last_seen = np.full((GRID_N, GRID_N), -1e9)
        self.records: List[Tuple[float, Vec2, float, str]] = []     # (t, pos, intensity, source)
        self.confirmed: List[Tuple[Vec2, float]] = []               # (pos, t) of drone confirmations
        self._tracks: List[Dict] = []
        self._next_id = 1

    # ------------------------------------------------------------------ #
    def predict(self, dt: float) -> None:
        a = min(0.2, self.diffuse * dt)
        P = np.pad(self.D, 1, mode="edge")
        lap = P[:-2, 1:-1] + P[2:, 1:-1] + P[1:-1, :-2] + P[1:-1, 2:] - 4 * self.D
        self.D = self.D + a * lap
        self.D += min(1.0, self.relax * dt) * (config.LH_PRIOR - self.D)
        np.clip(self.D, 0.0, 1.0, out=self.D)

    def update(self, obs: Observation, now: float) -> None:
        age = max(0.0, now - obs.t)
        w = footprint_weights(obs.aim, obs.radius_km)
        pd_c = np.clip(obs.pd_nominal * obs.visibility, 0.02, 0.995) * w      # cloudy scan = weak evidence either way
        self.last_seen = np.where(w > 0.5, now, self.last_seen)
        D = self.D
        if not obs.detections:
            D = D * (1.0 - config.LH_NEG_TRUST * pd_c)
        else:
            sig = math.sqrt(obs.sigma_km ** 2 + (config.LH_DRIFT_SPEED * age) ** 2)
            kappa = config.LH_CLUTTER_MULT * obs.fp_rate / (math.pi * obs.radius_km ** 2)   # clutter density per km^2 (pessimistic)
            new = (1.0 - pd_c) * D
            for det in obs.detections:
                G = np.exp(-((self.X - det.pos[0]) ** 2 + (self.Y - det.pos[1]) ** 2) / (2 * sig ** 2)) \
                    / (2 * math.pi * sig ** 2)
                term = pd_c * G * D
                new = new + term / (kappa + term.sum())
                self.records.append((obs.t, det.pos, det.intensity, obs.source))
                if obs.source == "DRONE":
                    self.confirmed.append((det.pos, now))
            D = new
            self.records = self.records[-300:]
        self.D = np.clip(D, 0.0, 1.0)

    # ------------------------------------------------------------------ #
    def grid(self) -> np.ndarray:
        return self.D

    def entropy_bits(self) -> float:
        return float(binary_entropy(self.D).sum())

    def best_location(self) -> Tuple[Vec2, float]:
        iy, ix = np.unravel_index(np.argmax(self.D), self.D.shape)
        return ((ix + 0.5) * CELL_KM, (iy + 0.5) * CELL_KM), float(self.D[iy, ix])

    def estimates(self, now: float, max_n: int = 4) -> List[Estimate]:
        W = self.D.copy()
        peaks: List[Tuple[Vec2, float, float]] = []
        for _ in range(max_n):
            S = _box_sum(W, 2)
            iy, ix = np.unravel_index(np.argmax(S), S.shape)
            if S[iy, ix] < config.LH_EST_MIN_MASS:
                break
            y0, y1, x0, x1 = max(0, iy - 4), min(GRID_N, iy + 5), max(0, ix - 4), min(GRID_N, ix + 5)
            win = W[y0:y1, x0:x1]
            m = float(win.sum())
            cx = float((win * self.X[y0:y1, x0:x1]).sum() / m)
            cy = float((win * self.Y[y0:y1, x0:x1]).sum() / m)
            var = float((win * ((self.X[y0:y1, x0:x1] - cx) ** 2 + (self.Y[y0:y1, x0:x1] - cy) ** 2)).sum() / m)
            peaks.append(((cx, cy), m, math.sqrt(max(var, 0.0) / 2.0 + 0.25 * CELL_KM ** 2)))
            W[max(0, iy - 5):iy + 6, max(0, ix - 5):ix + 6] = 0.0
        return self._to_estimates(peaks, now)

    def _to_estimates(self, peaks, now: float) -> List[Estimate]:
        out: List[Estimate] = []
        used = set()
        self.confirmed = [(p, t) for p, t in self.confirmed if now - t <= config.LH_CONFIRM_TTL]
        for pos, mass, sd in peaks:
            tid, best = None, 12.0
            for tr in self._tracks:
                d = dist(tr["pos"], pos)
                if tr["id"] not in used and d < best:
                    tid, best = tr["id"], d
            if tid is None:
                tid = f"{self.prefix}-{self._next_id:02d}"
                self._next_id += 1
                self._tracks.append({"id": tid, "pos": pos})
            used.add(tid)
            for tr in self._tracks:
                if tr["id"] == tid:
                    tr["pos"] = pos
            near = [r for r in self.records if dist(r[1], pos) < max(6.0, 3 * sd) and now - r[0] < 90]
            inten, growth = 0.5, 0.0
            if near:
                wts = np.array([math.exp(-(now - r[0]) / 40.0) for r in near])
                inten = float(np.average([r[2] for r in near], weights=wts))
                if len(near) >= 3:
                    ts = np.array([r[0] for r in near])
                    if ts.max() - ts.min() > 5:
                        growth = float(np.polyfit(ts, [r[2] for r in near], 1)[0] * 10.0)
            ex = min(1.0, mass)
            conf = ex / (1.0 + (sd / 4.0) ** 2)
            confirmed = any(dist(p, pos) < config.LH_CONFIRM_RADIUS for p, _ in self.confirmed) and ex > 0.5
            ix, iy = pos_to_cell(*pos)
            last = float(self.last_seen[max(0, iy - 1):iy + 2, max(0, ix - 1):ix + 2].max())
            out.append(Estimate(tid, (round(pos[0], 3), round(pos[1], 3)), round(ex, 4), round(conf, 4),
                                round(sd, 3), round(inten, 3), round(growth, 4), confirmed,
                                last if last > -1e8 else -1.0, len(near), self.kind))
        return out

    def uncertainty(self, ests: List[Estimate]) -> float:
        real = [e for e in ests if e.existence >= 0.3]
        return 1.0 if not real else float(1.0 - np.mean([e.confidence for e in real]))


class MultiKindLeakHunter:
    """One LeakHunter per hazard kind (wildfire, methane), behind the single LeakHunterAPI.

    * a scan is split by detection kind; a NEGATIVE scan updates every kind (methane with its weaker sensor)
    * grid() is the max over kinds (what the brain/HAPS planner use); grids() gives each kind's 50x50 grid
    * estimates() merges all kinds, each tagged Estimate.kind
    """

    def __init__(self, seed: int = config.SEED, kinds=None) -> None:
        self.kinds = list(kinds or config.LH_PARAMS)
        self.hunters: Dict[str, LeakHunter] = {
            k: LeakHunter(seed, kind=k, **config.LH_PARAMS.get(k, {})) for k in self.kinds}

    def reset(self) -> None:
        for h in self.hunters.values():
            h.reset()

    def predict(self, dt: float) -> None:
        for h in self.hunters.values():
            h.predict(dt)

    def _view_for(self, obs: Observation, kind: str) -> Observation:
        import dataclasses
        dets = [d for d in obs.detections if d.kind == kind]
        pd, sg = obs.pd_nominal, obs.sigma_km
        if kind == "methane":
            pd, sg = pd * config.METHANE_PD_SCALE, sg * config.METHANE_SIGMA_SCALE
        return dataclasses.replace(obs, detections=dets, pd_nominal=pd, sigma_km=sg)

    def update(self, obs: Observation, now: float) -> None:
        for k, h in self.hunters.items():
            h.update(self._view_for(obs, k), now)

    def grid(self) -> np.ndarray:
        return np.maximum.reduce([h.grid() for h in self.hunters.values()])

    def grids(self) -> Dict[str, np.ndarray]:
        return {k: h.grid() for k, h in self.hunters.items()}

    def entropy_bits(self) -> float:
        return float(sum(h.entropy_bits() for h in self.hunters.values()))

    def estimates(self, now: float, max_n: int = 4) -> List[Estimate]:
        out: List[Estimate] = []
        for h in self.hunters.values():
            out += h.estimates(now, max_n)
        return out

    def uncertainty(self, ests: List[Estimate]) -> float:
        real = [e for e in ests if e.existence >= 0.3]
        return 1.0 if not real else float(1.0 - np.mean([e.confidence for e in real]))
