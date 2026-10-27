# Home Assistant 이벤트 수집

[HA 모듈](../../Pauseable.ai/ha/README.md) · [개발환경](../DEVELOPMENT_ENVIRONMENT_KO.md) · [시연 절차](DEMO_RUNBOOK_KO.md)

## 수집 방식

| 방식 | 구현 | 용도 |
| --- | --- | --- |
| 상태 변경 구독 | [collect_ha_events_ws.py](../../Pauseable.ai/ha/src/collect_ha_events_ws.py) | WebSocket `state_changed` 이벤트 기록 |
| 현재 상태 조회 | [collect_ha_states.py](../../Pauseable.ai/ha/src/collect_ha_states.py) | 연결 점검·엔티티 목록·상태 Snapshot 확인 |

예를 들어 냉장고가 열린 뒤 2초 만에 닫히면, 닫힌 뒤에 수행한 상태 조회에는 열림이 나타나지 않을 수 있습니다. WebSocket 수집기는 HA가 전달한 두 상태 변경을 각각 기록합니다. 가전이나 HA가 보고하지 않은 변화까지 복원하는 기능은 아닙니다.

분석은 수집 CSV를 [entity_mapper.py](../../Pauseable.ai/ha/src/entity_mapper.py)로 정규화한 뒤 특징을 생성합니다. 도어의 `on/off`를 `open/close`로 매핑하는 것처럼 엔티티 종류와 설정에 맞춰 변환합니다. 초기 Snapshot은 반복 횟수에 포함하지 않습니다.

## 연결 준비

Python 3.12 가상환경과 HA 의존성을 준비합니다. HA 주소와 **Home Assistant 장기 액세스 Token**을 비공개 환경 파일의 `HA_URL`, `HA_TOKEN`에 설정합니다. LG ThinQ Token과는 다릅니다.

주소의 IP·포트는 현재 HA 설치 설정을 따릅니다. 예전 VirtualBox 주소나 포트를 그대로 사용하지 않습니다. Token 자체를 출력하거나 명령행 인수·공유 로그에 남기지 않습니다. 수집기는 두 환경변수를 읽을 수 있습니다.

## 짧은 수집 시험

환경변수가 설정된 터미널에서 **저장소 루트 기준으로** 실행합니다.

```sh
cd Pauseable.ai/ha
python src/collect_ha_events_ws.py --output data/raw/ha_collection_check.csv --duration-seconds 300 --write-initial-snapshot
```

실제 연결된 HA에 접근하지만, 수집기 자체는 가전 제어 명령을 보내지 않습니다. 시험 중 확인할 가전을 직접 조작하고 Event 시각·Entity·원시 상태가 CSV에 각각 기록됐는지 대조합니다.

기존 파일이 있으면 이어서 기록합니다. 별도 파일명으로 시험하고, 보존할 데이터에 `--truncate`를 사용하지 않습니다.

## 대상 선택과 기록 옵션

| 옵션 | 의미 |
| --- | --- |
| `--entity-id` | 정확한 Entity 선택. 여러 번 지정 가능 |
| `--exclude-entity-id` | 제외할 Entity. 여러 번 지정 가능 |
| `--entity-keyword` | 키워드 선택. 여러 번 지정 가능 |
| `--duration-seconds` | 수집 시간. 기본 0은 계속 수집 |
| `--write-initial-snapshot` | 선택한 엔티티의 시작 상태도 별도 기록 |
| `--include-all` | 기본 키워드 제한 해제 |
| `--include-telemetry` | 행동 외 엔티티도 감사 목적으로 수집 |
| `--include-attribute-only` | 상태는 같고 Attribute만 바뀐 이벤트도 포함 |
| `--truncate` | 시작 시 기존 출력 파일 교체 |

수집 대상으로 선택한 엔티티라도 Mapper가 지원하는 가전·신호가 아니면 모델 특징에 들어가지 않습니다. 변환 행 수, 제외 행 수와 관측 품질을 함께 확인합니다.

## 분석과 지속 운용

[run_ha_pipeline.py](../../Pauseable.ai/ha/src/run_ha_pipeline.py)는 수집 파일, 분석 대상과 Baseline을 받아 분석합니다. Baseline JSON은 정상 참조 특징으로 별도 준비해야 하며, 개인 모델이 저장소에 기본 포함된 것으로 가정하지 않습니다.

지속 운용은 [run_ha_full_service.py](../../Pauseable.ai/ha/src/run_ha_full_service.py)가 관리합니다. Collector의 지속 수집, 1분 간격 Feature 기준 시각, 기본 600초의 분석 회차 대기를 구분합니다. 기록 연속성과 연결·시각 상태가 불충분한 구간은 관측 품질 검사에 반영합니다.

실제 서비스·환경 파일 적용은 [배포 안내](../../Pauseable.deploy/README.md), 결과와 출력 확인은 [HA 시연 절차](DEMO_RUNBOOK_KO.md)를 따릅니다.
