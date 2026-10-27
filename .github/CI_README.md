# PAUSEABLE / CI

파트별 자동 검사와 Android 시험 APK 빌드를 정의합니다. 실행 서비스나 장치 배포 코드는 이 폴더가 아니라 [Deploy](../Pauseable.deploy/README.md)와 각 파트에 있습니다.

GitHub가 `.github/README.md`를 프로젝트 홈에 우선 표시하기 때문에, 이 폴더의 안내는 `CI_README.md`로 둡니다. 전체 소개는 저장소 루트의 README에서 시작합니다. [GitHub의 README 선택 규칙](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)을 참고합니다.

[전체 프로젝트](../README.md) · [AI](../Pauseable.ai/README.md) · [Apps](../Pauseable.apps/README.md) · [Edge](../Pauseable.edge/README.md)

## Workflows

| 파일 | 검사·산출물 | 주요 실행 조건 |
| --- | --- | --- |
| [`ha-report-checks.yml`](workflows/ha-report-checks.yml) | HA report regression, 일반·`python -O` 검사 | 관련 경로 PR·main push·수동 |
| [`native-alert-checks.yml`](workflows/native-alert-checks.yml) | API tests·공유 catalog·웹 알림·날씨, Flutter analyze/test/web/APK | 관련 경로 PR·main push·수동 |
| [`voice-checks.yml`](workflows/voice-checks.yml) | Worker/pipeline tests·Python compile·설정 JSON·모델 updater tests | 관련 경로 push·PR |
| [`favorite-music-checks.yml`](workflows/favorite-music-checks.yml) | 음악 Player·라우팅 회귀·Shell 문법 | 관련 경로 PR·main push·수동 |
| [`native-push-apk.yml`](workflows/native-push-apk.yml) | 비공개 팀 시험 APK와 SHA-256 | `workflow_dispatch` 수동 실행 |

경로 조건의 정확한 목록은 각 workflow의 `on` 정의를 확인합니다. README만 바뀐 commit에서는 경로 필터 때문에 일부 또는 전부가 실행되지 않을 수 있습니다.

## 기준 환경

| 영역 | 정의된 환경 |
| --- | --- |
| HA report·API·Favorite Music | Python 3.12 |
| Voice 검사 | Python 3.11 |
| Flutter | Flutter 3.47.6 |
| Android 빌드 | JDK 17, Android SDK 36, workflow의 실행기 설정 |

버전은 CI 정의와 각 파트의 `requirements`·`pubspec`을 기준으로 맞춥니다. 서로 다른 AI·API·Voice 의존성을 한 Python 환경에 무조건 합치지 않습니다.

## Android 시험 APK

```text
Actions → Build Android push test APK → Run workflow
  → 소스 검사·Flutter 테스트
  → 승인된 비공개 빌드 설정
  → APK + SHA-256 artifact
```

| 설정 | 용도 |
| --- | --- |
| Actions Variable `PAUSEABLE_FIREBASE_ANDROID_CONFIG_JSON` | Android 앱의 Firebase 클라이언트 설정 |
| Actions Secret `PAUSEABLE_APP_TOKEN` | 비공개 팀 시험 앱의 API 인증 |

서버용 Firebase 서비스 계정 JSON·Device Token·Worker Token·R2 키는 APK 빌드에 넣지 않습니다. 서비스 계정과 `google-services.json`은 서로 다른 파일입니다.

수동 APK workflow는 비공개 `RACOS-Team/Pauseable`에서 실행되도록 제한되어 있고 artifact 보관 기간은 3일입니다. 현재 공유 App Token·시험용 서명 빌드는 공개 배포용 인증·릴리스 체계를 대신하지 않습니다. 상세 준비와 실제 휴대폰 수신 확인은 [Android Push 안내](../Pauseable.apps/guardian/docs/ANDROID_PUSH_SETUP_KO.md)를 따릅니다.

## 자동 검사와 실기 검증의 차이

| CI에서 확인하는 것 | 별도 확인할 것 |
| --- | --- |
| 모의 API·플레이어와 회귀 테스트 | 실제 Render·YouTube·Pi 화면·스피커 |
| Flutter 분석·테스트·빌드 | 설치한 휴대폰의 알림 권한·FCM 수신·잠금 화면 |
| report 데이터·검증 로직 | 실제 가구 데이터·장기 운영·탐지 성능 |
| Worker·모델 교체 코드 | GPU 학습·R2 게시·Pi 설치·로컬 합성 |

workflow가 존재한다고 최신 실행이 성공한 것은 아닙니다. Actions 실행 결과와 대상 commit을 확인합니다. 현재 정의만으로 Central·센서·카메라·가전·앱 전체를 연결한 E2E 검사가 완성되었다고 설명하지 않습니다.

## 수정 전 확인

1. 수정하는 파트의 테스트와 경로 필터를 확인합니다.
2. 공유 계약 변경이면 producer·consumer 회귀 검사도 확인합니다.
3. 검사 실패를 숨기기 위해 테스트·인증·권한 조건을 완화하지 않습니다.
4. 실제 장치 동작이나 Push 발송을 CI에 추가할 때는 모의 시험과 명확히 분리합니다.
