<div align="center">

# PAUSEABLE

### 익숙한 생활 속 변화를 살피는 스마트 홈 케어

Home Assistant · mmWave · Raspberry Pi · Personalized Voice

**임베디드 SW 경진대회 | 스마트 가전 부문**

</div>

---

## 프로젝트 소개

PAUSEABLE은 치매 환자와 보호자의 일상생활 지원을 목표로, **가전 사용의 반복 패턴과 실내 이동의 변화**를 살펴보고 음성 안내·가전 동작·보호자 알림을 연결하는 생활 안전 보조 시스템입니다.

Home Assistant로 수집한 가전 이력과 mmWave 이동 정보를 각각 분석하며, Raspberry Pi 5의 **Central App**이 판단 결과를 검증하고 출력 정책을 적용합니다. 보호자는 Flutter 앱에서 알림과 출입 사진을 확인하고 음성·지역·선호 음악을 설정합니다.

| 주요 기능 | 처리 방식 |
| --- | --- |
| 가전 반복행동 분석 | 상태 변경 이력 → 시간 구간별 특징 → Baseline + Isolation Forest + Autoencoder |
| 배회 의심 상황 분석 | mmWave 이동 경로 → 반복 형태·지속성·개인 이력 비교 |
| 상황별 안내와 출력 | Central 승인 → Piper TTS·설정된 가전 동작·선호 음악 재생 요청 |
| 보호자 연결 | API → 알림 이력·WebSocket·FCM/Web Push, 출입 사진 확인 |
| 개인화 음성 | 동의 후 보호자 녹음 → GPU 학습 → 검증된 ONNX 모델의 Pi 배포 |

## 시스템 아키텍처

![PAUSEABLE 시스템 구조](Pauseable.docs/assets/pauseable-system.svg)

**반복행동 AI와 배회 AI는 별도 모델**입니다. 두 모델은 공통 JSON 계약으로 MQTT 메시지를 발행하고, Central이 이를 수신해 중복·시각·위험도·cooldown을 확인합니다. 하나의 신경망이 모든 센서를 함께 학습하는 구조는 아닙니다.

| 실행 위치 | 담당 역할 |
| --- | --- |
| Raspberry Pi 3 | ESP32/mmWave 센서 입력 릴레이 |
| Raspberry Pi 4 | 카메라 버퍼와 출입 이벤트 대표 사진 |
| Raspberry Pi 5 / Atlas | HA·mmWave 판단, C++ Central, 로컬 TTS와 가전 연동 |
| API 서버 / Render | 앱·장치 인증, 알림 저장·전달, 음성 학습 작업과 모델 배포 API |
| GPU Worker / R2 | Piper 학습·ONNX Export, 녹음과 모델의 비공개 저장 |
| Flutter 앱 | 보호자의 상태 확인·설정·음성 녹음 |

## 동작 흐름

1. **관찰:** HA 상태 변경과 mmWave 이동 정보를 수집하고 관측 품질을 확인합니다.
2. **판단:** 반복행동과 배회 모델이 각각 판단 근거와 상태를 생성합니다.
3. **검증:** Central이 MQTT 입력의 계약·출처·시각·중복을 검사합니다.
4. **실행:** Action Router가 허용한 경우에만 TTS와 설정된 출력 경로를 연결합니다.
5. **전달:** Central의 Decision Event를 API로 보내고 앱에서 이력과 알림을 확인합니다.

| 연결 | 인터페이스 |
| --- | --- |
| 반복행동 AI → Central | MQTT `pauseable/ai/repetitive/decision` |
| 배회 AI → Central | MQTT `pauseable/ai/wandering/decision` |
| Central → API | HTTPS `POST /api/events/decisions` |
| API → 보호자 앱 | REST·WebSocket·FCM/Web Push |

세부 필드와 검증 규칙은 [통신 계약 안내](Pauseable.contracts/README.md)에 정리되어 있습니다.

## 저장소 안내

**전체 흐름은 이 문서에서, 담당 파트의 구조와 실행 방법은 아래 README에서 확인합니다.**

| 폴더 | 내용 | 문서 |
| --- | --- | --- |
| `Pauseable.ai` | HA 반복행동·mmWave 배회 분석·음성 학습 | [AI README](Pauseable.ai/README.md) |
| `Pauseable.apps` | FastAPI 서버·Flutter 보호자 앱 | [Apps README](Pauseable.apps/README.md) |
| `Pauseable.edge` | Central·카메라·센서 릴레이·음성 모델 교체·출력 | [Edge README](Pauseable.edge/README.md) |
| `Pauseable.contracts` | 공통 JSON Schema와 이벤트 계약 | [Contracts README](Pauseable.contracts/README.md) |
| `Pauseable.deploy` | 장치별 배포 묶음·서비스 설정·이전 설정 대응표 | [Deploy README](Pauseable.deploy/README.md) |
| `Pauseable.integrations` | Home Assistant 날씨·지역·조명 연동 | [Integrations README](Pauseable.integrations/README.md) |
| `Pauseable.docs` | 운영·인수인계·평가·발표 자료 | [Docs README](Pauseable.docs/README.md) |
| `.github` | 자동 검사와 Android 시험 APK 빌드 | [CI README](.github/README.md) |

