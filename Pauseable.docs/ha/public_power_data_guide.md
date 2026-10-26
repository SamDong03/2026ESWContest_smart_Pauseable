# UK-DALE / REFIT power-data extension

## Scope

This is an additional, offline public-data preparation and benchmark path. It reuses
the existing Isolation Forest and dense Autoencoder trainer without replacing HA
event features, rule thresholds, personalized models, Pi services, or HA settings.
It neither controls appliances nor learns a clinical diagnosis.

The Excel proposal `AIoT_AI_Model_Data_Design.xlsx`, sheet
`데이터없는_AI학습전략`, identifies UK-DALE (A98/B98) and REFIT (A99).
The useful transfer is the measurement/feature method and an empirical model
comparison, not treating another household's power values as our home's normal.

## Sources and selection

- UK-DALE: Kelly and Knottenbelt, DOI 10.1038/sdata.2015.7.
  [Author page](https://jack-kelly.com/data/),
  [paper](https://www.nature.com/articles/sdata20157),
  [2015 channel archive](https://data.ceda.ac.uk/edc/d1/b3baa0aa-05ac-4ec8-b608-da5751758698/data/version_0/house_2).
  We use house 2, channel 15 microwave and channel 12 washing machine.
  These are individual active-power W channels, not mains apparent-power VA.
- [Author appliance metadata](https://github.com/JackKelly/UK-DALE_metadata/blob/master/building2.yaml)
  supplies microwave 200 W / 12 s minimum-on / 30 s minimum-off, and washer
  20 W / 1800 s / 160 s. This implementation confirms transitions causally;
  it does not claim equivalence to NILMTK's offline activation extraction.
- REFIT: Murray, Stankovic and Stankovic, DOI 10.1038/sdata.2016.122.
  [Institutional dataset](https://pureportal.strath.ac.uk/en/datasets/refit-electrical-load-measurements-cleaned/),
  [official linked CSV distribution](https://zenodo.org/records/5063428),
  [household mapping and cleaning notes](https://pure.strath.ac.uk/ws/portalfiles/portal/62090183/CLEAN_READ_ME_081116.txt).
  House 2 Appliance5 is microwave; Appliance2 is washing machine.
  UK-DALE activation values are only a declared engineering starting point for
  REFIT, not REFIT-provided labels or validated thresholds for those appliances.
- Both selected datasets are distributed under CC BY 4.0. Preserve the citations
  and the download manifests with derived data; describe transformations.

Each UK-DALE channel is capped at 8,000,000 bytes and REFIT house 2 at 24,000,000
bytes, keeping complete leading lines. This is a reproducible prefix selection,
not the entire datasets and not a claim of multi-household generalization.
The 2015 UK-DALE version permits small channel downloads instead of a multi-GB ZIP.
Metadata from the current author repository is recorded separately from that
2015 data version. URL, date, SHA-256, license, byte limit and partial status are
written to `<download>.source.json`; later preparation checks the input hash.

## Processing and semantics

`fetch_public_power.py` downloads bounded HTTPS text and rejects HTML error pages.
`prepare_public_power.py` reads the selected format with explicit household,
appliance, units, source type, and parameter provenance.
`power_features.py` implements a shared instantaneous-Watt feature extractor.
`run_public_power_benchmark.py` connects those features to the existing trainer.

1. Read UTC timestamps, reject invalid time, sort and deduplicate. Conflicting
   duplicates and invalid power remain missing instead of becoming zero usage.
2. For REFIT, mask records where `Issues != 0`. Cleaned REFIT has already filled
   some missing readings; those filled values cannot all be recovered as missing.
3. A sample supports at most its nominal interval (6 s UK-DALE, 8 s REFIT), capped
   at the next sample. Missing intervals do not acquire invented consumption.
   Energy is the integral `sum(W * supported_seconds) / 3600`, in Wh. It is
   observed energy, not a gap-corrected estimate of full energy.
4. Confirm an activation only after minimum-on evidence arrives; merge short
   below-threshold pauses using minimum-off. Do not count a channel already on
   at file start or after a gap as a newly observed start. Counts use confirmation
   timestamps, and average completed duration appears only after off confirmation.
5. Gaps, invalid samples, end-of-file and a 6-hour session cap censor sessions.
   Censoring means completion/duration is unknown, not normal or a completed cycle.
6. Produce a 2-hour lookback every 10 minutes. Require at least 95% supported time
   and a full lookback since the first sample; excluded feature rows remain NaN.
   This conservative rule can reject many jittery or missing-data windows.

Eleven predictors: observed Wh, mean observed W, above-threshold minutes,
confirmed starts, completed sessions, mean completed duration, night starts,
and sine/cosine pairs for local hour and weekday. Night means 21:00-06:00 in
Europe/London for these datasets. UTC remains the unique time axis through DST.

The Excel's frequency/duration/time/energy idea is thus implemented with explicit
units and limitations. A power-derived session is not a physical button press,
door opening, or HA operating-state transition. No unsupervised cluster is
silently labelled as a true behavioral anomaly.

## Model comparison

The existing trainer uses a 128-tree IF and an 11 -> 16 -> 6 -> 16 -> 11 dense
reconstruction AE for this schema. AE scaling is fitted on training only.
Chronological 60/20/20 boundaries are separated by a 481-minute purge, accounting
for 120-minute features plus a bounded 6-hour session history and gap margin.
Rows removed by that purge are not assigned to training or evaluation.

Calibration selects 95th/99th percentile score thresholds. The later holdout is
used to report each model's attention-or-risk fraction, plus OR and AND fractions.
These are not accuracy, recall, measured false-positive rate or clinical metrics:
the public records have not been verified as normal/anomalous. Models and
thresholds were not chosen by the lowest holdout alert fraction.

Models are marked `source_type=public`; observations prepared here also carry
source provenance. The existing scorer rejects a declared local input against a
public model. No public model path is installed into the production HA loop.
Load only locally created trusted joblib files, never arbitrary downloaded models.

## Reproduction

Run from the `ha_ai` directory in an isolated Python environment. The tested
Windows runtime was Python 3.12.14, numpy 2.3.5, pandas 3.0.1, scipy 1.16.3,
scikit-learn 1.7.2 and joblib 1.5.2. The existing Dockerfile.pi includes the model
dependencies, but this extension has not been runtime-tested or deployed on Pi.

Commands below are each a single line; no HA token or MQTT password is required.
Use a new output directory for each run. Existing downloads and experiment
directories are intentionally not overwritten.

```sh
python src/fetch_public_power.py --url https://dap.ceda.ac.uk/edc/d1/b3baa0aa-05ac-4ec8-b608-da5751758698/data/version_0/house_2/channel_15.dat --output data/public/ukdale_h2_microwave.dat --max-bytes 8000000 --text-prefix --citation https://doi.org/10.5286/UKERC.EDC.000001 --license CC-BY-4.0
python src/fetch_public_power.py --url https://dap.ceda.ac.uk/edc/d1/b3baa0aa-05ac-4ec8-b608-da5751758698/data/version_0/house_2/channel_12.dat --output data/public/ukdale_h2_washer.dat --max-bytes 8000000 --text-prefix --citation https://doi.org/10.5286/UKERC.EDC.000001 --license CC-BY-4.0
python src/fetch_public_power.py --url "https://zenodo.org/records/5063428/files/CLEAN_House2.csv?download=1" --output data/public/refit_h2.csv --max-bytes 24000000 --text-prefix --citation https://doi.org/10.15129/9ab14b0e-19ac-4279-938f-27f643078cec --license CC-BY-4.0
python src/run_public_power_benchmark.py --input data/public/ukdale_h2_microwave.dat --profile deploy/public_power/ukdale_h2_microwave.json --output-dir outputs/public_power/ukdale_microwave
python src/run_public_power_benchmark.py --input data/public/ukdale_h2_washer.dat --profile deploy/public_power/ukdale_h2_washer.json --output-dir outputs/public_power/ukdale_washer
python src/run_public_power_benchmark.py --input data/public/refit_h2.csv --profile deploy/public_power/refit_h2_microwave.json --output-dir outputs/public_power/refit_microwave
python src/run_public_power_benchmark.py --input data/public/refit_h2.csv --profile deploy/public_power/refit_h2_washer.json --output-dir outputs/public_power/refit_washer
python -m unittest discover -s tests -v
```

Each experiment contains `prepared/features.csv`, `prepared/sessions.csv`,
`prepared/quality.json`, `eligible_features.csv`, `model/manifest.json`,
model files, `comparison.csv`, and `experiment.json`. A successful command means
the processing/scoring completed, not that session quality or anomaly detection
is suitable for deployment. Read quality warnings and constant-feature metadata.

## Relationship to real appliances

The current HA state-event path remains unchanged. To reuse this power feature
path for real appliances, first obtain timestamped instantaneous active power in
W from their HA power sensors or smart plugs. A generic `power_csv` adapter accepts
`timestamp,power_w` with timezone-aware timestamps. It does not poll HA itself.
Use local appliance-specific thresholds and Asia/Seoul, confirm missing-data
semantics, and train/evaluate separately on reviewed local records. Changing only
the source label on public records is not personalization.

Devices with only `on/off`, mode, or door states must stay on the HA event path;
do not fabricate Watts for them. Public power data cannot provide our household's
personal baseline or ground truth for cognitive/medical risk.
