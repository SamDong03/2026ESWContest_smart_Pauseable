# Pauseable.third_party

**Pauseable이 사용하는 외부 소스와 원본 라이선스·저작권 고지를 보관합니다.**

[프로젝트](../README.md) · [AI 음성 학습](../Pauseable.ai/README.md#voice-학습과-운영-상세) · [Central](../Pauseable.edge/README.md)

## 포함한 외부 소스

| 구성 | 프로젝트에서 쓰는 곳 | 기록된 버전·조건 |
| --- | --- | --- |
| `nlohmann/json.hpp` | C++ Central의 JSON 처리 | 동봉한 [MIT 라이선스](nlohmann/LICENSE.MIT) |
| `piper1-gpl` | 보호자 음성 학습·Export·TTS | Piper v1.5.0, 패키지 표기 `GPL-3.0-or-later` |
| `NOTICE.txt` | 원본 헤더에서 보존한 고지 | 포함된 저작권·외부 코드 출처 |

프로젝트의 학습·Job 연동 코드는 [Pauseable.ai/voice](../Pauseable.ai/voice)에 있고, 이 폴더는 그 기반 외부 라이브러리입니다. 장치에 설치할 Piper 실행 파일이나 개인화 ONNX 모델을 함께 보관하는 폴더는 아닙니다.

## 폴더 구조

```text
Pauseable.third_party/
├── nlohmann/ — C++ JSON 단일 헤더와 MIT 라이선스
└── piper1-gpl/ — Piper 1.5.0 원본 기반 TTS·학습 소스
    ├── .github/ — 관련 구성: build-libpiper.yml, publish.yml
    │   └── workflows/ — 원본 자동 검사·배포 작업
    ├── docker/ — 컨테이너 실행·빌드 구성
    ├── docs/ — Piper CLI·API·빌드·학습 원본 문서
    ├── etc/ — Piper 원본 로고 리소스
    ├── libpiper/ — Piper C/C++ 합성 라이브러리
    │   ├── include/ — 공개 헤더와 연결 인터페이스
    │   ├── src/ — 구현 소스
    │   │   └── main/ — 기본 빌드 구현
    │   │       └── utils/ — CLI·테스트 공통 도구
    │   └── tests/ — 단위·회귀 검사
    │       └── utils/ — CLI·테스트 공통 도구
    ├── script/ — 원본 개발·학습·Export·패키징 도구
    ├── src/ — 구현 소스
    │   └── piper/ — Python TTS·음소화·다운로드·학습
    │       ├── img/ — 원본 패키지 이미지
    │       ├── tashkeel/ — 아랍어 발음 보조 자료와 원본 고지
    │       ├── templates/ — Piper HTTP UI 템플릿
    │       └── train/ — 학습·추론·ONNX Export
    │           └── vits/ — VITS 모델·Dataset·학습 구성
    │               └── monotonic_align/ — Cython 정렬 연산
    └── tests/ — 단위·회귀 검사
```

### nlohmann

`nlohmann/`에는 C++ 단일 JSON 헤더와 라이선스가 있습니다. Central의 CMake include 경로가 이 사본을 참조합니다. Piper 내부의 `libpiper/include/json.hpp`는 upstream 구성에 포함된 별도 사본이므로 위치가 다릅니다.

### Piper 하위 폴더

| 경로 | 내용 |
| --- | --- |
| `piper1-gpl/src/piper` | Python 음성 합성·음소화·다운로드·실행 코드 |
| `src/piper/train` | 학습 실행·PyTorch 추론·ONNX Export |
| `src/piper/train/vits` | VITS 모델·학습 구성·Dataset |
| `src/piper/train/vits/monotonic_align` | Cython 정렬 연산 |
| `src/piper/tashkeel` | 아랍어 발음 보조 코드·자료·고지 |
| `src/piper/templates`, `img` | HTTP 템플릿과 원본 패키지 리소스 |
| `libpiper/include`, `libpiper/src` | C/C++ 라이브러리·CLI·공통 유틸리티 |
| `libpiper/tests`, `tests` | C++·Python 원본 검사 |
| `script` | 개발·검사·Export·음성 다운로드·패키징 도구 |
| `docker` | 원본 컨테이너 진입 설정 |
| `docs` | CLI·Python/HTTP API·빌드·학습 안내 |
| `.github/workflows` | 원본 프로젝트의 CI 구성 |
| `etc` | 원본 로고와 리소스 |

## Pauseable과 연결되는 위치

```text
앱 녹음 → Pauseable.ai/voice 전처리·Job 관리
→ piper1-gpl 학습·ONNX Export → API/R2 게시
→ Pauseable.edge/voice-model 검증 → 장치 Piper로 TTS

Central JSON 입력·출력 → nlohmann/json.hpp
```

GPU 학습 환경은 [Dockerfile.train](../Pauseable.ai/voice/docker/Dockerfile.train), 작업 실행은 [train_voice_model.sh](../Pauseable.ai/voice/train_voice_model.sh)를 기준으로 준비합니다. 장치 실행은 SDK·운영체제·CPU에 맞는 Piper 바이너리와 모델 파일이 별도로 필요합니다.

## 원본과 변경 기록

| 기록 | 위치 |
| --- | --- |
| 원본 태그 | [piper1-gpl-tag.txt](../Pauseable.ai/voice/provenance/piper1-gpl-tag.txt): `v1.5.0` |
| 원본 커밋 | [piper1-gpl-commit.txt](../Pauseable.ai/voice/provenance/piper1-gpl-commit.txt): `e2a4b1fa1c502bbb97e729a5b34a6af565007843` |
| 프로젝트 수정 | [piper1-gpl-v1.5.0-local.patch](../Pauseable.ai/voice/provenance/piper1-gpl-v1.5.0-local.patch) |
| Piper 라이선스 | [COPYING](piper1-gpl/COPYING), [setup.py](piper1-gpl/setup.py) |
| 헤더별 고지 | [NOTICE.txt](NOTICE.txt) |

원본 태그·패키지 버전과 프로젝트 수정 기록을 함께 확인합니다. 라이브러리 소스를 바꿀 때는 사용 중인 학습·합성 경로와 기존 모델의 호환성도 검사합니다.

## 라이선스와 자료 구분

원본 라이선스·저작권 고지는 함께 보존합니다. 외부 코드·학습 자료·음성 모델은 각각의 이용 조건을 확인합니다. 소스를 공개했다고 모든 외부 데이터나 개인 모델에 동일한 이용 조건이 적용되는 것은 아닙니다.

AI README의 기존 SVG에 사용한 문서용 아이콘 고지는 [SimpleIcons.LICENSE.txt](../Pauseable.ai/assets/SimpleIcons.LICENSE.txt)에 있습니다. 개인 녹음·학습 checkpoint·ONNX와 실제 인증값은 이 외부 소스 폴더에 넣지 않습니다.
