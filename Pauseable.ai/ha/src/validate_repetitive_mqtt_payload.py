import argparse
import json
from datetime import datetime
from pathlib import Path
import re

from jsonschema import Draft202012Validator, FormatChecker


def default_schema_path() -> Path:
    pass
    module = Path(__file__).resolve()
    for parent in module.parents:
        candidate = parent / "Pauseable.contracts/communication-v1/schemas/behavior-inference.schema.json"
        if candidate.is_file():
            return candidate
    return module.parents[1] / "deploy/contracts/behavior-inference.schema.json"


def payload_validator(schema_path):
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    checker = FormatChecker()

    @checker.checks("date-time", raises=(ValueError, TypeError))
    def valid_timestamp(value):
        if not isinstance(value, str):
            return True
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
            return False
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    return Draft202012Validator(schema, format_checker=checker)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", required=True)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    schema_path = Path(args.schema)
    input_path = Path(args.input)

    validator = payload_validator(schema_path)

    checked = 0
    failed = 0

    with input_path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            checked += 1

            try:
                payload = json.loads(line)
            except json.JSONDecodeError as e:
                failed += 1
                print(f"[line {line_number}] invalid JSON: {e}")
                continue

            errors = sorted(
                validator.iter_errors(payload),
                key=lambda error: str(list(error.path)),
            )

            if errors:
                failed += 1
                print(f"[line {line_number}] schema validation failed")
                for error in errors:
                    path = ".".join(str(part) for part in error.path)
                    if not path:
                        path = "<root>"
                    print(f"  - {path}: {error.message}")

    if failed:
        print(f"FAILED: checked={checked}, failed={failed}")
        raise SystemExit(1)

    print(f"OK: checked={checked}, failed=0")


if __name__ == "__main__":
    main()
