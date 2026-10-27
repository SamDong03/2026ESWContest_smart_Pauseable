# Memolink 개인화 음성 학습

[AI 구성](../README.md) · [Worker 운영](../../Pauseable.docs/voice/OPERATIONS_KO.md) · [데이터 정책](../../Pauseable.docs/voice/DATA_AND_ARTIFACTS_KO.md) · [Pi 모델 적용](../../Pauseable.edge/README.md#음성-모델-교체)

보호자가 동의하고 녹음한 WAV와 대본으로 Piper 음성 모델을 학습합니다. GPU Worker가 작업을 처리하고, Pi는 검증된 ONNX를 내려받아 로컬 TTS에 사용합니다. HA의 IF·AE 학습과는 별도 파이프라인입니다.

## 입력과 산출물

| 단계 | 자료·형식 |
| --- | --- |
| 앱 수집 | 현재 160문장, WAV 16 kHz·mono·PCM16 |
| Worker 입력 | 160~240개 WAV, 대응 `recording_script.csv`, 동의·작업 정보 |
| 학습 전처리 | mono·22,050 Hz·PCM16로 변환 |
| 학습·Export | Piper fine-tuning, ONNX·Piper JSON |
| 게시 | manifest·status·샘플 WAV·로그와 검증한 모델 |
| Pi 적용 | 크기·SHA-256·설정·로컬 합성 검사 후 교체 |

## 주요 코드

| 파일 | 역할 |
| --- | --- |
| [pipeline/r2_worker.py](pipeline/r2_worker.py) | 작업 임대·다운로드·검사·학습·업로드 |
| [pipeline/prepare_dataset.py](pipeline/prepare_dataset.py) | 대본·WAV 검사와 데이터 준비 |
| [scripts/preprocess.py](scripts/preprocess.py) | 학습용 음성 형식 변환 |
| [train_voice_model.sh](train_voice_model.sh) | Docker 학습 실행 |
| [pipeline/publish_voice_model.py](pipeline/publish_voice_model.py) | 기존 검증 ONNX 게시 |
| [docker/Dockerfile.train](docker/Dockerfile.train) | Python 3.11·Piper·PyTorch 학습 환경 |
| [worker.env.example](worker.env.example) | API·Worker 인증·작업 경로 예시 |

## 검사와 운영

별도 Python 3.11 가상환경에서 저장소 루트 기준으로 실행합니다.

```sh
cd Pauseable.ai/voice
python -m pip install -r requirements.worker.txt
python -m unittest discover -s pipeline -p 'test_*.py' -v
```

실제 학습 전에는 [Worker의 dry-run](../../Pauseable.docs/voice/OPERATIONS_KO.md#3-설치와-사전-점검)으로 자료를 검사합니다. GPU·Driver·Docker 설정, 실제 Worker 실행과 systemd 등록은 같은 운영 문서를 따릅니다. 단위시험은 실제 GPU 학습·게시·Pi 음성 출력을 수행한 결과와 구분합니다.

원본 녹음·checkpoint·개인화 모델·Token을 Git에 넣지 않습니다. [Piper 출처와 버전](provenance), [외부 저작권 고지](../../Pauseable.third_party/NOTICE.txt)를 함께 확인합니다.
