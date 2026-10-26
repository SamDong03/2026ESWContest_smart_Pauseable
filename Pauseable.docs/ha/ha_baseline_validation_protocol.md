# HA Baseline Validation Protocol

## Purpose

This validation suite checks whether the Home Assistant baseline detector behaves consistently across many personalized living patterns. It is designed for engineering validation and demo readiness, not for clinical diagnosis.

## What Synthetic Validation Can Support

- The pipeline works end to end from standard HA events to features, baseline, inference, and episode summary.
- Personalized baselines are built per user instead of using one global threshold.
- Normal profile differences can be tested, such as night-owl users, frequent fridge users, low-activity users, and appliance-heavy users.
- Injected repeated-control patterns can be tested repeatedly instead of relying on a single hand-written demo CSV.
- Baseline threshold changes can be regression-tested with the same population suite.

## What Synthetic Validation Cannot Prove

- It cannot prove dementia diagnosis performance.
- It cannot prove that generated event rates match every real household.
- It cannot replace long-term real Home Assistant logs.
- It cannot validate sensor loss, cloud delays, or LG ThinQ state reporting quality by itself.
- It cannot validate mmWave and HA fusion until mmWave scores are added to the same test suite.

## Evidence Levels

1. **Code-level check**
   - Unit-like scenario CSVs pass.
   - Mapper skips telemetry and keeps behavior entities.

2. **Population synthetic check**
   - Many virtual users are generated.
   - Each user gets a normal training period.
   - Each user is tested with normal, attention, and risk cases.

3. **Sensitivity check**
   - The population suite is repeated with different random seeds and training-day lengths.
   - Results report false alarm rate, attention/risk detection rate, and risk recall.

4. **Real-data self-check**
   - Real HA logs from the target environment are used.
   - Normal self-check should not produce excessive attention/risk.

5. **Prospective demo check**
   - Live HA collection runs during a fixed time window.
   - A controlled repeated behavior is performed.
   - The system detects an episode without manually editing the result.

## Metrics To Report

- **Normal false alarm rate**
  - Normal test cases whose max level is attention or risk.
  - Lower is better.

- **Attention/risk detection rate**
  - Expected attention/risk cases whose max level is at least attention.
  - Higher is better.

- **Risk recall**
  - Expected risk cases whose max level is risk.
  - Higher is better.

- **Episode count agreement**
  - Generated repeated behaviors should produce a small number of grouped episodes, not hundreds of ungrouped windows.

- **Pattern agreement**
  - The primary pattern should match the injected behavior when one is expected.

## Recommended Use

Run a quick smoke test while editing:

```bash
python src/run_ha_population_validation.py \
  --users 2 \
  --train-days 7 \
  --output-dir outputs/ha_population_validation_smoke
```

Run a stronger population validation before presentation:

```bash
python src/run_ha_population_validation.py \
  --users 12 \
  --train-days 14 \
  --output-dir outputs/ha_population_validation
```

Run sensitivity validation before final tuning:

```bash
python src/run_ha_validation_sensitivity.py \
  --users 12 \
  --train-days 7,14,30 \
  --seeds 42,99,2026
```

## How To Answer The Synthetic-Data Validity Question

The correct claim is:

> Synthetic population validation is not clinical proof. It is an engineering regression test that checks whether the detector behaves consistently across many plausible personalized patterns. Final validity should be strengthened with real HA logs, normal-only baseline updates, and prospective live tests.

The project should avoid claiming:

> This synthetic validation proves dementia detection accuracy.

The stronger and safer claim is:

> The detector uses literature-inspired ADL features, personalized IQR baselines, and repeated synthetic population tests to reduce rule overfitting. Real user data is still required for final threshold calibration.
