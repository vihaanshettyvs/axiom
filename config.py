"""config.py -- all tunables, scenario definition and the USE_REAL switchboard."""
from __future__ import annotations

from contracts import DEFAULT_SEED

# --------------------------------------------------------------------------- #
# USE_REAL: flip each module independently between mock and real.
#   physics  -> P2's module (falls back to mocks.MockPhysics when False)
#   plume / leakhunter / triage / haps -> my modules (mock when False)
# --------------------------------------------------------------------------- #
USE_REAL = {
    "physics": True,         # P2 RealPhysics (physics/api.py); False = mocks.MockPhysics
    "plume": True,
    "leakhunter": True,
    "triage": True,
    "haps": True,            # True = adaptive planner, False = lawnmower even with brain ON
}
PHYSICS_REAL_PATH = "physics.api:RealPhysics"   # "module:Class" -- agree name with P2

# --- optional external data / extensions (all None = built-in synthetic scenario) -------------- #
WILDFIRE_DATA_PATH = None        # path to a NASA FIRMS-style CSV (see scenario_data.py); None = synthetic fires
HAZARD_SOURCE = None             # "module:function" returning a list of hazard spec dicts (overrides everything)
EXTENSIONS: dict = {}            # {"telemetry": "module:Class"}  optional hook objects (see engine.py)

SEED = DEFAULT_SEED
DURATION_MIN = 180
STEP_MIN = 1.0
LINK_MB_PER_MIN = 150.0          # satellite ground link capacity while in contact
OUT_DIR = "out"

# --------------------------------------------------------------------------- #
# Sensor specs per platform kind
# --------------------------------------------------------------------------- #
SENSOR_SPECS = {
    "SAT":   dict(radius=12.0, slew=22.0, pd=0.80, sigma=1.5, fp=0.04, raw_mb=20.0,
                  comp_pos_mb=0.5, comp_neg_mb=0.1, cloud=1.0),
    "HAPS":  dict(radius=7.0, slew=0.0, pd=0.92, sigma=0.7, fp=0.02, raw_mb=5.0,
                  comp_pos_mb=0.3, comp_neg_mb=0.05, cloud=0.2, speed=1.6),
    "DRONE": dict(radius=1.8, slew=0.0, pd=0.98, sigma=0.15, fp=0.002, raw_mb=2.0,
                  comp_pos_mb=0.2, comp_neg_mb=0.03, cloud=0.0, speed=0.7),
}

# --------------------------------------------------------------------------- #
# Scenario: two simultaneous wildfires + two towns at risk
# --------------------------------------------------------------------------- #
ASSETS = [
    dict(name="Eastgate", pos=(80.0, 60.0), weight=1.0),
    dict(name="Westvale", pos=(20.0, 30.0), weight=0.7),
]

HAZARDS = [
    dict(id="FIRE-E", pos=(72.0, 56.0), t_start=0.0, radius0=2.5, rmax=9.0, expansion=0.035,
         wind=(0.10, 0.05), wind_turn=0.004, int0=0.45, int_rate=0.006),
    dict(id="FIRE-W", pos=(26.0, 36.0), t_start=25.0, radius0=2.0, rmax=8.0, expansion=0.03,
         wind=(-0.04, 0.09), wind_turn=-0.003, int0=0.35, int_rate=0.007),
]
# Methane leaks: near-stationary sources whose emission rate (intensity) fluctuates.
HAZARDS += [
    dict(id="LEAK-1", kind="methane", pos=(55.0, 42.0), t_start=10.0, radius0=1.5, rmax=6.0, expansion=0.02,
         wind=(0.01, 0.015), wind_turn=0.001, int0=0.5, int_rate=0.003),
    dict(id="LEAK-2", kind="methane", pos=(44.0, 14.0), t_start=35.0, radius0=1.2, rmax=5.0, expansion=0.02,
         wind=(-0.01, 0.01), wind_turn=-0.001, int0=0.4, int_rate=0.004),
]
METHANE_PD_SCALE = 0.7           # spectrometer is less sensitive than the fire (thermal) channel
METHANE_SIGMA_SCALE = 1.4        # and localises worse
LH_PARAMS = {"wildfire": dict(prefix="EST", diffuse=None, relax=None),
             "methane": dict(prefix="LEAK", diffuse=0.01, relax=0.001)}   # leaks barely move, persist longer
PLUME_TURBULENCE = 0.04          # km/min gust std

