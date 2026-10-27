# Pauseable Android 실제 휴대폰 알림 설정과 확인

기존 `pauseable-api` Render 서버, 반복행동 결정 API, 알림 이력, 앱 화면을 그대로 사용한다.
이번 Android 알림 경로는 `Pi → Render → Firebase Cloud Messaging(FCM) → 설치한 APK`이다.
FCM은 휴대폰에 알림을 전달하는 서비스이며, 별도 API 서버를 만드는 절차가 아니다.

휴대폰 알림 코드는 PR #19로 main에 반영되었고 기존 Render 서버의 배포가 Live인 것을 확인했다.
수동 APK 빌드 워크플로도 main에 게시되어 있다. 서비스 계정 키와 빌드 토큰을 설정하고 새 APK를 설치해야 실제 휴대폰 알림을 시험할 수 있다.
배포 완료와 실제 휴대폰 수신 확인은 각각 기록한다.

## 1. Firebase Android 앱 설정

1. 팀에서 관리할 Google 계정으로 [Firebase 콘솔](https://console.firebase.google.com/)에 접속한다. 이번에 만든 **Pauseable**, 프로젝트 ID **`pauseable-862fe`**를 사용한다.
2. Firebase 프로젝트에 Android 앱을 등록한다. 패키지 이름은 정확히 `com.pauseable.pauseable_guardian`이다.
3. 해당 Android 앱의 `google-services.json`을 다운로드하여 `Pauseable.apps/guardian/android/app/google-services.json`에 둔다.
4. 승인 후 Google Cloud의 `pauseable-862fe` 프로젝트 **IAM 및 관리자 → 서비스 계정**에서 전송용 전용 계정을 준비한다.
   계정 ID는 `pauseable-fcm-sender`, 역할은 **Firebase Cloud Messaging API Admin**, 역할 ID는 정확히 **`roles/firebasecloudmessaging.admin`**이다.
   이 역할에 FCM HTTP v1 전송 권한인 `cloudmessaging.messages.create`가 포함된다. [Google Cloud 역할 정의](https://docs.cloud.google.com/iam/docs/roles-permissions/firebasecloudmessaging)
5. 해당 전용 계정의 **키 → 키 추가 → 새 키 만들기 → JSON**으로 서버용 키를 준비하여 Render Secret File에만 전달한다.
6. Firebase의 **프로젝트 설정 → Cloud Messaging**에서 Firebase Cloud Messaging API 사용 가능 여부를 확인한다.

`google-services.json`은 Android 앱 설정이다. 서비스 계정 JSON은 서버 권한을 가진 비밀 파일이다.
서비스 계정 JSON을 APK 폴더, Dart 코드, GitHub에 넣지 않는다. 두 파일의 Firebase 프로젝트가 같아야 한다.
앱 설정 파일이 없는 빌드도 기존 기능을 위해 가능하지만, 그런 APK에서는 휴대폰 푸시가 활성화되지 않는다.
시험 휴대폰은 Android 7.0(API 24) 이상이며 Google Play 서비스가 있어야 한다. [Firebase Flutter 설정 문서](https://firebase.google.com/docs/cloud-messaging/flutter/get-started)

## 2. 기존 Render 서버에 FCM 연결

대상은 [기존 pauseable-api 서비스](https://dashboard.render.com/web/srv-dacls7rm8hqs73bbl84g)이다.
저장소는 `RACOS-Team/Pauseable`를 사용한다. 이 구조를 GitHub에 반영할 때 기존 Render API의 Root Directory를 `Pauseable.apps/api`, Build Command를 `python -m pip install -r requirements.txt`, Start Command를 `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`로 함께 변경한다. 로컬 폴더 이동만으로 운영 Render 설정이 바뀌지는 않는다.
휴대폰 알림 API와 `../api/requirements.txt` 변경이 포함된 코드는 배포되어 있다. 아래의 FCM 자격증명 설정을 마친 뒤 환경변수를 사용하는 새 배포를 확인한다.

서비스 **Environment**에 다음을 설정한다.

| 항목 | 값 |
| --- | --- |
| `PAUSEABLE_FCM_ENABLED` | `1` |
| Secret File 이름 | `firebase-service-account.secrets.json` |
| Secret File 내용 | `pauseable-862fe`의 `pauseable-fcm-sender` 서비스 계정 JSON 전체 |
| `GOOGLE_APPLICATION_CREDENTIALS` | `/etc/secrets/firebase-service-account.secrets.json` |

Secret File 대신 환경변수 `PAUSEABLE_FIREBASE_SERVICE_ACCOUNT_JSON`에 서비스 계정 JSON을 넣는 방법도 지원한다. 한 방법만 사용한다.
기존 `PAUSEABLE_APP_TOKEN`, `PAUSEABLE_DEVICE_TOKEN`, R2 설정은 그대로 사용한다.
새 환경변수를 사용하도록 서버를 다시 배포한다. Render Secret File의 실행 경로는 `/etc/secrets/<파일명>`이다. [Render 공식 문서](https://render.com/docs/configure-environment-variables#secret-files)
서비스 계정 준비 절차는 [Firebase Admin 설정 문서](https://firebase.google.com/docs/admin/setup#initialize_the_sdk_in_non-google_environments)를 따른다.
서버 키는 APK 빌드에 사용하지 않으며 GitHub Actions에도 저장하지 않는다.

## 3. 새 APK 만들기

### GitHub에서 수동으로 APK 받기

이미 게시된 [Build Android push test APK 워크플로](https://github.com/RACOS-Team/Pauseable/actions/workflows/native-push-apk.yml)를 사용할 수 있다.
설정 **Secrets and variables → Actions**에 아래 값을 준비한다. Render 앱 토큰을 GitHub로 전달하는 작업은 사용자 승인 후 수행한다.

| 종류 | 이름 | 값 |
| --- | --- | --- |
| Variable | `PAUSEABLE_FIREBASE_ANDROID_CONFIG_JSON` | `pauseable-862fe` 프로젝트의 해당 Android 앱 `google-services.json` 전체 |
| Secret | `PAUSEABLE_APP_TOKEN` | 기존 Render의 `PAUSEABLE_APP_TOKEN` |

Firebase Android 앱 설정은 클라이언트 설정이고, 전송용 서비스 계정 JSON은 서버 비밀 키다. Actions Variable에는 Android 앱 설정을 넣는다.
설정을 완료하면 **Actions → Build Android push test APK → Run workflow → main**을 선택해 수동으로 실행한다.
이 워크플로는 비공개 `RACOS-Team/Pauseable` 저장소에서 수동 실행하며, 분석과 Flutter 테스트가 통과해야 APK를 빌드한다.
완료된 실행의 artifact에서 `pauseable-android-push-test-<커밋>`을 다운로드하고 ZIP 안의 `app-release.apk`를 설치한다.
함께 들어 있는 `app-release.apk.sha256`으로 파일 체크섬을 확인할 수 있다. artifact는 3일 후 만료되므로 그 전에 팀 시험 파일을 받아 둔다.
[GitHub 수동 실행 안내](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)

현재 앱 인증 구조상 `APP_TOKEN`이 APK에 포함되므로 결과 APK는 팀의 비공개 시험 휴대폰에만 전달한다.
현재 Gradle release 빌드는 시험용 debug 서명을 사용한다. CI 실행기마다 키가 달라질 수 있어 이후 APK 업데이트에는 팀의 동일한 서명 키가 필요하다.
공개 배포를 위한 사용자별 로그인과 권한 분리는 별도 작업이다.

### 팀원의 PC에서 빌드하기

빌드 담당자에게 Firebase Android 설정 파일과 Render 앱 토큰을 안전하게 전달한다.
`Pauseable.apps/guardian/android-test.secrets.json`을 로컬에서 만들고 아래 예시의 토큰 자리만 실제 `PAUSEABLE_APP_TOKEN` 값으로 바꾼다.
`PAUSEABLE_DEVICE_TOKEN`을 APK에 넣는 것이 아니다.

```json
{
  "API_BASE_URL": "https://pauseable-api.onrender.com",
  "PATIENT_ID": "byunwoojin",
  "APP_TOKEN": "REPLACE_WITH_RENDER_PAUSEABLE_APP_TOKEN"
}
```

`*.secrets.json`과 Firebase Android 설정 파일은 Git 제외 대상이다. 비밀 값을 채운 파일을 GitHub에 올리지 않는다.
현재 앱의 공유 `APP_TOKEN` 인증 방식을 유지한 팀 시험용 빌드다.

Flutter SDK와 Android 빌드 환경이 갖춰진 PC에서 `Pauseable.apps/guardian` 폴더로 이동해 실행한다.
이 변경은 Flutter 3.47.6으로 분석과 테스트를 확인했으며, APK 빌드에는 Android SDK 36과 JDK 17이 필요하다.
SDK가 없다면 [Flutter Android 환경 설정](https://docs.flutter.dev/platform-integration/android/setup)을 먼저 따른다. Android SDK 라이선스는 빌드 담당자가 직접 확인한다.

```sh
flutter pub get
flutter analyze
flutter test
flutter build apk --release --dart-define-from-file=android-test.secrets.json
```

Windows PowerShell에서는 같은 검사와 빌드를 한 번에 실행할 수 있다.

```powershell
./tools/build_android_push.ps1 -SecretConfig android-test.secrets.json
```

결과 파일은 `Pauseable.apps/guardian/build/app/outputs/flutter-apk/app-release.apk`이다.
팀원이 이전에 준 APK를 이 파일로 교체한다. 이전 APK와 서명 키가 달라 설치가 거부되면 같은 서명 키로 다시 빌드한다.
삭제 후 새로 설치하는 방법은 앱의 로컬 데이터가 사라지므로 시험 휴대폰에서만 선택한다.

## 4. 반복행동 시험 전에 휴대폰 알림부터 확인

1. 새 APK를 설치하고 앱을 한 번 연다.
2. 앱의 **설정 → 휴대폰 알림**에서 **알림 허용** 또는 **재시도**를 누르고 Android 알림 권한 요청을 허용한다.
3. 휴대폰 등록과 서버 준비가 완료되면 **시험 알림 보내기**를 누른다. 서버가 약 10초 뒤 보낸다. 현재 휴대폰의 토큰은 앱 내부에서 사용하며 화면에 노출하지 않는다.
4. 앱을 보고 있는 상태에서 기다려 알림 표시를 확인한다.
5. 다시 시험 버튼을 누른 뒤 바로 홈 버튼을 눌러 다른 앱으로 이동한다. 약 10초 뒤 수신을 확인한다.
6. 앱을 다시 열고 시험 버튼을 누른 뒤 바로 휴대폰을 잠근다. 약 10초 뒤 수신을 확인하고, 알림을 눌러 Pauseable 알림 화면으로 이동하는지 확인한다.

**시험 알림 보내기**는 사용자가 요청한 연결 시험이므로 **안전 이상 알림** 스위치와 무관하게 전송하며 소리가 있는 알림 채널을 사용한다.
실제 소리와 진동은 휴대폰의 채널 설정, 무음 모드, 방해 금지 설정에 따른다.

| 상태 | 확인할 결과 |
| --- | --- |
| 앱 화면을 보고 있음 | 휴대폰 시스템 알림이 표시됨 |
| 앱이 백그라운드에 있음 | 알림 목록에 새 알림이 표시됨 |
| 화면이 잠겨 있음 | 잠금화면/알림 목록에 새 알림이 표시됨(휴대폰 표시 설정에 따름) |
| 알림을 누름 | Pauseable가 열리고 알림 화면으로 이동함 |

Android 설정에서 **강제 종료**한 앱은 다시 열어야 FCM을 받을 수 있다. 앱을 한 번 열고 홈 버튼으로 나가는 방식으로 시험한다.
Android 13 이상은 알림 권한이 필요하다. 알림을 거부했다면 **휴대폰 알림 설정**에서 앱 알림을 허용한 뒤 **재시도**를 누른다.
Android의 채널 목록에서는 **보호자 안전 알림**과 **보호자 안전 알림 (무음)**을 각각 확인한다. 한 채널만 차단하면 다른 채널의 연결은 유지되지만 차단한 채널의 알림은 표시되지 않는다. [Firebase 수신 문서](https://firebase.google.com/docs/cloud-messaging/flutter/receive-messages)

서버 설정만 읽어 확인하려면 아래 명령을 실행한다. 토큰 값은 출력하지 않으며 알림을 보내거나 휴대폰을 등록하지 않는다.

```sh
python tools/verify_native_push.py --config android-test.secrets.json
```

`--send-test` 옵션은 이미 등록된 휴대폰에 알림 한 건을 보내며 FCM 토큰을 숨김 입력으로 받는다.
`--delay-seconds 10`을 추가하면 입력 완료 후 약 10초를 두고 전송하므로 홈 화면/잠금 상태를 시험할 수 있다.
일반 시험에서는 토큰을 꺼내는 대신 앱의 **시험 알림 보내기**를 사용한다.
서버의 `configured: true`는 설정이 준비되었다는 뜻이고, `accepted: 1`은 FCM이 전송 요청을 접수했다는 뜻이다.
최종 성공은 실제 휴대폰 화면에서 확인해야 한다.

## 5. 실제 반복행동 경로 확인

휴대폰 시험 알림이 성공한 뒤 Pi에서 반복행동을 시험한다.
앱의 **설정 → 안전 이상 알림**을 켠다. 이 스위치가 꺼져 있으면 실제 반복행동·배회 휴대폰 푸시를 보내지 않는다.
**알림음**을 켜면 소리가 있는 채널을, 끄면 소리와 진동을 요청하지 않는 채널을 사용한다. 소리를 끈 경우에도 알림 목록에는 표시된다.
시험 알림에서 소리가 났다는 이유로 실제 행동 알림의 **알림음** 설정이 켜진 것으로 판단하지 않는다.
알림 설정은 대상자별로 저장한다. `STORAGE_BACKEND=r2`이면 `patients/{patient_id}/notification-preferences.json`의 저장값을 서버 재시작·재배포 후에도 불러온다. 저장값이 없을 때의 기본값은 **안전 이상 알림 켜짐, 알림음 꺼짐**이다. 로컬 저장 모드에서는 파일 보존 여부에 따라 달라지므로, Render의 임시 파일시스템만으로 재배포 후 보존을 보장하지 않는다.
GitHub의 최신 `Pauseable.ai/ha/scripts/start-repetitive-demo.sh`를 실제 Pi의 같은 스크립트 위치에 반영한다.
현재 스크립트는 장비 설정 파일 `/var/lib/pauseable/ha.env`에 Render의 `PAUSEABLE_DEVICE_TOKEN`이 있는지 먼저 확인한다. Central의 기존 `ha.env`도 필요하다. 값을 로그나 화면 공유에 출력하지 않는다.

```sh
/data/ha_ai_fullcycle_20260911/scripts/start-repetitive-demo.sh
```

현재 스크립트는 `ENABLE_GUARDIAN_ALERTS` 값을 읽지 않고 Central 설정에 `REPETITIVE_ACTIONS_ENABLED=1`, `DECISION_GATEWAY_ENABLED=1`을 기록한다. 따라서 별도 옵션 없이 실행해도 서버 전달 설정을 켜며, 옵션을 생략한다고 전달이 꺼지는 것은 아니다. 실제 알림 생성에는 Device Token, Central 승인 및 `notify_guardian` 동작 등 아래의 전송 조건도 충족되어야 한다.
기본 반복행동 알림 간격은 900초다. 같은 단계의 위험을 연달아 시험하면 cooldown 때문에 새 알림이 생기지 않을 수 있다.
휴대폰 전송 자체는 앱의 시험 알림 버튼으로 먼저 확인하고, 실제 행동 경로는 새 이벤트와 정상/위험 전환을 확인하며 시험한다.

같은 이벤트 ID를 다음 순서로 맞춰 본다.

1. Pi Central 로그: 결정 수락, 보호자 알림 동작, gateway outbox 전송.
2. Render: `POST /api/events/decisions` 수신.
3. 서버 알림 이력: 같은 환자와 이벤트의 새 알림 저장.
4. Render FCM 전송 접수와 실제 휴대폰 알림 표시.

새 결정의 HTTP `202`만으로 알림 생성이 증명되지는 않는다. 결정에 `notify_guardian` 동작이 있어야 한다.
같은 이벤트 ID를 다시 보내면 중복으로 처리되며 추가 알림을 보내지 않는다.
상세 Pi 실행 조건은 기존 `Pauseable.docs/ha/DEMO_RUNBOOK_KO.md`의 보호자 알림 절차를 따른다.

## 문제가 남을 때 확인할 지점

| 상태/응답 | 먼저 확인 |
| --- | --- |
| 앱의 알림 설정이 없는 APK | `google-services.json`을 넣고 새 APK 빌드 |
| 서버가 휴대폰 알림을 준비하지 않음 / `configured: false` | FCM 환경변수, 서비스 계정 JSON, 해당 코드 배포 |
| `401` / `403` | APK의 `APP_TOKEN`과 Render `PAUSEABLE_APP_TOKEN` 일치 |
| 등록 또는 시험 API `404` | 새 백엔드 배포 여부, 앱에서 현재 휴대폰 등록 여부 |
| FCM 접수 실패 | Android 설정과 서비스 계정의 Firebase 프로젝트 일치, Cloud Messaging API/권한 |
| FCM 접수 성공, 화면에 없음 | 알림 권한, 알림 채널, 휴대폰 알림 설정, 강제 종료 여부 |
| 시험 버튼은 성공, 반복행동은 실패 | 앱의 **안전 이상 알림**, Pi gateway opt-in, 환자 ID, `notify_guardian`, cooldown, 서버 알림 이력 |
| 실제 행동 알림은 표시되지만 소리가 없음 | 앱의 **알림음**, Android 알림 채널 설정, 휴대폰 무음/방해 금지 설정 |

Android 구현과 실제 수신 확인이 완료되어야 Android 성공으로 기록한다. 기존 APK 수신이나 iPhone 수신까지 확인된 것으로 기록하지 않는다.
