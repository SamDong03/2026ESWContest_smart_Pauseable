

from __future__ import annotations

import hashlib
import builtins
import importlib.util
import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
FORMAT = "pauseable-geometric-repetition-rf-v2"
INPUT_CAST = "float32_then_compare_with_float64_threshold"
MAX_MODEL_BYTES = 64 * 1024 * 1024
MAX_TREES = 4096
MAX_NODES_PER_TREE = 65535
MAX_TOTAL_NODES = 1_000_000
TREE_FIELDS = ("left", "right", "feature", "threshold", "positive_probability")


@lru_cache(maxsize=4)
def _load_feature_source(relative: str, source: str, dependency_digest: str):
    path = HERE / relative
    spec = importlib.util.spec_from_file_location(
        "_pauseable_frozen_" + relative.replace("/", "_").replace(".", "_"), path)
    module = importlib.util.module_from_spec(spec)

    def local_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "legacy.features" and level == 0:
            return _feature_module("legacy/features.py")
        return builtins.__import__(name, globals, locals, fromlist, level)


    module.__dict__["__builtins__"] = dict(vars(builtins), __import__=local_import)
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def _feature_module(relative: str):
    source = (HERE / relative).read_text(encoding="utf-8").replace("\r\n", "\n")
    dependency = (HERE / "legacy/features.py").read_bytes() if relative == "shape_features.py" else b""
    return _load_feature_source(relative, source, hashlib.sha256(dependency).hexdigest())


def feature_contract(variant: str) -> dict:
    if variant not in ("legacy9", "multiscale"):
        raise ValueError("Unknown feature variant")
    relative_paths = ["legacy/features.py"]
    if variant == "multiscale":
        relative_paths.append("shape_features.py")
    sources = {}
    for relative in relative_paths:
        source = (HERE / relative).read_text(encoding="utf-8").replace("\r\n", "\n")
        sources[relative] = hashlib.sha256(source.encode("utf-8")).hexdigest()
    names = _feature_module(relative_paths[-1]).FEATURE_NAMES
    return {"variant": variant, "names": list(names), "source_sha256": sources}


def feature_vector(points, variant: str) -> np.ndarray:
    if variant == "legacy9":
        relative = "legacy/features.py"
    elif variant == "multiscale":
        relative = "shape_features.py"
    else:
        raise ValueError("Unknown feature variant")
    return _feature_module(relative).extract_features(points)


def export_forest(forest, variant: str, threshold: float, selection: dict) -> dict:
    _finite_number(threshold, "decision_threshold", 0.0, 1.0)
    if list(forest.classes_) != [0, 1]:
        raise ValueError("The exported forest must contain exactly classes 0 and 1")
    if forest.n_features_in_ != len(feature_contract(variant)["names"]):
        raise ValueError("The trained forest has incompatible feature dimensions")
    positive = list(forest.classes_).index(1)
    trees = []
    for estimator in forest.estimators_:
        tree = estimator.tree_
        values = tree.value[:, 0, :]
        probabilities = values[:, positive] / values.sum(axis=1)
        trees.append({
            "left": tree.children_left.tolist(),
            "right": tree.children_right.tolist(),
            "feature": tree.feature.tolist(),
            "threshold": tree.threshold.tolist(),
            "positive_probability": probabilities.tolist(),
        })
    model = {
        "format": FORMAT,
        "feature_contract": feature_contract(variant),
        "decision_threshold": float(threshold),
        "input_cast": INPUT_CAST,
        "classes": [0, 1],
        "label_meaning": {"0": "synthetic non-repetitive/non-wandering shape",
                          "1": "synthetic repetitive/wandering-like shape"},
        "score_is_calibrated_real_wandering_probability": False,
        "automatic_alerts_enabled": False,
        "personal_baseline_trained": False,
        "selection": selection,
        "trees": trees,
    }
    validate_forest(model)
    return model


def _finite_number(value, name: str, minimum=None, maximum=None) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{name} must be a finite number") from error
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and number < minimum or maximum is not None and number > maximum:
        raise ValueError(f"{name} is outside the supported range")
    return number


def _validate_header(model: dict) -> int:
    if not isinstance(model, dict) or model.get("format") != FORMAT:
        raise ValueError("Not a Pauseable v2 geometric repetition forest")
    contract = model.get("feature_contract")
    if not isinstance(contract, dict) or contract.get("variant") not in ("legacy9", "multiscale"):
        raise ValueError("Forest has no supported feature contract")
    if contract != feature_contract(contract["variant"]):
        raise ValueError("Feature implementation differs from trained model")
    _finite_number(model.get("decision_threshold"), "decision_threshold", 0.0, 1.0)
    classes = model.get("classes")
    if not isinstance(classes, list) or classes != [0, 1] or any(type(v) is not int for v in classes):
        raise ValueError("Forest classes must be [0, 1]")
    if model.get("input_cast") != INPUT_CAST:
        raise ValueError("Forest has an unsupported numeric input contract")
    for flag in ("score_is_calibrated_real_wandering_probability", "automatic_alerts_enabled",
                 "personal_baseline_trained"):
        if model.get(flag) is not False:
            raise ValueError(f"Unsupported forest claim: {flag}")
    trees = model.get("trees")
    if not isinstance(trees, list) or not 1 <= len(trees) <= MAX_TREES:
        raise ValueError("Forest has an unsupported number of trees")
    return len(contract["names"])


