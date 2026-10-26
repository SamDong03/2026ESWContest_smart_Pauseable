# HA MQTT 가상 기기 시연 가이드

이 문서는 실제 기기가 없는 에어컨, 전자레인지, 도어락을 Home Assistant에 MQTT 가상 엔티티로 등록하고, 해당 이벤트를 HA baseline 탐지 파이프라인에 넣는 절차를 정리한다.

## 1. 전제 조건

- Home Assistant OS가 VirtualBox에서 실행 중이어야 한다.
- Windows 브라우저에서 Home Assistant가 `http://127.0.0.1:8124`로 열려야 한다.
- Home Assistant에 Mosquitto MQTT Broker 애드온과 MQTT 통합이 추가되어 있어야 한다.
- VirtualBox NAT 포트 포워딩에 MQTT가 추가되어 있어야 한다.

VirtualBox 네트워크 포트 포워딩 예시는 다음과 같다.

| 이름 | 프로토콜 | 호스트 IP | 호스트 포트 | 게스트 IP | 게스트 포트 |
| --- | --- | --- | --- | --- | --- |
| HA Web | TCP | 빈칸 | 8124 | 빈칸 | 80 |
| MQTT | TCP | 빈칸 | 1884 | 빈칸 | 1883 |

## 2. Docker에서 환경 변수 설정

Docker 컨테이너 안에서 다음을 실행한다.

```bash
cd /app/ecoai-tutorial/ha_ai
source /app/venv/bin/activate
```

Docker에서 Windows 호스트 IP를 자동으로 잡는다.

```bash
HA_HOST=$(python - <<'PY'
import socket, struct

with open("/proc/net/route") as f:
    for line in f.readlines()[1:]:
        parts = line.split()
        if parts[1] == "00000000":
            print(socket.inet_ntoa(struct.pack("<L", int(parts[2], 16))))
            break
PY
)

export HA_URL="http://$HA_HOST:8124"
export MQTT_HOST="$HA_HOST"
export MQTT_PORT=1884
export MQTT_USER="mqtt_user"
read -s MQTT_PASSWORD
export MQTT_PASSWORD
```

`read -s MQTT_PASSWORD`를 실행하면 화면에 아무것도 표시되지 않는다. 이때 Mosquitto에 만든 MQTT 사용자 비밀번호를 입력하고 Enter를 누르면 된다.

Home Assistant API token도 같은 방식으로 등록한다.

```bash
read -s HA_TOKEN
export HA_TOKEN
```

## 3. MQTT 가상 기기 등록

먼저 필요한 Python 패키지가 없다면 설치한다.

```bash
pip install paho-mqtt
```

가상 기기 discovery 정보를 Home Assistant에 발행한다.

```bash
python src/publish_virtual_mqtt_devices.py \
  --scenario discover
```

Home Assistant의 설정 > 기기 및 서비스 > MQTT에서 다음 엔티티가 보이면 성공이다.

- `lock.pauseable_virtual_door_lock`
- `switch.pauseable_virtual_microwave_power`
- `sensor.pauseable_virtual_microwave_status`
- `switch.pauseable_virtual_air_conditioner_power`
- `select.pauseable_virtual_air_conditioner_mode`
- `number.pauseable_virtual_air_conditioner_temperature`

## 4. 시연용 이상행동 발행

가볍게 정상 사용을 발행할 때:

```bash
python src/publish_virtual_mqtt_devices.py \
  --scenario normal \
  --delay-seconds 2
```

도어락 반복 확인:

```bash
python src/publish_virtual_mqtt_devices.py \
  --scenario risk_door_lock \
  --delay-seconds 2
```

전자레인지 반복 사용:

```bash
python src/publish_virtual_mqtt_devices.py \
  --scenario risk_microwave \
  --delay-seconds 2
```

에어컨 모드/온도 반복 조작:

```bash
python src/publish_virtual_mqtt_devices.py \
  --scenario risk_air_conditioner \
  --delay-seconds 2
```

발표용 복합 시나리오:

```bash
python src/publish_virtual_mqtt_devices.py \
  --scenario demo_risk_combo \
  --delay-seconds 2
```

## 5. 이벤트 수집과 탐지

MQTT 상태 변화를 놓치지 않으려면 snapshot 수집보다 WebSocket 이벤트 수집을 우선 사용한다.

```bash
python src/collect_ha_events_ws.py \
  --ha-url "$HA_URL" \
  --token "$HA_TOKEN" \
  --output data/raw/ha_virtual_mqtt_events.csv \
  --duration-seconds 240 \
  --write-initial-snapshot \
  --entity-keyword pauseable_virtual \
  --truncate
```

다른 터미널에서 위 시나리오 발행 명령을 실행하면, 수집기가 HA 상태 변화를 CSV로 저장한다.

수집된 파일을 baseline 파이프라인에 넣는다.

```bash
python src/run_ha_pipeline.py \
  --input data/raw/ha_virtual_mqtt_events.csv \
  --baseline models/user_001_real_baseline_v2.json \
  --prefix ha_virtual_mqtt
```

결과 파일은 다음 위치에 생성된다.

- `outputs/ha_virtual_mqtt_result.csv`
- `outputs/ha_virtual_mqtt_episode_summary.csv`

## 6. 한 명령으로 시연 자동화

위 절차가 한 번 성공한 뒤에는 다음 명령으로 수집, MQTT 시나리오 발행, baseline 추론, episode 요약 출력을 한 번에 실행할 수 있다.

```bash
python src/run_ha_live_demo.py \
  --ha-url "$HA_URL" \
  --ha-token "$HA_TOKEN" \
  --mqtt-host "$MQTT_HOST" \
  --mqtt-port "$MQTT_PORT" \
  --mqtt-user "$MQTT_USER" \
  --mqtt-password "$MQTT_PASSWORD" \
  --scenario demo_risk_combo \
  --prefix ha_live_demo
```

이 명령은 내부에서 다음 순서로 동작한다.

1. Home Assistant WebSocket 수집기를 시작한다.
2. `pauseable_virtual` 엔티티의 초기 상태를 CSV에 저장한다.
3. MQTT 가상 기기 시나리오를 발행한다.
4. 수집된 CSV를 baseline 파이프라인에 넣는다.
5. `outputs/ha_live_demo_result.csv`와 `outputs/ha_live_demo_episode_summary.csv`를 만든다.
6. terminal에 level count와 episode 요약을 출력한다.

실행 전에 토큰과 비밀번호 환경변수가 들어 있는지 길이만 확인한다.

```bash
echo "$HA_URL"
echo "$MQTT_HOST"
echo "$MQTT_PORT"
echo "$MQTT_USER"
echo ${#HA_TOKEN}
echo ${#MQTT_PASSWORD}
```

토큰이나 비밀번호가 `0`으로 나오면 다시 입력한다.

```bash
read -s HA_TOKEN
export HA_TOKEN

read -s MQTT_PASSWORD
export MQTT_PASSWORD
```

## 7. 현재 의미

이 방식은 실제 기기를 사지 않고도 HA 엔티티 생성, 이벤트 수집, 표준화, feature 생성, baseline 추론, episode 요약까지 한 번에 검증하기 위한 시연용 구조다.

나중에 실제 도어락, 전자레인지, 에어컨 연동이 가능해지면 MQTT 가상 엔티티 대신 실제 Home Assistant 엔티티를 같은 mapper 규칙으로 읽으면 된다.

상시 실행은 `docs/ha_pi5_automation_guide.md`의 Raspberry Pi 5 자동화 루프와 `systemd` 서비스로 넘기면 된다.
