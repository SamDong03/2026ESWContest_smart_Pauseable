# Pauseable shape-model improvement protocol (fixed before training)

This experiment improves a geometric repetition classifier. It does not train a
clinical wandering diagnosis or a personal routine model. Synthetic walking
intent and dementia status are not observable from the supplied coordinates.

## Sources and splits

- Verify the two existing SmartCare source files against the pinned SHA256 values.
- Discard invalid/degenerate paths with explicit reasons. Split usable training
  paths 75/25, stratified by supplied label, using seed 20260911.
- The existing 20-path SmartCare validation set has already been examined in this
  project. Call it a **legacy regression audit**, not a new independent test.
- Generate 180/60/100/50 paths per labelled family for train/selection/test/challenge.
  The ten family definitions assign labels from the drawing procedure, not model
  scores or extracted features. Test uses fresh random base paths; challenge uses
  alternate drawing constructions from the same published generator code.
- These tests are conditional on our generators. They cannot establish performance
  on real people, real radar noise, or independently labelled clinical wandering.
- Group transformed variants together. Check forward/reverse normalized geometry
  fingerprints across splits. Retain reserved evaluation paths and exclude any
  overlapping training/selection paths. This is not proof against near duplicates.
- Ambiguous partial-loop and drifting-loop sweeps have no labels or accuracy.

## Selection fixed in advance

Candidates (all deterministic Random Forests):

1. Legacy 9 features, SmartCare training partition only, 200 trees/depth 5/leaf 2.
2. Legacy 9 features, SmartCare + generated training, 200 trees/depth 5/leaf 2.
3. Multiscale features, SmartCare training only, 200 trees/depth 5/leaf 2.
4. Multiscale features, SmartCare + generated training, 200 trees/depth 5/leaf 2.
5. Multiscale features, SmartCare + generated training, 300 trees/depth 10/leaf 3.

Augmented fitting gives the two sources equal total sample weight, and each class
equal weight within its source. Source metadata and path identifiers are never
model inputs. Compare thresholds 0.20 to 0.80 inclusive in steps of 0.02 using only
the selection partitions. Optimize the mean of source-specific balanced accuracy.
Ties favor the earlier/smaller candidate, then the threshold closest to 0.5.

Freeze the selected model and threshold before evaluating test/challenge/audit.
Do not refit on selection data. Do not change candidates/features/generators after
viewing final test metrics. Failure-driven software fixes are documented separately
and require checking whether the affected final test is still valid.

## Comparison and outputs

Reconstruct the old 200-tree/depth-5/leaf-2/seed-42 RF using all usable original
training paths. Compare it and the selected model on identical new test paths,
challenge paths and legacy audit. Report confusion matrices, accuracy, balanced
accuracy, precision, recall, F1, ROC-AUC and family-specific errors, including
regressions. Wilson intervals describe only labelled synthetic path samples.

Save per-path predictions, source/split hashes, exclusions, settings, environment,
feature names/hash, model.joblib, and a portable JSON forest. Verify JSON tree
evaluation against sklearn with float32 input semantics before delivery.

Any exported model requires matching feature extraction. The legacy run.py and
Pi5 application must not silently consume the new feature contract. No services,
personal-data stores, or installed production model pointers change in this run.
