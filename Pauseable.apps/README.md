# PAUSEABLE / Apps

**장치에서 감지한 상황을 보호자가 확인하고, 보호자의 설정을 다시 장치로 전달합니다.** Flutter 앱은 알림·사진·녹음·설정을 담당하고, FastAPI는 장치와 앱의 인증·저장·전달을 담당합니다.

[전체 프로젝트](../README.md) · [통신 계약](../Pauseable.contracts/README.md) · [장치 실행](../Pauseable.edge/README.md)

![Pi·API·Guardian·GPU Worker 및 비공개 모델 저장소의 연결](../Pauseable.docs/assets/readme/apps-connections.svg)

## 무엇을 담당하는가

| 폴더 | 역할 | 주요 기술 |
| --- | --- | --- |
| [`api`](api) | 인증·알림 이력·출입 사진·설정·음성 학습/모델 API | Python, FastAPI, R2, Firebase |
| [`guardian`](guardian) | 알림·사진 확인, 녹음·지역·선호 음악 설정 | Flutter, Dart, WebSocket, FCM |

## 알림 한 건이 전달되는 과정

![Central 결정부터 API 저장·WebSocket·Push·보호자 확인까지의 순서](../Pauseable.docs/assets/readme/notification-sequence.svg)

| 확인 지점 | 확인할 내용 | 이것만으로 알 수 없는 것 |
| --- | --- | --- |
| API 접수 | 인증·계약·`event_id`가 허용되었는가 | 휴대폰에 표시되었는가 |
| 이력 저장·재전송 | 같은 ID의 재전송이 새 알림을 중복 생성하지 않는가 | 모든 출력 장치의 실행 성공 |
| 휴대폰 표시·읽음 | 실제 표시와 보호자 확인이 기록되는가 | 보호자가 현장에서 조치했는가 |

AI 추론과 Pi의 가전 실행은 이 폴더가 대신하지 않습니다. WebSocket의 실시간 전달과 앱이 background 상태일 때의 Push 경로도 별도로 확인합니다.

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

`202 Accepted`나 Push 제공자의 접수 응답만으로 실제 휴대폰 표시까지 성공했다고 판단하지 않습니다. 같은 `event_id`를 재전송했을 때 새로운 알림이 중복 생성되는지도 구분합니다.

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
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -t . -p "test_*.py"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

API 문서: `http://127.0.0.1:8000/docs`. 기본 local storage는 실행 PC에 기록합니다. 이 개발 명령은 Render 운영 배포를 변경하지 않습니다.

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

토큰이 없는 development 모드를 외부에 노출하지 않습니다. 운영에서는 HTTPS, 서버 비밀 설정, 영속 저장소와 역할별 토큰이 필요합니다. App Token과 Device/Worker Token을 혼용하지 않습니다.

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
flutter run -d chrome --dart-define=API_BASE_URL=http://127.0.0.1:8000
```

이 명령은 같은 PC의 로컬 API를 사용합니다. 실제 Render를 확인할 때는 공유 App Token을 웹 파일에 직접 넣는 대신 [로컬 Render 중계 안내](guardian/docs/RENDER_WEB_PREVIEW_KO.md)를 따릅니다.

</details>

### Android Push 확인

1. [Android 설정 안내](guardian/docs/ANDROID_PUSH_SETUP_KO.md)에 따라 Firebase 설정과 서버 전송 권한을 준비합니다.
2. 새 APK를 만들고 시험 휴대폰에 설치합니다.
3. 앱의 시험 알림으로 foreground·background·잠금 상태를 각각 확인합니다.
4. Central 결정 → API 이력 → FCM 접수 → 실제 표시 순서로 확인합니다.

현재 공유 App Token과 시험용 서명 구조는 공개 서비스용 사용자별 로그인·권한 분리를 대신하지 않습니다. 서버용 비밀 키·Device/Worker Token·R2 키는 APK나 웹 빌드에 넣지 않습니다.

## 함께 볼 문서

| 목적 | 자료 |
| --- | --- |
| 휴대폰 Push 준비 | [Android Push](guardian/docs/ANDROID_PUSH_SETUP_KO.md) |
| 실제 표시 확인 | [실기 알림 점검](guardian/docs/REAL_DEVICE_ALERT_VERIFICATION.md) |
| Render 연결 미리보기 | [로컬 웹 중계](guardian/docs/RENDER_WEB_PREVIEW_KO.md) |
| 앱 지역 → 조명 연동 | [지역 설정 연결](../Pauseable.docs/integrations/home-assistant/RENDER_REGION_SETUP_KO.md) |
| 선호 음악 → Pi 재생 | [Favorite Music](../Pauseable.edge/actions/favorite-music/README.md) |
| 자동 검사·APK 산출물 | [CI README](../.github/CI_README.md) |

앱·API 코드 반영, 서버 배포, 새 APK 설치, 실제 알림 수신은 각각 별도의 완료 단계로 기록합니다.
