#!/usr/bin/env python3
import json
import os
import ssl
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, parse, request

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst


CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FPS = 10
CAMERA_SHARPNESS = 35

MOTION_WIDTH = 160
MOTION_HEIGHT = 120
MOTION_FPS = 5

MOTION_HISTORY_SECONDS = 20
PHOTO_HISTORY_SECONDS = 20
PHOTO_HISTORY_FPS = 2
POST_TRIGGER_SETTLE_SECONDS = 0.5
POST_EVENT_SECONDS = 10
EXIT_PHOTO_OFFSET_SECONDS = -0.75
RETURN_PHOTO_OFFSET_SECONDS = 2.5

PIXEL_DIFFERENCE_THRESHOLD = 25
MOTION_PIXEL_RATIO = 0.02
MIN_CONSECUTIVE_MOTION_FRAMES = 3

OUTPUT_DIR = "/app/output"
TRIGGER_TOKEN = os.getenv("PAUSEABLE_TRIGGER_TOKEN", "")
API_URL = os.getenv("PAUSEABLE_API_URL", "").rstrip("/")
DEVICE_TOKEN = os.getenv("PAUSEABLE_DEVICE_TOKEN", "")
DEVICE_ID = os.getenv("PAUSEABLE_DEVICE_ID", "pi4-front-door-01")
PATIENT_ID = os.getenv("PAUSEABLE_PATIENT_ID", "byunwoojin")
SSL_CERT_FILE = os.getenv("SSL_CERT_FILE", "").strip()
SSL_CONTEXT = ssl.create_default_context(
    cafile=SSL_CERT_FILE or None,
)

motion_history = deque(maxlen=MOTION_FPS * MOTION_HISTORY_SECONDS)
recent_photos = deque(maxlen=PHOTO_HISTORY_FPS * PHOTO_HISTORY_SECONDS)

previous_gray = None
last_history_photo_at = 0.0
active_motion_collector = None
active_photo_collector = None
last_result = None

state_lock = threading.Lock()
trigger_lock = threading.Lock()


def pull_bytes(sink):
    sample = sink.emit("pull-sample")
    if sample is None:
        return None

    buffer = sample.get_buffer()
    ok, mapped = buffer.map(Gst.MapFlags.READ)
    if not ok:
        return None

    try:
        return bytes(mapped.data)
    finally:
        buffer.unmap(mapped)


def on_photo_sample(sink):
    global active_photo_collector, last_history_photo_at

    jpeg = pull_bytes(sink)
    if jpeg is None:
        return Gst.FlowReturn.ERROR

    captured_at = time.time()
    with state_lock:
        if captured_at - last_history_photo_at >= 1.0 / PHOTO_HISTORY_FPS:
            recent_photos.append((captured_at, jpeg))
            last_history_photo_at = captured_at
        if active_photo_collector is not None:
            active_photo_collector.append((captured_at, jpeg))

    return Gst.FlowReturn.OK


def on_motion_sample(sink):
    global previous_gray, active_motion_collector

    gray = pull_bytes(sink)
    if gray is None:
        return Gst.FlowReturn.ERROR

    captured_at = time.time()
    if previous_gray is None or len(previous_gray) != len(gray):
        score = 0.0
        moving = False
    else:
        changed_pixels = sum(
            1
            for current, previous in zip(gray, previous_gray)
            if abs(current - previous) >= PIXEL_DIFFERENCE_THRESHOLD
        )
        score = changed_pixels / len(gray)
        moving = score >= MOTION_PIXEL_RATIO

    previous_gray = gray
    motion_sample = (captured_at, score, moving)

    with state_lock:
        motion_history.append(motion_sample)
        if active_motion_collector is not None:
            active_motion_collector.append(motion_sample)

    return Gst.FlowReturn.OK


