# Pauseable.third_party

<a id="pauseablethird_party"></a>

**Central의 JSON 처리와 개인화 음성 학습·합성에 사용하는 외부 소스, 버전과 라이선스를 관리합니다.**

[프로젝트](../README.md) · [AI 음성 학습](../Pauseable.ai/README.md#voice-학습과-운영-상세) · [Central](../Pauseable.edge/README.md)

[외부 소스](#포함한-외부-소스) · [폴더 구조](#폴더-구조) · [프로젝트 연결](#pauseable과-연결되는-위치) · [변경 기록](#원본과-변경-기록)

<a id="포함한-외부-소스"></a>

## 포함한 외부 소스

| 구성 | 저장된 버전 | Pauseable에서 사용하는 기능 |
| --- | --- | --- |
| `nlohmann/json.hpp` | 3.11.3 | C++의 JSON 파싱, 필드 검사와 사건·상태 직렬화 |
| `piper1-gpl/` | Piper 1.5.0 기반 | 보호자 음성 학습, ONNX Export와 로컬 TTS |
| `NOTICE.txt` | 외부 코드 고지 모음 | 저작권·출처 기록 |

음성 학습의 데이터 준비·Job 관리·모델 게시 코드는 [Pauseable.ai/voice](../Pauseable.ai/voice)에 있으며, 해당 파이프라인이 이 폴더의 Piper 소스를 빌드하고 실행합니다.

<a id="폴더-구조"></a>

## 폴더 구조

전체 하위 폴더와 핵심 라이브러리·빌드·라이선스 파일을 표시했습니다.

```text
Pauseable.third_party/
├── nlohmann/                              # C++ JSON 라이브러리
│   ├── json.hpp                           # nlohmann/json 3.11.3 단일 헤더
│   └── LICENSE.MIT                        # MIT 라이선스
├── piper1-gpl/                            # Piper 1.5.0 음성 합성·학습 소스
│   ├── .github/
│   │   └── workflows/
│   ├── docker/
│   ├── docs/                              # Piper CLI·API·빌드·학습 안내
│   ├── etc/
│   ├── libpiper/                          # C/C++ 음성 합성 라이브러리
│   │   ├── include/
│   │   ├── src/
│   │   │   └── main/
│   │   │       └── utils/
│   │   └── tests/
│   │       └── utils/
│   ├── script/
│   ├── src/
│   │   └── piper/                         # Python 합성·음소 변환·모델 로드
│   │       ├── img/
│   │       ├── tashkeel/                  # 아랍어 발음 보조 자료와 고지
│   │       ├── templates/
│   │       ├── train/                     # PyTorch 학습·추론·ONNX Export
│   │       │   └── vits/                  # VITS 모델·Dataset·학습 구성
│   │       │       └── monotonic_align/   # Cython 기반 텍스트·음성 정렬
│   │       └── voice.py                   # ONNX 모델 로드와 음성 합성
│   ├── tests/
│   ├── CMakeLists.txt                     # eSpeak 연동 확장 빌드
│   ├── COPYING                            # Piper 원본 라이선스
│   └── setup.py                           # 패키지 버전·의존성·CLI 등록
└── NOTICE.txt                             # 외부 코드의 저작권·출처 고지
```

<a id="nlohmann"></a>

### ① nlohmann/json

[json.hpp](nlohmann/json.hpp)는 JSON 자료형과 파싱·직렬화를 제공하는 단일 C++ 헤더입니다. Central은 `nlohmann::json`으로 MQTT 입력, 추론 결과, 최종 사건과 로컬 상태 파일을 처리합니다.

| 사용 코드 | JSON 처리 |
| --- | --- |
| [BehaviorInference.cpp](../Pauseable.edge/central/core/src/BehaviorInference.cpp) | 수신 추론의 필드·자료형·허용값 검사 |
| [ActionRouter.cpp](../Pauseable.edge/central/core/src/ActionRouter.cpp) | 출처별 활성 상태·위험도·마지막 알림 시각 저장·복원 |
| [DecisionEvent.cpp](../Pauseable.edge/central/core/src/DecisionEvent.cpp) | 보호자에게 전달할 사건 구성 |
| [DecisionOutbox.cpp](../Pauseable.edge/central/integration/src/DecisionOutbox.cpp) | 전송 대기 JSON과 재시도 정보 저장 |

[Central CMake](../Pauseable.edge/central/CMakeLists.txt)는 `Pauseable.third_party`를 include 경로에 추가해 이 헤더를 사용합니다. Piper의 C/C++ 라이브러리는 자체 `libpiper/include/json.hpp` 사본을 사용합니다.

<a id="piper-하위-폴더"></a>

### ② Piper 모듈 구성

| 경로 | 주요 구현 |
| --- | --- |
| `piper1-gpl/src/piper/voice.py` | ONNX 세션 생성, 모델 설정 로드, 음성 합성 |
| `src/piper/__main__.py` | `piper` CLI의 입력·출력 옵션과 합성 실행 |
| `src/piper/phonemize_espeak.py` | eSpeak 기반 텍스트 음소 변환 |
| `src/piper/phoneme_ids.py` | 음소를 모델 입력 ID로 변환 |
| `src/piper/audio_playback.py` | 합성 오디오 재생 |
| `src/piper/download_voices.py` | 음성 모델 다운로드 도구 |
| `src/piper/http_server.py`, `templates/` | HTTP 합성과 웹 UI |
| `src/piper/train/` | 학습 CLI, PyTorch 추론, ONNX Export |
| `src/piper/train/vits/` | VITS 네트워크, 손실 함수, Dataset·학습 설정 |
| `src/piper/train/vits/monotonic_align/` | 텍스트·음성 정렬용 Cython 연산 |
| `libpiper/` | C/C++ 합성 API와 실행 도구 |
| `script/`, `docker/` | 개발·검사·다운로드·패키징과 컨테이너 실행 도구 |
| `docs/` | CLI·Python/HTTP API·빌드·학습 문서 |

<a id="pauseable과-연결되는-위치"></a>

## Pauseable과 연결되는 위치

```text
앱 녹음 → AI 음성 전처리·Job 관리 → Piper 학습 → ONNX·설정 Export
→ API/R2 게시 → Pi 모델 검증·활성화 → Piper 합성 → 현장 음성 안내

Central의 MQTT·상태·사건 JSON ↔ nlohmann/json.hpp
```

### ① GPU 음성 학습

[Dockerfile.train](../Pauseable.ai/voice/docker/Dockerfile.train)은 이 폴더의 Piper 소스를 `/opt/piper`에 복사하고 `.[train]` 구성으로 설치합니다. 이어 `build_monotonic_align.sh`와 `setup.py build_ext --inplace`를 실행해 정렬 연산과 확장 모듈을 빌드합니다.

[train_voice_model.sh](../Pauseable.ai/voice/train_voice_model.sh)와 [음성 파이프라인](../Pauseable.ai/voice/pipeline)이 전처리된 WAV·대본을 학습에 전달하고, 생성한 checkpoint에서 ONNX와 모델 설정을 내보냅니다. 모델 게시에는 API와 R2 연결을 사용합니다.

### ② Pi 음성 합성

[voice-model](../Pauseable.edge/voice-model/voice_model_updater.py)이 게시된 ONNX·설정을 검증하고 장치 모델 경로에 적용합니다. [PiperTtsEngine.cpp](../Pauseable.edge/central/integration/src/PiperTtsEngine.cpp)는 장치의 Piper 실행 파일과 활성 모델을 이용해 안내 문장을 WAV로 합성합니다.

Pi의 런타임 구성은 `bin/piper`, `lib`, `share/espeak-ng-data`와 `models` 경로를 기준으로 준비합니다. 학습 환경은 Python·PyTorch, 장치 합성은 ONNX 모델과 해당 장치용 Piper 런타임을 사용합니다.

<a id="원본과-변경-기록"></a>

## 원본과 변경 기록

### ① 버전과 출처

| 기록 | 위치·값 |
| --- | --- |
| nlohmann 버전 | [json.hpp](nlohmann/json.hpp)의 `NLOHMANN_JSON_VERSION_*`: `3.11.3` |
| Piper 원본 태그 | [piper1-gpl-tag.txt](../Pauseable.ai/voice/provenance/piper1-gpl-tag.txt): `v1.5.0` |
| Piper 원본 커밋 | [piper1-gpl-commit.txt](../Pauseable.ai/voice/provenance/piper1-gpl-commit.txt): `e2a4b1fa1c502bbb97e729a5b34a6af565007843` |
| 프로젝트 적용 패치 | [piper1-gpl-v1.5.0-local.patch](../Pauseable.ai/voice/provenance/piper1-gpl-v1.5.0-local.patch) |
| 패키지 정의 | [setup.py](piper1-gpl/setup.py): `piper-tts`, 버전 `1.5.0` |

### ② 적용한 학습·Export 변경

저장된 패치는 학습 checkpoint를 `val_mel`과 마지막 상태 중심으로 보관하도록 콜백 구성을 조정하고, ONNX Export 호출에 `dynamo=False`를 지정합니다. 원본 태그·커밋과 패치를 함께 기록해 현재 학습 환경의 소스 구성을 재현합니다.

<a id="라이선스와-자료-구분"></a>

## 라이선스와 고지

| 구성 | 라이선스·고지 파일 |
| --- | --- |
| nlohmann/json | [LICENSE.MIT](nlohmann/LICENSE.MIT) |
| Piper | [COPYING](piper1-gpl/COPYING), [setup.py](piper1-gpl/setup.py)의 `GPL-3.0-or-later` 표기 |
| 기타 외부 코드 | [NOTICE.txt](NOTICE.txt)와 각 원본 소스의 고지 |
| AI 문서용 SVG 아이콘 | [SimpleIcons.LICENSE.txt](../Pauseable.ai/assets/SimpleIcons.LICENSE.txt) |

라이브러리의 원본 라이선스·저작권·출처 파일을 소스와 함께 보존합니다. Piper의 언어별 보조 자료는 해당 하위 폴더의 출처·라이선스 파일에서 확인할 수 있습니다.
