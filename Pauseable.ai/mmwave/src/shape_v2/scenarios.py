

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable

import numpy as np


PROTOCOL_VERSION = "pauseable-shape-scenarios-v2.0"
DEFAULT_SEEDS = {"train": 4101, "validation": 4102, "test": 4103, "challenge": 4104}
FAMILY_RULES = {
    "bent_transit": "0: one traversal of a randomly bent route with forward progress",
    "corridor_detour": "0: one angular detour with forward progress; no repeated circuit",
    "meandering_transit": "0: one meandering transit with monotonically increasing route axis",
    "single_return": "0: one outward trip followed by one partial return, without another outward trip",
    "open_arc": "0: one open curved route of less than one full revolution",
    "repeated_shuttle": "1: four to seven traversals of the same independently drawn curved route",
    "repeat_irregular_loop": "1: two to four complete traversals of one irregular closed loop",
    "repeat_figure8": "1: two to four complete traversals of an asymmetric figure-eight route",
    "transit_then_repetition": "1: a transit followed by two to four complete traversals of one loop",
    "repetition_then_transit": "1: two to four complete traversals of one loop followed by a transit",
}
FAMILY_LABELS = {family: int(rule[0]) for family, rule in FAMILY_RULES.items()}
LABELLED_FAMILIES = tuple(FAMILY_RULES)
NEGATIVE_FAMILIES = tuple(f for f, label in FAMILY_LABELS.items() if label == 0)
POSITIVE_FAMILIES = tuple(f for f, label in FAMILY_LABELS.items() if label == 1)


@dataclass(frozen=True)
class Scenario:
    path_id: str
    group_id: str
    family: str
    label: int | None
    points: np.ndarray
    split: str
    metadata: dict


def _derived_seed(seed: int, *parts: object) -> int:
    text = ":".join(map(str, (PROTOCOL_VERSION, seed, *parts)))
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")


def _join(*pieces: np.ndarray) -> np.ndarray:
    return np.concatenate([pieces[0], *(part[1:] for part in pieces[1:])])


def _polyline(vertices: np.ndarray, per_leg: int = 96) -> np.ndarray:
    parts = [np.linspace(a, b, per_leg) for a, b in zip(vertices[:-1], vertices[1:])]
    return _join(*parts)


def _resample(points: np.ndarray, positions: np.ndarray) -> np.ndarray:
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    keep = np.r_[True, lengths > 1e-12]
    points = points[keep]
    distance = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    if len(points) < 2 or distance[-1] <= 0:
        raise ValueError("Scenario generator produced an empty path")
    return np.column_stack([
        np.interp(positions * distance[-1], distance, points[:, axis])
        for axis in range(2)
    ])


def _route(rng: np.random.Generator, challenge: bool) -> np.ndarray:
    pass
    if challenge:
        n = int(rng.integers(3, 7))
        x = np.r_[0.0, np.sort(rng.uniform(0.1, 0.9, n - 2)), 1.0]
        y = rng.uniform(-0.3, 0.3, n)
        y -= y[0]
        return _polyline(np.column_stack([x, y]))
    u = np.linspace(0.0, 1.0, 480)
    a, b, c = rng.uniform(-0.25, 0.25, 3)
    y = a * np.sin(np.pi * u) + b * np.sin(2 * np.pi * u) + c * u
    return np.column_stack([u, y])


def _bent_transit(rng: np.random.Generator, challenge: bool):
    n = int(rng.integers(4, 10 if challenge else 8))
    x = np.r_[0.0, np.sort(rng.uniform(0.04, 0.96, n - 2)), 1.0]
    y = np.cumsum(rng.uniform(-0.28, 0.28, n))
    points = _polyline(np.column_stack([x, y]))
    return points, {"waypoint_count": n, "forward_axis_monotonic": True}


