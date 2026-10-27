# Pauseable.apps

<a id="pauseableapps"></a>

<a id="개인정보와-운영-설정"></a>
<a id="검증-기록과-실기-확인"></a>
<a id="주요-코드"></a>

**보호자 Flutter 앱과 장치·앱 사이의 FastAPI 서버입니다.**

[프로젝트](../README.md) · [AI](../Pauseable.ai/README.md) · [Edge](../Pauseable.edge/README.md) · [통신 규격](../Pauseable.contracts/README.md)

[주요 기능](#주요-기능) · [폴더 구조](#폴더-구조) · [API 처리 방식](#api-처리-방식) · [보호자 앱의 화면과 연결](#보호자-앱의-화면과-연결) · [설치 및 실행](#설치-및-실행)

<a id="주요-기능"></a>

## 주요 기능

| 영역 | 제공 기능 |
| --- | --- |
| API | 사건 접수·검증·이력, 출입 사진, 돌봄 설정, 음성 Job, Push 전달 |
| Guardian | 알림·출입 사진 확인, 읽음 처리, 대상자·지역·선호 음악·녹음 설정 |
| 알림 | WebSocket·Android FCM·Web Push, 반복행동 알림 일시 중지 |
| 저장 | 개발용 로컬 파일, 운영용 Cloudflare R2 연결 |

<a id="폴더-구조"></a>

## 폴더 구조

```text
Pauseable.apps/
├── api/                                       # 인증·사건 저장·Push·사진·학습 API
│   ├── app/                                   # FastAPI 라우트와 도메인별 저장·검증 코드
│   │   ├── data/
│   │   ├── media/                             # 시연용 출입 사진 샘플
│   │   ├── uploads/                           # 로컬 업로드 경로와 Git 제외 설정
│   │   │   ├── training/                      # 녹음 학습 세트 업로드 경로
│   │   │   └── voice/                         # 개별 음성 업로드 경로
│   │   ├── main.py                            # API 라우트·요청 검사·기능 연결
│   │   ├── security.py                        # 앱·장치·Worker 역할별 인증
│   │   └── voice_training_service.py          # 녹음 세트·학습 Job·모델 게시 관리
│   ├── tests/
│   └── requirements.txt                       # FastAPI 서버 의존성
└── guardian/                                  # Flutter 보호자 앱
    ├── android/                               # Android 플랫폼 프로젝트
    │   ├── app/                               # Android 앱 모듈
    │   │   └── src/
    │   │       ├── debug/
    │   │       ├── main/
    │   │       │   ├── kotlin/
    │   │       │   │   └── com/
    │   │       │   │       └── pauseable/
    │   │       │   │           └── pauseable_guardian/
    │   │       │   └── res/
    │   │       │       ├── drawable/
    │   │       │       ├── drawable-v21/
    │   │       │       ├── mipmap-hdpi/
    │   │       │       ├── mipmap-mdpi/
    │   │       │       ├── mipmap-xhdpi/
    │   │       │       ├── mipmap-xxhdpi/
    │   │       │       ├── mipmap-xxxhdpi/
    │   │       │       ├── raw/
    │   │       │       ├── values/
    │   │       │       └── values-night/
    │   │       └── profile/
    │   └── gradle/
    │       └── wrapper/
    ├── assets/
    │   ├── data/
    │   ├── images/
    │   └── mock/                              # 로컬 화면 시험용 스냅샷
    ├── docs/                                  # Android Push·실기 확인·웹 중계 안내
    ├── ios/                                   # iOS 플랫폼 프로젝트
    │   ├── Flutter/                           # iOS용 Flutter 빌드 설정
    │   ├── Runner/                            # iOS 앱 진입·리소스
    │   │   ├── Assets.xcassets/
    │   │   │   ├── AppIcon.appiconset/
    │   │   │   └── LaunchImage.imageset/
    │   │   └── Base.lproj/
    │   ├── Runner.xcodeproj/
    │   │   ├── project.xcworkspace/
    │   │   │   └── xcshareddata/
    │   │   └── xcshareddata/
    │   │       └── xcschemes/
    │   ├── Runner.xcworkspace/
    │   │   └── xcshareddata/
    │   └── RunnerTests/
    ├── lib/                                   # 화면·모델·API 접근·알림 서비스
    │   ├── config/                            # API 주소·대상자·빌드 설정
    │   ├── models/                            # 알림·사진·지역·녹음 등 자료형
    │   ├── repositories/                      # API·Mock 자료 접근 계층
    │   │   └── api_guardian_repository.dart   # 보호자 앱의 API 자료 접근
    │   ├── screens/                           # 설정 화면과 홈 화면 구성
    │   │   ├── tabs/                          # 홈·알림·기록·설정 탭
    │   │   └── widgets/                       # 사진·돌봄 설정·녹음 UI
    │   ├── services/                          # 인증 HTTP·실시간 알림·Push·녹음
    │   │   ├── live_alert_client.dart         # WebSocket 알림 연결
    │   │   └── voice_recording_service.dart   # 문장별 음성 녹음
    │   └── main.dart                          # Flutter 앱 진입과 화면 구성
    ├── test/
    ├── tools/                                 # APK 빌드·지역 변환·로컬 중계·확인 도구
    ├── web/                                   # Flutter 웹 실행·Push 리소스
    │   └── icons/
    └── pubspec.yaml                           # Flutter 패키지·Asset 설정
```

<a id="api-폴더의-역할"></a>

### ① API 폴더의 역할

| 경로 | 설명 |
| --- | --- |
| `api/app/main.py` | FastAPI 라우트·요청 검사·처리 연결 |
| `api/app/*_store.py` | 알림·사진·설정·Push 등 도메인별 저장 |
| `api/app/security.py` | 앱·장치·Worker 역할별 인증 |
| `api/app/data` | 기본 시연 자료·지역 목록·녹음 대본 |
| `api/app/uploads` | 로컬 음성·학습 세트 저장 경로. 실제 파일은 Git 제외 |
| `api/tests` | 인증·중복·이력·사진·학습·알림 회귀 검사 |

<a id="guardian-폴더의-역할"></a>

### ② Guardian 폴더의 역할

| 경로 | 설명 |
| --- | --- |
| `guardian/lib/models` | 화면과 API가 사용하는 자료형 |
| `guardian/lib/repositories` | API와 Mock의 자료 접근 분리 |
| `guardian/lib/screens/tabs` | 홈·알림·기록·설정 화면 |
| `guardian/lib/screens/widgets` | 사진 보기·녹음·돌봄 설정 UI |
| `guardian/lib/services` | 인증 HTTP·WebSocket·Push·녹음 기능 |
| `guardian/android`, `ios`, `web` | 플랫폼별 프로젝트와 리소스 |
| `guardian/assets` | 대본·지역 목록·시연용 샘플 |
| `guardian/docs`, `tools` | 플랫폼 안내·실기 확인·빌드·로컬 중계 도구 |

<a id="api-구현-상세"></a>

<a id="api-처리-방식"></a>

## API 처리 방식

```text
Central 최종 사건 → Device 인증·계약 검사 → event_id 중복·충돌 확인
→ 이력 저장 → 대상자 알림 정책 → WebSocket / FCM / Web Push
```

| 요청 주체 | 인증 설정 | 주로 접근하는 기능 |
| --- | --- | --- |
| 앱 | `PAUSEABLE_APP_TOKEN` | 알림·사진 조회, 설정·동의·녹음 등록 |
| Pi | `PAUSEABLE_DEVICE_TOKEN` | 사건·사진 업로드, 지역·곡·모델 조회 |
| GPU Worker | `PAUSEABLE_WORKER_TOKEN` | Job 임대·갱신·결과 게시 |

`POST /api/events/decisions`는 같은 사건 ID·같은 내용을 재전송으로 처리하고, 같은 ID의 다른 내용은 충돌로 구분합니다. 사진은 인증된 조회 경로로 전달하며 API 접수 성공과 휴대폰 표시 성공은 다릅니다.

<a id="보호자-앱-상세"></a>

<a id="보호자-앱의-화면과-연결"></a>

## 보호자 앱의 화면과 연결

| 화면 | 동작 |
| --- | --- |
| 홈 | 대상자 이름·최근 알림·앱과 알림 서버 연결 상태 |
| 알림 | 사건 내용·시각 확인과 읽음 처리 |
| 기록 | 출입 사진·촬영 시각·확대·조회 재시도 |
| 설정 | 돌봄 정보·알림·음성 녹음·거주지역·선호 YouTube 목록 |

기본 진입은 [main.dart](guardian/lib/main.dart)이며 [api_guardian_repository.dart](guardian/lib/repositories/api_guardian_repository.dart)가 실제 API에 접근합니다. 인증 실패를 Mock 자료로 자동 대체하지 않습니다. 실제 장비 상태가 확인되지 않은 위치·활동·안전·가상 기기 상태, 전화·SOS 버튼은 최신 화면에서 숨겼습니다.

<a id="알림-수신과-일시-중지"></a>

<a id="실시간-알림과-일시-중지"></a>

### ① 실시간 알림과 일시 중지

앱은 REST로 일회용 WebSocket ticket을 발급받아 `/ws/alerts`에 연결합니다. Android 시스템 알림은 FCM, 웹 시스템 알림은 Web Push를 사용합니다.

반복행동 알림 일시 중지는 대상자별 만료 시각을 저장합니다. 중지 중에는 반복행동의 WebSocket·Push 전달을 억제하지만 이력은 보존합니다. 배회·사진·Pi 감지·TTS·가전 동작을 중단하는 기능은 아닙니다. 앱 재실행 후에도 서버 값을 다시 확인합니다.

<a id="녹음과-개인화-설정"></a>

### ② 녹음과 개인화 설정

음성 수집은 동의 기록 후 문장별로 진행합니다. API가 녹음 세트와 학습 Job을 관리하고 GPU Worker가 모델을 게시합니다. 앱의 거주지역·선호곡은 장치가 Device API로 조회합니다.

<a id="음성-녹음과-동의"></a>

원본 WAV·사진·동의 자료·개인 모델은 공개 저장소에 넣지 않습니다. 음성 보관·삭제 처리는 [voice_training_service.py](api/app/voice_training_service.py), [main.py](api/app/main.py)의 보관 관리 작업과 [voice_consents.py](api/app/voice_consents.py)를 함께 확인합니다.

<a id="개발환경과-실행"></a>
<a id="로컬-개발과-실기-확인"></a>

<a id="설치-및-실행"></a>

## 설치 및 실행

<a id="api-로컬-실행"></a>

### ① API 로컬 실행

Python 3.12 가상환경에서 실행합니다. 아래 인증값은 로컬 시험용 예시입니다.

```sh
cd Pauseable.apps/api
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
export PAUSEABLE_ENV=development
export STORAGE_BACKEND=local
export PAUSEABLE_APP_TOKEN=LOCAL_DEVELOPMENT_ONLY
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Windows PowerShell에서는 `.\.venv\Scripts\Activate.ps1`로 활성화하고 `export NAME=value` 대신 `$env:NAME="value"`로 설정합니다.

<a id="flutter-실행"></a>

### ② Flutter 실행

새 터미널에서 저장소 루트를 기준으로 시작합니다.

```sh
cd Pauseable.apps/guardian
flutter pub get
flutter analyze
flutter test
flutter run -d chrome --web-port=18109 --dart-define=API_BASE_URL=http://127.0.0.1:8000 --dart-define=APP_TOKEN=LOCAL_DEVELOPMENT_ONLY
```

운영 API 주소와 실제 인증값은 공개 README의 예시와 분리합니다. Android의 FCM에는 프로젝트에 맞는 Firebase 클라이언트 설정과 OS 알림 권한이 필요합니다.

Android APK는 [Android Push 설정](guardian/docs/ANDROID_PUSH_SETUP_KO.md#팀원의-pc에서-빌드하기)에 따라 PC에서 빌드합니다. 공유 App Token을 포함하는 [Actions 수동 빌드](../.github/workflows/native-push-apk.yml)는 저장소 이름과 비공개 조건을 확인하며, 현재 공개 제출 저장소에서는 건너뜁니다. 실제 인증값이 포함된 APK는 공개 저장소와 분리해 관리합니다.

위 로컬 설정은 같은 PC의 API·웹 앱 시험용입니다. Pi 사건·사진 업로드에는 Device Token, 음성 학습에는 Worker Token과 R2 연결을 추가로 준비합니다. 기상청 Key나 서버용 Firebase 키는 Flutter 앱에 넣지 않습니다.

<a id="자동-검사와-팀-실기-기록"></a>

<a id="검사와-실기-확인"></a>

## 검사와 실기 확인

| 검사 | 명령·확인 위치 |
| --- | --- |
| API 회귀 | `api/`에서 `python -m unittest discover -s tests -t . -p 'test_*.py'` |
| Flutter | `guardian/`에서 `flutter analyze`, `flutter test` |
| Android Push | [ANDROID_PUSH_SETUP_KO.md](guardian/docs/ANDROID_PUSH_SETUP_KO.md) |
| 실제 알림·사진 | [REAL_DEVICE_ALERT_VERIFICATION.md](guardian/docs/REAL_DEVICE_ALERT_VERIFICATION.md) |
| 로컬 웹 중계 | [RENDER_WEB_PREVIEW_KO.md](guardian/docs/RENDER_WEB_PREVIEW_KO.md) |

실기에서는 같은 사건 ID의 API 저장·읽음 처리·잠금 화면 알림·사진을 대조합니다. 샘플 카메라 자료와 실제 `pi4_camera` 자료는 화면에서 구분합니다.

<a id="개인정보와-운영-범위"></a>

<a id="운영-설정"></a>

## 운영 설정

서버 운영 시 `PAUSEABLE_ENV=production`을 지정하고 App·Device·Worker Token을 각각 설정합니다. 개발 모드에서는 설정하지 않은 역할의 인증 검사가 생략되므로 위 로컬 실행 예시를 외부에 공개하지 않습니다. `STORAGE_BACKEND=r2`에는 R2 연결도 필요합니다.

FCM 서버 키·VAPID 개인키·Device/Worker Token은 앱 빌드에 넣지 않습니다. 현재 공유 App Token은 팀 운용용이며 사용자별 로그인·대상자 권한 분리와 다릅니다. APK도 인증값을 포함할 수 있으므로 운영 APK는 별도로 관리합니다.
