

from __future__ import annotations

import numpy as np

from legacy.features import FEATURE_NAMES as LEGACY_FEATURE_NAMES
from legacy.features import _prepare
from legacy.features import extract_features as extract_legacy_features


FEATURE_VERSION = "pauseable-shape-features-v2"
LOCAL_RESAMPLE_COUNT = 128
LOCAL_SCALES = (("quarter", 32), ("half", 64))
LOCAL_METRICS = (
    "length_over_diameter",
    "return_over_length",
    "revisit_fraction",
    "opposite_nearby_fraction",
    "absolute_turn_over_pi",
    "turn_direction_consistency",
)
FEATURE_NAMES = (
    *LEGACY_FEATURE_NAMES,
    "global_revisit_radius_025_fraction",
    "global_revisit_radius_100_fraction",
    "global_opposite_nearby_fraction",
    *(f"local_{scale}_{metric}_{aggregation}"
      for scale, _ in LOCAL_SCALES
      for metric in LOCAL_METRICS
      for aggregation in ("mean", "max")),
)


def _distances(points: np.ndarray) -> np.ndarray:
    differences = points[:, None, :] - points[None, :, :]
    return np.hypot(differences[:, :, 0], differences[:, :, 1])


def _sample(points) -> np.ndarray:
    pass
    prepared = _prepare(points)
    increments = np.linalg.norm(np.diff(prepared, axis=0), axis=1)
    positions = np.r_[0.0, np.cumsum(increments)]
    keep = np.r_[True, np.diff(positions) > 0.0]
    positions, prepared = positions[keep], prepared[keep]
    if positions[-1] <= 0.0 or not np.isfinite(positions[-1]):
        raise ValueError("The path must have a finite, nonzero length")
    requested = np.linspace(0.0, positions[-1], LOCAL_RESAMPLE_COUNT)
    sampled = np.column_stack([
        np.interp(requested, positions, prepared[:, axis]) for axis in (0, 1)
    ])
    diameter = float(_distances(sampled).max())
    if diameter <= 0.0:
        raise ValueError("The resampled path has zero diameter")
    return sampled / diameter


def _revisit(distances: np.ndarray, radius: float) -> float:
    indices = np.arange(len(distances))
    separation = max(3, int(np.ceil(0.15 * (len(distances) - 1))))
    nonlocal_pairs = np.abs(indices[:, None] - indices[None, :]) >= separation


    return float(np.any((distances < radius) & nonlocal_pairs, axis=1).mean())


def _opposite_nearby(points: np.ndarray) -> float:
    pass
    steps = np.diff(points, axis=0)
    lengths = np.linalg.norm(steps, axis=1)
    valid = lengths > 1e-12
    if np.count_nonzero(valid) < 2:
        return 0.0
    original_indices = np.flatnonzero(valid)
    directions = steps[valid] / lengths[valid, None]
    centers = ((points[:-1] + points[1:]) / 2.0)[valid]
    separation = max(3, int(np.ceil(0.15 * len(steps))))
    nonlocal_pairs = (
        np.abs(original_indices[:, None] - original_indices[None, :]) >= separation
    )
    opposite = directions @ directions.T < -0.5
    near = _distances(centers) < 0.08
    return float(np.any(nonlocal_pairs & opposite & near, axis=1).mean())


def _local_descriptors(points: np.ndarray) -> np.ndarray:
    translated = points - points[0]
    diameter = float(_distances(translated).max())
    if diameter <= 1e-12:
        return np.zeros(len(LOCAL_METRICS), dtype=np.float64)
    normalized = translated / diameter
    steps = np.diff(normalized, axis=0)
    lengths = np.linalg.norm(steps, axis=1)
    length = float(lengths.sum())
    if length <= 1e-12:
        return np.zeros(len(LOCAL_METRICS), dtype=np.float64)
    directions = steps[lengths > 1e-12] / lengths[lengths > 1e-12, None]
    previous, following = directions[:-1], directions[1:]
    cross = previous[:, 0] * following[:, 1] - previous[:, 1] * following[:, 0]
    dot = np.einsum("ij,ij->i", previous, following)
    turns = np.arctan2(cross, dot)


    absolute_turn = float(np.abs(turns).sum())
    signed_turn = float(turns[np.abs(cross) > 1e-12].sum())
    return np.asarray([
        length,
        np.clip(1.0 - np.linalg.norm(normalized[-1]) / length, 0.0, 1.0),
        _revisit(_distances(normalized), 0.08),
        _opposite_nearby(normalized),
        absolute_turn / np.pi,
        abs(signed_turn) / absolute_turn if absolute_turn > 1e-12 else 0.0,
    ], dtype=np.float64)


def extract_features(points) -> np.ndarray:
    pass


    legacy = extract_legacy_features(points)
    sampled = _sample(points)
    pairwise = _distances(sampled)
    extra = [
        _revisit(pairwise, 0.025),
        _revisit(pairwise, 0.1),
        _opposite_nearby(sampled),
    ]
    for _, segment_count in LOCAL_SCALES:

        final_start = len(sampled) - segment_count - 1
        starts = sorted(set(range(0, final_start + 1, segment_count // 2)) | {final_start})
        rows = np.vstack([
            _local_descriptors(sampled[start:start + segment_count + 1])
            for start in starts
        ])
        for column in range(len(LOCAL_METRICS)):
            extra.extend([float(rows[:, column].mean()), float(rows[:, column].max())])
    result = np.r_[legacy, np.asarray(extra, dtype=np.float64)]
    if result.shape != (len(FEATURE_NAMES),) or not np.isfinite(result).all():
        raise ValueError("The path did not produce finite features")
    return result
