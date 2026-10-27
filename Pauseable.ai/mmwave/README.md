# Memolink mmWave 이동 분석

[AI 구성·평가](../README.md) · [Runtime 정책](../../Pauseable.docs/mmwave/RUNTIME.md) · [기능별 코드](../../Pauseable.docs/SOURCE_MAP_KO.md#mmwave-이동-분석)

센서의 대상·위치·추적 정보를 이동 구간으로 묶어 경로 형태, 개인 이력과 관측 품질을 확인합니다. 반복 형태가 지속되는 상황과 개인 분포의 변화를 분리해 판단 근거를 생성합니다.

## 구성

| 경로·파일 | 담당 처리 |
| --- | --- |
| [wandering_live.py](src/wandering_live.py) | 실시간 실행 진입점 |
| [wandering_runtime.py](src/wandering_runtime.py) | 스트림별 구간·상태·결과 처리 |
| [personal_baseline.py](src/personal_baseline.py) | 개인 과거 분포와 비교 |
| [wandering_publisher.py](src/wandering_publisher.py) | 계약에 맞는 MQTT 판단 메시지 |
| [shape_v2](src/shape_v2) | 경로 형태 Random Forest와 연구 평가 |
| [센서 릴레이](../../Pauseable.edge/mmwave-relay) | Pi 3 입력 검증·Pi 5 중계 |

## 판단과 연구 모델

`shape_v2`의 36개 RF 특징과 기존 개인 이력의 9개 특징은 서로 다른 규격입니다. 모델·정책·특징 버전에 맞는 상태 DB를 사용하고, 센서·출처·대상별 스트림을 분리합니다.

형태 점수, 개인 희귀도, 연속 구간·누적 시간과 관측 품질을 함께 확인합니다. 연결 단절·저품질·시간 역전·모델 변경의 처리와 현재 후보 상태 이름은 [Runtime 정책](../../Pauseable.docs/mmwave/RUNTIME.md)에 정리했습니다.

저장된 형태 평가는 합성 경로를 사용한 `simulated_only` 연구 결과입니다. 연구 모델의 자동 알림은 비활성이며, 실제 LD6004와 확인 라벨을 이용한 검증은 별도입니다. 시연·운영 Publisher의 설정과 연구 결과를 혼동하지 않습니다.

## 설치와 확인

1. [mmWave 의존성](requirements.txt)과 [Pi 5 실행 구성](../../Pauseable.deploy/mmwave-autostart/pi5)을 확인합니다.
2. [센서 계약](../../Pauseable.contracts/mmwave-target-event.schema.json)에 맞는 입력과 serial·시계·추적 품질을 확인합니다.
3. 입력, Runtime 결과와 MQTT 메시지를 단계별로 대조합니다.
4. [Central](../../Pauseable.edge/central/README.md)의 검증·실행 정책 이후 출력을 따로 확인합니다.

[실험 설계](src/shape_v2/PROTOCOL.md) · [평가 원본](src/shape_v2/artifacts/metrics.json) · [경로 그림](src/shape_v2/artifacts/inspect_paths.png)