def _tree_size(tree) -> int:
    if not isinstance(tree, dict) or any(not isinstance(tree.get(k), list) for k in TREE_FIELDS):
        raise ValueError("Every tree must contain all five node arrays")
    size = len(tree["left"])
    if not 1 <= size <= MAX_NODES_PER_TREE or any(len(tree[k]) != size for k in TREE_FIELDS):
        raise ValueError("Tree node arrays have incompatible lengths")
    return size


def _node(tree: dict, node: int, size: int, feature_count: int):
    if type(node) is not int or not 0 <= node < size:
        raise ValueError("Tree child index is outside its node array")
    left, right, feature = (tree[k][node] for k in ("left", "right", "feature"))
    if any(type(v) is not int for v in (left, right, feature)):
        raise ValueError("Tree child and feature indices must be integers")
    threshold = _finite_number(tree["threshold"][node], "Tree threshold")
    probability = _finite_number(tree["positive_probability"][node], "Leaf probability", 0.0, 1.0)
    if left == -1 or right == -1:
        if left != -1 or right != -1 or feature != -2:
            raise ValueError("Tree leaf has invalid children or feature sentinel")
    elif not (0 <= left < size and 0 <= right < size and left != right and 0 <= feature < feature_count):
        raise ValueError("Tree branch has an invalid child or feature index")
    return left, right, feature, threshold, probability


def validate_forest(model: dict) -> None:
    feature_count = _validate_header(model)
    total_nodes = 0
    for tree in model["trees"]:
        size = _tree_size(tree)
        total_nodes += size
        if total_nodes > MAX_TOTAL_NODES:
            raise ValueError("Forest exceeds the supported total node count")
        pending, visited = [0], set()
        while pending:
            node = pending.pop()
            if node in visited:
                raise ValueError("Tree contains a cycle or shared child")
            visited.add(node)
            left, right, _, _, _ = _node(tree, node, size, feature_count)
            if left != -1:
                pending.extend((left, right))
        if len(visited) != size:
            raise ValueError("Tree contains unreachable nodes")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate model JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"Nonfinite model JSON constant: {value}")


def load_forest(path: Path) -> dict:
    with Path(path).open("rb") as source:
        raw = source.read(MAX_MODEL_BYTES + 1)
    if len(raw) > MAX_MODEL_BYTES:
        raise ValueError("Forest JSON exceeds the supported file size")
    try:
        model = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeError, RecursionError) as error:
        raise ValueError("Forest is not supported JSON") from error
    validate_forest(model)
    return model


def score_features(model: dict, values) -> float:
    feature_count = _validate_header(model)
    try:
        raw = np.asarray(values)
        if raw.dtype.kind not in "iuf":
            raise ValueError("Features must contain real numeric values")
        with np.errstate(over="ignore", invalid="ignore"):
            row = np.asarray(raw, dtype=np.float32)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError("Feature vector must be real finite numbers") from error
    if row.shape != (feature_count,) or not np.isfinite(row).all():
        raise ValueError("Feature vector has incompatible dimensions or nonfinite values")
    total = 0.0
    total_nodes = 0
    for tree in model["trees"]:
        size = _tree_size(tree)
        total_nodes += size
        if total_nodes > MAX_TOTAL_NODES:
            raise ValueError("Forest exceeds the supported total node count")
        node = 0
        for _ in range(size):
            left, right, feature, threshold, probability = _node(tree, node, size, feature_count)
            if left == -1:
                total += probability
                break

            value = float(row[feature])
            node = left if value <= threshold else right
        else:
            raise ValueError("Tree traversal exceeded its node count")
    return total / len(model["trees"])


def predict_path(model: dict, points) -> dict:
    _validate_header(model)
    values = feature_vector(points, model["feature_contract"]["variant"])
    score = score_features(model, values)
    return {
        "status": "shape_research_only",
        "shape_score_not_calibrated": score,
        "synthetic_shape_class": int(score >= model["decision_threshold"]),
        "decision_threshold": model["decision_threshold"],
        "feature_count": len(values),
        "personal_baseline": "not_evaluated",
        "wandering_decision": "not_evaluated",
        "alert": False,
    }
