# Data Provenance

This document satisfies Requirement 16 of the Msimulizi specification.  It
lists every external data source consulted during calibration, the specific
aggregate statistics extracted, the xG model inputs and training source, the
Premier League exclusion, and an explicit statement that no raw data was
committed to this repository.

---

## 1. Sources Consulted

| Source | URL | Licence |
|--------|-----|---------|
| StatsBomb Open Data | https://github.com/statsbomb/open-data | StatsBomb Open Data Licence (non-commercial, attribution required) |

No other external datasets, notebooks, or proprietary sources were used.

---

## 2. Premier League Exclusion

All files belonging to the **Premier League** competition (`competition_id = 2`)
in the StatsBomb Open Data repository were excluded from every calibration
computation.  The exclusion is enforced programmatically in
`scripts/calibrate_from_open_data.py` by reading `competitions.json` and
filtering out any `(competition_id, season_id)` pair where `competition_id`
is in the excluded set `{2}`.

---

## 3. Aggregate Statistics Extracted

The following aggregate statistics were computed and written to
`generator/calibration_aggregates.json`.  No individual match records,
player records, or raw event arrays are stored anywhere in the repository.

### 3.1 Pass Completion by Pitch Zone

For each of three pitch thirds (defending, middle, attacking):

- `attempts`    — total passes attempted from that zone
- `completions` — passes with a successful outcome
- `rate`        — completions / attempts

Zone boundaries use the StatsBomb native coordinate system (120 × 80 yards):
defending third x ∈ [0, 40), middle third x ∈ [40, 80), attacking third
x ∈ [80, 120].

### 3.2 Shot Conversion by Distance

For each distance bucket (yards from goal centre):
`0–6y`, `6–12y`, `12–18y`, `18–25y`, `25–35y`, `35–50y`, `50+y`

- `attempts` — shots from that distance range
- `goals`    — goals scored from that distance range
- `rate`     — goals / attempts

### 3.3 Shot Conversion by Angle

For each angle bucket (goal-mouth angle subtended at the shot location,
in radians): `0.0–0.2`, `0.2–0.4`, `0.4–0.6`, `0.6–0.8`, `0.8–1.0`,
`1.0–1.2`, `1.2+`

- `attempts` — shots in that angle range
- `goals`    — goals scored in that angle range
- `rate`     — goals / attempts

### 3.4 Events Per Minute

Total events (all types) divided by total match-minutes across all processed
matches, expressed as a float.

### 3.5 Pressure Rate

Pressure events (StatsBomb event type id 17) divided by total events,
expressed as a float.

---

## 4. xG Model

### 4.1 Training Source

The xG logistic regression was **trained from scratch during the hackathon
window** (29 September – 10 November 2026) using only the aggregate shot
statistics described in §3.2 and §3.3 above.  No individual shot records
were retained or committed.

### 4.2 Input Features

| Feature | Type | Description |
|---------|------|-------------|
| `distance` | float | Distance from goal centre in yards |
| `angle` | float | Goal-mouth angle subtended at shot location (radians) |
| `is_header` | binary | 1 if shot is a header, 0 otherwise |
| `is_penalty` | binary | 1 if shot is a penalty, 0 otherwise |

### 4.3 Model Architecture

Logistic regression with a sigmoid output.  Coefficients are stored in
`shared/xg_coefficients.json`.  Training is performed by
`scripts/train_xg.py` using scikit-learn's `LogisticRegression` (L-BFGS
solver, max 1 000 iterations) or a pure-Python gradient-descent fallback
when scikit-learn is unavailable.

Because only aggregate buckets are available (not individual shot records),
training samples are synthesised from bucket midpoints and scaled to a
maximum of 500 samples per distance bucket and 200 per angle bucket.  Penalty
samples use an independently derived conversion rate of 76 % across major
competitions.

### 4.4 Header Adjustment

A header penalty of −0.5 log-odds (approximately −35 % relative conversion)
is incorporated into the training data construction, consistent with widely
reported football analytics findings.  This figure does not derive from a
specific raw dataset.

---

## 5. No Raw Data Committed

> **No raw event records, datasets, match files, or notebooks derived from
> real football match data have been committed to this repository.**

`scripts/calibrate_from_open_data.py` downloads the StatsBomb Open Data zip
into a gitignored scratch directory (`.calibration_scratch/`), processes it
in memory, writes only the aggregate JSON file listed in §3, and then
**deletes the entire scratch directory** before the script exits.

The following `.gitignore` entries prevent accidental commits of raw data:

```
data/
raw_data/
open_data/
statsbomb_data/
datasets/
*.ipynb
```

---

## 6. StatsBomb Attribution

Per the StatsBomb Open Data Licence, the following attribution is required:

> Data provided by StatsBomb.
> Please visit https://statsbomb.com/news/statsbomb-release-free-football-data/

This attribution also appears in the repository README and in the application
About page.

---

## 7. Compliance Statement

- All code and model weights in this repository were written or trained during
  the hackathon window beginning 29 September 2026.
- The repository contains no `.pkl`, `.tflite`, `.onnx`, `.h5`, `.pt`,
  `.pth`, `.bin`, or `.safetensors` files produced before that date.
- The Match Generator uses only fictional club and player names.
- No StatsBomb-derived charts, branding, or trademarks appear in the demo
  video.
