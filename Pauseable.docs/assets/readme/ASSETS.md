# 구조도와 평가 그래프

README와 보고서에서 사용하는 구조도·평가 그래프의 출처와 생성 방법을 정리했습니다. 구조도는 모듈 간 연결을, 그래프는 저장된 평가 자료를 나타냅니다.

## 구조도

| 영역 | 그림 | 설명 |
| --- | --- | --- |
| 전체 | [`memolink-overview.svg`](memolink-overview.svg) | 처음 읽는 사람을 위한 수집·분석·Central·출력 개요와 별도 연결 기능 |
| AI | [`ai-pipelines.svg`](ai-pipelines.svg) | HA·mmWave·Voice의 입력과 출력, 실행 책임 |
| AI | [`learning-lifecycle.svg`](learning-lifecycle.svg) | 유효 이력·학습·검증·활성화·fallback |
| Apps | [`apps-connections.svg`](apps-connections.svg) | Pi·API·앱·Worker·저장소 연결 |
| Apps | [`notification-sequence.svg`](notification-sequence.svg) | 사건 접수·이력·WebSocket·Push·읽음 |
| Contracts | [`contract-map.svg`](contract-map.svg) | 추론·최종 결정·앱 알림의 차이 |
| Contracts | [`validation-gates.svg`](validation-gates.svg) | 문법·계약·출처·시각·중복·실행 정책 |
| Deploy | [`device-bundles.svg`](device-bundles.svg) | 장치별 소스 묶음과 설치 전 준비 |
| Deploy | [`deployment-stages.svg`](deployment-stages.svg) | 백업·검증·빌드·설정·설치·E2E |
| Docs | [`evidence-map.svg`](evidence-map.svg) | 코드·자동 검사·저장된 평가·실기의 근거 범위 |
| Edge | [`central-routing.svg`](central-routing.svg) | 입력 검증·Action Router·로컬 출력·Outbox |
| Edge | [`model-release.svg`](model-release.svg) | 음성 모델 검증과 교체 |
| Edge | [`favorite-music.svg`](favorite-music.svg) | 승인 이후 현재 선호 음악 조회·재생 요청 |
| Integrations | [`weather-light.svg`](weather-light.svg) | 앱 지역·날씨·태양 고도·HA 조명 |
| CI | [`ci-map.svg`](ci-map.svg) | Workflow별 검사 범위와 실행 조건 |
| CI | [`apk-build.svg`](apk-build.svg) | 수동 Android 시험 빌드와 휴대폰 확인 |

SVG는 외부 폰트·스크립트·이미지 없이 GitHub Markdown에서 표시됩니다. 모듈별 세부 조건과 기본값은 각 README 및 실행 코드에 정의되어 있습니다.

전체 시스템과 AI 구조도는 한글 설명과 영역별 색상으로 장치·Pi 5·클라우드의 책임을 구분합니다. Home Assistant는 Pi 5 안에 표시하며, 반복행동·배회 판단과 별도 음성 모델 학습 경로를 구분합니다. 한글은 시스템의 맑은 고딕·Apple SD Gothic Neo·Noto Sans KR 계열 폰트로 표시됩니다.

## 시스템 구조도 연결 기준

전체 구조도는 가전·센서, Pi 5, API·학습·저장, 보호자 앱을 실행 책임에 따라 구분합니다. 그림의 하단은 같은 API·장치에 연결되는 별도 기능 경로이지 추가 서버를 뜻하지 않습니다.

| 연결 | 그림에 표시한 경로 | 구현 근거 |
| --- | --- | --- |
| HA 상태 → 반복행동 분석 | WebSocket `state_changed` | [`collect_ha_events_ws.py`](../../../Pauseable.ai/ha/src/collect_ha_events_ws.py) |
| 센서 → Pi 3 → 분석 | UART/USB Serial → SSH → Pi 5 FIFO | [`relay_supervisor.py`](../../../Pauseable.edge/mmwave-relay/relay_supervisor.py), [`relay_serial.py`](../../../Pauseable.edge/mmwave-relay/relay_serial.py) |
| 센서 원시 관측 | UDP 복사 → Central 관측·Archive, 선택 경로 | [`main.cpp`](../../../Pauseable.edge/central/src/main.cpp)의 `MMWAVE_ENABLED`와 관측 전용 수신기. Action Router와 분리 |
| 두 AI → Broker → Central | 서로 다른 MQTT Topic의 공통 JSON | [`ha_decision_delivery.py`](../../../Pauseable.ai/ha/src/ha_decision_delivery.py), [`wandering_publisher.py`](../../../Pauseable.ai/mmwave/src/wandering_publisher.py), [`MqttDecisionSubscriber.cpp`](../../../Pauseable.edge/central/integration/src/MqttDecisionSubscriber.cpp) |
| Central → API | 최종 사건 HTTPS 전송·Outbox 재시도 | [`DecisionGatewayClient.cpp`](../../../Pauseable.edge/central/integration/src/DecisionGatewayClient.cpp), [`DecisionOutbox.cpp`](../../../Pauseable.edge/central/integration/src/DecisionOutbox.cpp) |
| API ↔ 앱 | REST·WebSocket·FCM/Web Push | [앱/API 처리와 시험](../../../Pauseable.apps/README.md) |
| 출입 사진 | HA HTTP POST 트리거 → Pi 4 → API/R2 → 앱 | [HA 트리거 설정](../../../Pauseable.edge/camera/home-assistant/pauseable_door_camera.yaml), [`camera_buffer.py`](../../../Pauseable.edge/camera/camera_buffer.py) |
| 음성 모델 | 앱 동의·녹음 → API/R2 → GPU Worker → 모델 게시 → Pi 검증·교체 | [`r2_worker.py`](../../../Pauseable.ai/voice/pipeline/r2_worker.py), [`voice_model_updater.py`](../../../Pauseable.edge/voice-model/voice_model_updater.py) |
| 환경 조명 | 앱 지역·기상청·태양 고도 → 별도 타이머 → HA 조명 | [`weather_api.py`](../../../Pauseable.integrations/home-assistant/weather-light-control/weather_api.py) |

