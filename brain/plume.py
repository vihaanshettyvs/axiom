"""brain/plume.py -- dynamic wildfire plume (ground truth) + imperfect sensor model.

The plume moves with a slowly turning wind plus gusts, expands, and its intensity
grows logistically with noise.  Sensors see it only probabilistically:

* missed detections : P(detect) = quality * edge(d) * intensity_term * (1 - cloud)
* localisation noise: Gaussian, sigma grows as sensor health falls
* false positives   : spurious blob at a random place in the footprint
* cloud cover       : hidden moving cloud band blinds optical sensors (the estimator
                      is NOT told about it -> it must not trust negatives blindly)
"""
from __future__ import annotations

import math
from typing import List

import numpy as np

import config
from contracts import (AREA_KM, Detection, Hazard, Observation, Satellite, Vec2, dist, make_rng)


def edge_weight(d, r: float):
    """1 inside 0.7r, linear fall-off to 0 at r.  Works on floats and arrays."""
    return np.clip((r - d) / (0.3 * r), 0.0, 1.0)


class PlumeModel:
    def __init__(self, seed: int = config.SEED, hazard_specs=None) -> None:
        self.seed = seed
        self.specs = {h["id"]: h for h in (hazard_specs or config.HAZARDS)}
        self._order = [h["id"] for h in (hazard_specs or config.HAZARDS)]
        self._cloud_phase = make_rng(seed, "cloud").uniform(0, 2 * math.pi)
        self.reset()

    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        self._rng = make_rng(self.seed, "plume")
        self._h = [Hazard(id=i, kind=self.specs[i].get("kind", "wildfire"), pos=tuple(self.specs[i]["pos"]),
                          vel=tuple(self.specs[i]["wind"]),
                          radius_km=self.specs[i]["radius0"], intensity=self.specs[i]["int0"],
                          t_start=self.specs[i]["t_start"]) for i in self._order]

    def hazards(self) -> List[Hazard]:
        return self._h

    def step(self, t: float, dt: float) -> None:
        """Advance every hazard to time t (call once per minute, in order)."""
        for h in self._h:
            sp = self.specs[h.id]
            gust = self._rng.normal(0.0, config.PLUME_TURBULENCE, 2)      # always drawn -> stable stream
            inten_noise = self._rng.normal(0.0, 0.008)
            h.active = t >= h.t_start
            if not h.active or dt <= 0:
                continue
            ang = sp["wind_turn"] * (t - h.t_start)
            wx = sp["wind"][0] * math.cos(ang) - sp["wind"][1] * math.sin(ang)
            wy = sp["wind"][0] * math.sin(ang) + sp["wind"][1] * math.cos(ang)
            h.vel = (wx + float(gust[0]), wy + float(gust[1]))
            x = min(max(h.pos[0] + h.vel[0] * dt, 3.0), AREA_KM - 3.0)
            y = min(max(h.pos[1] + h.vel[1] * dt, 3.0), AREA_KM - 3.0)
            h.pos = (x, y)
            h.radius_km = min(sp["rmax"], h.radius_km + sp["expansion"] * dt * (0.4 + h.intensity))
            h.intensity = float(min(1.0, max(0.05, h.intensity + sp["int_rate"] * (1.0 - h.intensity) * dt
                                             + inten_noise)))

    # ------------------------------------------------------------------ #
    def cloud_cover(self, t: float, pos: Vec2) -> float:
        """Hidden truth: 0 clear .. 0.8 heavy cloud (moving band)."""
        v = math.sin(0.045 * t + 0.06 * pos[0] + 0.02 * pos[1] + self._cloud_phase)
        return 0.8 * max(0.0, v) ** 2

    def observe(self, sensor: Satellite, aim: Vec2, t: float, obs_id: str) -> Observation:
        spec = config.SENSOR_SPECS[sensor.kind]
        rng = make_rng(self.seed, "obs", sensor.id, int(round(t)))
        quality = sensor.sensor_confidence
        cloud = self.cloud_cover(t, aim) * sensor.cloud_sensitivity
        sigma = sensor.sigma_km * (1.0 + (1.0 - sensor.health))
        dets: List[Detection] = []
        for h in self._h:
            u, nx, ny, ni = rng.random(), rng.normal(0, sigma), rng.normal(0, sigma), rng.normal(0, 0.08)
            if not h.active:
                continue
            reach = sensor.sensor_radius_km + 0.5 * h.radius_km
            d = dist(aim, h.pos)
            if d >= reach:
                continue
            pd = quality * float(edge_weight(d, reach)) * min(1.0, 0.35 + h.intensity) * (1.0 - cloud)
            sg = 1.0
            if h.kind == "methane":
                pd *= config.METHANE_PD_SCALE
                sg = config.METHANE_SIGMA_SCALE
            if u < pd:
                dets.append(Detection((h.pos[0] + nx * sg, h.pos[1] + ny * sg),
                                      float(min(1.0, max(0.0, h.intensity + ni))), False, h.id, h.kind))
        # false positive somewhere in the footprint
        vis = float(min(1.0, max(0.05, 1.0 - cloud + rng.normal(0, 0.1))))     # sensor's own cloud-mask estimate
        ufp, ang, rad, fi = rng.random(), rng.uniform(0, 2 * math.pi), rng.random(), rng.uniform(0.3, 0.8)
        fkind = "methane" if rng.random() < 0.25 else "wildfire"
        if ufp < sensor.fp_rate * (1.0 + cloud):
            r = sensor.sensor_radius_km * math.sqrt(rad)
            dets.append(Detection((aim[0] + r * math.cos(ang), aim[1] + r * math.sin(ang)), float(fi), True, None, fkind))
        return Observation(obs_id, t, sensor.id, sensor.kind, aim, sensor.sensor_radius_km, dets, sigma,
                           quality, sensor.fp_rate, spec["raw_mb"],
                           spec["comp_pos_mb"] if dets else spec["comp_neg_mb"], vis)
