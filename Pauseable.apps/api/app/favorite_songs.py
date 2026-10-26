

import json
import os
import re
import secrets
import uuid
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException

from app.r2_storage import R2Storage


SONGS_DIR = Path(__file__).resolve().parent / "data" / "favorite_songs"
VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
_lock = Lock()


def canonical_video_url(raw_url: str) -> tuple[str, str]:
    try:
        parsed = urlparse(raw_url.strip())
        host = (parsed.hostname or "").lower()
        has_credentials_or_port = bool(parsed.username or parsed.password or parsed.port)
    except ValueError:
        raise HTTPException(422, "Enter a valid YouTube video URL") from None
    if parsed.scheme not in {"http", "https"} or has_credentials_or_port:
        raise HTTPException(422, "Enter a valid YouTube video URL")
    if host == "youtu.be":
        video_id = parsed.path.removeprefix("/")
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            values = parse_qs(parsed.query).get("v", [])
            video_id = values[0] if len(values) == 1 else ""
        elif parsed.path.startswith(("/shorts/", "/live/")):
            video_id = parsed.path.split("/")[2]
        else:
            video_id = ""
    else:
        video_id = ""
    if not VIDEO_ID_PATTERN.fullmatch(video_id):
        raise HTTPException(422, "Enter a YouTube video link, not a playlist or channel")
    return video_id, f"https://www.youtube.com/watch?v={video_id}"


def _key(patient_id: str) -> str:
    return f"patients/{patient_id}/favorite-songs.json"


def _path(patient_id: str) -> Path:
    return SONGS_DIR / f"{patient_id}.json"


def load_songs(patient_id: str, storage_backend: str) -> list[dict[str, str]]:
    if storage_backend == "r2":
        payload = R2Storage.from_environment().get_json(_key(patient_id))
    else:
        path = _path(patient_id)
        payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    return list(payload["songs"]) if payload else []


def save_songs(patient_id: str, songs: list[dict[str, str]], storage_backend: str) -> list[dict[str, str]]:
    if len(songs) > 30:
        raise HTTPException(422, "You can save up to 30 songs")
    normalized = []
    seen = set()
    for song in songs:
        title = song["title"].strip()
        if not title or len(title) > 80:
            raise HTTPException(422, "Song title must be 1–80 characters")
        video_id, url = canonical_video_url(song["url"])
        if video_id in seen:
            raise HTTPException(422, "Duplicate YouTube video")
        seen.add(video_id)
        normalized.append({"video_id": video_id, "title": title, "url": url})

    payload = {"patient_id": patient_id, "songs": normalized}
    if storage_backend == "r2":
        R2Storage.from_environment().put_json(_key(patient_id), payload)
    else:
        path = _path(patient_id)
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
    return normalized


def choose_song(patient_id: str, storage_backend: str) -> dict[str, str]:
    songs = load_songs(patient_id, storage_backend)
    if not songs:
        raise HTTPException(404, "No favorite songs have been saved")
    return secrets.choice(songs)
