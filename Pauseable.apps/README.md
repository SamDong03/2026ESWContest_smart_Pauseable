# 보호자 앱과 API 서버

이 폴더의 `guardian/`은 보호자가 사용하는 Flutter 앱이고, `api/`는 앱과 장치 사이의 FastAPI 서버입니다. **앱은 상황 확인과 설정 입력을, API는 사건·파일·설정 저장과 알림 전달을 담당합니다.** 행동 분석은 Pi 5, 음성 모델 학습은 GPU Worker에서 수행합니다.

[전체 시스템](../README.md) · [AI 분석](../Pauseable.ai/README.md) · [Central·장치](../Pauseable.edge/README.md) · [통신 형식](../Pauseable.contracts/README.md)

| 읽을 부분 | 설명하는 내용 |
| --- | --- |
| 1. API | 장치가 보낸 사건을 인증하고 저장하는 과정 |
| 2~3. Guardian·알림 | 보호자가 보는 화면과 실시간 알림 전달 |
| 4~5. 녹음·설정 | 음성 학습 입력과 장치에서 사용하는 설정 |
| 6~9. 실행·검사 | 로컬 실행, 코드 위치, 실기 확인과 비공개 설정 |

<a id="api-구현-상세"></a>

## 1. API: 장치 사건을 앱에서 조회할 수 있도록 저장한다

### 1.1 요청한 프로그램을 확인한다

[security.py](api/app/security.py)는 앱·장치·Worker의 요청을 서로 다른 Token으로 검사합니다.

| 요청 주체 | 인증값 | 주로 하는 일 |
| --- | --- | --- |
| 보호자 앱 | `PAUSEABLE_APP_TOKEN` | 이력·사진 조회, 설정·동의·녹음 등록 |
| Pi 장치 | `PAUSEABLE_DEVICE_TOKEN` | 사건·사진 전송, 지역·곡·모델 조회 |
| GPU Worker | `PAUSEABLE_WORKER_TOKEN` | 학습 Job 임대·갱신·결과 게시 |

`PAUSEABLE_ENV=production`에서는 필요한 Token이 설정되지 않으면 운영을 막습니다. 현재 공유 App Token은 팀 시험용이며 사용자별 로그인과 대상자 접근권한 분리까지 구현한 방식은 아닙니다.

### 1.2 Central의 사건을 받는다

1. Central이 Device 인증으로 `POST /api/events/decisions`에 최종 판단을 보냅니다.
2. [main.py](api/app/main.py)가 메시지 형식, UTC 시각, actions와 사건 ID를 검사합니다.
3. 같은 `event_id`·같은 내용은 재전송으로 처리하고 다른 내용은 충돌로 구별합니다.
4. `Idempotency-Key` 헤더가 있으면 본문의 사건 ID와 비교합니다.
5. 사건을 이력에 저장한 뒤 알림 전달 정책을 적용합니다.

Central의 수신 검증·실행 정책과 API의 인증·저장은 다른 단계입니다. [공통 메시지 규격](../Pauseable.contracts/README.md)을 함께 확인합니다.

### 1.3 사건 외의 자료를 저장한다

| 범주 | API가 관리하는 내용 |
| --- | --- |
| 알림 이력 | 대상자별 조회, 읽음 상태, WebSocket ticket |
| 출입 사진 | Pi 4 업로드, 비공개 저장, 인증된 이미지 조회 |
| 돌봄 설정 | 대상자 이름·호칭, 거주지역, 선호 YouTube 목록 |
| 알림 설정 | 기기·브라우저 Push 등록, 반복행동 알림 중지 만료 시각 |
| 음성 학습 | 동의, 녹음 세트·clip, Job 상태, 모델 게시와 설치 확인 |

`STORAGE_BACKEND=local`은 로컬 저장을, `r2`는 Cloudflare R2 저장을 사용합니다. 실제 운영에는 역할별 Token·HTTPS·영속 저장소를 준비합니다. 음성 학습처럼 R2를 사용하는 경로는 별도 저장소 설정이 필요합니다.

<a id="보호자-앱-상세"></a>

## 2. Guardian: 보호자가 상황과 설정을 확인한다

