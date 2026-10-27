# Pauseable — Memolink

<a id="개발-목표"></a>
<a id="개발-환경"></a>
<a id="개인화가-적용되는-과정"></a>
<a id="검증과-적용-범위"></a>
<a id="동작-흐름"></a>
<a id="소스-구성"></a>
<a id="시스템-아키텍처"></a>
<a id="실행과-검토"></a>
<a id="외부-소스"></a>
<a id="운영-범위와-개인정보"></a>
<a id="프로젝트-소개"></a>

**치매 환자를 위한 스마트 가전 AIoT 시스템**

임베디드 소프트웨어 경진대회 · 스마트 가전 부문 · 개발팀 Pauseable

Memolink는 집 안의 가전 사용과 실내 이동을 기록하고, 반복행동과 배회 의심 상황을 분석합니다. Raspberry Pi 5의 Central이 판단 메시지를 확인해 현장 안내를 실행하고, 보호자 앱으로 알림과 출입 사진을 전달합니다.

[주요 기능](#주요-기능) · [시스템 구성](#시스템-구성) · [폴더 구조](#폴더-구조) · [설치 및 실행](#설치-및-실행) · [검증 범위](#검증-범위)

## 프로젝트 개요

| 구분 | 내용 |
| --- | --- |
| 가전 사용 분석 | Home Assistant 상태 변경을 특징으로 만들고 Baseline·개인 모델로 반복 사용 판단 |
| 실내 이동 분석 | mmWave 대상 좌표에서 경로 형태·개인 변화·지속성 확인 |
| 현장 대응 | Central 실행 정책에 따른 로컬 TTS와 등록된 출력 경로 호출 |
| 보호자 확인 | Flutter 앱의 사건 알림·출입 사진·돌봄 설정 |
| 개인화 음성 | 동의한 보호자 녹음으로 Piper 모델을 학습하고 Pi에서 검증 후 적용 |

## 주요 기능

| 기능 | 처리 과정 | 담당 폴더 |
| --- | --- | --- |
| 반복행동 감지 | 가전 이벤트 → 사용 특징 → 규칙·IF·AE → MQTT 판단 | [AI](Pauseable.ai/README.md) |
| 배회 의심 판단 | 센서 좌표 → 이동 구간 → 경로·개인 이력·지속성 | [AI](Pauseable.ai/README.md#mmwave-구현과-설치-상세) |
| 음성·현장 출력 | 추론 검증 → Action Router → TTS·출력 Watcher | [Edge](Pauseable.edge/README.md) |
| 출입 사진 | 가상 도어락 이벤트 → Pi 4 카메라 버퍼 → API → 앱 | [카메라](Pauseable.edge/README.md#카메라-트리거와-업로드) |
| 선호 음악 | 앱 등록곡 → 현재 목록 조회 → 안내 이후 Pi 또는 HA LG TV 재생 요청 | [Edge](Pauseable.edge/README.md#선호-음악-설치와-시험) |
| 환경 조명 | 앱의 거주지역·예보·태양 고도 → 밝기·색온도 계산 → HA | [Integrations](Pauseable.integrations/README.md) |
| 알림 일시 중지 | 대상자별 반복행동 알림의 만료 시각 저장·복원 | [Apps](Pauseable.apps/README.md) |

가전 출력 코드는 장치의 실제 연결과 엔티티 설정이 필요합니다. 디스플레이·조명·공기청정기·정수기 등 모든 장치가 현재 연결되어 있다고 가정하지 않습니다.

## 시스템 구성

| 구성 | 역할 |
| --- | --- |
| LD6004·ESP32 | 실내 대상의 위치·추적 정보를 생성 |
| Pi 3 또는 센서용 Pi | ESP32 USB 전원 공급 또는 저장소의 Serial 릴레이 운용 |
| Pi 4 | 출입 카메라 버퍼와 대표 사진 업로드 |
| Pi 5·Atlas | Home Assistant, 행동 AI, MQTT, C++ Central, 로컬 TTS |
| Render·FastAPI | 사건·설정·사진·음성 작업 관리와 알림 전달 |
| GPU Worker·Piper | 보호자 녹음 전처리·학습·ONNX 게시 |
| Cloudflare R2 | 비공개 사진·녹음·음성 모델 저장 |
| Flutter Guardian | Android·웹 보호자 화면 |

Pi가 ESP32에 전원만 공급하면 그 Pi는 데이터를 중계하지 않습니다. 저장소에는 Serial→SSH/FIFO 릴레이와 Central의 UDP 원시 관측 코드가 있습니다. ESP32 Wi-Fi→Pi 5 UDP 5005 직접 전송은 펌웨어·수신기·AI 입력 전달을 함께 맞춰야 하며, 원시 UDP 수신과 최종 배회 판단은 별도 단계입니다.

### 데이터 처리 흐름

```text
Home Assistant → HA 반복행동 AI ─┐
                               ├→ MQTT → Central 검증·실행 → 로컬 TTS·출력
mmWave 수신 경로 → 배회 AI ──────┘                   └→ API → 보호자 앱 알림

가상 도어락 → Pi 4 카메라 → API/R2 → 보호자 앱 사진
보호자 녹음 → API/R2 → GPU 학습 → ONNX 게시 → Pi 검증·교체
앱 거주지역 → 기상청·HA 태양 고도 → 별도 조명 타이머
```

## 소프트웨어 구성

| 영역 | 주요 기술 | 설명 |
| --- | --- | --- |
| 행동 AI | Python 3.12, NumPy·pandas·scikit-learn | 가전 특징·모델, 이동 경로·지속성 |
| Central | C++17, CMake, sdbus-c++, OpenSSL, Atlas SDK | MQTT 검증·실행 정책·Outbox·TTS |
| API | FastAPI, Uvicorn, boto3, Firebase Admin | REST·WebSocket·파일·Push |
| 보호자 앱 | Flutter·Dart, Firebase Messaging | 화면·알림·녹음·설정 |
| 음성 학습 | Python 3.11, Piper·PyTorch·ONNX, Docker GPU | 음성 모델 학습과 Export |
| 장치 운용 | MQTT·HTTPS·systemd·Docker | 서비스 실행과 장치별 배포 |

## 폴더 구조

```text
2026ESWContest_smart_Pauseable/
├── .github/ — GitHub Actions 검사와 빌드 설정
│   └── workflows/ — 원본 자동 검사·배포 작업
├── Pauseable.ai/ — 행동 분석과 보호자 음성 학습
│   ├── assets/ — AI README의 기존 그림과 출처
│   ├── ha/ — 가전 이벤트 수집·개인화·반복행동 판단
│   ├── mmwave/ — 이동 경로·개인 변화·지속성 판단
│   └── voice/ — 녹음 전처리·Piper 학습·모델 게시
├── Pauseable.apps/ — 보호자 Flutter 앱과 FastAPI 서버
│   ├── api/ — 인증·사건 저장·Push·사진·학습 API
│   └── guardian/ — Flutter 보호자 앱
├── Pauseable.contracts/ — 공통 JSON 규격과 메시지 예시
│   ├── communication-v1/ — AI→Central→API→앱 연결 규격 v1
│   └── examples/ — 메시지 예시
├── Pauseable.deploy/ — 장치별 소스 묶음·서비스·이전 설정
│   ├── gpu/ — GPU 음성 학습 장치 설정
│   ├── migration/ — 이전 이름·경로·서비스 대응 자료
│   ├── mmwave-autostart/ — 소스 Manifest·장치별 묶음 생성기
│   └── pi5/ — Pi 5 앱·Gateway·웹 실행 설정
├── Pauseable.edge/ — Central·센서·카메라·로컬 출력
│   ├── actions/ — 안내 이후 실행하는 음악·화면 출력
│   ├── camera/ — 카메라 버퍼·대표 사진 선택·업로드
│   ├── central/ — Atlas C++ 중앙 판단·실행 앱
│   ├── mmwave-relay/ — Serial 계약 검사·SSH/FIFO 전달·시뮬레이션
│   └── voice-model/ — ONNX 모델 다운로드·검증·활성화
├── Pauseable.integrations/ — Home Assistant 기반 환경 조명 연동
│   └── home-assistant/ — Home Assistant 외부 기능 연동
└── Pauseable.third_party/ — 외부 라이브러리와 원본 고지
    ├── nlohmann/ — C++ JSON 단일 헤더와 MIT 라이선스
    └── piper1-gpl/ — Piper 1.5.0 원본 기반 TTS·학습 소스
```

위 구조는 최상위와 그 바로 아래 폴더를 보여줍니다. 각 모듈 README에는 그 모듈의 전체 하위 폴더와 역할을 정리했습니다.

| 문서 | 읽을 내용 |
| --- | --- |
| [Pauseable.ai](Pauseable.ai/README.md) | HA·mmWave·Voice 알고리즘과 기존 AI 그림 |
| [Pauseable.apps](Pauseable.apps/README.md) | API·Flutter 구조와 알림·사진·녹음 연결 |
| [Pauseable.contracts](Pauseable.contracts/README.md) | 프로그램 사이의 메시지 규격과 검증 |
| [Pauseable.deploy](Pauseable.deploy/README.md) | Pi별 소스 묶음·설치·복구 |
| [Pauseable.edge](Pauseable.edge/README.md) | Central·센서·카메라·현장 출력 |
| [Pauseable.integrations](Pauseable.integrations/README.md) | 지역·날씨·Home Assistant 조명 연동 |
| [Pauseable.third_party](Pauseable.third_party/README.md) | 외부 소스의 용도·버전·라이선스 |

## 설치 및 실행

### 소스 받기

```sh
git clone https://github.com/SamDong03/2026ESWContest_smart_Pauseable.git
cd 2026ESWContest_smart_Pauseable
```

### 권장 실행 순서

1. [API와 앱](Pauseable.apps/README.md#개발환경과-실행)의 로컬 실행·검사를 진행합니다.
2. [AI 의존성](Pauseable.ai/README.md#로컬-검사)을 준비하고 입력·모델·대상자 ID를 확인합니다.
3. Atlas SDK 환경에서 [Central](Pauseable.edge/README.md#빌드와-검사)을 빌드합니다.
4. [배포 도구](Pauseable.deploy/README.md)로 장치별 소스 묶음을 만들고 실제 설정·서비스를 적용합니다.
5. 같은 사건 ID로 입력·판정·Central 승인·API 이력·앱 표시와 실제 소리를 대조합니다.

Python 환경은 AI·API·Voice별로 분리합니다. 장치용 Piper 실행 파일, 개인화 ONNX, 실제 Token과 기존 개인 DB는 별도로 준비합니다. 소스 압축, Central `.ipk`, Android `.apk`, 음성 `.onnx`는 서로 다른 산출물입니다.

| 먼저 맞출 값 | 확인할 대상 |
| --- | --- |
| `patient_id`, `device_id` | AI·Central·API·앱의 대상자와 장치 식별 |
| `household_id` | HA 학습 이력과 모델의 가구별 분리 |
| HA·MQTT 주소와 엔티티 | 실제 수집·메시지 전달·가전 호출 |
| App·Device·Worker 인증 | 앱 조회·장치 전송·학습 작업의 역할 분리 |

예시 서비스가 코드 기본값을 덮어쓸 수 있습니다. 설치할 서비스 하나를 선택해 경로·이미지·모드·ID를 맞추고, HA의 MQTT 발행과 Central의 행동별 출력·Gateway를 각각 활성화합니다.

## 검증 범위

| 저장소에서 확인할 수 있는 것 | 실제 장치에서 추가 확인할 것 |
| --- | --- |
| 가전 규칙·학습·개인화·MQTT 회귀 검사 | 실제 HA 엔티티와 장기 관측 |
| 합성 경로·센서 계약·입력 오류 처리 | 실측 LD6004와 현재 연결 방식 |
| Central 검증·Router·재전송 구현 | 설치 패키지와 TTS·가전 출력 |
| 앱·API·Push·녹음 자동 검사 | 설치 APK의 권한·잠금·절전 상태 |
| Worker·모델 교체 검사 | GPU 학습·R2 게시·Pi 합성 |

AI README의 그래프는 보관된 합성 평가 자료입니다. 실제 환자 대상 정확도나 현재 장치의 작동 상태를 나타내지 않습니다.

## 인증 정보와 외부 소스

앱·장치·Worker는 서로 다른 인증값을 사용합니다. 실제 Token, Firebase 서버 키, 원본 사진·녹음, 개인 이력·개인 모델은 공개 소스에 넣지 않습니다. 현재 공유 App Token 구조는 사용자별 로그인·대상자 권한 분리와 구분합니다.

외부 소스의 이용 조건은 [Third Party 안내](Pauseable.third_party/README.md)와 원본 라이선스에서 확인합니다. 프로젝트 전체에 별도의 통합 재사용 라이선스를 선언하지 않았습니다.

README의 개요·기술·폴더·실행 구분 방식은 [동방예의지국의 2025 경진대회 저장소](https://github.com/Dongbang-Yeuijiguk/2025ESWContest_smart_3019)를 참고했습니다. 구현 설명과 그림은 Pauseable 소스를 기준으로 작성했습니다.