`Pauseable.third_party`에는 외부 소스와 저작권 고지를 보존합니다. 별도 사용 조건은 해당 원본 고지를 확인합니다.

## 개발 환경

| 영역 | 주요 기술 |
| --- | --- |
| 데이터·AI | Python, NumPy, pandas, scikit-learn, SQLite |
| Central | C++17, CMake, Atlas/webOS SDK, D-Bus |
| 앱·API | Flutter/Dart, FastAPI, Uvicorn |
| 통신 | MQTT, JSON Schema, HTTPS, WebSocket |
| 음성 | Piper, ONNX, Docker GPU 학습 파이프라인 |
| 운영 | Docker, systemd, GitHub Actions, Render, R2, Firebase |

Python 의존성은 파트별 가상환경으로 분리합니다. HA/API CI는 Python 3.12, Voice CI는 Python 3.11, Flutter CI는 Flutter 3.47.6을 사용합니다. Central 정식 앱 빌드에는 Atlas SDK와 전용 라이브러리가 필요합니다.

### 처음 확인하는 순서

1. [Apps](Pauseable.apps/README.md)에서 로컬 API와 앱 실행 방법을 확인합니다.
2. [Contracts](Pauseable.contracts/README.md)에서 AI → Central → API의 계약을 확인합니다.
3. [AI](Pauseable.ai/README.md)와 [Edge](Pauseable.edge/README.md)에서 판단과 실행의 경계를 확인합니다.
4. [Deploy](Pauseable.deploy/README.md)를 따라 기기별 준비 사항과 현재 배포 점검 항목을 확인합니다.
5. [Docs](Pauseable.docs/README.md)에서 검증 기록과 시연 절차를 찾습니다.

## 검증과 적용 범위

| 구분 | 저장소에 포함된 근거 | 확인 범위 |
| --- | --- | --- |
| HA | [2026-10-23 검증 기록](Pauseable.docs/evaluation/ha/verification_summary.json) | unit 184개·report 16개 기록, 합성 데이터 기반 학습·갱신·시나리오 시험 |
| mmWave | [`shape_v2` 평가](Pauseable.ai/mmwave/src/shape_v2/artifacts/metrics.json) | 경로 형태 연구 모델, 실측 LD6004·임상 배회 성능 미검증 |
| Central·앱·음성 | 파트별 테스트·[CI 정의](.github/README.md)·운영 점검 문서 | 구현·자동 검사와 실제 장치 E2E 확인을 구분 |

위 수치는 **저장된 시험 기록**이며 현재 기기의 배포 완료나 임상 성능을 뜻하지 않습니다. HA 평가에는 정상 맥락 48개 중 30개에서도 경보가 발생한 한계가 남아 있습니다. 세부 데이터·제약과 실기 점검은 [검증 자료 안내](Pauseable.docs/README.md#평가-자료-읽기)를 참고합니다.

## 운영 시 주의사항

- **보조 시스템:** 반복행동·배회 의심 판단은 의료적 치매 진단이나 안전 보장이 아닙니다.
- **출력 확인:** MQTT PUBACK, API 접수, 실제 TTS·가전·휴대폰 동작은 각각 확인합니다.
- **데이터 보호:** 개인 이력·사진·녹음·모델·토큰·presigned URL을 저장소나 공개 로그에 넣지 않습니다.
- **연결 의존성:** Pi 내부 판단과 TTS, 인터넷이 필요한 제조사 가전·API·Push·R2를 구분합니다.
- **배포 구분:** GitHub 변경은 이미 설치된 Pi·Render·APK를 자동으로 갱신하지 않습니다.

## 외부 소스

[Piper 원본 정보](Pauseable.ai/voice/provenance), [외부 저작권 고지](Pauseable.third_party/NOTICE.txt), [nlohmann/json 라이선스](Pauseable.third_party/nlohmann/LICENSE.MIT)를 보존합니다. 프로젝트 전체에 적용되는 자체 `LICENSE`는 아직 없으며, 외부 코드·데이터·모델의 이용 조건은 각각 확인해야 합니다.
