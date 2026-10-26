# 냉장고·세탁기 반복행동 시연 실행 문서

> 2026-10-17 보강: 실제 저장소는 `src/`, `scripts/`, `deploy/` 구조다.
> 아래 `pi-src`/`pi-config`는 과거 공유본 표기다.
> 실행기 교체 시 `src/ha_recorder_observation.py`도 같은 src 디렉터리로 복사한다.
> 이 보강판은 Pi 미배포 상태이며 최신 제출 점검을 함께 본다.

## 1. 시연 목표

치매 고령자의 가전 반복행동을 실제 이벤트로 수집하고, 통계 규칙과 IF/AE 모델을 결합한 최종 판단 결과를 이용해 시간대별 출력을 실행합니다.

1. 08:00 이상 18:00 미만: 안내 TTS 후 실제 LG TV에서 YouTube 실행
2. 18:00 이상 다음 날 08:00 미만: 안내 TTS 후 실제 LG 공기청정기 전원 켜기

냉장고·세탁기 등 반복행동 종류는 출력 선택에 영향을 주지 않습니다.

보호자 앱 알림은 백엔드 결정 API가 배포될 때까지 별도 과제로 둡니다.

## 2. 동작 구조

```text
LG 냉장고
  -> LG ThinQ
  -> Home Assistant entity: binary_sensor.naengjanggo_door
  -> Home Assistant Recorder의 최근 2.25시간 이력
  -> run_repetitive_hybrid_demo.py
  -> 기존 feature/rule/model pipeline
  -> MQTT topic: pauseable/ai/repetitive/decision
     -> Central Atlas App: 계약 검증, 중복 방지, cooldown, ActionRouter 승인

LG 세탁기 sensor.setaggi_current_status (`initial`/`power_off`)
  -> run_washer_hybrid_demo.py
  -> 기존 washer operation 특징 형식으로 변환 후 기존 feature/rule/model pipeline
  -> 같은 MQTT topic, pattern_code=washer_power_repetition

Central의 동일 event_id `accepted + execute + speak=true`
  -> pauseable-repetitive-central-output.service
     -> 08:00-18:00: TV용 TTS -> Home Assistant -> YouTube 실행
     -> 18:00-08:00: 공기청정기용 TTS -> Home Assistant -> 공기청정기 켜기
```

AI MQTT를 직접 구독해 가전을 실행하는 별도 출력 라우터와 Home Assistant MQTT 자동화는
삭제했습니다. 따라서 Central에서 차단·억제한 사건은 가전 출력으로 진행할 수 없습니다.

## 3. 판단 조건

- 고정 횟수 기준을 출력 게이트로 사용하지 않습니다.
- 통계 기반 규칙과 IF/AE 모델이 결합된 최종 `level`이 `attention` 또는 `risk`일 때 MQTT를 발행합니다.
- 센서 횟수와 상태 변화는 하이브리드 파이프라인의 입력 특징으로만 사용합니다.
- 한 에피소드에서는 한 번만 발행합니다.
- 하이브리드 최종 결과가 다시 `normal`이 되면 `normal` 결정을 발행하고 다음 에피소드를 기다립니다.
- `pattern_code`와 관계없이 모든 반복행동은 같은 시간대 출력 규칙을 사용합니다.

현재 모델은 합성 데이터 기반 사전학습 모델입니다. 실가정 개인화 모델 또는 의료 진단 모델이 아닙니다.

## 4. 주요 경로

```text
호스트 영구 데이터: /data/ha_ai_fullcycle_20260911
컨테이너 마운트:    /app
실행기:             /app/src/run_repetitive_hybrid_demo.py
실행 로그:          /app/outputs/repetitive_hybrid_live.log
실행 상태:          /app/outputs/repetitive_hybrid_live_state.json
MQTT 발행 파일:     /app/outputs/repetitive_hybrid_live_publish.jsonl
TTS WAV:             /data/profiles/0/appdata/com.atlas.app.pauseableatlas/home/pauseable-air-purifier-tts.wav
세탁기 실행기:       /app/src/run_washer_hybrid_demo.py
세탁기 로그:         /app/outputs/washer_hybrid_live.log
세탁기 상태:         /app/outputs/washer_hybrid_live_state.json
세탁기 TTS WAV:      /data/profiles/0/appdata/com.atlas.app.pauseableatlas/home/pauseable-washer-youtube-tts.wav
YouTube URL:         /var/lib/pauseable/youtube/washer-favorite-url.txt
Central 환경:       /data/profiles/0/appdata/com.atlas.app.pauseableatlas/home/ha.env
Central 출력 로그: journalctl -u pauseable-repetitive-central-output.service
Central 출력 상태: /app/outputs/repetitive-central-output-state/
```

