
# ORBITA — P4 Data & Sensing

## 1. Overview

P4 is responsible for data ingestion, sensing analysis, telemetry simulation, hazard assessment, and performance reporting.

It consumes ORBITA simulation RunLogs produced by P1 and processes external historical fire data. It provides structured analysis that can be reused by other project modules, including the P3 interface.

P4 does not modify P1's simulation engine, physics, contracts, or decision-making logic.

## 2. Architecture

### Modules

| Module | Responsibility |
|---|---|
| `telemetry.py` | Synthetic satellite health and failure-mode telemetry simulation |
| `fire.py` | Loads and replays historical NASA FIRMS fire detections |
| `runlog.py` | Loads and extracts information from ORBITA RunLog JSON files |
| `insight.py` | Analyses observations, compression, delivery latency, and bandwidth |
| `hazardvalue.py` | Scores and ranks estimated hazards using evidence-weighted intensity |
| `report.py` | Generates structured P4 reports and compares BRAIN ON/OFF runs |

### Data flow

1. P1 produces simulation RunLogs.
2. P4 loads RunLogs without modifying them.
3. Observation and hazard analysis modules process the data.
4. The reporting module combines the results.
5. A structured JSON report is generated for downstream use.

## 3. Data Sources

### ORBITA RunLogs

Location:

- `data/runlogs/runlog_brain_on.json`
- `data/runlogs/runlog_brain_off.json`

These are simulation outputs supplied by P1.

They contain simulation frames, observations, decisions, estimates, events, and cumulative metrics.

P4 uses the brain-facing estimates and does not use ground-truth hazards to calculate hazard rankings.

### NASA FIRMS

Dataset:

`data/firms/sample_viirs_snpp.csv`

This is historical VIIRS active-fire sample data from NASA FIRMS.

The fire module supports:
- CSV ingestion
- Acquisition-time parsing
- Geographic coordinate conversion
- Detection replay over simulation time

The dataset is historical, not live. Geographic coordinates must be properly georeferenced before being interpreted as positions in ORBITA's local simulation grid.

### Synthetic Telemetry

`telemetry.py` provides a deterministic, configurable satellite-health simulation.

It models battery degradation, solar degradation, thermal stress, and propulsion failure.

These are synthetic assumptions, not live hardware readings or fields extracted from P1 RunLogs.

## 4. Hazard Scoring

`hazardvalue.py` calculates an analytical score:

`score = 100 × existence × confidence × intensity`

Where:
- `existence` represents estimated hazard existence probability.
- `confidence` represents confidence in the estimate.
- `intensity` represents estimated hazard intensity.

Estimates are ranked by this score.

Growth rate, localization uncertainty, and confirmation status are reported separately.

This score is a P4 analytical heuristic. It is not a physical hazard probability and is not the same as P1's decision urgency.

## 5. Observation and Bandwidth Analysis

`insight.py` analyses:
- Total observation count
- Raw and compressed observation sizes
- Estimated storage savings
- Positive and negative scans
- Delivered and undelivered observations
- Mean and maximum delivery latency
- Observation sources
- Final cumulative bandwidth usage

Observation-size compression statistics and engine-level cumulative bandwidth metrics are separate measurements and should not be treated as interchangeable.

## 6. Report Generation

The reporting module generates:

`data/p4_report.json`

The report contains:
- BRAIN ON analysis
- BRAIN OFF analysis
- Final hazard estimate rankings
- Observation analysis
- Summary metrics
- Run-to-run comparison
- Detection and localization times

Generate the report from the repository root:

```bash
python -c "import json; from pathlib import Path; from sensing.runlog import load_runlog; from sensing.report import generate_p4_report; on=load_runlog('data/runlogs/runlog_brain_on.json'); off=load_runlog('data/runlogs/runlog_brain_off.json'); report=generate_p4_report(on,off); Path('data/p4_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8'); print('P4 report generated.')"
```

## 7. Running Tests

Activate the project's virtual environment, then run:

```bash
python -m unittest discover -s tests -v
```

Latest verified result:

**35 tests passed, 0 failures.**

## 8. BRAIN ON vs BRAIN OFF

Results from the supplied deterministic simulation run (seed 42):

| Metric | BRAIN ON | BRAIN OFF |
|---|---:|---:|
| Mean localization error | 11.09513 km | 16.91494 km |
| Mean detection time | 56.5 min | 89.75 min |
| Mean localization time | 60.5 min | 116.5 min |
| Mean detection latency | 2.24249 min | 24.75 min |
| Bandwidth | 428.8 MB | 24,840 MB |
| Attention alerts | 5 | 85 |
| Satellites lost | 0 | 0 |
| Uncontrolled dead satellites | 0 | 1 |
| Satellites serviced | 1 | 0 |
| Fuel consumed | 0.96797 kg | 1.12447 kg |

The measured bandwidth reduction is approximately **98.27%**.

These results represent one deterministic run and are not generalized performance guarantees.

## 9. P1 Integration Boundary

P4 consumes P1 RunLogs as read-only JSON inputs.

P4 does not:
- Modify `contracts.py`
- Modify `engine.py`
- Modify `brain/`
- Modify `physics/`
- Modify `space/`
- Change P1 decision-making or simulation behaviour

This separation allows P4 to develop and test independently while remaining compatible with the shared ORBITA simulation outputs.

## 10. Repository Contents

- `sensing/` — P4 Python modules
- `tests/` — Automated unit tests
- `data/firms/` — Historical NASA FIRMS sample
- `data/runlogs/` — P1 simulation RunLog inputs
- `data/p4_report.json` — Generated P4 analysis report
