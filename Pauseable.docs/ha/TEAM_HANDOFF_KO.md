# Pauseable 냉장고·세탁기 반복행동 시연 인수인계

## 2026-10-17 로컬 제출 준비

- 최신 main `8e735ff`를 가져오고 기존 10월 5일 연구 파일을 보존해 통합했다.
- 시연의 Recorder 이력이 요청 시작 시점을 포함하는지, unknown/unavailable 구간이 있는지 검증한다.
- 첫 스냅샷의 관찰 시각은 요청 시작점에 두고 원본 last_changed는 보존한다.
- 새 공통 모듈 `src/ha_recorder_observation.py`를 두 시연 실행기와 함께 배포해야 한다.
- 단발 `--once` 실행 오류는 이제 종료 코드 1이다. 상시 실행은 오류를 기록하고 다음 주기에 재시도한다.
- 이 수정과 추가 연구용 Docker는 이번에 Pi에 배포하지 않았다.
- 아래의 404, 고정 횟수, 직접 MQTT 출력 기록은 날짜별 과거 상태다.
- 상세 결과와 남은 작업은 최신 제출 점검을 따른다.

## 2026-10-11 최종 판단·시간대 출력 구조로 변경

- 아래 2026-10-05 기록의 고정 횟수 게이트와 행동별 출력 매핑은 과거 구현 설명입니다.
- 냉장고 9회, 세탁기 ON 5회라는 별도 출력 게이트를 삭제했습니다.
- 출력 여부는 통계 규칙과 IF/AE 모델을 결합한 파이프라인의 최종 `level`만 사용합니다.
- 모든 `repetitive-ai`의 `caution`/`danger` MQTT 결정은 먼저 Central의 계약 검증, 중복 방지,
  cooldown 및 ActionRouter를 통과해야 합니다.
- 한국 시간 08:00 이상 18:00 미만에는 TV, 18:00 이상 다음 날 08:00 미만에는 공기청정기를 실행합니다.
- Central이 같은 사건을 `execute + speak=true`로 승인한 경우에만
  `pauseable-repetitive-central-output.service`가 시간대 출력을 실행합니다.
- MQTT를 직접 구독하던 `src/route_repetitive_output.py`, trigger path 유닛 및 HA 직접 자동화는
  삭제했습니다. 배회행동과 동일하게 Central이 모든 가전 출력의 필수 관문입니다.

## 2026-10-05 세탁기 시나리오 추가

- 실물 전원 버튼 변화는 `switch.setaggi_power` 이력에 남지 않고 `sensor.setaggi_current_status`에 `initial ↔ power_off`로 기록됩니다. 최근 10분 `power_off -> initial` 전환을 세어 5회에서 판단합니다.
- 전원 이력은 기존 학습 모델의 `washer operation` 특징 형식으로만 변환해 IF/AE 확인에 사용합니다.
- 가상 5회 시험에서 `model_status=shadow`, `IF=normal`, `AE=risk`, 최종 `risk=79`를 확인했습니다.
- MQTT `pattern_code`를 냉장고 `fridge_repeated_check`, 세탁기 `washer_power_repetition`으로 분리했습니다.
- 공기청정기 자동화는 냉장고 패턴에서만 실행됩니다.
- 세탁기용 영상 출력 대상은 라즈베리파이 디스플레이가 아니라 실제 LG webOS TV입니다.
- 기존 라즈베리파이 브라우저 요청은 제거했습니다.
- 세탁기 TTS 완료 후 `play_lg_tv_youtube.py`가 Home Assistant의 LG webOS TV 엔티티에 YouTube 영상 ID `-ra8Hpyylpw`를 전달합니다.
- 영상 실행 엔티티는 장비별 `TV_ENTITY` 환경변수로 설정합니다.
- TV 전원은 `TV_MAC`과 `TV_BROADCAST_ADDRESS` 환경변수에 지정한 주소로 Wake-on-LAN 패킷을 보내며, 실기에서 꺼진 TV가 약 2초 만에 다시 연결되는 것을 확인했습니다. 실제 주소는 저장소에 커밋하지 않습니다.
- 앱 알림은 같은 MQTT 결정에 세탁기 패턴이 포함되도록 준비했지만, 앱/백엔드 수신 기능은 담당 팀의 후속 작업입니다.
- 냉장고 출력은 맞춤 TTS 재생이 완전히 끝난 뒤 Home Assistant API로 공기청정기를 켜도록 순차화했습니다. 기존 MQTT Home Assistant 자동화는 중복·동시 실행을 막기 위해 비활성화합니다.
- 실기 시험에서 TTS 서비스 시작 `02:34:10`, 공기청정기 ON 요청 `02:34:18`, 실제 ON 확인 `02:34:20`을 확인했습니다.

## 1. 이번 작업의 목적

실제 LG 냉장고 문 이벤트를 사용해 반복행동을 판단하고, 하나의 MQTT 결정으로 다음 두 출력을 실행하는 시연을 완성했습니다.

1. 라즈베리파이 디스플레이 스피커에서 맞춤 한국어 TTS 재생
2. Home Assistant에 연결된 실제 LG 공기청정기 전원 켜기

보호자 앱 알림은 현재 배포 백엔드에 결정 수신 API가 없어 이번 촬영 범위에서 제외했습니다.

## 2. 최종 동작 흐름