def _corridor_detour(rng: np.random.Generator, challenge: bool):
    sections = int(rng.integers(2, 5 if challenge else 4))
    x = np.r_[0.0, np.sort(rng.uniform(0.08, 0.92, sections)), 1.0]
    level = 0.0
    vertices = [[0.0, level]]
    for boundary in x[1:-1]:
        vertices.append([float(boundary), level])
        level += float(rng.uniform(-0.5, 0.5))
        vertices.append([float(boundary), level])
    vertices.append([1.0, level])
    points = _polyline(np.asarray(vertices))
    if challenge:

        points[:, 1] += 0.16 * np.sin(3 * np.pi * points[:, 0])
    return points, {"detour_sections": sections, "forward_axis_monotonic": True}


def _meandering_transit(rng: np.random.Generator, challenge: bool):
    u = np.linspace(0, 1, 1200)
    frequency = float(rng.uniform(1.2, 4.8))
    amplitude = float(rng.uniform(0.04, 0.22))
    phase = float(rng.uniform(-np.pi, np.pi))
    y = amplitude * np.sin(2 * np.pi * frequency * u + phase)
    y += float(rng.uniform(-0.18, 0.18)) * u
    if challenge:
        y += amplitude * 0.4 * np.sin(2 * np.pi * (frequency + 2.3) * u)
    return np.column_stack([u, y]), {"frequency": frequency, "amplitude": amplitude,
                                         "phase": phase, "forward_axis_monotonic": True}


def _single_return(rng: np.random.Generator, challenge: bool):
    route = _route(rng, challenge)
    returned_fraction = float(rng.uniform(0.2, 0.9))
    back = _resample(route, np.linspace(1.0, 1.0 - returned_fraction, 400))
    return _join(route, back), {"outward_traversals": 1, "return_traversals": 1,
                                "returned_fraction": returned_fraction}


def _open_arc(rng: np.random.Generator, challenge: bool):
    sweep = float(rng.uniform(0.35, 1.65) * np.pi)
    t = np.linspace(0, sweep, 900)
    ratio = float(rng.uniform(0.45, 1.8))
    radius = 1 + float(rng.uniform(-0.13, 0.13)) * np.sin(2 * t)
    if challenge:
        radius += np.linspace(0, float(rng.uniform(-0.3, 0.3)), len(t))
    points = np.column_stack([radius * np.cos(t), ratio * radius * np.sin(t)])
    return points, {"sweep_radians": sweep, "complete_circuits": 0, "axis_ratio": ratio}


