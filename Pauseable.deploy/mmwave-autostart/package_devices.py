import argparse
import gzip
import hashlib
import io
from pathlib import Path
import tarfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
COMMON = ("Pauseable.contracts", "Pauseable.deploy/migration", "Pauseable.docs/DEPLOYMENT_HANDOFF.txt")
COMPONENTS = {
    "pi3": ("Pauseable.edge/mmwave-relay", "Pauseable.deploy/mmwave-autostart/pi3", *COMMON),
    "pi4": ("Pauseable.edge/camera", "Pauseable.docs/DEPLOYMENT_HANDOFF.txt", "Pauseable.deploy/migration"),
    "pi5": (
        "Pauseable.edge/central", "Pauseable.edge/voice-model", "Pauseable.edge/actions", "Pauseable.edge/mmwave-relay",
        "Pauseable.ai/mmwave", "Pauseable.ai/ha", "Pauseable.ai/voice/serving", "Pauseable.apps/api",
        "Pauseable.integrations/home-assistant", "Pauseable.third_party/nlohmann",
        "Pauseable.deploy/pi5", "Pauseable.deploy/mmwave-autostart/pi5",
        ".dockerignore", *COMMON,
    ),
}


def canonical_payload(source):
    payload = source.read_bytes()
    if source.suffix.lower() in {".png", ".pdf", ".pptx", ".joblib", ".patch", ".csv"}:
        return payload
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload
    return payload.replace(b"\r\n", b"\n")


def source_manifest():
    rows = []
    for line in (HERE / "FILES.sha256").read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        expected, name = line.split("  ", 1)
        source = REPO / name
        if not source.resolve().is_relative_to(REPO.resolve()):
            raise ValueError("Source manifest path escaped the repository")
        rows.append((expected, name, source))
    return rows


def source_files(device):
    selected = {}
    for expected, name, source in source_manifest():
        if not any(name == prefix or name.startswith(prefix + "/") for prefix in COMPONENTS[device]):
            continue
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"Required deployment input is missing or linked: {name}")
        if source.name.endswith(".env") or (source.name.startswith(".env.") and not source.name.endswith("example")):
            continue
        if hashlib.sha256(canonical_payload(source)).hexdigest() != expected:
            raise ValueError(f"Source checksum mismatch: {name}")
        selected[name] = source
    if not selected:
        raise ValueError(f"No declared deployment inputs for {device}")
    return dict(sorted(selected.items()))


def verify_source_manifest():
    rows = source_manifest()
    for expected, name, source in rows:
        if hashlib.sha256(canonical_payload(source)).hexdigest() != expected:
            raise ValueError(f"Source checksum mismatch: {name}")
    print(f"SOURCE_MANIFEST_OK files={len(rows)}")


def add_payload(bundle, name, payload, executable=False):
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = 0o755 if executable else 0o644
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    bundle.addfile(info, io.BytesIO(payload))


def package_device(device, output):
    selected = source_files(device)
    prefix = "pauseable-" + device
    archive = output / (prefix + ".tar.gz")
    checks = []
    with archive.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as bundle:
                for name, source in selected.items():
                    payload = canonical_payload(source)
                    add_payload(bundle, prefix + "/" + name, payload, source.suffix == ".sh")
                    checks.append(hashlib.sha256(payload).hexdigest() + "  " + name)
                add_payload(bundle, prefix + "/BUNDLE.sha256", ("\n".join(checks) + "\n").encode())
    print(f"{archive} files={len(selected)}")
    print("SHA256=" + hashlib.sha256(archive.read_bytes()).hexdigest())
    return archive


def main():
    parser = argparse.ArgumentParser(description="Build separate Pi3, Pi4 and Pi5 source deployment bundles.")
    parser.add_argument("--output", type=Path, default=HERE / "dist")
    parser.add_argument("--verify-source-manifest", action="store_true")
    args = parser.parse_args()
    if args.verify_source_manifest:
        verify_source_manifest()
        return
    args.output.mkdir(parents=True, exist_ok=True)
    for device in COMPONENTS:
        package_device(device, args.output)


if __name__ == "__main__":
    main()
