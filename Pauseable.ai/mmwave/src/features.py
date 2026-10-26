from __future__ import annotations
import hashlib
import numpy as np

RESAMPLE_COUNT = 64
FEATURE_NAMES = (
    "path_length_over_diameter",
    "net_displacement_over_length",
    "endpoint_distance_over_diameter",
    "mean_absolute_turn_radians",
    "turn_over_90deg_fraction",
    "total_absolute_turn_over_pi",
    "pca_minor_over_major_variance",
    "convex_hull_area_over_diameter_squared",
    "nonlocal_revisit_fraction",
)

def _prepare(points) -> np.ndarray:
    try:
        raw = np.asarray(points)
        if np.iscomplexobj(raw):
            raise ValueError("Complex coordinates are not supported")
        coordinates = np.asarray(raw, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise ValueError("points must be a numeric N-by-2 sequence") from error
    if coordinates.ndim != 2 or coordinates.shape[1] != 2:
        raise ValueError("points must have shape (N, 2)")
    if len(coordinates) < 3 or not np.isfinite(coordinates).all():
        raise ValueError("At least three finite coordinate pairs are required")

    coordinate_scale = float(np.max(np.abs(coordinates)))
    if coordinate_scale == 0.0:
        raise ValueError("The path has zero length")
    coordinates = coordinates / coordinate_scale
    coordinates = coordinates - coordinates[0]
    keep = np.r_[True, np.any(np.diff(coordinates, axis=0) != 0.0, axis=1)]
    coordinates = coordinates[keep]
    if len(np.unique(coordinates, axis=0)) < 3:
        raise ValueError("The path must contain at least three distinct points")

    extent = float(np.max(np.abs(coordinates)))
    if extent == 0.0 or not np.isfinite(extent):
        raise ValueError("The path has no representable extent")
    return coordinates / extent

def _resample(points) -> np.ndarray:
    coordinates = _prepare(points)
    steps = np.diff(coordinates, axis=0)
    lengths = np.hypot(steps[:, 0], steps[:, 1])
    cumulative = np.r_[0.0, np.cumsum(lengths)]
    total = float(cumulative[-1])
    if total <= 0.0 or not np.isfinite(total):
        raise ValueError("The path must have a finite, nonzero length")

    keep = np.r_[True, np.diff(cumulative) > 0.0]
    cumulative = cumulative[keep]
    coordinates = coordinates[keep]
    positions = np.linspace(0.0, total, RESAMPLE_COUNT)
    return np.column_stack(
        [np.interp(positions, cumulative, coordinates[:, axis]) for axis in (0, 1)]
    )

def _pairwise_distances(points: np.ndarray) -> np.ndarray:
    delta = points[:, None, :] - points[None, :, :]
    return np.hypot(delta[:, :, 0], delta[:, :, 1])

def _convex_hull_area(points: np.ndarray) -> float:
    vertices = sorted(set(map(tuple, points.tolist())))
    if len(vertices) < 3:
        return 0.0

    def cross(origin, first, second):
        return ((first[0] - origin[0]) * (second[1] - origin[1])
                - (first[1] - origin[1]) * (second[0] - origin[0]))

    lower = []
    for vertex in vertices:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], vertex) <= 0:
            lower.pop()
        lower.append(vertex)
    upper = []
    for vertex in reversed(vertices):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], vertex) <= 0:
            upper.pop()
        upper.append(vertex)
    hull = np.asarray(lower[:-1] + upper[:-1], dtype=np.float64)
    if len(hull) < 3:
        return 0.0
    following = np.roll(hull, -1, axis=0)
    return float(abs(np.sum(hull[:, 0] * following[:, 1]
                            - hull[:, 1] * following[:, 0])) / 2.0)

def extract_features(points) -> np.ndarray:
    sampled = _resample(points)
    distances = _pairwise_distances(sampled)
    diameter = float(distances.max())
    if diameter <= 0.0:
        raise ValueError("The resampled path has zero diameter")
    sampled = sampled / diameter
    distances = distances / diameter
    steps = np.diff(sampled, axis=0)
    lengths = np.hypot(steps[:, 0], steps[:, 1])
    path_length = float(lengths.sum())
    endpoint_distance = float(distances[0, -1])

    valid = lengths > 1e-12
    directions = steps[valid] / lengths[valid, None]
    if endpoint_distance <= 1e-12 and len(directions) > 1:
        directions = np.vstack([directions, directions[0]])
    first, second = directions[:-1], directions[1:]
    cross = first[:, 0] * second[:, 1] - first[:, 1] * second[:, 0]
    dot = np.sum(first * second, axis=1)
    turns = np.arctan2(np.abs(cross), dot)

    centered = sampled - sampled.mean(axis=0)
    eigenvalues = np.maximum(np.linalg.eigvalsh(centered.T @ centered), 0.0)
    pca_ratio = float(eigenvalues[0] / eigenvalues[1])

    indices = np.arange(RESAMPLE_COUNT)
    nonlocal_mask = np.abs(indices[:, None] - indices[None, :]) >= 7
    revisit_fraction = float(np.any((distances <= 0.05) & nonlocal_mask, axis=1).mean())

    features = np.asarray([
        path_length,
        endpoint_distance / path_length,
        endpoint_distance,
        float(turns.mean()) if turns.size else 0.0,
        float(np.mean(turns > np.pi / 2.0 + 1e-12)) if turns.size else 0.0,
        float(turns.sum() / np.pi),
        pca_ratio,
        _convex_hull_area(sampled),
        revisit_fraction,
    ], dtype=np.float64)
    if not np.isfinite(features).all():
        raise ValueError("The path did not produce finite features")
    return features

def path_fingerprint(points) -> str:
    sampled = _resample(points)
    distances = _pairwise_distances(sampled)
    diameter = float(distances.max())
    if diameter <= 0.0:
        raise ValueError("The resampled path has zero diameter")
    signature = distances[np.triu_indices(RESAMPLE_COUNT, k=1)] / diameter
    quantized = np.rint(signature * 1_000_000).astype("<i8")
    return hashlib.sha256(b"smartcare-shape-v1:64:6:" + quantized.tobytes()).hexdigest()
