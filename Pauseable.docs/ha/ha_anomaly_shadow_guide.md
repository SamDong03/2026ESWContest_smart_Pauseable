# IF and Dense AE Shadow Comparison

> Historical 2026-09-08 shadow-only guide. The later lifecycle can explicitly use hybrid promotion after its validation gate. See [the 2026-09-11 service guide](PI_FULL_AUTOMATION_KO.md) for the deployed flow; shadow remains the default policy for standalone calls.

Revision: 2026-09-08. The model bundle is a research aid, not a dementia diagnosis or a safety guarantee.

## Policy

The pipeline keeps `rule_level` and `rule_score`. Its final `level` and `risk_score` are those rule values. IF and Dense AE scores are recorded independently in `*_model_comparison.csv`; they never promote alerts. The earlier legacy AE promotion is no longer the default path.

`models/anomaly_current/manifest.json` is the default bundle location. No bundle is shipped there. `not_trained` is expected until normal local history has been collected and reviewed. Public/synthetic bundles cannot score observations marked `local`. Only trusted locally produced joblib files may be loaded.

## Running

The existing automation command continues to work. Its default is real local data and all supported behavioral entities. Virtual MQTT entities are excluded from local features. For a synthetic demo use `--data-source synthetic` on the pipeline or loop and a separate `--event-history` file. Never use the live history file for a demo.

For custom selection pass repeated `--entity-keyword` arguments. The mapper still defines supported device/signal pairs; collecting an entity does not guarantee it becomes a model feature. Check the conversion counts and data quality output.

Useful output fields:

- `data_quality.status`: `ok` or `no_usable_data`, not a health status.
- `history_complete`: two hours of collection-session continuity. It does not prove every cloud device reported correctly.
- `model_status`: `not_trained`, `shadow`, `invalid_features`, `incompatible_source`, `insufficient_history`, or an artifact/runtime error state.
- `source_type`: local/public/synthetic/unknown provenance.
- `model_id`: version of the trusted bundle used for comparison.

`HA_TIMEZONE` defaults to `Asia/Seoul`. Naive legacy timestamps are treated as local wall time. Regenerate historical features for consistent comparisons; do not mix old and new schemas or assume old thresholds were validated under corrected counting.

The old `--autoencoder-model-dir` option is retained only for command parsing compatibility; use `--model-dir` for the new joint bundle. `--no-autoencoder` hides AE comparison scores, not IF scores. `train_ha_autoencoder.py` now forwards to the versioned trainer and requires the new arguments below.

## Preparing Local Training Data

Run inside a compatible Python container in `/app`, after enough real history is collected:

```sh
python src/prepare_ha_training_data.py --output data/features/normal_candidate_v1.csv --household-id home_001
```

This does not train anything. It writes rows as `unreviewed`. Select normal periods after reviewing outages, test sessions, absences and known unusual behavior; mark only confirmed normal rows `reviewed_normal` in a separate reviewed CSV. Do not automatically label every rule-normal row as ground truth.

```sh
python src/train_ha_anomaly_models.py --input data/features/normal_reviewed_v1.csv --output-dir models/anomaly_v1 --source-type local --household-id home_001 --normal-basis "Reviewed routine periods; outages and test sessions excluded"
```

Training requires complete rolling history, consistent source/household, at least 7 observed days, actual varying behavior features and sufficient split sizes. Seven days is an engineering lower bound, not evidence of accuracy. Prefer multiple weeks including weekdays and weekends. The trainer refuses to overwrite an existing model version.

The split is chronological 60/20/20 with a 120-minute purge before calibration and test. Scaling is fit on train only; thresholds come from calibration only. Test alert fractions are not precision/recall without reviewed anomaly labels. Further tuning after inspecting test results requires a fresh evaluation period.

No automatic model activation or monthly retraining is installed. To evaluate a reviewed version, pass `--model-dir models/anomaly_v1` explicitly. Changing the persistent Pi service should follow backup, short isolated validation, then restarting only the AI service. Keep HA and MQTT running. Retain the frozen rule/model version for rollback and long-term drift comparisons.

## Dependencies and Tests

Python 3.12, numpy, pandas, scikit-learn 1.7.2, scipy 1.16.3, joblib 1.5.2, threadpoolctl 3.6.0. The forest runtime version is checked against training. Dense AE export is checked against sklearn output.

```sh
python -m unittest discover -s tests -v
```

Tests leave generated fixtures under `outputs/test_runs` for auditing. These fixtures and public benchmark models must not be deployed as personalized models.

On this ATLAS Pi, the normal Docker builder cannot load the host's docker-default AppArmor profile. The audit contains the tested candidate-image procedure using the same per-container security option as the existing runner. No host-wide AppArmor change is required. The production image and service have not been switched by the candidate test.