def longest_motion_run(samples):
    longest = 0
    current = 0
    for _, _, moving in samples:
        if moving:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def movement_summary(samples):
    run = longest_motion_run(samples)
    moving_frames = sum(1 for _, _, moving in samples if moving)
    max_score = max((score for _, score, _ in samples), default=0.0)
    return {
        "samples": len(samples),
        "moving_frames": moving_frames,
        "longest_run": run,
        "max_score": round(max_score, 4),
        "movement": run >= MIN_CONSECUTIVE_MOTION_FRAMES,
    }


def classify(pre_summary, post_summary):
    before = pre_summary["movement"]
    after = post_summary["movement"]


    if before and not after:
        return "EXIT"
    if not before and after:
        return "RETURN"
    if before and after:
        return "UNKNOWN_ACTIVE_BOTH"
    return "NO_PASSAGE"


def strongest_motion_time(samples, fallback):
    if not samples:
        return fallback
    return max(samples, key=lambda item: item[1])[0]


def select_representative_photo(
    decision, triggered_at, pre_photos, post_photos, pre_motion, post_motion
):
    if decision == "EXIT":
        offset = EXIT_PHOTO_OFFSET_SECONDS
        photos = [item for item in pre_photos if item[0] <= triggered_at]
        target_time = triggered_at + offset
        policy = "exit_before_trigger"
    elif decision == "RETURN":
        offset = RETURN_PHOTO_OFFSET_SECONDS
        photos = [item for item in post_photos if item[0] >= triggered_at]
        target_time = triggered_at + offset
        policy = "return_after_trigger"
    else:
        photos = pre_photos + post_photos
        target_time = strongest_motion_time(pre_motion + post_motion, triggered_at)
        offset = target_time - triggered_at
        policy = "strongest_motion_unconfirmed_direction"

    selection = {
        "policy": policy,
        "time_basis": "pi4_trigger_received_at",
        "requested_offset_seconds": round(offset, 4),
    }
    if not photos:
        selection["status"] = "missing"
        return None, selection

    captured_at, jpeg = min(photos, key=lambda item: abs(item[0] - target_time))
    selection.update({
        "status": "selected",
        "captured_at": datetime.fromtimestamp(captured_at, timezone.utc).isoformat(),
        "selected_offset_seconds": round(captured_at - triggered_at, 4),
        "selection_error_seconds": round(abs(captured_at - target_time), 4),
    })
    return jpeg, selection