def _repeated_shuttle(rng: np.random.Generator, challenge: bool):
    route = _route(rng, challenge)
    traversals = int(rng.integers(4, 8))
    pieces = [route if k % 2 == 0 else route[::-1] for k in range(traversals)]
    return _join(*pieces), {"route_traversals": traversals,
                           "complete_out_and_back_cycles": traversals // 2}


def _loop(rng: np.random.Generator, challenge: bool) -> np.ndarray:
    if challenge:

        n = int(rng.integers(3, 8))
        theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
        theta += rng.uniform(-0.2, 0.2, n)
        radius = rng.uniform(0.7, 1.3, n)
        vertices = np.column_stack([radius * np.cos(theta), radius * np.sin(theta)])
        vertices[:, 1] *= float(rng.uniform(0.45, 1.7))
        points = _polyline(np.vstack([vertices, vertices[:1]]))
    else:
        theta = np.linspace(0, 2 * np.pi, 1000)
        p, q = rng.uniform(-np.pi, np.pi, 2)
        a, b = rng.uniform(0.03, 0.18, 2)
        radius = 1 + a * np.sin(2 * theta + p) + b * np.sin(3 * theta + q)
        points = np.column_stack([radius * np.cos(theta), radius * np.sin(theta)])
        points[:, 1] *= float(rng.uniform(0.45, 1.7))
    return points - points[0]


def _repeat_irregular_loop(rng: np.random.Generator, challenge: bool):
    loop = _loop(rng, challenge)
    circuits = int(rng.integers(2, 5))
    return _join(*(loop for _ in range(circuits))), {"complete_circuits": circuits}


def _repeat_figure8(rng: np.random.Generator, challenge: bool):
    t = np.linspace(0, 2 * np.pi, 1300)
    lobe_asymmetry = float(rng.uniform(-0.35, 0.35))
    axis_ratio = float(rng.uniform(0.3, 1.15))
    x = np.sin(t) * (1 + lobe_asymmetry * np.sin(t))
    y = axis_ratio * np.sin(2 * t)
    if challenge:

        positions = np.linspace(0, len(t) - 1, int(rng.integers(9, 16))).astype(int)
        loop = _polyline(np.column_stack([x, y])[positions])
    else:
        y += float(rng.uniform(-0.13, 0.13)) * np.sin(t)
        loop = np.column_stack([x, y])
    circuits = int(rng.integers(2, 5))
    return _join(*(loop for _ in range(circuits))), {"complete_figure8_traversals": circuits,
                                                    "lobe_asymmetry": lobe_asymmetry,
                                                    "axis_ratio": axis_ratio}


def _transit_loop(rng: np.random.Generator, challenge: bool, loop_first: bool):
    loop = _loop(rng, challenge)
    circuits = int(rng.integers(2, 5))
    transit_extent = float(rng.uniform(1.2, 9.0))
    offset = float(rng.uniform(-2.0, 2.0))
    if loop_first:
        vertices = [[0, 0], [transit_extent * 0.45, offset], [transit_extent, offset * 0.5]]
        pieces = [*(loop for _ in range(circuits)), _polyline(np.asarray(vertices))]
    else:
        vertices = [[-transit_extent, offset], [-transit_extent * 0.45, offset * 0.4], [0, 0]]
        pieces = [_polyline(np.asarray(vertices)), *(loop for _ in range(circuits))]
    return _join(*pieces), {"complete_circuits": circuits,
                           "transit_extent_in_loop_units": transit_extent,
                           "repetition_location": "start" if loop_first else "end"}


_GENERATORS: dict[str, Callable] = {
    "bent_transit": _bent_transit,
    "corridor_detour": _corridor_detour,
    "meandering_transit": _meandering_transit,
    "single_return": _single_return,
    "open_arc": _open_arc,
    "repeated_shuttle": _repeated_shuttle,
    "repeat_irregular_loop": _repeat_irregular_loop,
    "repeat_figure8": _repeat_figure8,
    "transit_then_repetition": lambda r, c: _transit_loop(r, c, False),
    "repetition_then_transit": lambda r, c: _transit_loop(r, c, True),
}


def _nuisance(points: np.ndarray, rng: np.random.Generator):
    count = int(rng.integers(96, 221))
    density_power = float(rng.uniform(0.7, 1.4))
    u = np.linspace(0, 1, count)
    sampled = _resample(points, u ** density_power)
    extent = float(np.linalg.norm(np.ptp(sampled, axis=0)))
    noise_fraction = float(rng.uniform(0.0, 0.003))
    phases = rng.uniform(-np.pi, np.pi, 2)

    smooth_noise = np.column_stack([
        np.sin(2 * np.pi * 3 * u + phases[0]),
        np.sin(2 * np.pi * 4 * u + phases[1]),
    ])
    sampled += noise_fraction * extent * smooth_noise
    angle = float(rng.uniform(-np.pi, np.pi))
    scale = float(np.exp(rng.uniform(np.log(0.3), np.log(4.0))))
    shift = rng.uniform(-5, 5, 2)
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    sampled = scale * sampled @ rotation.T + shift
    return sampled, {"point_count": count, "density_power": density_power,
                     "smooth_perturbation_fraction": noise_fraction,
                     "rotation_radians": angle, "scale": scale, "translation": shift.tolist()}


def generate_split(split: str, per_family: int, seed: int) -> list[Scenario]:
    pass


    if not isinstance(split, str) or not split or not split.replace("_", "").isalnum():
        raise ValueError("split must be a nonempty alphanumeric name")
    if isinstance(per_family, bool) or not isinstance(per_family, int) or per_family < 1:
        raise ValueError("per_family must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    challenge = split == "challenge"
    result = []
    for family, generator in _GENERATORS.items():
        for index in range(per_family):
            geometry_seed = _derived_seed(seed, split, family, index, "geometry")


            nuisance_seed = _derived_seed(seed, split, index, "nuisance")
            points, details = generator(np.random.default_rng(geometry_seed), challenge)
            points, nuisance = _nuisance(points, np.random.default_rng(nuisance_seed))
            path_id = f"shape-v2:{split}:{seed}:{family}:{index:05d}"
            metadata = {
                "protocol_version": PROTOCOL_VERSION,
                "source": "independently_drawn_synthetic_geometry",
                "data_origin": "simulated",
                "label_semantics": "geometric_repetition_only",
                "clinical_label": None,
                "label_scope": "entire_trajectory",
                "rule": FAMILY_RULES[family],
                "seed": seed,
                "geometry_seed": geometry_seed,
                "nuisance_seed": nuisance_seed,
                "index": index,
                "units": "arbitrary_not_metres",
                "timestamps_available": False,
                "challenge_construction": challenge,
                "construction": details,
                "nuisance": nuisance,
            }
            result.append(Scenario(path_id, path_id, family, FAMILY_LABELS[family],
                                   points, split, metadata))
    return result


def generate_ambiguous(seed: int = 4201) -> list[Scenario]:
    pass


    u = np.linspace(0, 1, 300)
    result = []

    def add(family: str, index: int, points: np.ndarray, parameters: dict,
            note: str, group_id: str | None = None):
        path_id = f"shape-v2:ambiguous:{seed}:{family}:{index:03d}"
        result.append(Scenario(path_id, group_id or path_id, family, None,
                               np.asarray(points, dtype=np.float64), "ambiguous", {
            "protocol_version": PROTOCOL_VERSION,
            "data_origin": "simulated",
            "label_semantics": "unlabelled_exploration",
            "clinical_label": None,
            "seed": seed,
            "parameters": parameters,
            "note": note,
            "timestamps_available": False,
            "units": "arbitrary_not_metres",
        }))

    x = np.where(u < 0.65, 8 * u / 0.65, 8 - 4 * (u - 0.65) / 0.35)
    add("prior_one_return", 0, np.column_stack([x, 0.2 * np.sin(2 * np.pi * u)]), {},
        "One outward trip and one partial return; no clinical truth label.")
    for index, strength in enumerate(np.linspace(0, 1, 11)):
        t = np.linspace(0, np.pi * (0.8 + 0.8 * strength), 300)
        points = np.column_stack([2.5 * np.cos(t) + 2.2 * u, 2.5 * np.sin(t)])
        add("prior_partial_loop", index, points, {"strength": float(strength)},
            "Arc sweep is 0.8 to 1.6 pi radians with drift; never a complete revolution.")
    for index, strength in enumerate(np.linspace(0, 1, 21)):
        t = 2 * np.pi * (0.7 + 0.8 * strength) * u
        x = (1 - strength) * 8 * u + strength * (2 * np.cos(t) + 2 * u)
        y = strength * 2 * np.sin(t)
        add("prior_weak_loop", index, np.column_stack([x, y]), {"strength": float(strength)},
            "Formula strength has no truth label; at 1.0 this is 1.5 turns plus drift.")

    rng = np.random.default_rng(_derived_seed(seed, "same_geometry_context"))
    loop, _ = _repeat_irregular_loop(rng, False)
    points = _resample(loop, np.linspace(0, 1, 180))
    group_id = f"shape-v2:ambiguous:{seed}:same_geometry_different_intent"
    for index, context in enumerate(("planned walking exercise", "reported concern about wandering")):
        add("same_geometry_different_intent", index, points.copy(), {"described_context": context},
            "Exactly the same points; these descriptions are hypothetical context, not patient labels.",
            group_id)
    return result
