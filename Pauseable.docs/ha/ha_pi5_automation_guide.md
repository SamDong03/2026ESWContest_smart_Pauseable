# Raspberry Pi 5 Home Assistant 자동화 가이드

> 초기 일반 Linux/Python 환경용 가이드다. ATLAS의 읽기 전용 호스트에서 apt/venv 절차를 그대로 실행하지 않는다. 현재 Docker 및 연속 수집 서비스는 [9월 11일 배포 기록](PI_FULL_AUTOMATION_KO.md)을 기준으로 한다.

이 문서는 Home Assistant 이벤트 수집, baseline 탐지, autoencoder 이상탐지를 Raspberry Pi 5에서 자동 실행하는 방법을 정리한다.

## 1. 목표 구조

최종 구조는 다음처럼 잡는다.

```text
Home Assistant -> WebSocket event collector -> baseline + autoencoder pipeline -> CSV result/summary
```

Pi에서는 터미널을 열어 둔 상태가 아니라 `systemd` 서비스가 자동으로 Python 루프를 실행한다. Pi가 켜지면 자동 시작되고, 중간에 죽어도 다시 시작된다.

## 2. Home Assistant 위치별 URL

Home Assistant가 같은 Pi에서 돌면 다음을 쓴다.

```bash
HA_URL=http://127.0.0.1:8123
```

Home Assistant가 같은 공유기의 다른 장치에서 돌면 다음처럼 쓴다.

```bash
HA_URL=http://homeassistant.local:8123

HA_URL=http://192.168.0.50:8123
```

현재 Windows VirtualBox HA를 계속 쓰는 경우에는 Pi가 Windows PC에 접근해야 하므로 Windows PC와 VirtualBox가 켜져 있어야 한다. 최종 발표/상시 운용은 HA도 Pi나 별도 상시 장치에 두는 편이 낫다.

## 3. Pi에 코드 준비

Pi에서 필요한 패키지를 설치한다.

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git
```

프로젝트 폴더를 Pi의 `/home/pi/ha_ai`에 둔다. GitHub를 쓰면 clone하고, 아니면 현재 `Pauseable.ai/ha` 폴더를 그대로 복사해도 된다.

```bash
cd /home/pi/ha_ai
python3 -m venv .venv
source .venv/bin/activate
pip install pandas paho-mqtt
```

## 4. 환경변수 파일 만들기

예시 파일을 복사한다.

```bash
cd /home/pi/ha_ai
cp deploy/systemd/ha-ai.env.example deploy/systemd/ha-ai.env
nano deploy/systemd/ha-ai.env
chmod 600 deploy/systemd/ha-ai.env
```

`deploy/systemd/ha-ai.env` 안에서 최소한 아래 두 값을 실제 값으로 바꾼다.

```bash
HA_URL=http://127.0.0.1:8123
HA_TOKEN=여기에_HA_장기_액세스_토큰
```

가상 MQTT 기기 시연까지 Pi에서 같이 할 때만 `MQTT_*` 값도 채운다.

## 5. 서비스 등록 전에 수동 테스트

먼저 한 번만 실행해서 HA 연결과 파이프라인을 확인한다.

```bash
cd /home/pi/ha_ai
source .venv/bin/activate
set -a
source deploy/systemd/ha-ai.env
set +a

python src/run_ha_automation_loop.py \
  --collection-seconds 120 \
  --max-cycles 1 \
  --prefix ha_pi_test
```

성공하면 결과가 아래에 생긴다.

```text
outputs/ha_pi_test_YYYYMMDD_HHMMSS_result.csv
outputs/ha_pi_test_YYYYMMDD_HHMMSS_autoencoder_result.csv
outputs/ha_pi_test_YYYYMMDD_HHMMSS_episode_summary.csv
outputs/ha_automation_cycle_summary.csv
```

`*_result.csv`에는 baseline 판정과 autoencoder 판정이 합쳐져 저장된다. 주요 autoencoder 컬럼은 `ae_reconstruction_error`, `ae_score`, `ae_level`, `ae_reason`이다.

가상기기만 수집하고 싶으면 `--entity-keyword pauseable_virtual`을 붙인다.

```bash
python src/run_ha_automation_loop.py \
  --collection-seconds 120 \
  --max-cycles 1 \
  --prefix ha_pi_virtual_test \
  --entity-keyword pauseable_virtual
