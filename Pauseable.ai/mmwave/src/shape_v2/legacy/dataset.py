from __future__ import annotations
import hashlib
import json
import math
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

COMMIT = "1d479627158cfb46bef837afedc0f63b6c8bbbe0"
REPOSITORY = "https://github.com/Unilasalle-SmartCare/smartcare-machinelearning"
FILES = {
    "dataset.json": "25845a0d66022285e4b631d3101e574f60aa5996275c65222b759bfaf3473b71",
    "dataset-validacao.json": "afac7512dfd3903bb87ec006da20937591b699a5eecee7377b7825ae1360bc75",
}

@dataclass(frozen=True)
class Trajectory:
    path_id: str
    points: tuple[tuple[float, float], ...]
    label: int

def decode_document(raw: bytes | str):
    pass
    value = json.loads(raw)
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list) or not value:
        raise ValueError("Expected a nonempty JSON array of point records")
    return value

def xy(point: dict) -> tuple[float, float]:
    values = []
    for key in ("x", "y"):
        value = point.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Point {key} must be a finite number")
        try:
            value = float(value)
        except (OverflowError, ValueError) as error:
            raise ValueError(f"Point {key} is outside the supported numeric range") from error
        if not math.isfinite(value):
            raise ValueError(f"Point {key} must be a finite number")
        values.append(value)
    return values[0], values[1]

def load_trajectories(path: Path) -> list[Trajectory]:
    groups: OrderedDict[str, list] = OrderedDict()
    for point in decode_document(path.read_bytes()):
        if not isinstance(point, dict):
            raise ValueError("Every point must be an object")
        date = point.get("date")
        if not isinstance(date, str) or not date:
            raise ValueError("SmartCare point lacks its trajectory grouping date")
        if type(point.get("stress")) is not bool:
            raise ValueError("SmartCare 'stress' must be boolean (synthetic class label)")
        groups.setdefault(date, []).append(point)
    result = []
    for index, (_, points) in enumerate(groups.items()):
        labels = {p["stress"] for p in points}
        if len(labels) != 1:
            raise ValueError(f"Mixed class labels inside trajectory {index}")
        result.append(Trajectory(
            path_id=f"{path.name}:{index:03d}",
            points=tuple(xy(p) for p in points),
            label=int(points[0]["stress"]),
        ))
    return result

def verified_sources(directory: Path) -> dict:
    pass
    result = {}
    for name, expected in FILES.items():
        path = directory / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Checksum mismatch: {name}; existing file left unchanged")
        result[name] = {"sha256": actual, "bytes": path.stat().st_size}
    return {"repository": REPOSITORY, "commit": COMMIT, "files": result}

def fetch(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    for name, expected in FILES.items():
        path = directory / name
        if not path.exists():
            url = f"https://raw.githubusercontent.com/Unilasalle-SmartCare/smartcare-machinelearning/{COMMIT}/model/dados/{name}"
            request = Request(url, headers={"User-Agent": "Pauseable-SmartCare-research-prototype"})
            with urlopen(request, timeout=30) as response:
                raw = response.read(5_000_001)
            if len(raw) > 5_000_000 or hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError(f"Unexpected upstream contents: {name}; not saved")
            with path.open("xb") as output:
                output.write(raw)
    return verified_sources(directory)