`MMWAVE_ENABLED`의 코드 기본값은 `0`이며, UDP 복사를 보내는 것과 Central 관측기를 켜는 것은 다른 설정입니다. 구조도는 코드의 구성과 통신 역할을 설명하며 현재 장치의 설치 상태를 표시하지 않습니다.

## 브랜드 로고 출처

Home Assistant, Raspberry Pi, Python, Docker, C++, MQTT, FastAPI, Render, Cloudflare, Flutter, Firebase 로고는 **Simple Icons 16.36.0**의 단색 SVG 경로를 사용했습니다. [`brand-icons.json`](brand-icons.json)에 원본 출처·색상·브랜드 안내 주소와 패키지 SHA-512를 기록했습니다. 아이콘 경로는 구조도에 직접 포함하므로 GitHub 표시나 그림 재생성 때 외부 서버를 호출하지 않습니다.

배포 패키지의 CC0-1.0 원문은 [`SimpleIcons.LICENSE.txt`](SimpleIcons.LICENSE.txt)에 보존했습니다. 각 브랜드의 상표 권리는 별개이며, 로고는 사용 기술을 식별하기 위한 것입니다. 후원·인증 관계를 나타내지 않습니다. README 제목과 표에는 이모티콘을 사용하지 않습니다.

## 평가 그래프

| 그림 | 원본·범위 | 주의 |
| --- | --- | --- |
| [`ha-event-features.png`](ha-event-features.png) | [`visual_data.json`](../../evaluation/ha/visual_data.json), 48시간·8개 가전·54개 특징·52개 상태 변경 | 두 Heatmap은 단위가 다름. 아래 색만 −2~4로 제한 |
| [`ha-model-scores.png`](ha-model-scores.png) | 같은 원본의 정상 후보 Holdout 144개, IF/AE 점수와 각 임계값 | 학습 Loss나 환자 탐지 성능이 아님 |
| [`ha-component-comparison.png`](ha-component-comparison.png) | [`baseline_comparison.json`](../../evaluation/ha/baseline_comparison.json), 반복 가설 24개·정상 맥락 48개 | 경보 건수와 분모를 그대로 표시. 임상 정확도가 아님 |

세 그래프는 합성 평가 자료를 사용합니다. [`evaluation_figure_manifest.json`](evaluation_figure_manifest.json)에 원본 SHA-256, 사용 수치와 해석 범위를 기록했습니다. 생성기는 원본 JSON을 읽고 저장된 scaler 결과를 사용하며 모델 학습은 수행하지 않습니다.

[`inspect_paths.png`](../../../Pauseable.ai/mmwave/src/shape_v2/artifacts/inspect_paths.png)는 `shape_v2/train.py`가 생성한 합성 경로 분류 결과입니다. 좌표는 실제 미터 단위가 아니며, 해당 연구의 경로 생성 규칙과 모델 점수를 나타냅니다.

## 재생성

저장소 루트에서 실행합니다. Python은 문서용 가상환경으로 분리합니다. 기준 환경은 Matplotlib 3.10.8·NumPy 2.3.5입니다.

```sh
node Pauseable.docs/assets/readme/build_diagrams.mjs
python -m pip install matplotlib==3.10.8 numpy==2.3.5
python Pauseable.docs/assets/readme/plot_evaluation.py
```

- [`build_diagrams.mjs`](build_diagrams.mjs): Node.js 표준 모듈로 SVG 16개와 [`diagram_manifest.json`](diagram_manifest.json) 생성.
- [`build_overview.mjs`](build_overview.mjs): 동작 개요 1개 생성. 외부 이미지 없이 직접 그린 선형 아이콘을 사용하며 위 전체 생성 명령에 포함.
- [`build_architectures.mjs`](build_architectures.mjs): 전체 시스템 및 AI 구조도 2개 생성. 위 전체 생성 명령에서도 호출하며 별도 실행도 가능.
- [`build_system_architecture.mjs`](build_system_architecture.mjs): 전체 시스템 구조도의 장치·서비스·프로토콜과 브랜드 로고 배치. 위 구조도 생성기에서 호출.
- [`plot_evaluation.py`](plot_evaluation.py): 저장된 JSON을 읽어 PNG 3개와 출처 Manifest 생성. 임시 Matplotlib cache는 종료 시 정리.
- 별도 모델·서비스 실행, 네트워크 호출, 개인정보·인증값 접근은 하지 않음.
- 학습 iteration별 Loss 시계열은 선택한 원본에 포함되지 않음.

[Docs 인덱스로 돌아가기](../../README.md) · [AI README](../../../Pauseable.ai/README.md)
