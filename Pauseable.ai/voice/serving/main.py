

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


AUDIO_DIR = Path(
    os.getenv(
        "TTS_AUDIO_DIR",
        str(Path(__file__).resolve().parent / "generated-audio"),
    ),
)
PUBLIC_TTS_BASE_URL = os.getenv("PUBLIC_TTS_BASE_URL", "").rstrip("/")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Pauseable Development TTS API",
    version="0.1.0",
    description="학습 음성 모델 연결 전 통신 검증에 사용하는 eSpeak NG 기반 임시 TTS 서버",
)


class VoiceRequest(BaseModel):
    request_id: str = Field(min_length=1)
    occurred_at: datetime
    situation: str = Field(min_length=1)
    voice_profile_id: str | None = None
    message_candidates: list[str] = Field(min_length=1)


class VoiceResult(BaseModel):
    request_id: str
    status: Literal["completed", "failed"]
    audio_url: str | None = None
    selected_message: str | None = None
    error: str | None = None


def _synthesize_to_file(message: str, output_path: Path) -> None:
    executable = shutil.which("espeak-ng")
    if executable is None:
        raise HTTPException(
            status_code=503,
            detail="espeak-ng is not installed on the TTS host",
        )

    try:
        subprocess.run(
            [executable, "-v", "ko", "-s", "155", "-w", str(output_path), message],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (subprocess.SubprocessError, OSError) as error:
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {error}") from error


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "engine": "espeak-ng",
        "engine_available": shutil.which("espeak-ng") is not None,
    }


@app.post("/api/tts", response_model=VoiceResult)
def synthesize_voice(payload: VoiceRequest, request: Request) -> VoiceResult:
    selected_message = payload.message_candidates[0].strip()
    if not selected_message:
        raise HTTPException(status_code=422, detail="TTS message must not be empty")

    filename = f"{uuid4().hex}.wav"
    output_path = AUDIO_DIR / filename
    _synthesize_to_file(selected_message, output_path)

    audio_url = (
        f"{PUBLIC_TTS_BASE_URL}/audio/{filename}"
        if PUBLIC_TTS_BASE_URL
        else str(request.url_for("get_audio", filename=filename))
    )
    return VoiceResult(
        request_id=payload.request_id,
        status="completed",
        audio_url=audio_url,
        selected_message=selected_message,
    )


@app.get("/audio/{filename}", name="get_audio")
def get_audio(filename: str) -> FileResponse:
    if Path(filename).name != filename or not filename.endswith(".wav"):
        raise HTTPException(status_code=404, detail="Audio file not found")

    audio_path = (AUDIO_DIR / filename).resolve()
    if AUDIO_DIR.resolve() not in audio_path.parents or not audio_path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(audio_path, media_type="audio/wav", filename=filename)
