# Memolink 보호자 앱 · Flutter

반복행동·배회 판단 알림과 현관 출입 사진을 확인하고, 보호자 음성·호칭·거주지역·선호 음악을 등록하는 Flutter 앱입니다. 판단 결과는 Central과 API를 거쳐 수신합니다. AI 분석, 음성 모델 학습과 가전 출력은 각 서버·장치 모듈에서 처리합니다.

[전체 프로젝트](../../README.md) · [앱/API 구성](../README.md) · [API 코드](../api/app/main.py) · [Pi 음악 적용 안내](../../Pauseable.edge/actions/favorite-music/README.md)

- 담당: **권태준 ([ktj-oss](https://github.com/ktj-oss))**: Flutter 화면·상태 처리, API·실시간 알림·녹음 및 설정 연동
- 주요 기술: Flutter/Dart, REST API, WebSocket, Web Push, Android FCM
- 주 실행·시험 환경: 노트북 웹앱 및 Android 앱. iOS 폴더는 있으나 iOS 실기 빌드·푸시 수신을 검증한 상태는 아닙니다.

## 1. 앱의 역할과 연결 구조

![보호자 앱·API·Pi·음성 학습 Worker의 연결](../../Pauseable.docs/assets/readme/apps-connections.svg)

<details>
<summary>사건 수신과 설정 전달 경로</summary>

```text
센서/AI → Pi Central 승인 → Render API → WebSocket / Push → 보호자 앱
카메라 → Pi 업로드 → Render의 출입 이벤트·비공개 이미지 → 앱 사진 확인

보호자 앱 → REST API → Render 저장
  ├─ 녹음 WAV·동의 기록 → 저장소 / GPU Worker → 음성 모델 → Pi
  ├─ 가족관계·patient_call_name → Pi의 TTS 문장 개인화
  ├─ 거주지역 → 날씨·조명 모듈의 지역 조회
  └─ 유튜브 등록곡 → Pi가 무작위 선택 API 조회 → 화면·스피커 재생
```

</details>

보호자 앱은 REST API로 설정을 저장하고 WebSocket·Push로 알림을 받습니다. Pi의 D-Bus와 Home Assistant 제어는 Central 및 장치 모듈이 담당합니다. 보호자 앱과 환자 측 ATLAS 앱은 서로 다른 프로그램입니다.

## 2. 구현된 기능과 범위

| 기능 | 구현 내용 | 적용 범위 |
| --- | --- | --- |
| 홈·알림·기록·설정 | 하단 메뉴 전환, 상태·이력 표시, 서버 오류 안내 및 재시도 | API에 기본 데모 데이터가 남아 있으므로 화면의 모든 값이 실측값이라는 뜻은 아님 |
| 반복행동·배회 알림 | 인증된 WebSocket 연결, 연결 상태·재연결, 이력 조회·읽음 처리 | 판단 알고리즘은 앱에 없으며, Pi의 승인·서버 전송이 선행되어야 함 |
| 웹/Android 알림 | Web Push 구독·시험 알림, Android FCM 등록·알림 선택 시 앱 이동 | 권한·서버 설정·플랫폼 상태별 실제 표시 확인이 별도로 필요 |
| 현관 출입 사진 | 이벤트 정보 조회, App Bearer를 붙인 이미지 바이트 조회·확대·재시도 | 앱이 촬영하지 않음. 카메라·Pi 업로드가 있어야 실제 사진 표시 가능 |
| 보호자·대상자 설정 | 이름, 가족관계, 편집 가능한 TTS 호칭 `patient_call_name` 저장·재조회 | TTS 문장에 값을 넣고 합성·재생하는 처리는 Pi/음성 모듈의 역할 |
| 거주지역 | 최초 선택 및 설정에서 변경, 지역 코드·기상청 격자 연동용 정보 저장 | 상세 도로명주소·GPS 위치 추적·보호자용 날씨 표시 기능은 아님 |
| 보호자 음성학습 | 동의 기록 저장, 고정 대본 표시, 문장별 WAV 자동 업로드·실패 재전송·진행 조회 | 녹음 업로드 성공과 GPU 학습·모델 설치·실제 합성 성공은 다른 단계 |
| 새 음성학습 | 완료된 세트에서 확인 후 새 세트 생성, 문장 1번부터 수집 | 기존 모델 유지·교체는 서버/장비 정책이며 실제 새 모델 설치까지 확인해야 함 |
| 좋아하는 노래 | 제목·유튜브 동영상 링크 추가/삭제, 중복·형식 검사, 최대 30곡 | 앱이 재생하지 않음. Pi에 별도 음악 연동을 설치해야 감지 후 재생 가능 |
| 알림·화면 설정 | 안전 이상 알림·알림음 설정 요청, 실행 중 라이트/다크 모드 전환 | 테마는 현재 앱 실행 상태이며 영구 저장 기능으로 설명하지 않음 |

### 데모·시험용 동작

- 보호 전화·긴급 연락 요청은 현재 API의 **가상 요청**입니다. 실제 전화 발신·문자 전송·긴급기관 연결 기능으로 사용하지 않습니다.
- 연결된 기기 화면은 API의 데모 연결 상태를 사용합니다. 화면의 “정상 연결”만으로 실제 Pi·센서·카메라의 건강 상태를 증명할 수 없습니다.
- 시나리오 변경과 기본 센서 이력에는 데모 데이터가 포함됩니다. 열림/닫힘 및 초 단위 시각을 표시하는 UI와 모든 실제 센서 이력의 수집 완료는 구분합니다.
- 알림 일시 중지·재개 요청 UI가 있으나, 현재 서버의 일시 중지 상태는 메모리 기반입니다. Pi 감지기 정지나 모든 실제 푸시·안전 경보의 차단이 검증된 기능으로 해석하지 않습니다.
- 실시간 알림의 누락된 횟수는 `null회`나 임의의 숫자로 표시하지 않고 감지 내용·시각 중심으로 표시합니다.

## 3. 개발 환경과 실행

### 준비 사항

- CI 기준 Flutter **3.47.6**. `pubspec.yaml`의 Dart SDK 조건은 `^3.13.0`입니다.
- 웹: Chrome 및 마이크·알림 권한. 지원 범위는 브라우저와 OS 정책에 따릅니다.
- 로컬 중계/API: Python 3.12 기준, [`../api/requirements.txt`](../api/requirements.txt).
- Android 빌드: JDK 17, Android SDK 36. FCM 실기 시험은 Firebase Android 설정 및 서버 전송 설정이 추가로 필요합니다.

### Render 연결 미리보기

저장소 루트에서 앱 폴더로 이동합니다. 아래는 **Windows PowerShell 예시**이며, Python 가상환경을 이미 준비했다면 재사용할 수 있습니다.

```powershell
cd Pauseable.apps/guardian
flutter pub get
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r ../api/requirements.txt
```

앱 폴더의 `render-web.secrets.json`에 앱용 Token과 서버에 등록된 대상자 ID를 입력합니다. 다음은 형식 예시이며 두 placeholder를 실제 설정으로 바꿉니다.

```json
{
  "API_BASE_URL": "https://pauseable-api.onrender.com",
  "PATIENT_ID": "SET_PATIENT_ID_FROM_CONFIG",
  "APP_TOKEN": "REPLACE_WITH_APP_TOKEN_LOCALLY"
}
```

```powershell
.\.venv\Scripts\python.exe -m tools.serve_render_web --build
```

브라우저에서 `http://127.0.0.1:18108/`을 엽니다. Flutter가 PATH에 없다면 `--flutter "Flutter SDK의 bin/flutter.bat 경로"`를 추가합니다. 서버를 종료하면 미리보기도 접속할 수 없습니다. 같은 포트·대상자·빌드를 다시 사용할 때는 `--build` 없이 실행합니다.

이 도구는 실제 Render App Token을 **로컬 Python 중계**에서 읽고, 웹 빌드에는 별개의 로컬 접속값을 넣습니다. 포트·대상자가 바뀌거나 앱 코드를 수정했다면 다시 빌드합니다. 실제 Render 모드에서 저장·삭제·녹음 업로드는 실제 서버 데이터를 변경합니다.

자세한 설정·제한: [Render 웹 미리보기](docs/RENDER_WEB_PREVIEW_KO.md). 중계는 노트북 내부 전용이며 외부 IP·공개 터널로 노출하지 않습니다.

<details>
<summary>외부 서버를 바꾸지 않는 로컬 개발 실행</summary>

첫 번째 PowerShell에서 저장소 루트 기준으로 로컬 API를 실행합니다. 다음 토큰 문자열은 로컬 시험용 예시이며 실제 Render 토큰이 아닙니다.

```powershell
cd Pauseable.apps/api
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PAUSEABLE_ENV = "development"
$env:STORAGE_BACKEND = "local"
$env:PAUSEABLE_APP_TOKEN = "LOCAL_DEVELOPMENT_ONLY"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

두 번째 PowerShell에서 저장소 루트 기준으로 앱을 실행합니다. 중계 미리보기의 18108과 겹치지 않도록 예시 포트는 18109를 사용합니다.

```powershell
cd Pauseable.apps/guardian
flutter pub get
flutter run -d chrome --web-port=18109 --dart-define=API_BASE_URL=http://127.0.0.1:8000 --dart-define=APP_TOKEN=LOCAL_DEVELOPMENT_ONLY
```

위 명령은 `api_config.dart`의 기본 시연 대상자를 사용합니다. 다른 대상자는 서버 설정과 같은 `PATIENT_ID`를 추가로 지정합니다. 기본 `main.dart`는 실제 API Repository를 사용하며, 테스트용 `MockGuardianRepository`는 명시적으로 주입합니다. 인증 실패 시 가상 데이터로 전환하지 않고, App Token이 비어 있으면 요청을 차단합니다.

</details>

### Android 시험용 APK

[Android Push 설정 안내](docs/ANDROID_PUSH_SETUP_KO.md)에 따라 Firebase 설정과 로컬 `android-test.secrets.json`을 준비한 뒤 실행합니다.

```sh
flutter pub get
flutter analyze
flutter test
flutter build apk --release --dart-define-from-file=android-test.secrets.json
```

결과: `build/app/outputs/flutter-apk/app-release.apk`. [수동 APK 워크플로](../../.github/workflows/native-push-apk.yml)도 사용할 수 있습니다. 단순 CI 빌드 성공은 Firebase·앱 인증 설정을 포함한 배포 APK의 실제 수신 성공을 뜻하지 않습니다. 현재 시험용 서명과 공유 토큰 구조는 공개 배포용 로그인·서명 관리의 대체물이 아닙니다.

## 4. 주요 파일

```text
lib/
├─ main.dart                      API·실시간 알림·푸시 클라이언트 구성
├─ app.dart                       초기 지역 선택·앱 생명주기·테마
├─ config/api_config.dart         빌드 설정 읽기
├─ models/                       API 응답·알림·사진·설정·학습 상태 모델
├─ repositories/
│  ├─ guardian_repository.dart    화면에서 사용하는 데이터 계약
│  ├─ api_guardian_repository.dart  REST·업로드·비공개 사진 처리
│  └─ mock_guardian_repository.dart 테스트/데모용 구현
├─ services/                     인증 HTTP·WebSocket·웹/Android 푸시·녹음
└─ screens/
   ├─ guardian_home_page.dart     탭 구성·실시간 알림·화면 간 상태 연결
   ├─ tabs/                      홈·알림·기록·설정
   ├─ home_region_page.dart       거주지역 선택
   ├─ favorite_songs_page.dart    선호곡 등록·삭제
   ├─ voice_recording_consent_sheet.dart  동의 안내·서버 저장
   └─ widgets/                   문장 녹음·프로필 편집·사진 확대 등
assets/                         고정 대본·지역 목록·데모 자료
test/                           API 계약·인증·화면·알림·사진·동의 테스트
tools/                          로컬 Render 중계·Android 빌드/연결 점검
web/                            Flutter 웹 진입점·웹 푸시 서비스워커
```

`GuardianRepository`는 화면과 데이터 접근을 분리합니다. REST·업로드·사진 조회는 `api_guardian_repository.dart`, 인증·알림·녹음 처리는 `services/`에 구현했습니다.

## 5. 대표 API와 통신 방식

| 용도 | 앱이 사용하는 경로 |
| --- | --- |
| 홈·알림 이력 | `GET /api/patients/{patient_id}/dashboard`, `GET /api/patients/{patient_id}/alerts` |
| 실시간 연결 | `POST /api/patients/{patient_id}/alert-websocket-ticket` → 일회용 ticket으로 `/ws/alerts` 접속 |
| 현관 사진 | `GET /api/door-events/{event_id}/image` — 인증 후 이미지 바이트 표시 |
| 이름·가족관계·호칭 | `GET/PUT /api/patients/{patient_id}/care-profile` |
| 지역·조명 설정 | `GET/PUT /api/patients/{patient_id}/home-environment` |
| 선호곡 | `GET/PUT /api/patients/{patient_id}/favorite-songs` |
| 음성 동의 | `POST /api/patients/{patient_id}/voice-training/consents` |
| 음성 진행·새 세트 | `GET /api/patients/{patient_id}/voice-training`, `POST /api/patients/{patient_id}/voice-training/sessions` |
| 문장 WAV 업로드 | `POST /api/voice-training/clips` — multipart 파일·대본·길이·세트 ID |

- REST 인증은 `AppAuthenticatedClient`에서 App Bearer를 붙입니다. 설정된 API 출처를 벗어나거나 인증을 동반한 리다이렉트는 허용하지 않습니다.
- WebSocket은 `ready`/`app_alert` 메시지를 처리하며 연결 종료 시 재접속을 시도합니다. 앱을 닫았을 때의 시스템 알림은 별도의 Web Push/FCM 경로입니다.
- Pi의 `GET /api/device/patients/{patient_id}/favorite-songs/random`은 **Device Token을 사용하는 장비 API**이며 보호자 앱이 직접 호출하지 않습니다.
- `API_BASE_URL`, `PATIENT_ID`, `APP_TOKEN`은 [`api_config.dart`](lib/config/api_config.dart)의 빌드 설정입니다. 웹은 로컬 API, Android는 Render 주소가 기본값입니다. 대상자 ID는 시연 설정을 사용하고, App Token은 별도로 입력합니다.

## 6. 녹음·개인정보·인증 주의사항

- 현재 앱에 포함된 고정 대본은 **160문장**입니다. 총 **800초는 권장 분량**이지 총 녹음 시간을 자르는 상한이 아닙니다. 수집 가능한 세트 상태·대본 범위 안에서 추가 녹음하며, 문장당 녹음 제한은 45초입니다.
- 녹음 원본은 PCM 16-bit·16 kHz·mono WAV로 생성해 문장 종료 후 전송합니다. Voice 전처리에서 학습용 22,050 Hz로 변환합니다. 실패한 녹음은 열린 화면에서 재전송할 수 있으며, 앱 종료 후 영구 복구 기능은 제공하지 않습니다.
- [`VoiceRecordingConsentSheet`](lib/screens/voice_recording_consent_sheet.dart)의 동의 여부·버전·서버 영수증 확인 후 녹음 화면을 엽니다. 동의 거부·저장 실패 시 녹음/업로드는 막되 기존 알림·사진 확인은 유지합니다.
- 보관·삭제 정책은 동의 화면에 안내합니다. 실제 녹음·모델 삭제는 서버/Worker의 역할이며 **동의 화면 표시만으로 삭제 실행을 증명하지 않습니다.** 앱에는 전체 데이터 즉시 삭제·동의 철회 UI가 구현된 상태가 아닙니다.
- `*.secrets.json`, `.env`, `android/app/google-services.json`은 Git 제외 대상입니다. 실제 토큰, 녹음, 사용자 사진·주소, 서비스 계정 키를 README·스크린샷·커밋에 넣지 않습니다.
- `PAUSEABLE_APP_TOKEN`만 앱용으로 사용합니다. Device/Worker Token, R2 키, VAPID 개인키, Firebase 전송용 서비스 계정은 앱에 포함하지 않습니다.
- 실제 공유 토큰을 `--dart-define`으로 웹에 직접 넣으면 다운로드되는 JavaScript에서 노출될 수 있습니다. 로컬 Render 시험은 위의 중계를 사용하고, APK도 공유 토큰 추출 가능성을 전제로 팀 내부에만 전달합니다. 사용자별 로그인·대상자 접근권한 분리 및 공개 서비스 배포 준비는 별도 과제입니다.

## 7. 검증 결과와 남은 확인

다음은 2026-10-28 정리한 음악 연동 기능 commit [`d2b49a8`](https://github.com/RACOS-Team/Pauseable/commit/d2b49a8a32beeb5fca4e61e0be0a20a7f60fc27b) 및 [PR #1](https://github.com/RACOS-Team/Pauseable/pull/1)의 검사 기록입니다. 테스트 수와 결과는 해당 코드 버전을 기준으로 합니다.

| 확인 종류 | 확인한 범위 |
| --- | --- |
| Flutter 정적 분석 | `flutter analyze` — 문제 없음 |
| Flutter 자동 테스트 | 85개 통과: 인증, 알림/푸시 이동, 사진 접근·확대, 설정, 동의·녹음, 새 학습 세트, 선호곡 등 |
| API 회귀 테스트 | 158개 통과: 앱/서버 계약, 알림·사진·동의·설정, 저장곡 → 장비 조회 → 모의 Pi 전달 등 |
| 웹 푸시 서비스워커 | Node 테스트 6개 통과 |
| 빌드 | GitHub Actions에서 웹 release 및 Android APK release 빌드 성공 |

**실제 서버·팀 시험에서 확인한 범위**

- 노트북 웹앱의 실제 Render 연결과 선호곡 저장 후 API 재조회(`200`)를 확인했습니다. 문서에는 실제 사용자 입력값이나 토큰을 포함하지 않습니다.
- 기존 팀 시험에서 음성 동의 기록의 Render 저장, Chrome 탭을 닫은 상태의 웹 푸시 표시·알림 선택 시 앱 연결을 확인했습니다. Chrome 프로그램 완전 종료·모든 브라우저/OS에서의 수신 보장은 아닙니다.
- 기존 배회 알림·야간 현관 사진의 휴대폰 수신은 **팀원의 실장비 시연 성공 보고**가 있습니다. 이 보고와 최신 APK·모든 기기 상태의 재시험 완료는 구분합니다.

**별도 설치·실장비 확인이 필요한 범위**

- 새 선호곡 재생: 최신 main을 Pi에 설치하고 반복행동/배회 각각에서 실제 화면·소리를 확인해야 합니다. 기본 300초 재요청 제한과 YouTube 광고·로그인·네트워크도 확인합니다. [Pi 적용 안내](../../Pauseable.edge/actions/favorite-music/README.md)
- 새 음성학습: 새 세트 수집 → GPU 학습 → 모델 게시 → Pi 검증·설치 → 기존 목소리 교체 및 실제 합성을 각각 확인해야 합니다.
- 지역 연동: 앱 저장 성공과 그 지역에 맞는 실제 조명 밝기 변경은 별도입니다. 장비의 Render 지역 조회 설정이 필요합니다. [조명 모듈 적용 안내](../../Pauseable.docs/integrations/home-assistant/RENDER_REGION_SETUP_KO.md)
- Android: 실제 배포 APK의 Firebase·인증 설정, 알림 권한, foreground/background/잠금 상태를 기기별로 확인합니다. 강제 종료·절전·방해 금지 설정의 영향을 받습니다. iOS 네이티브 푸시는 현재 구현·검증 범위에 포함하지 않습니다.
- 실기 증거에는 앱·서버·Pi 버전과 같은 `event_id`의 전송/저장/표시를 함께 남깁니다. API `200/202`, Push 서비스 접수, 학습 `completed`만으로 모든 후속 장치 동작이 성공했다고 판단하지 않습니다.

### 자동 검사 재현

앱 폴더에서 실행합니다. Node 테스트에는 Node.js가 추가로 필요합니다.

```sh
flutter analyze
flutter test
node --test test/web_push_service_worker.test.cjs
```

API 폴더에서는 Python 가상환경과 의존성을 준비한 뒤 다음을 실행합니다. 테스트는 임시 저장소·모의 API/플레이어를 사용하며 실제 환자 데이터를 변경하는 실장비 시험과 다릅니다.

```sh
python -m unittest discover -s tests -t . -p "test_*.py"
```

관련 CI: [자동 검사](../../.github/workflows/native-alert-checks.yml), [Android 시험 APK](../../.github/workflows/native-push-apk.yml). GitHub 코드 반영, Render 배포, APK 설치, Pi 런타임 적용은 서로 다른 단계입니다.

## 8. 자주 확인할 문제

| 증상 | 확인 사항 |
| --- | --- |
| `127.0.0.1:18108` 접속 거부 | 해당 노트북의 미리보기 서버 실행 여부. 다른 휴대폰에서 같은 주소로 접속할 수 없음 |
| API `401/403` | App Token 누락·불일치 또는 Device/Worker Token 혼용 여부 |
| API `404` | 앱·서버 코드 버전, API 경로, 일치하는 `PATIENT_ID` |
| 사진이 표시되지 않음 | 이벤트의 실제 사진 업로드 여부, 인증된 이미지 조회 응답, 연결 상태 |
| 열린 앱에는 오지만 닫으면 알림 없음 | WebSocket과 별개로 Push 구독·Firebase·브라우저/OS 권한 확인 |
| 노래 저장은 되지만 소리가 안 남 | Pi 음악 연동 설치·실행, 대상자 일치, 빈 목록·cooldown·플레이어 로그 |
| 녹음 불가/전송 실패 | 동의 영수증 저장, 마이크 권한, 세트 수집 가능 상태, 서버 연결 확인 |

알림 실기 점검은 [실장비 알림 확인 절차](docs/REAL_DEVICE_ALERT_VERIFICATION.md)를 함께 참고하되, 과거 날짜의 상태 설명을 최신 장비 검증 결과로 대체해 해석하지 않습니다.
