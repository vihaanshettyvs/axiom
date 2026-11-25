"""contracts.py -- shared data contracts for ORBITAL TRIAGE.

FROZEN at hour 1 (CONTRACT_VERSION 1.0.0). Any change must be announced to the
team BEFORE it is made (see CONTRACTS.md).

Conventions
-----------
* Time ............ minutes (float), simulation starts at t = 0.
* Position ........ km, shared local 2D frame, origin = south-west corner of the
                    100 x 100 km region of interest (x east, y north).
* Probability grid  GRID_N x GRID_N = 50 x 50, indexed grid[iy][ix];
                    cell (ix, iy) covers x in [ix*CELL_KM, (ix+1)*CELL_KM) etc.
* Randomness ...... every random draw comes from make_rng(seed, *keys); never
                    from global state.  Same seed => identical RunLog.
* Frontend ........ reads ONLY the RunLog JSON (RunLog.save / to_dict).
"""
from __future__ import annotations

import copy
import json
import typing
import zlib
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Tuple

import numpy as np

CONTRACT_VERSION = "1.1.0"      # 1.1.0: additive only (hazard kinds, belief_by_kind, RunLog.from_dict)
GRID_N = 50
AREA_KM = 100.0
CELL_KM = AREA_KM / GRID_N
DEFAULT_SEED = 42
STEP_MIN = 1.0

Vec2 = Tuple[float, float]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def make_rng(seed: int, *keys: Any) -> np.random.Generator:
    """Deterministic RNG stream identified by (seed, *keys).

    Streams keyed by (sensor id, minute) etc. make the world's randomness
    independent of decision order, so BRAIN ON and BRAIN OFF see the *same*
    world (same hazards, same debris, same sensor luck for the same pointing).
    """
    ints = [int(seed) & 0xFFFFFFFF]
    for k in keys:
        if isinstance(k, (int, np.integer)):
            ints.append(int(k) & 0xFFFFFFFF)
        else:
            ints.append(zlib.crc32(str(k).encode()))
    return np.random.default_rng(ints)


_XY_CACHE: Optional[Tuple[np.ndarray, np.ndarray]] = None


def grid_xy() -> Tuple[np.ndarray, np.ndarray]:
    """(X, Y) arrays of cell-centre coordinates in km, shape (GRID_N, GRID_N)."""
    global _XY_CACHE
    if _XY_CACHE is None:
        c = (np.arange(GRID_N) + 0.5) * CELL_KM
        X, Y = np.meshgrid(c, c)  # X[iy, ix]
        _XY_CACHE = (X, Y)
    return _XY_CACHE


