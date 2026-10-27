# Pauseable.deploy

<a id="pauseabledeploy"></a>

<a id="장치별-배포-구성"></a>

**공통 소스에서 Pi별 배포 묶음을 만들고 장치 서비스·설치·복구 구성을 관리합니다.**

[프로젝트](../README.md) · [AI](../Pauseable.ai/README.md) · [장치 실행](../Pauseable.edge/README.md) · [앱·API](../Pauseable.apps/README.md)

[배포 산출물](#배포-산출물) · [폴더 구조](#폴더-구조) · [소스 검사와 묶음 생성](#소스-검사와-묶음-생성) · [설치 순서](#설치-순서) · [시연 확인 기준](#시연-확인-기준)

<a id="배포-산출물"></a>

## 배포 산출물

| 산출물 | 만드는 과정 | 사용하는 곳 |
| --- | --- | --- |
| 장치별 `.tar.gz` | Manifest에 선언한 소스·설정 선택 | Pi에 소스 준비 |
| Central `.ipk` | Atlas SDK 빌드·패키징 | Pi 5 앱 설치 |
| Android `.apk` | Flutter 빌드 | 보호자 휴대폰 |
| 음성 `.onnx`·설정 | GPU Piper 학습·Export | Pi 로컬 합성 |

장치별 소스 묶음을 준비한 뒤 실행 파일을 설치합니다. 사용자·권한·인증·모델·이미지와 입력 경로를 각 장치에 맞게 설정합니다.

<a id="폴더-구조"></a>

## 폴더 구조

```text
Pauseable.deploy/
├── gpu/                                              # GPU 음성 학습 장치 설정
│   └── voice-worker/                                 # 학습 Worker systemd 서비스
│       └── pauseable-voice-training-worker.service   # GPU 음성 학습 Worker 실행
├── migration/
│   └── legacy-checks/
├── mmwave-autostart/                                 # 소스 Manifest·장치별 묶음 생성기
│   ├── pi3/                                          # Serial 릴레이 설치기·서비스
│   │   ├── install.sh                                # Serial 릴레이 설치
│   │   └── pauseable-mmwave-relay.service            # 센서 릴레이 서비스
│   ├── pi5/                                          # FIFO·mmWave Docker·Publisher 설정
│   │   ├── pauseable-wandering-publisher.service     # Pi 5 배회 판단 발행 서비스
│   │   └── publisher.env.example                     # 배회 Publisher 환경 설정
│   ├── FILES.sha256                                  # 배포 입력 파일의 SHA-256 목록
│   └── package_devices.py                            # 소스 검사와 Pi별 배포 묶음 생성
└── pi5/                                              # Pi 5 앱·Gateway·웹 실행 설정
    └── systemd/
        └── pauseable-pi-app.service                  # Atlas Central 앱 실행
```

| 경로 | 준비하는 구성 |
| --- | --- |
| `gpu/voice-worker` | 음성 학습 Worker의 systemd 서비스 |
| `migration/legacy-checks` | 기존 장치 파일을 대조할 이전 체크섬 |
| `migration/legacy-to-pauseable.json` | 이전 이름·경로·서비스·Topic 대응 |
| `mmwave-autostart` | 전체 소스 체크섬과 장치별 압축 생성기 |
| `mmwave-autostart/pi3` | Serial 릴레이 설치·실행 설정 |
| `mmwave-autostart/pi5` | FIFO 준비·Docker·배회 Publisher 설정 |
| `pi5/systemd` | Central·Gateway·Flutter 웹·터널 등 실행 Unit |

카메라 구성은 [Edge camera](../Pauseable.edge/camera), HA 서비스는 [AI ha/deploy](../Pauseable.ai/ha/deploy)에 있으며 생성기가 해당 경로를 장치별로 선택합니다.

<a id="기기별-소스-묶음"></a>
<a id="배포-준비-상태"></a>

<a id="소스-검사와-묶음-생성"></a>

## 소스 검사와 묶음 생성

Python 3.12로 저장소 루트에서 실행합니다.

```sh
python Pauseable.deploy/mmwave-autostart/package_devices.py --verify-source-manifest
python Pauseable.deploy/mmwave-autostart/package_devices.py --output deployment-bundles
```

[FILES.sha256](mmwave-autostart/FILES.sha256)는 선언한 입력 파일과 SHA-256을 기록합니다. [package_devices.py](mmwave-autostart/package_devices.py)는 경로·파일·체크섬을 검사하고 장치에 필요한 항목만 선택합니다.

| 묶음 | 포함 대상 |
| --- | --- |
| `pauseable-pi3.tar.gz` | 센서 릴레이·계약·Pi 3 설치 설정 |
| `pauseable-pi4.tar.gz` | 카메라·트리거 설정·이전 자료 |
| `pauseable-pi5.tar.gz` | Central·AI·API·음성·연동·Pi 5 설정 중 선언한 입력 |

각 압축에는 `BUNDLE.sha256`이 있습니다. 압축을 푼 최상위 폴더에서 `sha256sum -c BUNDLE.sha256`으로 확인합니다. 실제 Token·개인 녹음·개인 ONNX·Central 실행 바이너리·APK는 이 소스 묶음과 분리합니다.

<a id="배포-순서"></a>
<a id="장치별-준비"></a>

<a id="설치-순서"></a>

## 설치 순서

1. 대상 장치와 현재 소스·모델·환경·서비스 버전을 확인합니다.
2. 교체할 설정·모델·DB와 서비스 파일을 백업합니다.
3. 소스 Manifest와 압축 내부 체크섬을 확인합니다.
4. SDK·Docker 이미지·Piper 실행 파일 등 대상 환경을 준비합니다.
5. 실제 사용자·장치 경로·인증·가구 ID·엔티티·네트워크 설정을 맞춥니다.
6. 필요한 파일만 설치하고 서비스를 시작한 뒤 실제 입력부터 확인합니다.

| 대상 | 설치 전 확인 | 설치 후 확인 |
| --- | --- | --- |
| Serial 릴레이 Pi | Serial 권한·SSH·Pi 5 FIFO reader | 실제 센서 입력·중계·재연결 |
| 카메라 Pi 4 | 카메라·Docker·트리거 및 Device 인증 | 버퍼·대표 사진·업로드 |
| Pi 5 | Atlas SDK 산출물·HA·MQTT·모델·음성 환경 | 판단 수신·실행 승인·TTS·API |
| GPU Worker | NVIDIA Driver·GPU Docker·Worker 인증 | 자료 검사·Job·학습·게시 |
| 앱·API | 저장소·Push·환경변수·플랫폼 설정 | 인증·이력·실제 휴대폰 수신 |

Serial 중계 구성은 Pi에 릴레이 서비스를 설치하고 Pi 5 FIFO에 연결합니다. Pi 3가 ESP32의 USB 전원을 공급하는 Wi-Fi 구성은 ESP32 펌웨어의 목적지와 Pi 5의 수신·분석 입력을 함께 설정합니다.

<a id="완료-기준"></a>

<a id="시연-확인-기준"></a>

## 시연 확인 기준

서비스의 실행 상태와 센서·가전·스피커·앱의 실제 출력을 확인합니다. 동일 사건 ID로 입력, AI 판단, Central 승인, Outbox·API 저장과 보호자 표시를 대조합니다. 출입 사진은 해당 출입 사건으로 대조하고 중복·단절·재시작도 시험합니다.

<a id="기존-장치에서-이름-이전"></a>