```

## 6. 부팅 자동실행 등록

수동 테스트가 성공한 뒤 서비스를 등록한다.

```bash
sudo cp deploy/systemd/ha-ai-automation.service /etc/systemd/system/ha-ai-automation.service
sudo systemctl daemon-reload
sudo systemctl enable ha-ai-automation
sudo systemctl start ha-ai-automation
```

상태 확인은 다음 명령을 쓴다.

```bash
sudo systemctl status ha-ai-automation
journalctl -u ha-ai-automation -f
```

멈출 때는 다음을 쓴다.

```bash
sudo systemctl stop ha-ai-automation
```

## 7. 운영 옵션

기본 서비스는 10분마다 한 번의 수집 구간을 만들고 바로 분석한다.

```text
--collection-seconds 600
```

baseline 자동 업데이트까지 켜고 싶으면 서비스의 `ExecStart` 끝에 아래 옵션을 추가한다. 발표 전 실험 단계에서는 먼저 결과가 안정적인지 본 뒤 켜는 편이 좋다.

```text
--update-baseline --init-history-from-current-normal
```

## 8. 현재 Windows/Docker에서 같은 루프 테스트

지금 쓰는 Docker 컨테이너 안에서는 아래처럼 한 회차만 확인할 수 있다.

```bash
cd /app/ecoai-tutorial/ha_ai
source /app/venv/bin/activate

python src/run_ha_automation_loop.py \
  --ha-url "$HA_URL" \
  --ha-token "$HA_TOKEN" \
  --collection-seconds 120 \
  --max-cycles 1 \
  --prefix ha_docker_test \
  --entity-keyword pauseable_virtual
```

현재처럼 VirtualBox HA를 쓰면 `HA_URL`은 Docker에서 접근 가능한 주소여야 한다. 예를 들면 지금 성공했던 값은 다음 형태다.

```bash
HA_URL=http://172.19.128.1:8124
```

## 9. ATLAS Platform처럼 Python 없이 Docker만 있는 Pi

ATLAS Platform 이미지처럼 `python`, `python3`, `apt`가 없고 `docker`만 있는 경우에는 Python을 OS에 설치하지 않고 Docker 이미지로 실행한다.

Docker daemon이 꺼져 있으면 먼저 켠다.

```bash
dockerd >/tmp/dockerd.log 2>&1 &
docker info
```

Pi에서 한 번만 이미지를 만든다.

```bash
cd /data/ha_ai
docker build -f Dockerfile.pi -t ha-ai-runner:pi .
```

HA 연결 테스트:

```bash
docker run --rm \
  --network host \
  --security-opt apparmor=unconfined \
  --env-file deploy/systemd/ha-ai.env \
  -v /data/ha_ai:/app \
  -w /app \
  ha-ai-runner:pi \
  python src/run_ha_automation_loop.py \
    --collection-seconds 120 \
    --max-cycles 1 \
    --prefix ha_pi_test \
    --entity-keyword pauseable_virtual
```

`--security-opt apparmor=unconfined`은 현재 ATLAS 이미지에서 Docker 기본 AppArmor 프로필 로딩이 실패할 때 필요한 옵션이다.

또는 프로젝트에 포함된 실행 스크립트를 쓴다.

```bash
cd /data/ha_ai
./run_pi_ha_ai.sh \
  --collection-seconds 120 \
  --max-cycles 1 \
  --prefix ha_pi_test \
  --entity-keyword pauseable_virtual
```

상시 자동화는 가상 엔티티만 보지 않도록 `--entity-keyword`를 빼고 실행한다. 이렇게 해야 LG ThinQ처럼 실제 Home Assistant 통합으로 들어온 냉장고, 세탁기, 건조기, 공기청정기 엔티티도 같은 collector가 함께 수집한다.

```bash
./run_pi_ha_ai.sh \
  --collection-seconds 600 \
  --prefix ha_pi_all \
  --summary-csv outputs/ha_pi_all_cycle_summary.csv \
  --log-dir outputs/logs/ha_pi_all
```

부팅 자동실행 등록:

```bash
cp deploy/systemd/ha-ai-docker.service /etc/systemd/system/ha-ai-docker.service
systemctl daemon-reload
systemctl enable ha-ai-docker.service
systemctl start ha-ai-docker.service
systemctl status ha-ai-docker.service --no-pager
```
