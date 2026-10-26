
import argparse
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

READY = b"PAUSEABLE_FIFO_READY"
REMOTE_COMMAND = (
    "test -p /run/pauseable-wandering-input.fifo || exit 20; "
    "exec 3>/run/pauseable-wandering-input.fifo; "
    "printf 'PAUSEABLE_FIFO_READY\\n' >&2; exec cat >&3"
)


def announce(status, **values):
    print(json.dumps({"supervisor": status, **values}), flush=True)


def wait_ready(process, timeout, stopping):
    deadline = time.monotonic() + timeout
    buffer = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(process.stderr, selectors.EVENT_READ)
        while time.monotonic() < deadline and not stopping():
            for key, _ in selector.select(0.2):
                data = os.read(key.fd, 4096)
                if not data:
                    raise RuntimeError("SSH closed before the FIFO reader became ready")
                buffer.extend(data)
                if len(buffer) > 16384:
                    raise RuntimeError("Unexpected SSH output before readiness")
                while b"\n" in buffer:
                    line, _, rest = buffer.partition(b"\n")
                    buffer = bytearray(rest)
                    if line.rstrip(b"\r") == READY:
                        return


            if process.poll() is not None:
                raise RuntimeError("SSH failed before readiness")
    raise RuntimeError("Pi5 FIFO reader did not become ready before timeout")


def stop_children(relay, ssh):
    if relay is not None and relay.poll() is None:
        relay.send_signal(signal.SIGINT)
        try:
            relay.wait(timeout=3)
        except subprocess.TimeoutExpired:
            relay.kill()
            relay.wait(timeout=2)
    if ssh is not None:
        if ssh.stdin and not ssh.stdin.closed:
            ssh.stdin.close()
        if ssh.poll() is None:
            ssh.terminate()
            try:
                ssh.wait(timeout=3)
            except subprocess.TimeoutExpired:
                ssh.kill()
                ssh.wait(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.123.102")
    parser.add_argument("--device", default="/dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=230400)
    parser.add_argument("--record-dir", type=Path, default=Path("/var/lib/pauseable-mmwave-relay/captures"))
    args = parser.parse_args()
    if not args.host or any(c not in "0123456789." for c in args.host):
        parser.error("--host must be an IPv4 address")
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    relay = ssh = None
    try:
        ssh = subprocess.Popen([
            "/usr/bin/ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=3",
            "root@" + args.host, REMOTE_COMMAND,
        ], stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
        wait_ready(ssh, 30, lambda: stopping)
        if stopping:
            return 0


        relay = subprocess.Popen([
            sys.executable, "-u", str(Path(__file__).with_name("relay_serial.py")),
            "--device", args.device, "--baud", str(args.baud),
            "--udp-host", args.host, "--record-dir", str(args.record_dir),
        ], stdout=ssh.stdin)
        ssh.stdin.close()
        announce("CONNECTED", host=args.host, baud=args.baud)

        with selectors.DefaultSelector() as selector:
            selector.register(ssh.stderr, selectors.EVENT_READ)
            while not stopping:
                if relay.poll() is not None or ssh.poll() is not None:
                    announce("RECONNECT_REQUIRED", relay_exit=relay.poll(), ssh_exit=ssh.poll())
                    return 1
                for key, _ in selector.select(0.2):
                    if not os.read(key.fd, 4096):
                        selector.unregister(key.fileobj)
        return 0
    except (OSError, RuntimeError) as error:
        announce("RECONNECT_REQUIRED", reason=str(error))
        return 0 if stopping else 1
    finally:
        stop_children(relay, ssh)
        announce("STOPPED")


if __name__ == "__main__":
    raise SystemExit(main())
