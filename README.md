<div align="center">

# Memolink

### 가전 사용과 실내 이동을 살피고, 익숙한 음성으로 안내하는 생활 안전 보조 시스템

**임베디드 SW 경진대회 | 스마트 가전 부문**

**개발팀 PAUSEABLE**

Home Assistant ·  mmWave ·  개인화 행동 분석 ·  Piper TTS ·  보호자 앱

[프로젝트 소개](#프로젝트-소개) · [시스템 구조](#시스템-아키텍처) · [주요 기능](#주요-기능) · [설치와 실행](#실행과-검토) · [검증 결과](#검증과-적용-범위)

</div>

---

<a id="개발-목표"></a>

## 프로젝트 소개

Memolink는 **치매 환자를 위한 스마트 가전 AIoT 시스템**입니다. 가전 사용 이력과 실내 이동 경로를 AI로 분석해 반복행동·배회 의심 상황에 대응합니다. PAUSEABLE 팀은 보호자가 곁에 없을 때도 일상 속 변화를 확인하고 안내할 수 있도록, 가전·센서·음성·보호자 앱을 연결했습니다.

예를 들어 냉장고 문을 짧은 간격으로 계속 열거나 실내에서 비슷한 경로를 반복해 이동하면, 각각의 분석 모듈이 횟수·지속 시간·평소 패턴과 관측 품질을 확인합니다. 이후 Pi 5의 **Central App**이 메시지와 실행 조건을 검사하고, 허용된 음성 안내·가전 동작·보호자 알림을 처리합니다. 한 번 문을 열었다는 이유만으로 반복행동을 판단하거나, 센서가 끊긴 상태를 정상으로 간주하지 않습니다.

![Memolink의 수집·분석·실행 결정·음성 및 앱 연결을 한눈에 보는 흐름](Pauseable.docs/assets/readme/memolink-overview.svg)

| 살펴보는 상황 | 입력과 판단 | 연결되는 기능 |
| --- | --- | --- |
|  가전을 반복 조작하는 상황 | HA의 열림·닫힘·시작·정지 이력에서 반복 횟수와 패턴 확인 | 반복행동 판단 → Central → 설정된 안내·가전·알림 |
|  비슷한 동선을 반복하는 상황 | mmWave 위치·추적 정보에서 경로 형태와 지속성, 개인 이력 확인 | 배회 의심 판단 → Central → 설정된 안내·알림 |
|  현관 출입 상황 | 도어락·HA 출입 트리거와 카메라 버퍼 연결 | Pi 4 대표 사진 → API → 보호자 앱 |
|  생활 환경 변화 | 앱 거주지역·기상청 날씨·HA 태양 고도 확인 | 별도 조명 규칙으로 밝기·색온도 조절 |

위 표는 기능 연결을 설명한 것입니다. 반복 조작의 원인을 '잊어버림'으로 확정하거나 이동만으로 임상적 배회를 진단하지는 않습니다. 현재 구현과 검증 범위는 [검증 결과](#검증과-적용-범위)에 구분했습니다.

## 시스템 아키텍처

![Memolink 시스템 구조 · 개발팀 PAUSEABLE](Pauseable.docs/assets/pauseable-system.svg)

### 집 안에서 처리하는 일과 서버에서 처리하는 일

**Raspberry Pi 5가 현장 처리의 중심**입니다. Home Assistant와 MQTT Broker를 Pi에 두고, Python 분석 모듈과 C++ Central을 실행합니다. Central은 AI 모델이 아니라, 판단 메시지를 확인하고 실제 출력을 결정하는 앱입니다.

API 서버는 보호자 앱과 집 안 장치를 연결합니다. 별도의 GPU Worker는 보호자 음성 모델을 학습하고, R2는 사진·녹음·모델 파일을 비공개로 보관합니다. **행동 분석용 IF·AE 학습과 보호자 음성 학습은 다른 과정**입니다.

구조도에서 센서 분석 입력은 **Pi 3 → SSH/FIFO → Pi 5**로, 최종 행동 판단은 **AI → MQTT Broker → Central**로 구분했습니다. 점선 UDP는 Central의 선택적 원시 관측 경로이며 자동 실행 판단과 분리됩니다. 출입 사진·음성 모델·환경 조명은 하단의 별도 연결입니다. [원본 SVG](Pauseable.docs/assets/pauseable-system.svg) · [연결별 구현 근거](Pauseable.docs/assets/readme/ASSETS.md#시스템-구조도-연결-기준)

| 실행 위치 | 하는 일 | 관련 문서 |
| --- | --- | --- |
|  ESP32·mmWave / Pi 3 | 센서의 위치·추적 정보를 검증해 Pi 5로 중계 | [센서 릴레이](Pauseable.edge/README.md#센서-릴레이와-카메라) |
|  Pi 4 | 카메라 버퍼에서 출입 시점의 대표 사진을 선택하고 업로드 | [카메라 모듈](Pauseable.edge/camera) |
|  Pi 5 / Atlas | HA 수집·행동 분석·Central·로컬 음성 합성·가전 연동 | [AI](Pauseable.ai/README.md), [Central](Pauseable.edge/README.md#central-구현과-설치-상세) |
|  FastAPI / Render | 인증, 사건 이력, 앱 실시간 연결, 설정과 학습 작업 관리 | [앱·API](Pauseable.apps/README.md) |
|  GPU Worker / R2 | Piper 음성 학습과 ONNX 게시, 파일 저장 | [Voice](Pauseable.ai/README.md#voice-학습과-운영-상세) |
|  Flutter 보호자 앱 | 알림·사진 확인, 음성·호칭·지역·선호 음악 등록 | [앱 상세](Pauseable.apps/README.md#보호자-앱-상세) |

## 주요 기능

### 1. 가전 사용 이력으로 반복행동 분석

**Home Assistant(HA)**는 가전 상태를 한곳에서 다루는 플랫폼입니다. 수집기는 HA의 `state_changed` 이벤트를 WebSocket으로 구독합니다. 즉, 정해진 시간마다 상태를 물어보는 대신 **상태가 바뀔 때 HA가 보내는 소식을 기록**합니다. HA가 두 변화를 전달하면 2초 만에 열고 닫은 기록도 각각 남습니다.

기록한 상태를 가전별 행동으로 정리한 뒤, 최근 **10분·30분·1시간·2시간**의 횟수·상태 전환·재시작 등을 54개 수치 특징으로 만듭니다. 한 번의 조작, 짧은 연속 조작, 긴 간격의 반복을 서로 다른 시간 구간에서 살피기 위한 구성입니다.

| 구분 | 역할 |
| --- | --- |
| Baseline | 정상 참조 이력의 통계와 최소 횟수·반복 규칙으로 초기 판단 |
| Isolation Forest(IF) | 정상 학습 특징의 분포에서 얼마나 벗어났는지 계산 |
| Autoencoder(AE) | 정상 특징을 복원하도록 학습하고, 현재 입력의 Reconstruction Error 계산 |
| Routine | 확인된 개인의 시간대·요일별 생활패턴과 현재 근거를 비교해 경보 보정 |
| Episode | 연속된 이상 판정 구간을 묶어 사건의 시작·종료와 강도를 요약 |

수집·특징 계산·서비스 분석 회차는 서로 다른 주기입니다. 기본 서비스는 분석이 끝난 뒤 600초를 기다리며, 수집기는 그동안에도 계속 기록합니다. **즉시 기록된다는 것이 즉시 알림을 보낸다는 뜻은 아닙니다.**

[HA 처리·주기·실행 방법](Pauseable.ai/README.md#ha-구현과-실행-상세) · [특징과 평가 그래프](Pauseable.ai/README.md#ha-데이터-수집과-특징-생성)

### 2. mmWave 이동 경로로 배회 의심 상황 분석

mmWave 센서에서 얻은 위치·추적 정보를 시간 구간별 경로로 묶습니다. 경로의 반복 형태뿐 아니라 **얼마나 지속됐는지, 평소 이동과 다른지, 추적이 안정적인지**를 함께 봅니다. 가전 반복행동 분석과 입력·특징·모델이 다른 독립 파이프라인입니다.

경로 형태 연구에는 Random Forest를 사용합니다. 저장된 연구 평가는 합성 경로 기준이며, 실측 LD6004와 임상 배회 성능을 검증한 결과는 아닙니다. 해당 연구 모델의 자동 알림은 비활성이며, 시연·운영 Publisher 설정과 구분합니다.

[mmWave 구성](Pauseable.ai/README.md#mmwave-구현과-설치-상세) · [Runtime 정책](Pauseable.docs/mmwave/RUNTIME.md)

### 3. Central에서 판단을 검증하고 출력 결정

두 AI 모듈은 서로 다른 MQTT Topic으로 JSON 메시지를 보냅니다. **MQTT는 모듈 사이에 메시지를 전달하는 통로**, JSON은 그 메시지의 데이터 형식입니다. Central은 메시지를 받았다고 바로 가전을 작동시키지 않습니다.

| 순서 | Central이 확인하는 것 | 필요한 이유 |
| --- | --- | --- |
| ① 수신·형식 검사 | 필수 필드·자료형·위험 단계·대상자/장치 ID | 서로 다른 모듈이 같은 의미로 해석하도록 함 |
| ② 출처·시각 검사 | Topic/source 일치, 사건 시각의 유효 범위 | 잘못된 출처나 오래된 사건의 실행 방지 |
| ③ 중복·충돌 검사 | 같은 `event_id`와 내용 비교 | 재전송으로 알림·동작이 중복되는 것 방지 |
| ④ Action Router | 행동 종류·위험도·활성화 설정·cooldown | 반복 실행을 제한하고 허용할 출력 결정 |
| ⑤ 출력·전송 | 로컬 TTS·가전 처리와 API 전송 대기·재시도 | 현장 안내와 보호자 연결을 분리해 관리 |

Outbox는 전송하지 못한 API 사건을 보관하고 다시 보내는 **영속 전송 대기함**입니다. API 전송 성공을 실제 스피커·가전·휴대폰 출력 성공과 같은 상태로 처리하지 않습니다.

[Central 구조](Pauseable.edge/README.md#central-구현과-설치-상세) · [Subscribe·Action Router 등 파일 위치](Pauseable.docs/SOURCE_MAP_KO.md#central-수신과-실행) · [메시지 계약](Pauseable.contracts/README.md)

### 4. 음성·가전·보호자 앱으로 상황 연결

| 출력·화면 | 동작 방식 |
| --- | --- |
|  음성 안내 | Piper가 문장을 음성으로 합성해 Pi 스피커로 출력. 검증된 보호자 음성 모델 적용 가능 |
|  가전 동작 | Central이 허용한 요청을 설정된 연동 경로로 전달. 실제 장치 지원 상태와 인증 필요 |
|  선호 음악 | 앱에 등록한 현재 목록에서 API가 영상을 선택하고 Pi 화면·스피커 재생 요청 |
|  보호자 알림 | 최종 사건을 API에 저장한 뒤 WebSocket·FCM/Web Push로 전달 |
|  출입 사진 | Pi 4가 업로드한 대표 사진을 보호자가 인증 후 조회 |
|  조명 제어 | 행동 판단과 별개로 지역·날씨·태양 고도에 따른 밝기·색온도 규칙 적용 |

앱이 열려 있을 때의 실시간 갱신은 WebSocket, 화면에 없을 때의 알림은 FCM/Web Push가 담당합니다. 휴대폰 알림 권한과 서비스 연결이 필요합니다.

[보호자 앱 기능](Pauseable.apps/README.md#보호자-앱-상세) · [음악 재생](Pauseable.edge/README.md#선호-음악-설치와-시험) · [지역·조명 연동](Pauseable.integrations/README.md)

## 개인화가 적용되는 과정

새 사용자의 실제 이력이 없을 때는 공통 참조 Baseline으로 시작합니다. 개인 이력이 쌓이면 정상 후보를 선별하고 IF·AE를 학습·검증합니다. **30일은 달력만 세는 고정 대기시간이 아니라, 유효 관측과 정상 후보 조건을 충족한 날짜 수의 기본 기준**입니다.

![유효 이력 확인·IF와 AE 학습·검증·활성화·실패 처리](Pauseable.docs/assets/readme/learning-lifecycle.svg)

| 단계 | 실제 처리 |
| --- | --- |
| 이력 부족 | Baseline으로 판단하고 관측 품질·사용 이력 수집 |
| 학습 후보 준비 | 같은 가구·출처·특징 규격의 정상 후보 확보. 기본 하루 12개 이상 시간대, 유효 관측일 30일 |
| 학습·검증 | 시간순으로 Train·Calibration·Holdout 분리, IF·AE 학습과 임계값 보정 |
| Shadow / Hybrid | Shadow에서는 모델 점수 관찰, Hybrid에서는 반복 근거·품질 조건과 함께 모델 신호 반영 |
| 모델 갱신·실패 처리 | 설정한 갱신 조건에 따라 재학습. 검증 실패 시 기존 호환 모델 또는 Baseline 유지 |

규칙으로 고른 정상 후보와 사람이 확인한 정상 이력은 구분합니다. 재학습은 `retrain_days` 설정으로 제어하며 `0`이면 꺼져 있습니다. 시간·요일 특징은 반복되는 생활패턴을 표현하기 위한 것이며, 지난주 같은 요일의 사건 하나를 그대로 대조하는 방식은 아닙니다.

**보호자 음성 개인화는 별도입니다.** 앱의 동의·문장 녹음 → API/R2 → GPU Worker의 Piper 학습 → ONNX 검증·게시 → Pi 모델 검증·교체 순서로 진행합니다. 행동 모델 학습은 Pi 이력을 사용하고, 음성 학습은 별도 GPU 환경을 사용합니다.

[행동 모델 운용](Pauseable.ai/README.md#baseline과-개인화-모델) · [보호자 음성 학습](Pauseable.ai/README.md#voice-학습과-운영-상세)

## 동작 흐름

가전·이동 분석은 입력부터 독립적으로 진행되며, 결과만 공통 계약으로 Central에 모입니다. 카메라 사진·음성 학습·지역 조명은 각각의 별도 경로로 연결됩니다.

| 연결 | 통신 방식·데이터 |
| --- | --- |
| HA → 반복행동 분석 | WebSocket `state_changed`, 상태 이력 |
| 센서 릴레이 → 이동 분석 | 센서 대상·좌표·시각·추적 품질 |
| 반복행동 분석 → Central | MQTT `pauseable/ai/repetitive/decision` |
| 배회 분석 → Central | MQTT `pauseable/ai/wandering/decision` |
| Central → API | HTTPS `POST /api/events/decisions`, 최종 결정과 허용한 actions |
| API → 보호자 앱 | REST 이력 조회, WebSocket 갱신, FCM/Web Push 알림 |
| 음성 Worker → Pi | API/R2에 게시한 ONNX·설정·manifest를 Pi가 검증 후 적용 |

메시지에는 사건 ID·시각·출처·대상자·판단 상태·근거를 담습니다. 관측 부족이나 오류는 `unknown`으로 보내며, 잘못된 JSON을 정상 판단으로 자동 변환하지 않습니다. [공통 통신 규격](Pauseable.contracts/README.md)

## 소스 구성

작품명은 **Memolink**, 팀명은 **PAUSEABLE**입니다. 기존 설치와의 호환성을 위해 저장소·폴더·서비스·Topic의 `Pauseable`·`pauseable` 식별자는 유지합니다.

| 영역 | 담당 범위 | 읽기 |
| --- | --- | --- |
|  `Pauseable.ai` | HA 반복행동·mmWave 이동 분석·보호자 음성 학습 | [AI README](Pauseable.ai/README.md) |
|  `Pauseable.apps` | Flutter 보호자 앱·FastAPI 서버 | [Apps README](Pauseable.apps/README.md) |
|  `Pauseable.edge` | Central·센서 릴레이·카메라·음성 교체·음악 출력 | [Edge README](Pauseable.edge/README.md) |
|  `Pauseable.contracts` | 모듈 간 JSON Schema·이벤트 계약 | [Contracts README](Pauseable.contracts/README.md) |
|  `Pauseable.deploy` | 장치별 소스 묶음·서비스·설치 설정 | [Deploy README](Pauseable.deploy/README.md) |
|  `Pauseable.integrations` | Home Assistant 지역·날씨·조명 연결 | [Integrations README](Pauseable.integrations/README.md) |
|  `Pauseable.docs` | 설계·평가·보고서·운영 기록 | [문서 및 검증 자료](Pauseable.docs/README.md) |
|  `.github` | 자동 검사와 Android 시험 APK 빌드 | [CI README](.github/CI_README.md) |

외부 소스와 저작권 고지는 `Pauseable.third_party`에 보존합니다. 기능을 구현한 파일부터 찾으려면 [기능별 코드 위치](Pauseable.docs/SOURCE_MAP_KO.md)를 확인합니다.

## 개발 환경

| 영역 | 주요 기술 | 용도 |
| --- | --- | --- |
| 데이터·AI | Python, NumPy, pandas, scikit-learn, SQLite | 수집·특징 생성·모델·판정 이력 |
| Central | C++17, CMake, Atlas/webOS SDK, D-Bus | 현장 메시지 검증·실행 제어 |
| 앱·API | Flutter/Dart, FastAPI, Uvicorn | 보호자 화면·서버 요청 처리 |
| 통신 | MQTT, JSON Schema, HTTPS, WebSocket | 메시지 전달·검증·실시간 연결 |
| 음성 | Piper, ONNX, PyTorch, Docker GPU | 보호자 음성 학습·로컬 합성 |
| 운영 | Docker, systemd, GitHub Actions, Render, R2, Firebase | 서비스 실행·검사·저장·알림 |

HA/API의 기준 환경은 Python 3.12, Voice는 Python 3.11, Flutter CI는 Flutter 3.47.6입니다. Python 환경은 파트별로 분리합니다. Central 정식 앱 빌드에는 Atlas SDK와 전용 라이브러리가 필요합니다. [장치·버전·환경 준비](Pauseable.docs/DEVELOPMENT_ENVIRONMENT_KO.md)

## 실행과 검토

이 저장소는 여러 장치와 서비스를 포함합니다. 아래 순서로 필요한 파트를 준비하고, 각 문서의 실행 명령을 따릅니다. 소스 압축 파일·Central `.ipk`·Android APK·개인화 ONNX는 서로 다른 산출물입니다.

| 순서 | 준비·확인할 것 | 문서 |
| --- | --- | --- |
| 1 | 개발 도구, 장치 역할, 가상환경 | [개발환경](Pauseable.docs/DEVELOPMENT_ENVIRONMENT_KO.md) |
| 2 | HA 엔티티·Token, MQTT Broker, 센서 입력·시간 동기화 | [HA 수집](Pauseable.docs/ha/ha_realtime_collection_guide.md), [mmWave](Pauseable.ai/README.md#mmwave-구현과-설치-상세) |
| 3 | Baseline·모델·이력 경로, 분석 서비스 | [HA 모듈](Pauseable.ai/README.md#ha-구현과-실행-상세) |
| 4 | Central 빌드·설정·수신·출력 정책 | [Central](Pauseable.edge/README.md#central-구현과-설치-상세), [통신 규격](Pauseable.contracts/README.md) |
| 5 | API 인증·저장소·Push, 앱 빌드 설정 | [API·Flutter 로컬 실행](Pauseable.apps/README.md), [Android Push](Pauseable.apps/guardian/docs/ANDROID_PUSH_SETUP_KO.md) |
| 6 | 장치별 설치와 실제 입력·TTS·가전·휴대폰 확인 | [배포 안내](Pauseable.deploy/README.md), [전체 인계](Pauseable.docs/DEPLOYMENT_HANDOFF.txt) |

파트별 자동 검사는 [CI README](.github/CI_README.md), 시연 입력과 확인 순서는 [HA 시연 절차](Pauseable.docs/ha/DEMO_RUNBOOK_KO.md)에 있습니다. 설치 전 [배포 준비 상태](Pauseable.deploy/README.md#배포-준비-상태)도 확인합니다.

## 검증과 적용 범위

저장된 실험은 **데이터 출처·조건·분모와 함께** 읽습니다. 아래 HA 비교는 합성 평가에서 Baseline과 모델 추가의 차이를 확인한 결과입니다.

![반복 가설 24개와 정상 맥락 48개에서 Baseline·IF·AE·Hybrid 경보 비교](Pauseable.docs/assets/readme/ha-component-comparison.png)

| 구분 | 저장된 결과 | 해석 범위 |
| --- | --- | --- |
| HA 반복 가설 | Baseline 16/24 → Hybrid 24/24 경보 | 모델 추가 후 경보 범위 확대 |
| HA 정상 맥락 | Baseline 22/48 → Hybrid 30/48 경보 | 정상 사용의 경보도 증가. Routine 미적용 비교 |
| 별도 Routine 시험 | 576개 시점 중 Attention 6개를 Normal로 보정, Risk 6개 유지 | 위 48개 정상 맥락과 다른 시험 |
| HA 자동 검사 | 2026-10-23 기록: Unit 184개·Report 16개, 학습·갱신·시나리오 시험 | x86_64 합성 입력. 해당 기록의 Pi·실가전 E2E는 미실행 |
| mmWave | `shape_v2` 합성 경로 평가 | 실측 LD6004·임상 배회 성능 미검증 |
| Central·앱·음성 | 파트별 테스트·CI·팀 앱 검증 기록 | 실제 설치 버전과 장치 출력은 별도 확인 |

표의 경보 수는 Attention 또는 Risk가 한 번 이상 나온 시나리오 수입니다. 실제 환자의 탐지 정확도나 전체 오탐 해결률이 아닙니다. [AI 결과와 그래프 해석](Pauseable.ai/README.md#ha-평가-결과) · [평가 원본·검증 기록](Pauseable.docs/README.md#평가-자료-읽기) · [앱 검증 기록](Pauseable.apps/README.md#7-검증-결과와-남은-확인)

## 자주 묻는 질문

<details>
<summary><strong>PC를 계속 켜 두어야 하나요? 인터넷이 끊겨도 되나요?</strong></summary>

Pi에 설치한 HA·MQTT Broker·행동 분석·Central·로컬 TTS는 개발 PC와 분리해 실행하는 구성입니다. Pi 전원과 집 안 장치 연결은 유지해야 합니다. 제조사 클라우드 가전, API·Push, YouTube, 기상청과 R2에는 해당 외부 서비스 연결이 필요합니다. 같은 Wi-Fi에 연결돼 있는 것과 외부 인터넷에 접속되는 것은 다른 조건입니다.

</details>

<details>
<summary><strong>30일 전에는 판단하지 못하나요? 모델이 자동으로 바뀌나요?</strong></summary>

이력이 부족할 때도 Baseline으로 판단합니다. IF·AE는 유효 이력·정상 후보·분할 검증·호환 조건을 통과한 뒤 설정한 운용 모드에 따라 적용합니다. 단순히 한 달이 지났다고 검증 없이 모델로 교체하지 않습니다. 재학습 활성화 여부는 장치 설정을 확인합니다.

</details>

<details>
<summary><strong>API에 사건이 저장되면 모든 안내가 성공한 건가요?</strong></summary>

아닙니다. Central의 실행 승인, API 접수, 실제 스피커·가전·휴대폰 출력은 다른 단계입니다. 같은 사건 ID로 각 로그와 실제 출력을 대조합니다. Outbox는 API 재전송을 위한 것이며 모든 물리 동작을 다시 실행하는 큐는 아닙니다.

</details>

<details>
<summary><strong>처음 보는 용어는 무슨 뜻인가요?</strong></summary>

| 용어 | 이 시스템에서의 의미 |
| --- | --- |
| Entity | HA가 관리하는 센서·스위치·가전 상태 항목 |
| Feature | 사용 횟수·전환·시간대 등을 숫자로 표현한 모델 입력 |
| Baseline | 데이터가 적을 때도 사용하는 통계·반복 규칙 기준 |
| Calibration | 학습과 별도 구간에서 모델 임계값을 정하는 단계 |
| MQTT Topic | 특정 종류의 메시지를 보내고 받는 주소 |
| Central / Action Router | 메시지를 검사하고, 허용할 동작을 결정하는 앱과 내부 모듈 |
| cooldown | 같은 출력을 짧은 시간에 반복하지 않도록 제한하는 시간 |
| ONNX | Pi에 내려받아 음성 합성에 사용하는 모델 파일 형식 |

</details>

## 적용 범위와 개인정보

Memolink는 생활 안전을 돕는 연구·시연용 구현이며 의료 진단이나 안전을 보장하는 시스템은 아닙니다. 원본 녹음·출입 사진·개인 이력·개인화 모델·인증값은 저장소에 포함하지 않습니다. 음성 수집에는 동의 기록을 사용하고, API의 App·Device·Worker 인증을 분리합니다. 현재 팀 시험용 공유 App Token 구조는 사용자별 로그인·대상자 접근권한 분리를 대신하지 않습니다.

[음성 데이터·보관 정책](Pauseable.docs/voice/DATA_AND_ARTIFACTS_KO.md) · [보호자 앱 적용 범위](Pauseable.apps/README.md#구현-및-검증-범위)

## 외부 소스

[Piper 원본 정보](Pauseable.ai/voice/provenance), [외부 저작권 고지](Pauseable.third_party/NOTICE.txt), [nlohmann/json 라이선스](Pauseable.third_party/nlohmann/LICENSE.MIT)를 포함합니다. 외부 코드·데이터·모델은 각 원본의 이용 조건을 따릅니다. 프로젝트 전체의 재사용 라이선스는 별도로 정의하지 않았습니다.