## 5. 최초 배포

저장소 파일을 아래와 같이 복사합니다.

```text
src/run_repetitive_hybrid_demo.py, src/run_washer_hybrid_demo.py,
src/ha_recorder_observation.py 및 나머지 src/*.py
  -> /data/ha_ai_fullcycle_20260911/src/

deploy/*.service, deploy/repetitive-central-*.sh, deploy/*.awk
  -> /data/ha_ai_fullcycle_20260911/config/

scripts/*.sh
  -> /data/ha_ai_fullcycle_20260911/scripts/
```

셸 스크립트에 실행 권한을 부여합니다.

```sh
chmod 0755 /data/ha_ai_fullcycle_20260911/scripts/*.sh
```

맞춤 TTS를 한 번 생성합니다.

```sh
/data/ha_ai_fullcycle_20260911/scripts/generate-air-purifier-tts.sh
```

다음 모델 자산은 용량과 배포 정책 때문에 이 공유 폴더의 Git 추적 대상이 아닙니다. 기존 라즈베리파이 배포본에 있어야 하며, 새 장비로 옮길 때는 팀의 모델 artifact 저장소 또는 승인된 전달 경로로 별도 배포합니다.

```text
/data/ha_ai_fullcycle_20260911/outputs/normal_demo_baseline_v2.json
/data/ha_ai_fullcycle_20260911/outputs/fridge_ai_demo_lifecycle_20261004/
/data/ha_ai_fullcycle_20260911/outputs/washer_ai_demo_lifecycle_20261005/
```

기존 MQTT 공기청정기 자동화는 Central을 우회하므로 삭제합니다. 공기청정기는 Central 승인
서비스가 `pauseable-air-purifier-tts.service`를 시작한 뒤 `ExecStartPost`에서 켭니다. 실제
엔티티는 다음과 같습니다.

```text
냉장고 문: binary_sensor.naengjanggo_door
공기청정기 전원: switch.gonggiceongjeonggi_power
세탁기 상태: sensor.setaggi_current_status
```

## 6. 시연 시작

재부팅 시 브라우저 서비스의 대기 스크립트가 아래 시작 스크립트를 한 번 호출해 자동 복구합니다. 수동 복구나 촬영 전 재초기화가 필요하면 직접 실행해도 됩니다.

```sh
/data/ha_ai_fullcycle_20260911/scripts/start-repetitive-demo.sh
```

이 스크립트는 다음을 수행합니다.

- 읽기 전용 `/etc` 대신 `/run/systemd/system`에 TTS 런타임 유닛 복구
- 기존 일반 반복행동 TTS 비활성화
- Central의 전역 YouTube 자동 실행 비활성화
- `REPETITIVE_ACTIONS_ENABLED=1`로 Central ActionRouter 활성화
- Central 승인 로그에만 반응하는 시간대별 출력 서비스 적용
- 기존 MQTT 직접 출력 라우터·trigger path·HA 직접 자동화 제거
- 미배포 앱 Decision Gateway 비활성화
- 컨테이너, 기준선, 모델 lifecycle, 맞춤 TTS 자산 존재 여부 확인
- Central Atlas App 재시작
- 기존 데모 실행기와 직접 MQTT 라우터를 종료하고 Central 승인 서비스와 감지기만 재시작

## 7. 촬영 전 체크

### 컨테이너

```sh
docker ps --format '{{.Names}}\t{{.Status}}' | grep -E 'homeassistant|ha-ai-full'
```

두 컨테이너 모두 `Up`이어야 합니다.

### 실행기

```sh
docker exec ha-ai-full tail -n 20 /app/outputs/repetitive_hybrid_live.log
docker exec ha-ai-full tail -n 20 /app/outputs/washer_hybrid_live.log
journalctl -u pauseable-repetitive-central-output.service --since '5 minutes ago' --no-pager
```

두 감지기 로그에는 다음 형태가 보여야 합니다.

```text
RECORDER_STATUS ... opens_10m=...
DEMO_NO_ACTION hybrid_final_level=normal
RECORDER_STATUS ... washer_on_10m=... toggles_10m=...
DEMO_NO_ACTION hybrid_final_level=normal
```

Central 승인 출력 서비스는 `active`이고, 직접 MQTT 출력 프로세스는 없어야 합니다.

