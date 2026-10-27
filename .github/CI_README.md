# GitHub Actions 검사와 Android 빌드

이 폴더의 `workflows/`는 코드를 바꿨을 때 실행할 검사와 빌드 순서를 정의합니다. 이를 **CI**라고 합니다. 관련 경로의 변경을 감지하고, 임시 실행 환경에서 의존성을 설치한 뒤 테스트·분석·빌드를 수행합니다.

[전체 시스템](../README.md) · [AI](../Pauseable.ai/README.md) · [Apps](../Pauseable.apps/README.md) · [Edge](../Pauseable.edge/README.md) · [배포](../Pauseable.deploy/README.md)

<a id="자동-검사-구성"></a>

## 1. 변경한 파트의 Workflow를 확인한다

| Workflow | 실행하는 검사·빌드 | 시작 조건 |
| --- | --- | --- |
| [native-alert-checks.yml](workflows/native-alert-checks.yml) | API·공유 목록·서비스워커·날씨, Flutter analyze/test/web/APK | 관련 경로 PR·main push·수동 |
| [voice-checks.yml](workflows/voice-checks.yml) | Voice Worker·파이프라인·모델 교체 테스트, Python·JSON 검사 | 관련 경로 push·PR |
| [favorite-music-checks.yml](workflows/favorite-music-checks.yml) | 음악 Player·출력 필터·Shell 문법 | 관련 경로 PR·main push·수동 |
| [native-push-apk.yml](workflows/native-push-apk.yml) | 비공개 팀 시험 APK·SHA-256 | 수동 `workflow_dispatch` |

정확한 경로 조건은 각 파일의 `on.paths`를 확인합니다. README만 바뀌면 경로 조건에 따라 일부 또는 전체 검사가 실행되지 않을 수 있습니다.

<a id="기준-환경"></a>

## 2. Workflow가 검사 환경을 준비한다

| 대상 | 정의한 환경 |
| --- | --- |
| API·날씨·음악 | Python 3.12 |
| Voice | Python 3.11 |
| Flutter | Flutter 3.47.6 |
| Android | JDK 17·Android SDK 36 및 각 Workflow 실행기 |

각 job은 저장소 checkout, 도구·의존성 준비, 파트별 검사 순으로 진행합니다. API와 앱이 공유하는 지역 목록·음성 대본도 대조합니다. 실제 Token은 공개 소스 대신 Actions 변수·Secret에서 필요한 작업에만 제공합니다.

HA의 Python 3.12 검사는 현재 Workflow에 없으므로 [AI README의 로컬 명령](../Pauseable.ai/README.md#로컬-검사)으로 별도 실행합니다. 코드가 저장소에 있다는 사실과 CI에서 자동 검사한다는 사실은 구분합니다.

## 3. 검사 결과를 읽는다

1. 저장소의 **Actions**에서 대상 commit의 실행을 선택합니다.
2. 실패한 job과 step을 열고 오류와 실행 명령을 확인합니다.
3. 코드·계약·설정 중 무엇이 바뀌었는지 대조합니다.
4. 수정한 뒤 같은 범위의 검사를 다시 실행합니다.

검사 성공, APK 생성과 실제 장치 동작은 서로 다른 결과입니다. 현재 Workflow에는 정식 Atlas Central `.ipk` 빌드와 전체 센서 E2E job이 없습니다.

<a id="android-시험-apk"></a>

## 4. Android 시험 APK를 수동으로 만든다

이 작업은 App Token을 포함하는 비공개 팀 시험용입니다. 공개 제출 저장소에서는 `github.event.repository.private` 조건에 따라 건너뜁니다. 공개 상태에서 시험 APK가 필요하면 [로컬 비공개 빌드](../Pauseable.apps/guardian/docs/ANDROID_PUSH_SETUP_KO.md#팀원의-pc에서-빌드하기)를 사용합니다.

1. **Actions → Build Android push test APK → Run workflow**를 선택합니다.
2. 빌드할 버전을 고릅니다.
3. Workflow가 Flutter 분석·테스트 후 비공개 Android 설정을 준비합니다.
4. release APK와 SHA-256을 생성해 artifact로 올립니다.
5. 휴대폰에 설치한 뒤 실제 알림 수신을 시험합니다.

| Actions 설정 | 용도 |
| --- | --- |
| Variable `PAUSEABLE_FIREBASE_ANDROID_CONFIG_JSON` | Android 앱 Firebase 클라이언트 설정 |
| Secret `PAUSEABLE_APP_TOKEN` | 팀 시험 앱 API 인증 |

Workflow의 저장소 식별자는 `SamDong03/2026ESWContest_smart_Pauseable`이며 비공개 상태에서만 실행하도록 제한합니다. artifact 보관 기간은 3일입니다. Firebase 서버용 서비스 계정과 Device/Worker Token·R2 키를 APK에 넣지 않습니다. 시험 서명과 공유 App Token은 공개 배포의 서명·로그인 관리와 구분합니다.

[Android Push 설정](../Pauseable.apps/guardian/docs/ANDROID_PUSH_SETUP_KO.md) · [실기 알림 확인](../Pauseable.apps/guardian/docs/REAL_DEVICE_ALERT_VERIFICATION.md)

<a id="자동-검사와-실기-검증의-차이"></a>

## 5. 실제 장치에서 남은 연결을 확인한다

| 자동 검사에서 다루는 범위 | 별도 실기 시험 |
| --- | --- |
| 모의 API·임시 저장소·Player 응답 | 실제 Render·Pi 화면·스피커·YouTube 재생 |
| Flutter 분석·테스트·빌드 | 설치한 휴대폰의 권한·잠금·절전·Push 수신 |
| 파트별 모의 입력·검사 코드 | 실제 가구 데이터·장기 운영·탐지 성능 |
| Worker·모델 교체 코드 | GPU 학습·R2 게시·Pi 설치·합성 |

HA 모듈 검사는 [AI 안내](../Pauseable.ai/README.md#로컬-검사)의 명령으로 별도 실행합니다. Voice 검사는 실제 GPU 학습, 음악 검사는 실제 YouTube 재생을 수행하지 않습니다.

<a id="검사-유지-기준"></a>

## 6. 검사를 바꿀 때 함께 확인한다

공유 계약을 바꾸면 보내는 프로그램과 받는 프로그램의 회귀 검사도 함께 수정합니다. 새 테스트가 경로 필터에 포함되는지 확인하고, 실장비·Push 발송처럼 외부 상태를 바꾸는 시험은 모의 검사와 분리합니다.
