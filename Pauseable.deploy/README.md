# 장치별 빌드·설치·복구

이 폴더는 공통 저장소의 소스와 설정을 Pi 3·Pi 4·Pi 5에 나누어 전달하는 배포 도구를 관리합니다. **소스 준비, 대상 환경 빌드, 장치 설치와 실기 확인은 순서대로 진행합니다.** GitHub 갱신만으로 실행 중인 장치가 바뀌지는 않습니다.

[전체 시스템](../README.md) · [장치 프로그램](../Pauseable.edge/README.md) · [상세 배포 인계](README.md#배포-순서)

## 1. 먼저 산출물을 구분한다

| 산출물 | 만드는 과정 | 사용하는 곳 |
| --- | --- | --- |
| `tar.gz` | 장치별 소스·설정 묶음 생성 | 대상 장치에서 파일 준비 |
| `.ipk` | Atlas SDK로 Central 빌드·패키징 | Pi 5 앱 설치 |
| `.apk` | Flutter Android 빌드 | 보호자 휴대폰 설치 |
| `.onnx`와 Piper 설정 | GPU 음성 학습·Export·검증 | Pi 로컬 TTS |

소스 압축 파일에는 빌드한 Central 바이너리·APK·개인화 음성 모델이 자동으로 들어가지 않습니다. 각 산출물을 별도 과정으로 준비합니다.

<a id="장치별-배포-구성"></a>

## 2. 설치할 장치와 구성 파일을 정한다

| 장치·영역 | 담당 기능 | 배포 관련 경로 |
| --- | --- | --- |
| Pi 3 | mmWave Serial 입력·SSH 중계 | [mmwave-autostart/pi3](mmwave-autostart/pi3) |
| Pi 4 | 카메라 버퍼·대표 사진 업로드 | [camera 소스](../Pauseable.edge/camera), [배포 인계](README.md#배포-순서) |
| Pi 5 | AI·Central·FIFO·음성·출력 | [mmwave-autostart/pi5](mmwave-autostart/pi5), [pi5/systemd](pi5/systemd) |
| HA 서비스 | 가전 수집·분석·출력 서비스 | [HA deploy](../Pauseable.ai/ha/deploy) |
| GPU Worker | Piper 학습 작업 | [gpu/voice-worker](gpu/voice-worker) |
| 기존 장치 이전 | 이름·서비스·경로 대응 | [migration](migration) |

API·Flutter 설정과 빌드는 [Apps README](../Pauseable.apps/README.md#개발환경과-실행)에서 준비합니다. 음성 모델 교체·행동별 가전 출력·음악 설치는 [Edge README](../Pauseable.edge/README.md)에서 이어집니다.

<a id="배포-순서"></a>

## 3. 기존 설치를 백업한다

1. 현재 소스·모델·서비스 버전과 실행 장치를 기록합니다.
2. 환경 파일·개인 모델·DB·서비스 설정 중 교체할 파일을 백업합니다.
3. Token·사용자·그룹·장치 경로와 읽기/쓰기 권한을 확인합니다.
4. 데이터 폴더 전체를 덮어쓰지 않고 필요한 파일만 설치 대상으로 정합니다.

이름을 이전할 때는 [legacy-to-pauseable.json](migration/legacy-to-pauseable.json)의 Topic·환경변수·서비스·경로 대응을 함께 확인합니다. 폴더 이름 변경과 기존 DB·모델의 호환성 확인은 다른 작업입니다.

<a id="기기별-소스-묶음"></a>

## 4. 소스 무결성을 검사하고 묶음을 만든다

Python 3.12로 **저장소 루트에서** 실행합니다.

```sh
python Pauseable.deploy/mmwave-autostart/package_devices.py --verify-source-manifest
```

[FILES.sha256](mmwave-autostart/FILES.sha256)는 배포에 포함할 파일과 기대 체크섬을 정한 목록입니다. [package_devices.py](mmwave-autostart/package_devices.py)는 이 목록의 파일을 검사하고 장치 역할에 맞게 선택합니다.

검사가 통과한 소스에서 묶음을 생성합니다.

```sh
python Pauseable.deploy/mmwave-autostart/package_devices.py --output deployment-bundles
```

| 묶음 | 포함 대상 |
| --- | --- |
| `pauseable-pi3.tar.gz` | 센서 릴레이·관련 계약·설치 설정 |
| `pauseable-pi4.tar.gz` | 카메라·이전 설정 |
| `pauseable-pi5.tar.gz` | Manifest에 선언한 Central·AI·API·음성·연동·Pi 5 설정 |

묶음에는 실제 Token·원본 녹음·개인 모델을 넣지 않습니다. 압축을 푼 최상위 폴더에서 포함 파일을 다시 확인합니다.

```sh
sha256sum -c BUNDLE.sha256
```

<a id="배포-준비-상태"></a>

### 현재 소스 검사 결과

2026-10-28 최종 문서 정리를 반영한 소스 Manifest는 744개 파일을 선언합니다. 삭제된 문서 경로를 제외하고, 현재 `main`의 앱·API·음악 출력 변경과 README를 포함해 체크섬을 갱신했습니다.

소스 무결성 검사와 Pi 3·Pi 4·Pi 5 묶음 생성·압축 내부 체크섬 검사를 통과했습니다. 실제 장치 설치·센서·카메라·음성·휴대폰의 E2E 확인은 별도입니다.

<a id="장치별-준비"></a>

## 5. 대상 환경에서 빌드하고 설치한다

| 대상 | 설치 전 준비 | 설치 후 첫 확인 |
| --- | --- | --- |
| Pi 3 | Serial/dialout 권한·Pi 5 주소·SSH 계정·FIFO reader | 센서 입력과 연결 끊김 복구 |
| Pi 4 | 카메라·Docker·트리거 인증·Device Token | 버퍼·대표 사진·업로드 |
| Pi 5 | Atlas SDK 산출물·Docker·모델·환경 파일·권한 | Central·AI·TTS·가전·API |
| GPU Worker | NVIDIA Driver·Docker GPU·Worker Token | dry-run·Job 임대·학습·게시 |
| API·앱 | API 저장소·Push 설정·앱 빌드 설정 | 인증·이력·설치 APK의 알림 |

Pi 3 설치기의 `--check`는 파일 구성을 확인하고 `--apply`는 설치를 수행합니다. 설치만으로 서비스를 자동 시작하지 않습니다. 각 설치 스크립트와 [배포 인계](README.md#배포-순서)의 시작 순서를 따릅니다. ATLAS 읽기 전용 루트나 보안 설정을 설치 편의를 위해 임의로 완화하지 않습니다.

<a id="완료-기준"></a>

## 6. 입력부터 실제 출력까지 확인한다

1. 서비스 시작과 실제 입력 수신을 나누어 확인합니다.
2. HA·센서 입력이 AI 판단과 MQTT 메시지로 이어지는지 확인합니다.
3. Central의 승인·억제 사유와 실제 음성·가전 동작을 대조합니다.
4. 같은 사건 ID로 Outbox·API 저장·앱 알림을 확인합니다. 출입 사진은 해당 출입 사건으로 별도 대조합니다.
5. 중복·재연결·재시작·모델 검증 실패 시 복구 동작을 시험합니다.

`active`는 서비스 실행 상태입니다. 스피커·가전·사진·휴대폰 알림까지 확인한 결과와 구분해 기록합니다.

<a id="기존-장치에서-이름-이전"></a>

## 7. 문제가 생기면 해당 파일과 버전을 복원한다

교체 전 백업으로 모델·환경·DB·서비스를 필요한 범위만 복원합니다. 서비스 파일을 바꿨으면 `systemctl daemon-reload` 후 해당 서비스의 입력부터 다시 확인합니다. 모델 교체기는 실패 시 기존 모델을 유지하는 정책을 사용합니다.

복구 기록에는 원인, 복원한 버전과 재시험 결과를 남깁니다. 개인 이력·사진·Token·presigned URL은 공유 로그에서 제외합니다.
