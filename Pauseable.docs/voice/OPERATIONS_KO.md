# GPU Voice Training Worker 운영 가이드

이 문서는 `pipeline/r2_worker.py`를 운영 GPU PC에서 실행하는 방법과 장애 발생 시 확인 순서를 설명합니다.

## 1. 동작 흐름

1. Worker가 Render API에서 대기 중인 작업을 임대합니다.
2. Render가 발급한 presigned URL로 R2의 WAV와 대본을 내려받습니다.
3. 입력 파일 개수, 이름, WAV 포맷 및 metadata 행을 검증합니다.
4. `train_voice_model.sh`가 Docker 학습 파이프라인을 실행합니다.
5. ONNX·JSON·manifest·샘플 WAV를 검증합니다.
6. 결과 파일을 R2에 업로드하고 Render에 완료 상태를 기록합니다.

Worker는 프로세스 잠금을 사용하므로 같은 `PAUSEABLE_WORK_ROOT`에서 두 인스턴스가 동시에 작업하지 않습니다.

## 2. 환경 변수

`worker.env.example`을 복사해 Git에 추적되지 않는 `worker.env`를 만듭니다.

| 변수 | 필수 | 설명 |
|---|---:|---|
| `PAUSEABLE_API_URL` | 예 | Render API base URL, 끝의 `/` 제외 |
| `PAUSEABLE_WORKER_TOKEN` | 예 | GPU Worker 전용 인증 토큰 |
| `PAUSEABLE_WORKER_ID` | 예 | GPU PC를 구분하는 안정적인 ID |
| `PAUSEABLE_WORK_ROOT` | 아니요 | 다운로드·잠금·임시 작업 루트 |
| `PAUSEABLE_TRAINING_OUTPUT_ROOT` | 아니요 | 학습 결과 루트 |
| `PAUSEABLE_WORKER_POLL_SECONDS` | 아니요 | 작업 조회 주기, 기본 30초 |
| `PAUSEABLE_WORKER_LEASE_SECONDS` | 아니요 | 작업 임대 시간, 기본 300초 |
| `PAUSEABLE_WORKER_HEARTBEAT_SECONDS` | 아니요 | 임대 갱신 주기, 기본 60초 |

`PAUSEABLE_WORKER_HEARTBEAT_SECONDS`는 lease보다 짧아야 합니다.

## 3. 설치와 사전 점검

```bash
cd Pauseable.ai/voice
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.worker.txt
docker compose build trainer
docker compose run --rm trainer nvidia-smi
```

실데이터를 사용하기 전 dry-run으로 입력만 검사합니다.

```bash
python pipeline/r2_worker.py \
  --dry-run \
  --dataset-dir /path/to/wav-directory \
  --metadata-file /path/to/recording_script.csv
```

## 4. 실행 모드

한 작업만 처리하고 종료:

```bash
set -a
. ./worker.env
set +a
python pipeline/r2_worker.py --once
```

계속 대기하며 처리:

```bash
set -a
. ./worker.env
set +a
python pipeline/r2_worker.py
```

## 5. systemd user service

저장소의 unit은 `$HOME/Pauseable`와 `$HOME/Pauseable/Pauseable.ai/voice/.venv`를 기준으로 합니다. 다른 위치를 사용하면 설치 전에 unit의 경로를 수정합니다.

```bash
mkdir -p ~/.config/systemd/user ~/.config/pauseable
install -m 600 worker.env ~/.config/pauseable/voice-worker.env
install -m 644 ../../Pauseable.deploy/gpu/voice-worker/pauseable-voice-training-worker.service \
  ~/.config/systemd/user/pauseable-voice-training-worker.service
systemctl --user daemon-reload
systemctl --user enable --now pauseable-voice-training-worker.service
```

상태와 로그 확인:

```bash
systemctl --user status pauseable-voice-training-worker.service
journalctl --user -u pauseable-voice-training-worker.service -n 100 --no-pager
```

로그를 공유하기 전에 토큰, presigned URL, 환자 식별 정보가 없는지 확인합니다.

## 6. 기존 ONNX 게시

재학습 없이 검증된 ONNX를 R2에 게시할 때만 다음 도구를 사용합니다.

```bash
set -a
. ./worker.env
set +a
python pipeline/publish_voice_model.py \
  --patient-id patient-001 \
  --version 2026.10.23.1 \
  --onnx /secure/path/ko_KR-guardian-medium.onnx \
  --config /secure/path/ko_KR-guardian-medium.onnx.json
```

이 도구는 로컬 해시를 계산하고, Render의 업로드 계획을 받아 R2로 전송한 뒤 서버 검증이 끝난 모델만 최신 버전으로 공개합니다.

## 7. 장애 확인 순서

| 증상 | 확인 항목 | 안전한 조치 |
|---|---|---|
| Worker 시작 실패 | 필수 환경 변수, 디렉터리 권한 | `worker.env.example`과 변수 이름 비교 |
| 작업을 가져오지 못함 | Render 상태, Worker Token 종류 | App/Device Token이 아닌 Worker Token 사용 |
| 다운로드 실패 | presigned URL 만료, 시스템 시각 | 새 작업 임대를 받고 PC 시각 동기화 |
| dry-run 실패 | 파일 수, `S001.wav` 형식, metadata | 원본을 보존하고 복사본을 수정 |
| Docker GPU 실패 | NVIDIA driver, toolkit | `docker compose run --rm trainer nvidia-smi` 재확인 |
| 학습 중 실패 | `status.json`, `training.log`, 디스크 용량 | 실패 단계부터 원인 분석; 결과를 완료로 게시하지 않음 |
| 게시 실패 | 결과 파일 크기·해시, R2 연결 | 로컬 결과를 보존하고 게시 단계만 재시도 |

실패한 작업의 임시 파일을 즉시 삭제하지 마십시오. `status.json`, `manifest.json`, 로그는 원인 분석과 재현에 필요합니다.
