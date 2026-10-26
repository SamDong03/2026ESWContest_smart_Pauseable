
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def source_manifest():
    paths = [*BASE.glob("Dockerfile*"), BASE / "requirements.txt", *BASE.glob("compose*.yaml")]
    for folder in ("src", "tests", "deploy", "scripts"):
        paths.extend(p for p in (BASE / folder).rglob("*")
                     if p.is_file() and p.suffix in {".py", ".json", ".sh", ".awk", ".service", ".example"})
    return {str(p.relative_to(BASE)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(paths)) if p.is_file()}


def run(output_dir, minder_zip=None):
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Use a new empty output directory; previous checks must be preserved")
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
              "architecture": platform.machine(), "local_checks_passed": False,
              "clinical_validation": False, "production_eligible": False,
              "external_checks": {"pi_arm64": "not_run", "physical_appliance_events": "not_run",
                                  "mqtt_central_tts_appliances": "not_run",
                                  "deployed_backend_flutter": "not_run"},
              "checks": []}
    write_json(output / "source_manifest.json", source_manifest())
    write_json(output / "submission_report.json", report)
    steps = [
        ("unit_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]),
        ("month_train", [sys.executable, "src/verify_ha_month_cycle.py", "--phase", "train",
                         "--output-dir", str(output / "month")]),
        ("month_verify", [sys.executable, "src/verify_ha_month_cycle.py", "--phase", "verify",
                          "--output-dir", str(output / "month")]),
        ("month_refresh", [sys.executable, "src/verify_ha_month_cycle.py", "--phase", "refresh",
                           "--output-dir", str(output / "month")]),
        ("fridge_five_minute", [sys.executable, "src/verify_ha_behavior_cases.py",
                                "--month-dir", str(output / "month"), "--output-dir", str(output / "fridge")]),
        ("personalization", [sys.executable, "src/verify_ha_personalization.py",
                             "--output-dir", str(output / "personalization")]),
        ("evidence", [sys.executable, "src/run_ha_evidence_research.py",
                      "--output-dir", str(output / "evidence"), "--seeds", "47", "89"]),
    ]
    if minder_zip:
        steps[-1][1].extend(["--minder-zip", str(Path(minder_zip).resolve())])
    for name, command in steps:
        began = time.monotonic()
        print(f"SUBMISSION_CHECK_STARTED {name}", flush=True)
        try:
            with (output / f"{name}.log").open("w", encoding="utf-8") as stream:
                result = subprocess.run(command, cwd=BASE, stdout=stream, stderr=subprocess.STDOUT,
                                        timeout=1800, check=False)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
        check = {"name": name, "command": command, "exit_code": code,
                 "seconds": round(time.monotonic() - began, 3), "log": f"{name}.log"}
        report["checks"].append(check)
        write_json(output / "submission_report.json", report)
        print(json.dumps(check), flush=True)
        if code != 0:
            return report
    evidence = json.loads((output / "evidence/report.json").read_text(encoding="utf-8"))
    month = [json.loads((output / f"month/{phase}_report.json").read_text(encoding="utf-8"))
             for phase in ("train", "verify", "refresh")]
    report["local_checks_passed"] = bool(
        all(item["passed"] for item in month) and evidence["completed"]
        and evidence["all_pair_features_identical"] and evidence["optimizer_converged"])
    report["evidence_cases"] = evidence["cases"]
    report["personalization"] = json.loads((output / 'personalization/report.json').read_text())
    report["local_checks_passed"] &= report["personalization"]["passed"]
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json(output / "submission_report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--minder-zip")
    args = parser.parse_args()
    report = run(args.output_dir, args.minder_zip)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    raise SystemExit(0 if report["local_checks_passed"] else 1)


if __name__ == "__main__":
    main()
