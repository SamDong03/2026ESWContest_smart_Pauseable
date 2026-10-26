# Post-freeze synthetic sensitivity audit

Declared before executing this audit. This audit was added after the original
training/evaluation run, and is not part of model or threshold selection.

- Frozen run: `training-runs/20260911T115015603307Z`.
- Compare its historical baseline (threshold 0.5) and selected model (the frozen
  threshold in `model.json`), with no fitting, calibration, threshold changes,
  smoothing, feature edits, or altered generator labels.
- Use the exact 1,000 base paths in `datasets/generated_test.jsonl`. Score the
  original inputs and three paired perturbations of those same paths.
- Condition 1: remove exactly floor(30% of interior points), chosen without
  replacement; preserve the original first and last points and remaining order.
- Condition 2: independent zero-mean Gaussian noise on both coordinates of every
  point, with per-coordinate standard deviation 0.005 times original path
  diameter (largest Euclidean distance between original input points).
- Condition 3: same definition with standard deviation 0.02 times diameter.
- Seeds are derived from the protocol identifier, path ID, and condition name
  using SHA256. No perturbation is chosen or rejected using a model score.
- Both models receive exactly the same perturbed coordinates and original
  generator label. That label refers to the underlying constructed path, not a
  newly established interpretation of the noisy path.
- Feature rejection counts as abstention, not a dropped test case. Report
  coverage, accuracy with the full 1,000-path denominator, accuracy among scored
  paths, and per-class recall whose denominator includes abstentions.
- These four conditions reuse the same base paths: they are paired sensitivity
  measurements, not 4,000 independent trajectories. Do not pool them into an
  enlarged sample or claim independent real-world accuracy.
- Noise/dropout magnitudes are arbitrary synthetic stress settings. No assertion
  is made that they represent LD6004 measurement errors or clinical wandering.
- Verify five successfully scored selected-model predictions per condition
  against the portable JSON evaluator before saving results. Preserve model and
  base dataset SHA256 hashes before and after audit execution.
- Save `robustness.json`, `robustness.png`, and `ROBUSTNESS.md` in the frozen run.
  Any later improvements informed by these results need newly reserved data.


## Repository packaging note

The frozen `training-runs/` directory and generated `artifacts/datasets/` files
are not committed in this repository subset. Their frozen hashes remain in
`artifacts/manifest.json`; the reported audit outputs remain under `artifacts/`.