# Satellites: ground track A->B (km, straight line through/near the region),
# repeating every `period` min, offset by `phase`.
SATELLITES = [
    dict(id="SAT-01", A=(-60, 62), B=(160, 70), period=110, phase=10, importance=0.7,
         fuel=1.6, health=0.95, degrade=0.0004),
    dict(id="SAT-02", A=(-60, 38), B=(160, 34), period=110, phase=13, importance=0.8,
         fuel=1.2, health=0.90, degrade=0.0005),
    dict(id="SAT-03", A=(-60, 70), B=(160, 42), period=110, phase=85, importance=0.9,
         fuel=0.35, health=0.78, degrade=0.0006),      # LOW FUEL -> tug candidate
    dict(id="SAT-04", A=(30, -60), B=(42, 160), period=120, phase=30, importance=0.8,
         fuel=1.5, health=0.95, degrade=0.0004),
    dict(id="SAT-05", A=(70, -60), B=(76, 160), period=120, phase=40, importance=0.5,
         fuel=0.9, health=0.42, degrade=0.0038),       # DYING -> retire candidate
    dict(id="SAT-06", A=(-50, -50), B=(150, 150), period=130, phase=60, importance=0.6,
         fuel=1.3, health=0.92, degrade=0.0004),
    dict(id="SAT-07", A=(-60, 22), B=(160, 30), period=115, phase=20, importance=0.6,
         fuel=1.4, health=0.90, degrade=0.0004),
    dict(id="SAT-08", A=(14, -60), B=(24, 160), period=120, phase=70, importance=0.7,
         fuel=1.5, health=0.93, degrade=0.0004),
    dict(id="SAT-09", A=(55, -60), B=(66, 160), period=125, phase=5, importance=0.5,
         fuel=1.1, health=0.88, degrade=0.0005),
    dict(id="SAT-10", A=(-60, 88), B=(160, 84), period=110, phase=60, importance=0.6,
         fuel=0.45, health=0.70, degrade=0.0007),      # 2nd tug candidate -> competes with SAT-03
    dict(id="SAT-11", A=(160, -30), B=(-60, 130), period=130, phase=35, importance=0.7,
         fuel=1.6, health=0.96, degrade=0.0004),
    dict(id="SAT-12", A=(-40, 110), B=(140, -40), period=125, phase=90, importance=0.5,
         fuel=1.2, health=0.90, degrade=0.0005),
]
SAT_FUEL_CAPACITY = 2.0
CONTACT_S_RANGE = (0.74, 0.97)   # fraction of the track where a ground station is visible

# Scripted debris conjunctions: (sat, debris id, tca min, probability if no manoeuvre)
CONJUNCTIONS = [
    ("SAT-01", "DEB-1107", 40, 0.004),    # trivial -> a good brain ignores it
    ("SAT-05", "DEB-0382", 60, 0.10),     # dying sat -> not worth the fuel
    ("SAT-02", "DEB-2210", 70, 0.08),
    ("SAT-03", "DEB-0777", 100, 0.03),
    ("SAT-04", "DEB-3341", 120, 0.15),
    ("SAT-06", "DEB-1499", 150, 0.02),
    ("SAT-08", "DEB-5521", 85, 0.05),
    ("SAT-09", "DEB-7710", 158, 0.12),    # SAT-09 is watching the landfill leak around t~67-71: debris approaches the observer
    ("SAT-11", "DEB-6102", 130, 0.012),
]
CONJ_FORECAST_MIN = 90           # how far ahead the brain sees conjunctions
CONJ_PEAK_WIDTH = 12.0           # instantaneous risk = p*exp(-((t-tca)/w)^2)
SHOCK_PROB = 0.002               # per-min random degradation shock probability

HAPS_START = (50.0, 30.0)
HAPS_ASSET_BIAS = 1.5            # exploration is biased toward towns at risk
DRONE_BASE = (50.0, 50.0)
TUG = dict(eta_min=25.0, service_min=15.0, fuel_gain_kg=1.0, health_gain=0.35, cooldown_min=60.0)

# --------------------------------------------------------------------------- #
# LeakHunter
# --------------------------------------------------------------------------- #
LH_PRIOR = 0.0008                # P(hazard centre in a given cell)  ~ 2 hazards / 2500
LH_DIFFUSE = 0.03                # per-minute neighbour mixing weight (belief spreading)
LH_RELAX = 0.002                 # per-minute relaxation back to prior (staleness)
LH_CLUTTER_MULT = 2.0            # assume sensors are 2x more false-alarm prone than their spec sheet
LH_NEG_TRUST = 0.85              # discount on negative evidence (sensors may be blinded)
LH_DRIFT_SPEED = 0.15            # km/min inflation of sigma for old observations
LH_EST_MIN_MASS = 0.12
LH_CONFIRM_RADIUS = 5.0
LH_CONFIRM_TTL = 60.0

# --------------------------------------------------------------------------- #
# Triage utility weights (everything is converted into "utility units")
# --------------------------------------------------------------------------- #
INFO_VALUE = 40.0                # value of a unit of urgency*importance*info_gain
FUEL_VALUE = 60.0                # per kg
BW_VALUE = 0.05                  # per MB
LOSS_VALUE = 400.0               # value of a fully healthy, fully important satellite
DEBRIS_PENALTY = 150.0           # value of avoiding an uncontrolled death
SERVICE_VALUE = 120.0
TUG_COST = 25.0
SLEW_FUEL_PER_KM = 0.0004      # only charged when the tasking changes (tracking a held target is free)
URGENCY_CONFIRM_W = 0.3          # extra urgency for tracks that are still coin-flips (need a confirming look)
REPEAT_LOOK_DECAY = 0.35         # value multiplier for each extra satellite already looking at the same hazard
GAIN_K = 8.0                     # info gain saturation constant
GAIN_MASS_W = 6.0
FUEL_RESERVE_KG = 0.05
RETIRE_RUL_MIN = 30.0
HAPS_BURN_PER_KM = 0.001
BASELINE_DODGE_RISK = 0.01       # brain OFF dodges only when instantaneous risk exceeds this

# Retirement option scoring (used by the brain to choose between controlled_deorbit / drag_sail / edt_tether)
RETIRE_RISK_W = 150.0            # penalty per unit of failure risk of the chosen method (debris left behind)
RETIRE_TIME_W = 0.2              # penalty per minute the method takes
DATA_SOURCE_LABEL = {"synthetic": "SIMULATED", "firms": "NASA FIRMS (real detections)", "custom": "CUSTOM"}

FIRMS_REGION = None              # (lat, lon) to force the centre of the simulated 100x100 km window; None = densest cluster
FIRMS_CREDIT = "NASA FIRMS VIIRS S-NPP historical sample data (sample_viirs_snpp_071223.csv, acquisitions 2023-07-12)"
