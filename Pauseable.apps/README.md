# Memolink / Apps

Flutter 보호자 앱과 FastAPI 서버를 구현한 영역입니다. 앱은 행동 판단 알림과 출입 사진을 보여주고, 보호자 음성·호칭·거주지역·선호 음악을 등록합니다. API는 장치와 앱의 인증, 사건 이력 저장, 실시간 알림과 음성 학습 작업을 처리합니다.

[전체 프로젝트](../README.md) · [통신 계약](../Pauseable.contracts/README.md) · [장치 실행](../Pauseable.edge/README.md)

![Pi·API·Guardian·GPU Worker 및 비공개 모델 저장소의 연결](../Pauseable.docs/assets/readme/apps-connections.svg)

## 구성

| 폴더 | 역할 | 주요 기술 |
| --- | --- | --- |
| [`api`](api) | 인증·알림 이력·출입 사진·설정·음성 학습/모델 API | Python, FastAPI, R2, Firebase |
| [`guardian`](guardian) | 알림·사진 확인, 녹음·지역·선호 음악 설정 | Flutter, Dart, WebSocket, FCM |

## 알림 한 건이 전달되는 과정

![Central 결정부터 API 저장·WebSocket·Push·보호자 확인까지의 순서](../Pauseable.docs/assets/readme/notification-sequence.svg)

| 단계 | 처리 내용 | 완료 기준 |
| --- | --- | --- |
| API 접수 | Device 인증·계약·`event_id` 검사 | 서버 접수 응답 |
| 이력 저장·전달 | 중복 처리, 이력 저장, WebSocket·Push 전송 | 저장된 사건과 전송 결과 확인 |
| 앱 표시·읽음 | 실제 알림 표시와 읽음 상태 처리 | 휴대폰 표시·선택·앱 이동 확인 |

열린 앱에는 WebSocket으로 새 사건을 전달하고, 앱이 화면에 없을 때는 Web Push·FCM을 사용합니다. AI 판단과 가전 실행은 Pi가 담당합니다. 알림의 읽음 상태는 보호자의 실제 현장 조치 여부와는 별개입니다.

## API 기능

시작점은 [`api/app/main.py`](api/app/main.py), 인증 구분은 [`api/app/security.py`](api/app/security.py)입니다.

| 기능 | 담당 처리 |
| --- | --- |
| 결정 수신 | `POST /api/events/decisions`, 계약·UTC·event ID 확인 |
| 알림 이력 | 이벤트 저장, 중복 처리, 읽음 상태, 실시간 전달 |
| 휴대폰·웹 알림 | FCM/Web Push 구독·전송, 알림 설정 반영 |
| 출입 사진 | 장치 업로드·저장·보호자 인증 조회 |
| 개인 설정 | 돌봄 프로필, 지역, 선호 음악 |
| 음성 | 동의·녹음·학습 Job·Worker 임대·모델 게시와 설치 확인 |

같은 `event_id`의 재전송은 중복으로 처리하며, 같은 ID에 다른 내용이 들어오면 충돌로 구분합니다. API와 Push 서비스의 접수 응답 이후 실제 휴대폰 표시까지 확인하는 절차는 [실기 알림 점검](guardian/docs/REAL_DEVICE_ALERT_VERIFICATION.md)에 정리했습니다.

<details>
<summary><strong>API 개발 환경과 실행 명령</strong></summary>

Python 3.12와 별도 가상환경을 사용합니다. **저장소 루트에서** 시작합니다.

```sh
cd Pauseable.apps/api
python -m venv .venv
```

운영체제에 맞는 한 가지 활성화 명령을 실행합니다.

```sh
# Linux / macOS
. .venv/bin/activate
export PAUSEABLE_ENV=development
export STORAGE_BACKEND=local
export PAUSEABLE_APP_TOKEN=LOCAL_DEVELOPMENT_ONLY
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
$env:PAUSEABLE_ENV = "development"
$env:STORAGE_BACKEND = "local"
$env:PAUSEABLE_APP_TOKEN = "LOCAL_DEVELOPMENT_ONLY"
```

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -t . -p "test_*.py"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

API 문서는 `http://127.0.0.1:8000/docs`에서 확인합니다. 위 설정은 로컬 개발 전용이며, 데이터는 실행 PC에 저장합니다. 실제 서버 토큰을 예시 토큰으로 교체하지 않습니다.

</details>

<details>
<summary><strong>API 인증과 저장 설정</strong></summary>

