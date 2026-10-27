# PAUSEABLE / Docs

전체 시스템의 운영·검증·연구·시연 자료를 찾는 문서 인덱스입니다. **처음 보는 사람은 현재 구조 → 담당 파트 → 검증 원본 → 실기 절차 순서**로 읽으면 됩니다.

[전체 프로젝트](../README.md) · [AI](../Pauseable.ai/README.md) · [Apps](../Pauseable.apps/README.md) · [Edge](../Pauseable.edge/README.md) · [Deploy](../Pauseable.deploy/README.md)

## 목적별 시작점

| 알고 싶은 내용 | 먼저 볼 자료 |
| --- | --- |
| 전체 구조와 파트 역할 | [프로젝트 README](../README.md) |
| 장치별 설치·이전·확인 | [Deploy README](../Pauseable.deploy/README.md), [배포 인계](DEPLOYMENT_HANDOFF.txt) |
| AI 메시지와 Central 통신 | [Contracts README](../Pauseable.contracts/README.md) |
| HA 수집·학습·판정 | [AI README](../Pauseable.ai/README.md), [실시간 수집](ha/ha_realtime_collection_guide.md) |
| HA 시연과 장치 로그 | [시연 Runbook](ha/DEMO_RUNBOOK_KO.md) |
| 배회 결과의 의미 | [mmWave Runtime](mmwave/RUNTIME.md) |
| 음성 학습 Worker | [Voice 운영](voice/OPERATIONS_KO.md) |
| 녹음·모델 동의와 보관 | [Voice 데이터 정책](voice/DATA_AND_ARTIFACTS_KO.md) |
| 지역·날씨·조명 연결 | [지역 설정 연동](integrations/home-assistant/RENDER_REGION_SETUP_KO.md) |
| 앱 Push·실기 수신 | [Android 설정](../Pauseable.apps/guardian/docs/ANDROID_PUSH_SETUP_KO.md), [실기 점검](../Pauseable.apps/guardian/docs/REAL_DEVICE_ALERT_VERIFICATION.md) |
| 최근 선호 음악 출력 | [Favorite Music](../Pauseable.edge/actions/favorite-music/README.md) |

## 자료 구성

| 경로 | 내용 |
| --- | --- |
| [`ha`](ha) | 수집·자동 운용·Baseline·이상 탐지·공개 데이터·시연 기록 |
| [`mmwave`](mmwave) | 경로 형태·개인 변화·지속성과 결과 해석 |
| [`voice`](voice) | 학습 Worker 운영·데이터·산출물 정책 |
| [`integrations`](integrations) | Home Assistant 지역·날씨 연동 |
| [`evaluation/ha`](evaluation/ha) | HA 평가 원본·보고서 데이터·회귀 검사 |
| [`presentation/ha`](presentation/ha) | 저장된 HA 보고서 PPTX/PDF |
| [`assets`](assets) | README 시스템 구조도 등 문서용 그림 |

## 평가 자료 읽기

**구현된 코드, 기록된 테스트, 현재 장치에서 다시 확인한 결과는 다릅니다.**

| 자료 | 무엇을 보여주는가 | 한계 |
| --- | --- | --- |
| [HA 검증 요약](evaluation/ha/verification_summary.json) | 2026-10-23 x86_64 검증 기록, unit 184개·report 16개, 월간 학습·검증·갱신 시험 | 합성 데이터, 해당 기록에서 Pi·실가전 E2E 미실행 |
| [HA 비교·시나리오 자료](evaluation/ha) | Baseline/IF/AE 비교와 판정 분포 | 정상 맥락 48개 중 30개 경보, 미해결 오탐 한계 |
| [mmWave `metrics.json`](../Pauseable.ai/mmwave/src/shape_v2/artifacts/metrics.json) | 경로 형태 모델의 데이터 출처·분할·평가 | `simulated_only`, 실측 LD6004·임상 배회 미검증 |
| [mmWave 연구 프로토콜](../Pauseable.ai/mmwave/src/shape_v2/PROTOCOL.md) | 데이터 분리와 모델 선택 과정 | 임상 데이터셋이나 실제 환자 사건 수가 아님 |
| [CI 안내](../.github/README.md) | 자동 검사·빌드의 대상과 실행 방식 | workflow 정의가 있다는 사실과 최신 실행 성공은 다름 |

### 수치를 해석할 때

- 겹치는 1분 특징과 seed별 시나리오를 서로 독립인 환자·사건으로 세지 않습니다.
- 정상 학습·보정·검증 자료의 시간순 분리를 확인합니다.
- 학습 loss·복원오차·경보 건수는 각각 의미가 다릅니다. loss가 낮다고 임상 탐지 성능이 증명되지는 않습니다.
- 모델 경보, Central 승인, API 접수, 실제 출력 성공을 구분합니다.
- 실제 가구·기기·날짜·코드 버전과 근거 파일이 없는 결과를 실기 성공으로 확장하지 않습니다.

## 보고서와 그림

| 자료 | 위치 |
| --- | --- |
| HA 보고서 PowerPoint | [`HA_Final_Report.pptx`](presentation/ha/HA_Final_Report.pptx) |
| HA 보고서 PDF | [`HA_Final_Report.pdf`](presentation/ha/HA_Final_Report.pdf) |
| 현재 README 시스템 구조도 | [`pauseable-system.svg`](assets/pauseable-system.svg) |

발표·보고서 파일은 저장된 버전의 산출물입니다. 최신 코드·실험 결과를 자동으로 따라 바뀌지 않으므로, 인용 전 평가 원본과 날짜를 대조합니다.

## 과거 기록을 읽는 기준

[`PI_FULL_AUTOMATION_KO.md`](ha/PI_FULL_AUTOMATION_KO.md), [`TEAM_HANDOFF_KO.md`](ha/TEAM_HANDOFF_KO.md)처럼 날짜별 인수인계 자료는 당시 Pi·서비스·가전·API 상태를 기록합니다. 이후 코드에서 해결된 항목도 있으므로 **과거의 '미구현'이나 예전 장치 IP를 현재 사실로 그대로 사용하지 않습니다.**

현재 구조는 각 영역의 README와 실행 코드를 먼저 확인하고, 과거 기록은 변경 이유·실측 사례·한계의 근거로 사용합니다. 특히 최신 출력은 [선호 음악 가이드](../Pauseable.edge/actions/favorite-music/README.md), 현재 배포 준비 상태는 [Deploy README](../Pauseable.deploy/README.md)를 대조합니다.

## 기록과 공유

새 검증 기록에는 코드·모델 버전, 실행 환경, 데이터 출처, 명령, 결과 파일, 미실행 항목을 함께 남깁니다. 개인 원본 이력·사진·녹음·인증값·presigned URL은 문서나 공개 로그에 첨부하지 않습니다.

이번 README 구성은 [동방예의지국 저장소](https://github.com/Dongbang-Yeuijiguk/2025ESWContest_smart_3019)의 개요·구조·실행·검증을 나누는 흐름을 참고했습니다. 설명·그림·경로는 PAUSEABLE 코드에 맞게 새로 작성했으며 타 프로젝트의 성능·하드웨어·라이선스를 가져오지 않았습니다.
