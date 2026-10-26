
from __future__ import annotations

import argparse
import json
from pathlib import Path

from legacy.dataset import decode_document, xy
from portable_forest import load_forest, predict_path


def load_one_path(path: Path):
    records = decode_document(path.read_bytes())
    if not all(isinstance(p, dict) for p in records):
        raise ValueError("Input must be one list of ordered {x, y} points")
    if any("date" in p for p in records):
        keys = [p.get("date") for p in records]
        if not all(isinstance(v, str) and v for v in keys) or len(set(keys)) != 1:
            raise ValueError("Do not join multiple paths/date groups")
    for key in ("sensor_id", "session_id", "target_id"):
        if any(key in p for p in records):
            values = [p.get(key) for p in records]
            if any(value is None for value in values) or any(value != values[0] for value in values):
                raise ValueError(f"Input contains mixed or missing {key}")
    return [xy(p) for p in records]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = predict_path(load_forest(args.model), load_one_path(args.input))
    except (ValueError, OSError) as error:
        parser.exit(2, f"ERROR: {error}\n")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