def pos_to_cell(x: float, y: float) -> Tuple[int, int]:
    """(ix, iy) of the cell containing (x, y); clamped to the grid."""
    return (min(GRID_N - 1, max(0, int(x // CELL_KM))),
            min(GRID_N - 1, max(0, int(y // CELL_KM))))


def dist(a: Vec2, b: Vec2) -> float:
    return float(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5)


def to_jsonable(o: Any) -> Any:
    """Recursively convert dataclasses / enums / numpy to plain JSON types."""
    if is_dataclass(o) and not isinstance(o, type):
        return {f.name: to_jsonable(getattr(o, f.name)) for f in fields(o)}
    if isinstance(o, Enum):
        return o.value
    if isinstance(o, np.ndarray):
        return to_jsonable(o.tolist())
    if isinstance(o, (np.floating,)):
        return round(float(o), 5)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, float):
        return round(o, 5)
    if isinstance(o, dict):
        return {str(k): to_jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [to_jsonable(v) for v in o]
    return o


# --------------------------------------------------------------------------- #
# enums
# --------------------------------------------------------------------------- #
class ActionType(str, Enum):
    OBSERVE = "OBSERVE"
    DOWNLINK = "DOWNLINK"
    HANDOFF = "HANDOFF"
    DODGE = "DODGE"
    RETIRE = "RETIRE"
    DISPATCH_HAPS = "DISPATCH_HAPS"
    DISPATCH_DRONE = "DISPATCH_DRONE"
    REQUEST_TUG = "REQUEST_TUG"


class Status(str, Enum):
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"      # still usable, health < 0.5
    SERVICING = "SERVICING"    # tug is docked, unavailable
    RETIRING = "RETIRING"      # executing de-orbit
    RETIRED = "RETIRED"        # graceful end of life (no debris created)
    DEAD = "DEAD"              # died uncontrolled -> becomes debris (bad)
    LOST = "LOST"              # destroyed by collision (bad)
    IDLE = "IDLE"              # HAPS / drone / tug parked


# --------------------------------------------------------------------------- #
# the six required classes
# --------------------------------------------------------------------------- #
@dataclass
class Satellite:
    """Any platform: LEO satellite, HAPS, drone or servicing tug (see `kind`)."""
    id: str
    kind: str = "SAT"                       # "SAT" | "HAPS" | "DRONE" | "TUG"
    pos: Vec2 = (0.0, 0.0)                  # km; nadir / ground position
    vel: Vec2 = (0.0, 0.0)                  # km/min
    status: str = Status.ACTIVE.value
    fuel_kg: float = 1.0                    # propellant (HAPS/drone: battery-equivalent)
    fuel_capacity_kg: float = 2.0
    health: float = 1.0                     # 0..1, 1 = new
    sensor_confidence: float = 0.8          # nominal P(detect) at footprint centre, already health-adjusted
    sensor_radius_km: float = 12.0          # footprint radius
    slew_km: float = 0.0                    # max re-pointing offset from nadir
    sigma_km: float = 1.5                   # 1-sigma localisation noise of the sensor
    fp_rate: float = 0.04                   # P(false positive) per scan
    cloud_sensitivity: float = 1.0          # 0 = unaffected by cloud, 1 = fully affected
    rul_min: float = 1e9                    # remaining useful life estimate (min)
    mission_importance: float = 0.5         # 0..1 role weight (sat's value to the mission)
    debris_risk: float = 0.0                # instantaneous collision probability
    in_view: bool = False                   # footprint can reach the region of interest
    in_contact: bool = False                # ground-station contact now
    view_left_min: float = 0.0              # minutes of view left (0 if not in view)
    next_view_min: float = 0.0              # minutes until next view window (0 if in view)
    next_contact_min: float = 0.0           # minutes until next ground contact (0 if in contact)
    buffer_mb: float = 0.0                  # data waiting for downlink
    aim: Optional[Vec2] = None              # current sensor pointing
    target: Optional[Vec2] = None           # waypoint (HAPS / drone / tug)
    orbit: Dict[str, Any] = field(default_factory=dict)   # physics-private (P2 owns)

    def copy(self) -> "Satellite":
        return copy.deepcopy(self)

    @property
    def operational(self) -> bool:
        return self.status in (Status.ACTIVE.value, Status.DEGRADED.value)


@dataclass
class Hazard:
    """GROUND TRUTH hazard (wildfire plume). The brain never reads this."""
    id: str
    kind: str = "wildfire"
    pos: Vec2 = (0.0, 0.0)
    vel: Vec2 = (0.0, 0.0)                  # km/min (wind drift + turbulence)
    radius_km: float = 3.0
    intensity: float = 0.5                  # 0..1
    t_start: float = 0.0                    # ignition time (min)
    active: bool = False


@dataclass
class Detection:
    pos: Vec2
    intensity: float
    is_false_positive: bool = False         # truth flag (debug / metrics only)
    hazard_id: Optional[str] = None         # truth flag
    kind: str = "wildfire"                  # "wildfire" | "methane"  (what the sensor believes it saw)


@dataclass
class Observation:
    """One scan by one sensor at one minute.  `detections == []` is a NEGATIVE."""
    id: str
    t: float
    sensor_id: str
    source: str                             # "SAT" | "HAPS" | "DRONE"
    aim: Vec2
    radius_km: float
    detections: List[Detection] = field(default_factory=list)
    sigma_km: float = 1.5
    pd_nominal: float = 0.8                 # what the estimator is told (ignores cloud)
    fp_rate: float = 0.04
    size_raw_mb: float = 20.0
    size_comp_mb: float = 0.5
    visibility: float = 1.0                 # sensor's own clear-sky estimate (cloud mask), 0..1
    delivered_t: Optional[float] = None     # when it reached the estimator

    @property
    def detected(self) -> bool:
        return len(self.detections) > 0


@dataclass
class Action:
    type: ActionType
    actor_id: str
    target: Optional[Vec2] = None           # aim point / waypoint / etc.
    target_id: Optional[str] = None         # estimate id, satellite id, debris id...
    params: Dict[str, Any] = field(default_factory=dict)
    fuel_cost: float = 0.0                  # kg
    bandwidth_cost: float = 0.0             # MB


@dataclass
class Decision:
    """An Action plus the full reasoning trail.  `reason` is human readable."""
    t: float
    action: Action
    urgency: float                          # 0..1
    importance: float                       # 0..1 mission importance
    info_gain: float                        # 0..1 expected information gain
    fuel_cost: float                        # kg
    bandwidth_cost: float                   # MB
    risk_reduction: float                   # 0..1 (probability of loss avoided)
    health: float                           # 0..1 actor health factor
    expected_benefit: float                 # utility units (see config weights)
    reason: str
    alternatives: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Estimate:
    """LeakHunter's belief about one hazard (what the brain is allowed to see)."""
    id: str
    pos: Vec2
    existence: float                        # P(a hazard is really there), 0..1
    confidence: float                       # existence discounted by spatial spread
    uncertainty_km: float                   # 1-sigma position spread
    intensity_est: float = 0.5
    growth_est: float = 0.0                 # intensity change per 10 min
    confirmed: bool = False                 # ground-level (drone) confirmation
    last_obs_t: float = -1.0
    n_pos: int = 0                          # recent positive detections near it
    kind: str = "wildfire"                  # "wildfire" | "methane"


@dataclass
class Asset:
    name: str
    pos: Vec2
    weight: float                           # 0..1 value at risk


@dataclass
class Conjunction:
    sat_id: str
    debris_id: str
    tca: float                              # time of closest approach (min)
    probability: float                      # collision probability if no manoeuvre


@dataclass
class PendingItem:
    """Observation waiting in a satellite's downlink buffer (brain-visible)."""
    id: str
    sat_id: str
    t: float
    has_detection: bool
    size_raw_mb: float
    size_comp_mb: float
    prior_mass: float                       # belief mass inside footprint when scanned
    aim: Vec2
    radius_km: float


@dataclass
class WorldView:
    """Everything the brain may look at.  NO ground truth in here."""
    t: float
    satellites: List[Satellite]
    estimates: List[Estimate]
    belief: np.ndarray                      # (50,50) hazard-centre probability
    assets: List[Asset]
    conjunctions: Dict[str, List[Conjunction]]
    pending: Dict[str, List[PendingItem]]
    tug: Dict[str, Any]
    dodged: List[Tuple[str, str]]
    link_mb_per_min: float
    seed: int = DEFAULT_SEED


@dataclass
class Frame:
    t: float
    satellites: List[Satellite]
    hazards: List[Hazard]                   # truth, for visualisation only
    observations: List[Observation]
    decisions: List[Decision]
    estimates: List[Estimate]
    belief_permille: List[List[int]]        # 50x50 ints, probability*1000
    entropy_bits: float
    uncertainty: float                      # 0 = certain, 1 = clueless
    events: List[Dict[str, Any]]
    metrics: Dict[str, float]               # cumulative, see CONTRACTS.md
    belief_by_kind: Dict[str, List[List[int]]] = field(default_factory=dict)   # per-kind 50x50 permille grids


@dataclass
class RunLog:
    meta: Dict[str, Any]
    scenario: Dict[str, Any]
    frames: List[Frame] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return to_jsonable(self)

    def save(self, path: str) -> None:
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh, separators=(",", ":"))

    @staticmethod
    def load_dict(path: str) -> Dict[str, Any]:
        """Raw JSON dict (what the frontend sees)."""
        with open(path) as fh:
            return json.load(fh)

    load = load_dict                        # backwards-compatible name used by earlier tests/tools

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RunLog":
        """Rebuild typed objects (Frame, Satellite, Decision...) from a saved RunLog dict."""
        return cls(meta=d["meta"], scenario=d.get("scenario", {}),
                   frames=[_hydrate(Frame, f) for f in d.get("frames", [])], summary=d.get("summary", {}))

    @classmethod
    def read(cls, path: str) -> "RunLog":
        return cls.from_dict(cls.load_dict(path))


def _hydrate(tp: Any, v: Any) -> Any:
    """Generic JSON -> dataclass reconstruction driven by the type hints."""
    if v is None:
        return None
    origin, args = typing.get_origin(tp), typing.get_args(tp)
    if origin is typing.Union:                                  # Optional[X]
        inner = [a for a in args if a is not type(None)]
        return _hydrate(inner[0], v) if inner else v
    if origin in (list, List):
        return [_hydrate(args[0], x) for x in v]
    if origin in (tuple, Tuple):
        return tuple(v)
    if origin in (dict, Dict):
        return {k: _hydrate(args[1], x) for k, x in v.items()} if len(args) == 2 else dict(v)
    if isinstance(tp, type) and issubclass(tp, Enum):
        return tp(v)
    if is_dataclass(tp):
        hints = typing.get_type_hints(tp)
        return tp(**{f.name: _hydrate(hints[f.name], v[f.name]) for f in fields(tp) if f.name in v})
    return v


# --------------------------------------------------------------------------- #
# module interfaces (Protocols) -- mock and real implementations must match
# --------------------------------------------------------------------------- #
class PhysicsAPI(Protocol):
    """Implemented by P2 (real) and mocks.MockPhysics (stand-in).

    The engine NEVER re-implements any of this; it only calls it.
    """

    def reset(self, seed: int, sats: List[Satellite]) -> List[Satellite]: ...

    def step(self, sats: List[Satellite], t: float, dt: float) -> List[Satellite]:
        """Propagate orbits, apply degradation, servicing completion, and refresh
        derived fields: pos, vel, health, sensor_confidence, rul_min, status,
        debris_risk, in_view, in_contact, view_left_min, next_view_min,
        next_contact_min."""

    def coverage_windows(self, sat: Satellite, t: float, horizon_min: float) -> List[Tuple[float, float]]: ...

    def upcoming_conjunctions(self, sat: Satellite, t: float, horizon_min: float) -> List[Conjunction]:
        """Conjunctions with t <= tca < t + horizon_min."""

    def dodge_fuel_cost(self, sat: Satellite, lead_min: float) -> float: ...

    def dodge_effectiveness(self, sat: Satellite, lead_min: float) -> float:
        """Fraction of collision probability removed by a manoeuvre with this lead time."""

    def retirement_options(self, sat: Satellite, t: float) -> List[Dict[str, Any]]:
        """[{"name", "fuel_kg", "duration_min"}] -- empty if not enough fuel."""

    def tug_status(self, t: float) -> Dict[str, Any]:
        """{"available": bool, "eta_min": float, "service_min": float}"""

    def request_tug(self, sat: Satellite, t: float) -> Dict[str, Any]:
        """{"accepted": bool, "arrival_t": float, "complete_t": float}"""


class PlumeAPI(Protocol):
    def reset(self) -> None: ...
    def step(self, t: float, dt: float) -> None: ...
    def hazards(self) -> List[Hazard]: ...
    def observe(self, sensor: Satellite, aim: Vec2, t: float, obs_id: str) -> Observation: ...


class LeakHunterAPI(Protocol):
    def reset(self) -> None: ...
    def predict(self, dt: float) -> None: ...
    def update(self, obs: Observation, now: float) -> None: ...
    def grid(self) -> np.ndarray: ...
    def estimates(self, now: float, max_n: int = 4) -> List[Estimate]: ...
    def entropy_bits(self) -> float: ...
    def uncertainty(self, ests: List[Estimate]) -> float: ...


class TriageAPI(Protocol):
    def decide(self, view: WorldView) -> List[Decision]: ...
