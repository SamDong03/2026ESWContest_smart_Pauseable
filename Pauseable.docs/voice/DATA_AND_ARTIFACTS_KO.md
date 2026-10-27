# Voice 데이터와 산출물 정책

## 1. 입력 데이터 계약

학습 세트는 160~240개의 WAV와 대응하는 `recording_script.csv`로 구성합니다. 앱은 16 kHz·mono·PCM 16-bit WAV를 수집하고, 전처리에서 아래 학습용 형식으로 변환합니다.

| 항목 | 학습용 전처리 결과 |
|---|---|
| 파일명 | `S001.wav`부터 연속된 번호 |
| 채널 | mono |
| sample rate | 22,050 Hz |
| sample subtype | PCM 16-bit |
| metadata 구분자 | `|` |
| metadata 행 | WAV와 1:1 대응 |

기본값은 [학습 설정](../../Pauseable.ai/voice/configs/guardian-medium-v1.json)에 정의되어 있으며, 현재 앱 고정 대본은 160문장입니다. [전처리 코드](../../Pauseable.ai/voice/scripts/preprocess.py)는 원본의 sample rate·채널·길이와 변환 결과를 기록합니다.

## 2. 처리 단계

```text
원본 WAV
  -> 무결성·파일명·metadata 검사
  -> mono·22,050 Hz·PCM 16-bit 변환
  -> Piper용 dataset 생성
  -> base checkpoint fine-tuning
  -> latest last.ckpt 선택
  -> ONNX export
  -> 샘플 문장 추론
  -> 결과 패키지 검증
  -> R2 게시
```

동일한 입력과 설정으로 이미 완전한 결과가 존재하면 manifest의 해시를 비교해 잘못된 결과 재사용을 막습니다.

## 3. 결과 패키지

| 파일 | 필수 | 내용 |
|---|---:|---|
| `model.onnx` | 예 | Pi5에서 실행할 신경망 |
| `model.onnx.json` | 예 | Piper 음성 설정 |
| `manifest.json` | 예 | 입력·설정·산출물 해시, pipeline 및 image 정보 |
| `status.json` | 예 | 단계, 생성·갱신 시각, 실패 정보 |
| `test.wav` | 예 | 지정 문장으로 만든 smoke-test 음성 |
| `training.log` | 예 | 학습 표준 출력과 종료 코드 |

완료 판정은 파일 존재만으로 하지 않습니다. 파일이 비어 있지 않아야 하며, JSON 파싱과 입력·설정 해시 비교를 통과해야 합니다.

## 4. 저장 위치

| 데이터 | 저장 위치 | Git 추적 |
|---|---|---:|
| Python·Shell·Docker 설정 | 이 저장소 | 예 |
| Piper upstream source와 provenance | 이 저장소 | 예 |
| 원본 보호자 WAV | 비공개 R2 / Worker 임시 공간 | 아니요 |
| checkpoint·cache·logs | GPU PC 로컬 작업 공간 | 아니요 |
| ONNX·JSON·manifest·test WAV | 비공개 R2 / Pi5 런타임 | 아니요 |
| API·Worker·Device Token | 비밀 환경 파일/호스팅 설정 | 아니요 |

최상위 `GPU-Server/piper-guardian`에 저장되던 ARM 바이너리, eSpeak 데이터와 개인화 ONNX는 생성·배포 산출물이므로 현재 소스 트리에는 포함하지 않습니다. 이미 배포된 Pi5 런타임은 이 정리로 변경되지 않습니다.

## 5. 개인정보와 보안

- 음성 원본과 개인화 모델은 환자를 식별할 수 있는 민감 데이터로 취급합니다.
- 공개 URL 대신 만료 시간이 짧은 presigned URL을 사용합니다.
- 로그에는 토큰, presigned query string, 원문 음성 데이터가 들어가지 않아야 합니다.
- 로컬 환경 파일은 최소 권한으로 보관하고 백업·공유 시 제외합니다.
- Pi5는 내려받은 모델의 크기와 SHA-256을 확인한 뒤 임시 파일을 rename하여 교체합니다.
- 새 모델 검증에 실패하면 현재 동작 중인 모델을 유지합니다.

### 자동 보존 기간

| 대상 | 삭제 기준 |
|---|---|
| R2 원본 WAV·학습 Job 중간 산출물 | Pi5 설치 및 로컬 합성 검증 성공 ACK 후 24시간 |
| ACK가 없거나 미완료인 R2 원본 | Job 생성 후 최대 14일 |
| GPU Worker 다운로드·checkpoint·결과 복사본 | 성공·실패와 관계없이 작업 시도 종료 즉시 |
| 교체된 이전 ONNX 릴리스 | 7일 롤백 기간 종료 후 |
| 현재 활성 ONNX | 다음 모델이 검증 설치될 때까지 |

Render는 시작 시와 실행 중 매시간 만료 항목을 확인합니다. 호스팅이 휴면 중이면 다음 기동 때 밀린 삭제를 처리하므로 실제 제거 시각은 기준 시각보다 늦을 수 있습니다. 삭제 후에도 Job ID, 처리 시각, 해시와 같은 비음성 감사 정보는 남지만 객체 경로와 음성 바이트는 제거됩니다.

## 6. 저장소에 잘못 추가했을 때

민감 파일을 아직 commit하지 않았다면 추적 대상에서 제거하고 `.gitignore`를 확인합니다. 이미 원격 저장소에 push했다면 단순 삭제 commit만으로 과거 이력이 사라지지 않으므로, 팀 책임자와 즉시 토큰 폐기·저장소 이력 정리 절차를 결정해야 합니다.