| 환경변수 | 용도 |
| --- | --- |
| `PAUSEABLE_APP_TOKEN` | 보호자 앱 요청 |
| `PAUSEABLE_DEVICE_TOKEN` | Pi 이벤트·장치 조회·모델 설치 경로 |
| `PAUSEABLE_WORKER_TOKEN` | GPU Worker 작업 처리 |
| `PAUSEABLE_ENV=production` | 운영 모드에서 미설정 토큰 요청 차단 |
| `STORAGE_BACKEND` | `local` 또는 `r2` 저장 경로 선택 |

운영 환경은 HTTPS와 영속 저장소를 사용하며 App·Device·Worker Token을 역할별로 분리합니다. development 서버는 로컬 인터페이스에서만 실행합니다.

</details>

## Flutter 보호자 앱

주요 화면과 모델은 [`guardian/lib`](guardian/lib), API 주소·대상자·App Token은 [`api_config.dart`](guardian/lib/config/api_config.dart)에서 빌드 설정으로 읽습니다.

| 앱에서 하는 일 | 연결되는 경로 |
| --- | --- |
| 상황·알림·출입 사진 확인 | API 이력·인증된 사진·WebSocket·FCM |
| 지역·선호 음악 설정 | API 저장 → 조명 모듈·Pi 음악 Player 조회 |
| 녹음·학습 동의·모델 상태 확인 | API/R2 → GPU Worker → Pi Model Updater |

<details>
<summary><strong>Flutter 개발 환경과 로컬 웹 실행</strong></summary>

Flutter 3.47.6을 기준으로 구성되어 있습니다. **새 터미널에서 저장소 루트 기준으로** 실행합니다.

```sh
cd Pauseable.apps/guardian
flutter pub get
flutter analyze
flutter test
flutter run -d chrome --dart-define=API_BASE_URL=http://127.0.0.1:8000 --dart-define=APP_TOKEN=LOCAL_DEVELOPMENT_ONLY
```

위 API 실행 예시와 같은 PC·로컬 토큰을 사용합니다. 앱은 Token이 비어 있으면 요청을 차단합니다. 실제 Render 연결은 비공개 Token을 로컬 중계에서 사용하는 [웹 미리보기 절차](guardian/docs/RENDER_WEB_PREVIEW_KO.md)를 따릅니다.

</details>

### Android Push 확인

1. [Android 설정 안내](guardian/docs/ANDROID_PUSH_SETUP_KO.md)에 따라 Firebase 설정과 서버 전송 권한을 준비합니다.
2. 새 APK를 만들고 시험 휴대폰에 설치합니다.
3. 앱의 시험 알림으로 foreground·background·잠금 상태를 각각 확인합니다.
4. Central 결정 → API 이력 → FCM 접수 → 실제 표시 순서로 확인합니다.

현재 앱은 팀 시험용 공유 App Token과 시험용 서명을 사용합니다. 공개 서비스에 필요한 사용자별 로그인·대상자 접근권한 분리는 별도 적용 대상입니다. 서버 비밀 키·Device/Worker Token·R2 키는 앱 빌드에서 제외합니다.

## 구현 및 검증 범위

[보호자 앱 상세 README](guardian/README.md)에는 화면별 기능, API 연결, 녹음 형식, 자동 검사와 팀 실기 시험 기록을 정리했습니다. 일부 대시보드·기기 연결 상태·긴급 연락 요청에는 데모 동작이 포함되어 있습니다. 실제 전화·긴급기관 연결 기능으로 사용하지 않습니다.

음성 녹음은 앱에서 16 kHz·mono·PCM 16-bit로 수집하고, Voice 전처리에서 학습용 22,050 Hz로 변환합니다. 지역·음악 설정의 서버 저장과 실제 조명·음악 출력은 각 장치 모듈에서 확인합니다.

## 함께 볼 문서

| 목적 | 자료 |
| --- | --- |
| 휴대폰 Push 준비 | [Android Push](guardian/docs/ANDROID_PUSH_SETUP_KO.md) |
| 실제 표시 확인 | [실기 알림 점검](guardian/docs/REAL_DEVICE_ALERT_VERIFICATION.md) |
| Render 연결 미리보기 | [로컬 웹 중계](guardian/docs/RENDER_WEB_PREVIEW_KO.md) |
| 앱 지역 → 조명 연동 | [지역 설정 연결](../Pauseable.docs/integrations/home-assistant/RENDER_REGION_SETUP_KO.md) |
| 선호 음악 → Pi 재생 | [Favorite Music](../Pauseable.edge/actions/favorite-music/README.md) |
| 자동 검사·APK 산출물 | [CI README](../.github/CI_README.md) |

서버 배포 버전, 설치한 APK와 Pi 런타임 버전은 별도로 관리합니다.
