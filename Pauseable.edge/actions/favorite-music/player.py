#!/usr/bin/env python3
"""Request one saved favorite after approved guidance; never emit safety events."""

from __future__ import annotations

import json
import math
import os
import re
import stat
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
PATIENT_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
DEFAULT_API = "https://pauseable-api.onrender.com"
DEFAULT_FIFO = "/run/pauseable-youtube-request.fifo"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        # Do not forward a device bearer credential to a redirect destination.
        return None


def fetch_random_song(base_url, patient_id, device_token, *, timeout=30, opener=None):
    parsed = urlsplit(base_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("invalid_api_configuration")
    if not PATIENT_ID.fullmatch(patient_id) or not device_token.strip():
        raise ValueError("invalid_device_configuration")
    request = Request(
        f"{base_url.rstrip('/')}/api/device/patients/{quote(patient_id, safe='')}/favorite-songs/random",
        headers={"Authorization": f"Bearer {device_token}", "Accept": "application/json"},
    )
    with (opener or build_opener(NoRedirect())).open(request, timeout=timeout) as response:
        data = response.read(16385)
    if len(data) > 16384:
        raise ValueError("invalid_song_response")
    song = json.loads(data)
    if not isinstance(song, dict):
        raise ValueError("invalid_song_response")
    video_id = song.get("video_id")
    if not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id):
        raise ValueError("invalid_video_id")
    if song.get("url") != f"https://www.youtube.com/watch?v={video_id}":
        raise ValueError("invalid_video_url")
    # The API selects from this patient's current list on EACH request. No cache,
    # downloaded audio, arbitrary URL, or built-in demo song is used as fallback.
    return video_id


def play_atlas(video_id, fifo=DEFAULT_FIFO):
    if not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id):
        raise ValueError("invalid_video_id")
    path = Path(fifo)
    if not stat.S_ISFIFO(path.lstat().st_mode):
        raise ValueError("invalid_player_fifo")
    flags = os.O_WRONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISFIFO(os.fstat(descriptor).st_mode):
            raise ValueError("invalid_player_fifo")
        message = f"PLAY_VIDEO {video_id}\n".encode("ascii")
        if os.write(descriptor, message) != len(message):
            raise OSError("incomplete_player_request")
    finally:
        os.close(descriptor)


def cooldown_seconds(environment):
    seconds = float(environment.get("PAUSEABLE_MUSIC_COOLDOWN_SECONDS", "300"))
    if not math.isfinite(seconds) or not 0 <= seconds <= 86400:
        raise ValueError("invalid_cooldown")
    return seconds


def request_playback(environment, state_dir, *, now=None, fetch=None, atlas=None):
    """Called under the service lock. A music failure never fails alert delivery."""
    if environment.get("PAUSEABLE_FAVORITE_MUSIC_ENABLED", "1") != "1":
        print("FAVORITE_MUSIC_SKIPPED reason=disabled", flush=True)
        return
    backend = "atlas"
    patient = environment.get("PATIENT_ID", "byunwoojin")
    timestamp = time.time() if now is None else now
    marker = Path(state_dir) / "last-request.json"
    cooldown = cooldown_seconds(environment)
    if marker.exists():
        previous = json.loads(marker.read_text(encoding="utf-8"))
        last = float(previous["requested_at"])
        if not math.isfinite(last):
            raise ValueError("invalid_cooldown_state")
        if (previous.get("patient_id") == patient and previous.get("backend") == backend
                and timestamp - last < cooldown):
            print("FAVORITE_MUSIC_SKIPPED reason=cooldown", flush=True)
            return
    try:
        video_id = (fetch or fetch_random_song)(
            environment.get("PAUSEABLE_API_BASE_URL", DEFAULT_API),
            patient, environment.get("PAUSEABLE_DEVICE_TOKEN", ""),
        )
    except HTTPError as error:
        reason = "no_saved_songs_or_patient" if error.code == 404 else "api_http_error"
        print(f"FAVORITE_MUSIC_SKIPPED reason={reason} status={error.code}", flush=True)
        return
    if not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id):
        raise ValueError("invalid_video_id")
    (atlas or play_atlas)(video_id, environment.get("PAUSEABLE_YOUTUBE_FIFO", DEFAULT_FIFO))
    # Only successful player requests consume the cooldown. This is NOT a claim
    # that YouTube displayed/played the video (ads, login and network still apply).
    payload = {"patient_id": patient, "backend": backend, "requested_at": timestamp}
    descriptor, temporary = tempfile.mkstemp(prefix="last-request-", dir=state_dir)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output)
        os.replace(temporary, marker)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print(f"FAVORITE_MUSIC_REQUESTED backend={backend} video_id={video_id}", flush=True)


def main():
    if os.getenv("PAUSEABLE_FAVORITE_MUSIC_ENABLED", "1") != "1":
        print("FAVORITE_MUSIC_SKIPPED reason=disabled", flush=True)
        return 0
    try:
        import fcntl  # Linux device only; serialize direct and service requests.

        state = Path(os.getenv("PAUSEABLE_MUSIC_STATE_DIR", "/state"))
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (state / "player.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("FAVORITE_MUSIC_SKIPPED reason=busy", flush=True)
                return 0
            request_playback(os.environ, state)
    except Exception:
        # Never log exception text: it may contain bearer tokens, HA credentials,
        # private URLs or HTTP response bodies. No fallback to an unrelated song.
        print("FAVORITE_MUSIC_SKIPPED reason=configuration_network_or_player", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