def encode_multipart(fields, file_field, file_path):
    boundary = f"----pauseable-{int(time.time() * 1000)}"
    chunks = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                ).encode(),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )

    with open(file_path, "rb") as source:
        image_bytes = source.read()
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                'filename="representative.jpg"\r\n'
            ).encode(),
            b"Content-Type: image/jpeg\r\n\r\n",
            image_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def upload_event(metadata):
    if not API_URL:
        return {"status": "disabled", "reason": "PAUSEABLE_API_URL is empty"}

    image_path = os.path.join(
        OUTPUT_DIR,
        metadata["event"],
        "representative.jpg",
    )
    if not os.path.isfile(image_path):
        return {"status": "skipped", "reason": "representative image missing"}

    fields = {
        "event_id": metadata["event"],
        "event_time": metadata["event_time"],
        "decision": metadata["decision"],
        "patient_id": PATIENT_ID,
        "pre_motion": json.dumps(metadata["pre_motion"]),
        "post_motion": json.dumps(metadata["post_motion"]),
    }
    body, content_type = encode_multipart(
        fields,
        "representative",
        image_path,
    )
    url = (
        f"{API_URL}/api/devices/"
        f"{parse.quote(DEVICE_ID, safe='')}/door-events"
    )
    headers = {"Content-Type": content_type}
    if DEVICE_TOKEN:
        headers["Authorization"] = f"Bearer {DEVICE_TOKEN}"

    last_error = None
    for attempt in range(3):
        api_request = request.Request(
            url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(
                api_request,
                timeout=20,
                context=SSL_CONTEXT,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return {
                    "status": payload.get("status", "accepted"),
                    "http_status": response.status,
                }
        except error.HTTPError as api_error:
            details = api_error.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {api_error.code}: {details}"
            if api_error.code not in {429, 500, 502, 503, 504}:
                break
        except (error.URLError, TimeoutError, json.JSONDecodeError) as api_error:
            last_error = str(api_error)

        if attempt < 2:
            time.sleep(2 ** attempt)

    return {"status": "failed", "error": last_error or "unknown error"}


def save_event(triggered_at=None):
    global active_motion_collector, active_photo_collector

    try:
        if triggered_at is None:
            triggered_at = time.time()

        with state_lock:
            pre_motion = [item for item in motion_history if item[0] <= triggered_at]
            pre_photos = [item for item in recent_photos if item[0] <= triggered_at]
            post_motion = []
            post_photos = []
            active_motion_collector = post_motion
            active_photo_collector = post_photos

        time.sleep(POST_EVENT_SECONDS)

        with state_lock:
            active_motion_collector = None
            active_photo_collector = None

        post_motion_for_decision = [
            sample
            for sample in post_motion
            if sample[0] >= triggered_at + POST_TRIGGER_SETTLE_SECONDS
        ]

        pre_summary = movement_summary(pre_motion)
        post_summary = movement_summary(post_motion_for_decision)
        decision = classify(pre_summary, post_summary)

        event_name = datetime.now().strftime("event_%Y%m%d_%H%M%S")
        event_dir = os.path.join(OUTPUT_DIR, event_name)
        os.makedirs(event_dir, exist_ok=True)

        all_photos = [("pre", item) for item in pre_photos]
        all_photos.extend(("post", item) for item in post_photos)
        for index, (phase, (_, jpeg)) in enumerate(all_photos):
            filename = f"{index:03d}_{phase}.jpg"
            with open(os.path.join(event_dir, filename), "wb") as output:
                output.write(jpeg)

        representative, photo_selection = select_representative_photo(
            decision,
            triggered_at,
            pre_photos,
            post_photos,
            pre_motion,
            post_motion_for_decision,
        )

        if representative is not None:
            with open(os.path.join(event_dir, "representative.jpg"), "wb") as output:
                output.write(representative)

        metadata = {
            "event": event_name,
            "event_time": datetime.fromtimestamp(
                triggered_at,
                timezone.utc,
            ).isoformat(),
            "decision": decision,
            "camera_position": "indoor",
            "pre_motion": pre_summary,
            "post_motion": post_summary,
            "pre_photos": len(pre_photos),
            "post_photos": len(post_photos),
            "photo_selection": photo_selection,
        }
        with open(
            os.path.join(event_dir, "result.json"), "w", encoding="utf-8"
        ) as output:
            json.dump(metadata, output, ensure_ascii=False, indent=2)

        return metadata
    finally:
        with state_lock:
            active_motion_collector = None
            active_photo_collector = None


def event_worker(triggered_at):
    global last_result

    try:
        result = save_event(triggered_at)
        result["upload"] = upload_event(result)
        result_path = os.path.join(
            OUTPUT_DIR,
            result["event"],
            "result.json",
        )
        with open(result_path, "w", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
        print(f"event complete: {result['decision']} ({result['event']})", flush=True)
        print(f"photo selection: {json.dumps(result['photo_selection'])}", flush=True)
        print(f"upload result: {result['upload']['status']}", flush=True)
    except Exception as error:
        result = {"status": "error", "error": str(error)}
        print(f"event failed: {error}", flush=True)
    finally:
        with state_lock:
            last_result = result
        trigger_lock.release()


def start_event_capture(triggered_at=None):
    if triggered_at is None:
        triggered_at = time.time()
    if not trigger_lock.acquire(blocking=False):
        return False
    threading.Thread(target=event_worker, args=(triggered_at,), daemon=True).start()
    return True


class RequestHandler(BaseHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            with state_lock:
                buffered_photos = len(recent_photos)
                motion_samples = len(motion_history)
            self.send_json(
                200,
                {
                    "status": "ok",
                    "buffered_photos": buffered_photos,
                    "motion_samples": motion_samples,
                },
            )
            return
        if self.path == "/last-result":
            with state_lock:
                result = last_result
            if result is None:
                self.send_json(200, {"status": "no_result_yet"})
            else:
                self.send_json(200, result)
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        received_at = time.time()
        if self.path != "/trigger":
            self.send_json(404, {"error": "not found"})
            return

        if TRIGGER_TOKEN:
            expected = f"Bearer {TRIGGER_TOKEN}"
            if self.headers.get("Authorization") != expected:
                self.send_json(401, {"error": "unauthorized"})
                return

        if not start_event_capture(received_at):
            self.send_json(409, {"error": "event capture already running"})
            return
        self.send_json(202, {"status": "accepted"})

    def log_message(self, format_, *args):
        print(f"http: {format_ % args}", flush=True)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    Gst.init(None)

    pipeline = Gst.parse_launch(
        "v4l2src name=camera_source device=/dev/video0 ! "
        f"video/x-raw,format=YUY2,width={CAMERA_WIDTH},height={CAMERA_HEIGHT},framerate={CAMERA_FPS}/1 ! "
        "tee name=t "
        "t. ! queue max-size-buffers=2 leaky=downstream ! "
        "videoconvert ! videoflip video-direction=90l ! "


        "videobox left=-792 right=-792 top=-8 bottom=-8 ! "
        "video/x-raw,pixel-aspect-ratio=1/1 ! "
        "jpegenc quality=95 ! "
        "appsink name=photo_sink emit-signals=true max-buffers=1 drop=true sync=false "
        "t. ! queue max-size-buffers=2 leaky=downstream ! "
        "videoconvert ! videoscale ! videorate ! "
        f"video/x-raw,format=GRAY8,width={MOTION_WIDTH},height={MOTION_HEIGHT},framerate={MOTION_FPS}/1 ! "
        "appsink name=motion_sink emit-signals=true max-buffers=1 drop=true sync=false"
    )

    camera_source = pipeline.get_by_name("camera_source")
    camera_source.set_property(
        "extra-controls",
        Gst.Structure.new_from_string(f"controls,sharpness=(int){CAMERA_SHARPNESS}"),
    )

    photo_sink = pipeline.get_by_name("photo_sink")
    motion_sink = pipeline.get_by_name("motion_sink")
    photo_sink.connect("new-sample", on_photo_sample)
    motion_sink.connect("new-sample", on_motion_sample)

    server = ThreadingHTTPServer(("0.0.0.0", 8080), RequestHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    pipeline.set_state(Gst.State.PLAYING)
    print("camera ready: 1280x720 @ 10 fps", flush=True)
    print(f"camera sharpness: {CAMERA_SHARPNESS} (LifeCam range 0-50)", flush=True)
    print("motion detector: 160x120 @ 5 fps, 20-second history", flush=True)
    print("photo history: 720x1280 portrait on 2304x1296 canvas @ 2 fps, 20-second history, rotation=counterclockwise", flush=True)
    print("indoor logic: pre-only=EXIT, post-only=RETURN", flush=True)
    print(
        f"photo timing: EXIT={EXIT_PHOTO_OFFSET_SECONDS:+.2f}s, "
        f"RETURN={RETURN_PHOTO_OFFSET_SECONDS:+.2f}s from trigger receipt", flush=True
    )
    if TRIGGER_TOKEN:
        print("trigger authentication: enabled", flush=True)
    else:
        print("WARNING: trigger authentication is disabled", flush=True)
    if API_URL:
        print(f"result upload: {API_URL} ({DEVICE_ID})", flush=True)
    else:
        print("result upload: disabled (PAUSEABLE_API_URL is empty)", flush=True)

    loop = GLib.MainLoop()
    try:
        loop.run()
    finally:
        server.shutdown()
        pipeline.set_state(Gst.State.NULL)


if __name__ == "__main__":
    main()