```text
systemctl is-active pauseable-repetitive-central-output.service
docker top ha-ai-full | grep route_repetitive_output.py  # 출력이 없어야 정상
```

### 공기청정기와 자동화

- 공기청정기 전원은 촬영 전에 `off`로 둡니다.
- MQTT를 직접 구독하는 Home Assistant 반복행동 자동화가 없어야 합니다.
- `pauseable-air-purifier-tts.service`에 `ExecStartPost`가 설정됐는지 확인합니다.
- 디스플레이 스피커가 연결되어 있어야 합니다.
- 유튜브 브라우저가 남아 있으면 브라우저 서비스와 브리지 앱을 종료하고 홈 앱을 다시 시작합니다.

## 8. 촬영 순서

1. 현재 시간대의 출력 대상(TV 또는 공기청정기)이 대기 상태인지 촬영합니다.
2. 냉장고 또는 세탁기에서 모델이 반복행동으로 판정할 행동을 수행합니다.
3. 마지막에는 가전을 안전한 상태로 둡니다.
4. 하이브리드 최종 판정과 MQTT 발행을 기다립니다.
5. 08:00–18:00이면 TV, 18:00–08:00이면 공기청정기가 실행되는 모습을 촬영합니다.

행동 횟수는 촬영 절차의 고정 성공 조건이 아닙니다. 성공 여부는 하이브리드 최종 판정 로그로 확인합니다.

## 9. 성공 확인

### AI 및 MQTT

```sh
docker exec ha-ai-full tail -n 100 /app/outputs/repetitive_hybrid_live.log
```

성공 시 핵심 로그:

```text
model_status ... shadow
published topic=pauseable/ai/repetitive/decision
DEMO_PUBLISHED ...
```

Central 승인 출력 성공 로그:

```text
CENTRAL_DECISION_ACCEPTED ... source=repetitive-ai decision=repetitive_behavior
CENTRAL_ACTION_ROUTED ... disposition=execute ... speak=true
REPETITIVE_CENTRAL_OUTPUT_SELECTED ... output=tv
# 또는
REPETITIVE_CENTRAL_OUTPUT_SELECTED ... output=air_purifier
REPETITIVE_CENTRAL_OUTPUT_COMPLETED ...
```

### Central Atlas App

```sh
journalctl -b -u am.com.atlas.app.pauseableatlas.service --no-pager \
  | grep -E 'CENTRAL_DECISION_ACCEPTED|CENTRAL_ACTION_ROUTED' \
  | tail -n 20
```

### TTS

```sh
journalctl -b -u pauseable-air-purifier-tts.service --no-pager | tail -n 20
journalctl -b -u pauseable-washer-youtube-tts.service --no-pager | tail -n 20
journalctl -b -u pauseable-youtube-control.service --no-pager | tail -n 20
```

`status=0/SUCCESS`가 보여야 합니다.

### 공기청정기

Home Assistant에서 `switch.gonggiceongjeonggi_power`가 `on`인지 확인합니다.

## 10. 재촬영

- 로그와 CSV를 지우지 않습니다.
- 즉시 다시 촬영할 때는 `docker exec ha-ai-full python /app/src/prepare_fridge_retake.py` 또는 `prepare_washer_retake.py`를 실행해 에피소드 상태를 초기화합니다.
- 하이브리드 최종 판정이 `normal`로 돌아오면 실행기가 `normal` 결정을 발행하고 다음 에피소드를 기다립니다.
- Central action router의 쿨다운은 15분입니다. 두 촬영 사이에는 최소 15분을 둡니다.
- 다음 촬영 전에 공기청정기를 다시 `off`로 둡니다.

## 11. 알려진 제한

- 모델은 합성 데이터 기반이며 실가정 개인화 모델이 아닙니다. 횟수 게이트 대신 모델 검증과 오탐률 측정으로 품질을 관리해야 합니다.
- Atlas OS의 `/etc/systemd/system`은 읽기 전용이므로 TTS와 Central 승인 출력 유닛은 재부팅 시 사라집니다. 시작 스크립트가 이를 복구합니다.
- OS에 고정된 브라우저 서비스는 부팅 시 대기만 하도록 영구 스크립트를 수정했습니다. 브라우저는 `PLAY_WASHER_FAVORITE` 요청에서만 실제로 열립니다.
- 보호자 앱용 `/api/events/decisions`가 현재 백엔드에 배포되지 않아 Decision Gateway는 비활성화합니다.
- `run_repetitive_mqtt_stream.py`는 현재 시연 구성과 호환되지 않습니다.