앱 담당: **권태준 ([ktj-oss](https://github.com/ktj-oss))**. Flutter 화면·상태 관리와 API·알림·녹음·설정 연동을 구현했습니다.

### 2.1 앱을 열고 데이터를 가져온다

기본 [main.dart](guardian/lib/main.dart)는 API Repository를 사용합니다. `GuardianRepository`가 화면과 데이터 접근을 분리하고, [api_config.dart](guardian/lib/config/api_config.dart)가 `API_BASE_URL`·`PATIENT_ID`·`APP_TOKEN`을 읽습니다. Token 누락·인증 실패는 오류로 표시하며 Mock 데이터로 자동 전환하지 않습니다.

### 2.2 알림과 출입 사진을 확인한다

| 화면 | 표시·처리 |
| --- | --- |
| 홈 | 대상자 이름, 최근 알림, 앱과 알림 서버의 연결 상태 |
| 알림 | 감지 내용·시각, 상세 보기와 읽음 처리 |
| 기록 | 출입 사진과 촬영 시각, 확대·조회 재시도, 사진이 없을 때 빈 상태 |
| 설정 | 보호자 정보, 알림·음성·지역·선호 음악 등 돌봄 설정 |

사진은 Pi 4에서 업로드한 뒤 앱이 인증된 이미지 바이트로 조회합니다. `source=mock_camera` 또는 `asset://` 사진은 샘플로 표시하고, `pi4_camera` 사진에는 샘플 문구를 붙이지 않습니다.

### 2.3 최신 화면에서 제외한 내용을 구분한다

| 항목 | 현재 앱의 처리 |
| --- | --- |
| 미확인 위치·활동·안전·오늘 상태·마지막 연결 | 홈에서 표시하지 않음 |
| 가상 기기 정상 연결 상태·고정 센서 이력 | 설정·기록에서 숨기고 가상 연결 조회·재확인도 호출하지 않음 |
| 전화 걸기·SOS·빠른 실행 | 실제 전화·긴급기관 연동이 없어 버튼을 숨김 |
| 데모 상황 시뮬레이터·기본 샘플 | 남아 있으므로 실제 장비 기록과 구분 |

API의 이전 가상 요청 경로는 호환을 위해 유지합니다. 앱의 ‘실시간 알림 서버 연결됨’은 앱과 서버 사이의 연결만 나타냅니다. 화면의 표시 범위는 [화면 테스트](guardian/test/widget_test.dart)에서도 확인할 수 있습니다.

<a id="알림-수신과-일시-중지"></a>

## 3. 새 사건을 실시간 알림으로 전달한다

### 3.1 앱이 열려 있을 때

1. 앱이 `POST /api/patients/{patient_id}/alert-websocket-ticket`으로 일회용 ticket을 받습니다.
2. ticket으로 `/ws/alerts`에 연결합니다.
3. API가 저장한 새 사건을 전달하면 앱이 목록을 갱신합니다.
4. 연결이 끊기면 재연결 상태와 재시도를 처리합니다.

장기 App Token을 WebSocket URL에 직접 넣지 않습니다. REST API는 이전 이력·설정·사진을 조회할 때 사용합니다.

### 3.2 시스템 알림이 필요할 때

| 환경 | 사용하는 경로 | 준비 |
| --- | --- | --- |
| Android | Firebase Cloud Messaging(FCM) | Firebase 설정, 기기 등록, OS 알림 권한 |
| 웹 | Web Push | 브라우저 구독, 서비스워커, OS·브라우저 알림 권한 |

API의 Push 요청 성공과 휴대폰의 실제 표시는 별도로 확인합니다. Android는 앱 실행 중·백그라운드·잠금·절전 상태에서 시험합니다. iOS 네이티브 Push는 현재 실기 검증 범위가 아닙니다.

### 3.3 반복행동 알림을 잠시 중지할 때

보호자는 30분·1시간·3시간·24시간 중 하나를 선택합니다. API는 만료 시각을 저장하고, 앱은 재접속 후 그 상태를 복원합니다. 만료 또는 수동 재개 후에는 새 알림부터 다시 전달합니다.

| 중지 기간의 처리 | 동작 |
| --- | --- |
| 반복행동 WebSocket·Web Push·FCM | 전달 중지 |
| 반복행동 이력 | 계속 저장. 재개 시 지난 알림을 몰아서 재발송하지 않음 |
| 배회 알림·출입 사진 | 유지 |
| Pi의 감지·TTS·가전 | 유지 |
| 중지 저장 실패 | 완료로 표시하지 않음 |
| 중지 상태 조회 장애 | 알림 전달 유지 |

경로는 `GET/POST/DELETE /api/patients/{patient_id}/repetitive-alert-pause`입니다. R2 모드에서는 `patients/{patient_id}/repetitive-alert-pause.json`에 보관합니다. 이미 전송 중이거나 도착한 알림을 취소하는 기능은 아닙니다.

<a id="음성-녹음과-동의"></a>

## 4. 보호자 목소리를 수집하고 학습 상태를 확인한다

1. [동의 화면](guardian/lib/screens/voice_recording_consent_sheet.dart)에서 동의 버전과 서버 영수증을 확인합니다.
2. 160문장의 고정 대본으로 문장별 녹음을 진행합니다. 녹음은 PCM16·16 kHz·mono WAV, 문장당 최대 45초입니다.
3. 문장 종료 후 업로드합니다. 실패한 clip은 녹음 화면이 열린 동안 재전송할 수 있습니다.
4. API가 녹음 세트와 학습 Job 상태를 관리하고, GPU Worker가 모델을 학습합니다.
5. 모델 게시와 Pi의 검증·설치 상태를 확인합니다. 완료 세트에서 다시 학습하려면 새 세트를 만들고 문장 1번부터 수집합니다.

권장 총 녹음시간 800초는 입력 상한이 아닙니다. 녹음 화면 종료 후 실패 자료의 영구 복구와 전체 삭제·동의 철회 UI는 아직 제공하지 않습니다. 동의 거부·저장 실패는 녹음과 업로드만 막고 기존 알림·사진 조회는 유지합니다.

다음 과정: [Voice 전처리·학습](../Pauseable.ai/README.md#voice-학습과-운영-상세) · [Pi 모델 교체](../Pauseable.edge/README.md#음성-모델-교체)

## 5. 돌봄 설정을 장치에 연결한다

| 설정 | 저장한 뒤 사용하는 곳 |
| --- | --- |
| 대상자 이름·가족관계·`patient_call_name` | Pi의 안내 문장과 TTS 호칭 |
| 거주지역·기상청 격자 | [환경 조명 모듈](../Pauseable.integrations/README.md)의 Device 조회 |
| 좋아하는 YouTube 영상 | [Pi 음악 모듈](../Pauseable.edge/README.md#선호-음악-설치와-시험)의 현재 목록 조회·무작위 선택 |
| 안전 알림·알림음 | 서버 알림 정책과 앱 알림 상태 |

선호곡은 형식·중복을 검사하며 최대 30곡입니다. 지역 설정은 GPS 추적이나 상세 주소 기능이 아닙니다. 앱의 `auto_lighting_enabled` 저장과 장치 타이머 시작·중지는 직접 연결되어 있지 않습니다. 테마 변경은 현재 앱 실행 중에만 유지됩니다.

<a id="개발환경과-실행"></a>

## 6. 로컬에서 실행하는 순서

### 6.1 API를 먼저 실행한다

Python 3.12를 사용합니다. **저장소 루트에서 API 폴더로 이동한 뒤** 가상환경을 만듭니다.

```sh
cd Pauseable.apps/api
python -m venv .venv
```

운영체제에 맞는 한 가지 방법으로 활성화하고 로컬 시험 설정을 지정합니다.

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

이후 API 폴더에서 설치·검사·서버 실행을 진행합니다. 위 Token은 로컬 시험용입니다.

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -t . -p "test_*.py"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`http://127.0.0.1:8000/health`에서 서버 상태, `http://127.0.0.1:8000/docs`에서 API를 확인합니다.

이 설정은 같은 PC의 웹 앱으로 조회·설정을 시험하는 용도입니다. Pi의 사건·사진 전송에는 Device Token, 음성 Worker 연결에는 Worker Token과 저장소 설정이 추가로 필요합니다. Android 실장비의 `127.0.0.1`은 개발 PC가 아니라 휴대폰 자신이므로 실장비에서는 접근 가능한 API 주소를 사용합니다.

### 6.2 Flutter 앱을 실행한다

Flutter 3.47.6·Dart `^3.13.0` 기준입니다. 새 터미널에서 **저장소 루트부터** 시작합니다.

```sh
cd Pauseable.apps/guardian
flutter pub get
flutter analyze
flutter test
flutter run -d chrome --web-port=18109 --dart-define=API_BASE_URL=http://127.0.0.1:8000 --dart-define=APP_TOKEN=LOCAL_DEVELOPMENT_ONLY
```

대상자를 바꾸면 `PATIENT_ID`도 서버와 맞춥니다. Render 연결은 [비공개 로컬 중계 가이드](guardian/docs/RENDER_WEB_PREVIEW_KO.md)의 `render-web.secrets.json`과 `python -m tools.serve_render_web --build`를 사용합니다. 이 경로는 실제 서버의 저장·삭제·업로드를 변경하므로 로컬 모의 시험과 구분합니다.

### 6.3 Android에서 알림을 시험한다

JDK 17·Android SDK 36과 [Firebase 설정](guardian/docs/ANDROID_PUSH_SETUP_KO.md)을 준비합니다. 앱 폴더에서 비공개 설정 파일로 빌드합니다.

```sh
flutter build apk --release --dart-define-from-file=android-test.secrets.json
```

APK는 `build/app/outputs/flutter-apk/app-release.apk`에 생깁니다. [Actions 수동 빌드](../.github/CI_README.md#android-시험-apk)는 비공개 저장소에서만 실행되며 공개 제출 저장소에서는 건너뜁니다. 설치 후에는 [실기 알림 확인 절차](guardian/docs/REAL_DEVICE_ALERT_VERIFICATION.md)를 진행합니다.

<a id="주요-코드"></a>

## 7. 기능별 코드 위치

| 범주 | 시작할 파일·폴더 |
| --- | --- |
| API 경로·인증 | [main.py](api/app/main.py), [security.py](api/app/security.py) |
| 저장·음성·알림 서비스 | [api/app](api/app) |
| 앱 진입점·구성 | [main.dart](guardian/lib/main.dart), [app.dart](guardian/lib/app.dart) |
| API 접근·데이터 형식 | [repositories](guardian/lib/repositories), [models](guardian/lib/models) |
| Push·녹음·연결 | [services](guardian/lib/services) |
| 홈·알림·기록·설정 | [screens](guardian/lib/screens) |
| 지역 목록·대본 | [assets](guardian/assets) |
| 자동 검사 | [API tests](api/tests), [Flutter test](guardian/test), [워크플로](../.github/workflows/native-alert-checks.yml) |

<a id="검증-기록과-실기-확인"></a>
<a id="자동-검사와-팀-실기-기록"></a>

## 8. 검사 결과와 실기 확인

앱 폴더에서 `flutter analyze`, `flutter test`, `node --test test/web_push_service_worker.test.cjs`를 실행합니다. API 폴더에서는 위 `unittest` 명령을 사용합니다. 현재 검사 결과는 대상 commit의 Actions 로그에서 확인합니다.

<details>
<summary>이전 버전의 검사·팀 시험 기록</summary>

| 대상 버전 | 저장된 기록 |
| --- | --- |
| [d2b49a8](https://github.com/SamDong03/2026ESWContest_smart_Pauseable/commit/d2b49a8a32beeb5fca4e61e0be0a20a7f60fc27b) · 음악 연동 | Flutter 85개, API 158개, 웹 서비스워커 6개 통과, 웹·APK 빌드 성공 |
| [dae8b91](https://github.com/SamDong03/2026ESWContest_smart_Pauseable/commit/dae8b9199c18d834c9f4168b5a20707d2c4c413f) · 홈 표시 정리 | Flutter 91개, API 166개, 웹 서비스워커 6개 통과 |

Render 선호곡 저장·재조회와 음성 동의 저장, Chrome 탭을 닫은 상태의 웹 Push는 팀 시험 기록이 있습니다. 배회·야간 현관 사진은 팀원의 휴대폰 실장비 시연 성공 보고가 있습니다. 위 수치는 해당 버전의 기록이며 최신 변경을 같은 수로 재시험했다는 뜻은 아닙니다.

</details>

새 버전에서는 API 수신·이력 저장·Push 요청·실제 알림 표시를 나누어 확인합니다. 선호곡 재생, 음성 학습부터 Pi 합성까지의 연결, 앱 지역에 맞는 조명 반응도 설치 버전별 실기 시험 대상입니다.

### 문제 해결

| 증상 | 먼저 확인할 곳 |
| --- | --- |
| API `401/403` | Token 누락·불일치·App/Device/Worker 역할 혼용 |
| API `404` | 서버 버전·요청 경로·대상자 ID |
| `18108` 접속 거부 | Render 웹 미리보기 중계 서버 실행 여부 |
| 사진 조회 실패 | 업로드 기록과 인증된 이미지 응답 |
| 열린 앱에서만 알림 | Push 등록·Firebase·브라우저/OS 권한 |
| 녹음·업로드 실패 | 동의 영수증·마이크·세트 상태·서버 연결 |
| 곡은 저장되지만 재생 안 됨 | Pi 설치·대상자·cooldown·Player 로그 |

<a id="개인정보와-운영-설정"></a>

## 9. 비공개 설정 관리

`*.secrets.json`·`.env`·`android/app/google-services.json`은 Git 제외 대상입니다. Device/Worker Token, R2 키, VAPID 개인키와 Firebase 서비스 계정을 앱에 넣지 않습니다. 웹에 실제 공유 Token을 직접 빌드하면 JavaScript에서 노출될 수 있고, APK도 추출 가능성을 전제로 팀 내부에서만 사용합니다.

서버 배포, APK 설치, Pi 설정은 각각 적용해야 합니다. 파일 갱신만으로 실행 중인 서버와 장치가 함께 바뀌지는 않습니다.