```text
냉장고 문 10회 열고 닫기
-> LG ThinQ
-> Home Assistant Recorder
-> 1분 단위 특징 생성
-> 기존 규칙 + Isolation Forest + Autoencoder 하이브리드 판단
-> 냉장고 최근 열림 횟수 게이트 확인
-> MQTT pauseable/ai/repetitive/decision 발행
-> Central Atlas App 결정 수신
-> 맞춤 Piper TTS 재생
-> Home Assistant MQTT 자동화
-> 공기청정기 켜기
```

물리 행동은 10회 수행하지만 LG ThinQ 클라우드 이벤트가 한 번 누락된 실측 사례가 있어, 실행기의 수신 기준은 최근 10분 열림 9회입니다.

## 3. 실제로 확인한 항목

- 실제 냉장고 엔티티 `binary_sensor.naengjanggo_door`의 열림/닫힘 이벤트 수집
- 원시 Home Assistant 이벤트를 프로젝트 표준 형식으로 변환
- 2시간 이상 연속 관측 범위를 확보한 뒤 사전학습 모델 점수 생성
- Isolation Forest와 Autoencoder 결과가 포함된 하이브리드 결과 생성
- 현재 adapter는 pipeline의 최종 attention/risk를 전달한다. 규칙 단독 경보도 포함되며 IF/AE 동시 경보가 필수인 것은 아니다.
- 기존 MQTT exporter의 하드코딩된 모델 상태를 제거하고 명시적으로 전달된 메타데이터만 기록
- Central Atlas App의 MQTT 수신 및 action routing
- 정확한 문장 `할머니 잠깐 쉬어가요, 공기청정기 켜드릴게요` TTS 재생
- MQTT 자동화를 통한 실제 공기청정기 전원 켜기
- 반복행동 시 자동으로 켜지던 YouTube 기능 비활성화
- 재부팅 후 한 명령으로 데모 환경 복구

검증된 실제 이벤트 예시는 `repetitive-hybrid-live-20261004T140213Z`이며, 이 이벤트에서 MQTT 발행, Central 수신, TTS 성공, Home Assistant 자동화 실행, 공기청정기 `on`을 모두 확인했습니다.

## 4. 진행 중 발견한 핵심 문제

### 모델이 처음 실행되지 않았던 이유

초기 실행에서는 모델 파일이 없거나 `source_type`, `household_id`, 관측 이력 조건이 맞지 않아 `not_trained`, `incompatible_source`, `insufficient_history`가 순서대로 발생했습니다. 특히 특징에 최대 2시간 lookback이 있어 연속 관측 범위가 완성되기 전에는 모델 출력을 사용하지 않도록 구현되어 있었습니다.

Home Assistant Recorder의 실제 이력을 사용하고 호환되는 모델 bundle과 household 설정을 적용해 모델 점수가 나오도록 했습니다. 현재 모델은 합성 정상 데이터로 학습된 시연용 모델이므로 의료 판단이나 실가정 개인화 모델로 설명하지 않습니다.

### 기존 스트리머를 사용하지 않는 이유

기존 `run_repetitive_mqtt_stream.py`는 현재 시연의 모델 lifecycle, 관측 범위, MQTT 메타데이터를 완전히 반영하지 못했습니다. 따라서 `run_repetitive_hybrid_demo.py`를 별도 데모 adapter로 추가했습니다.

### 앱 알림이 제외된 이유

Central Atlas App은 `POST /api/events/decisions`로 결정을 전달하지만 현재 배포된 백엔드에는 해당 경로가 없어 `404 Not Found`가 발생합니다. `/api/demo/scenarios/repetitive_behavior`는 현관문 고정 시나리오라 실제 냉장고 AI 이벤트의 대체 경로로 사용하지 않았습니다.

## 5. 현재 운영 설정

- `AI_LOCAL_TTS_ENABLED=0`: Central의 일반 문구 TTS 중복 방지
- `PAUSEABLE_YOUTUBE_ENABLED=0`: 반복행동 시 YouTube 자동 실행 방지
- `DECISION_GATEWAY_ENABLED=0`: 존재하지 않는 앱 결정 API 호출 방지
- 맞춤 TTS는 별도 systemd path/service가 trigger 파일 변경을 감지해 재생
- Home Assistant 자동화가 동일 MQTT를 받아 공기청정기를 켬

## 6. 재부팅 후 실행

```sh
/data/ha_ai_fullcycle_20260911/scripts/start-repetitive-demo.sh
```

실행 후 다음 로그에서 `DEMO_ARMED`를 확인합니다.

```sh
docker exec ha-ai-full tail -n 20 /app/outputs/repetitive_hybrid_live.log
```

전체 촬영 절차와 성공 확인 명령은 `docs/DEMO_RUNBOOK_KO.md`를 따릅니다.

## 7. 팀 후속 작업

1. 백엔드에 `/api/events/decisions` 구현 및 보호자 앱 실시간 갱신 연결
2. 실제 가정 정상 이력으로 모델 재학습 및 임계값 검증
3. 실행기와 TTS 서비스를 Atlas 정식 패키지 또는 supervisor로 이동
4. 환자 ID, 장치 ID, 엔티티 ID를 배포 환경 설정으로 완전히 분리
5. 오탐률, 재현율, 클라우드 이벤트 누락률 측정

세부 항목은 `docs/GITHUB_TODO_KO.md`에 정리되어 있습니다.

## 8. 검증 결과

라즈베리파이의 실제 `ha-ai-full` 컨테이너에서 Python 문법 검사와 전체 테스트를 실행했습니다. 기존 테스트와 새 exporter 회귀 테스트를 합쳐 총 60개가 통과했습니다.
