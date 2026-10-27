# README Visual Assets

각 영역의 README에 쓰는 구조도와 평가 그래프입니다. **현재 코드의 처리 구조**와 **저장된 평가 자료**를 설명하며, 실시간 서비스 상태나 이번 작업에서 새로 측정한 성능을 표시하지 않습니다.

## 구조도

| 영역 | 그림 | 설명 |
| --- | --- | --- |
| AI | [`ai-pipelines.svg`](ai-pipelines.svg) | HA·mmWave·Voice의 입력과 출력, 실행 책임 |
| AI | [`learning-lifecycle.svg`](learning-lifecycle.svg) | 유효 이력·학습·검증·활성화·fallback |
| Apps | [`apps-connections.svg`](apps-connections.svg) | Pi·API·앱·Worker·저장소 연결 |
| Apps | [`notification-sequence.svg`](notification-sequence.svg) | 사건 접수·이력·WebSocket·Push·읽음 |
| Contracts | [`contract-map.svg`](contract-map.svg) | 추론·최종 결정·앱 알림의 차이 |
| Contracts | [`validation-gates.svg`](validation-gates.svg) | 문법·계약·출처·시각·중복·실행 정책 |
| Deploy | [`device-bundles.svg`](device-bundles.svg) | 장치별 소스 묶음과 설치 전 준비 |
| Deploy | [`deployment-stages.svg`](deployment-stages.svg) | 백업·검증·빌드·설정·설치·E2E |
| Docs | [`evidence-map.svg`](evidence-map.svg) | 코드·자동 검사·저장된 평가·실기의 근거 범위 |
| Edge | [`central-routing.svg`](central-routing.svg) | 입력 검증·Action Router·로컬 출력·Outbox |
| Edge | [`model-release.svg`](model-release.svg) | 음성 모델 검증과 교체 |
| Edge | [`favorite-music.svg`](favorite-music.svg) | 승인 이후 현재 선호 음악 조회·재생 요청 |
| Integrations | [`weather-light.svg`](weather-light.svg) | 앱 지역·날씨·태양 고도·HA 조명 |
| CI | [`ci-map.svg`](ci-map.svg) | Workflow별 검사 범위와 실행 조건 |
| CI | [`apk-build.svg`](apk-build.svg) | 수동 Android 시험 빌드와 휴대폰 확인 |

SVG는 이 저장소의 설명을 위해 새로 작성했습니다. 외부 폰트·스크립트·이미지를 불러오지 않으며 GitHub Markdown의 일반 이미지로 표시됩니다. 세부 조건과 기본값은 연결된 README 및 실행 코드를 기준으로 확인합니다.

## 평가 그래프

| 그림 | 원본·범위 | 주의 |
| --- | --- | --- |
| [`ha-event-features.png`](ha-event-features.png) | [`visual_data.json`](../../evaluation/ha/visual_data.json), 48시간·8개 가전·54개 특징·52개 상태 변경 | 두 Heatmap은 단위가 다름. 아래 색만 −2~4로 제한 |
| [`ha-model-scores.png`](ha-model-scores.png) | 같은 원본의 정상 후보 Holdout 144개, IF/AE 점수와 각 임계값 | 학습 Loss나 환자 탐지 성능이 아님 |
| [`ha-component-comparison.png`](ha-component-comparison.png) | [`baseline_comparison.json`](../../evaluation/ha/baseline_comparison.json), 반복 가설 24개·정상 맥락 48개 | 경보 건수와 분모를 그대로 표시. 임상 정확도가 아님 |

세 그래프의 원본은 **합성 검증 fixture**입니다. 정상 맥락의 경보 증가도 숨기지 않고 표시합니다. 원본 SHA-256·사용 수치·해석 범위는 [`evaluation_figure_manifest.json`](evaluation_figure_manifest.json)에 있습니다. 원본을 수정하거나 모델을 재학습하지 않았고, 저장된 scaler 결과를 다시 fit하지 않았습니다.

AI README에 함께 표시한 [`inspect_paths.png`](../../../Pauseable.ai/mmwave/src/shape_v2/artifacts/inspect_paths.png)는 기존 연구 산출물을 그대로 연결했습니다. arbitrary units의 합성 경로이며 이번에 생성한 그림에 포함하지 않습니다.

## 재생성

저장소 루트에서 실행합니다. Python은 앱 런타임과 분리된 문서용 가상환경을 권장합니다. 이번 생성 환경은 Matplotlib 3.10.8·NumPy 2.3.5입니다.

```sh
node Pauseable.docs/assets/readme/build_diagrams.mjs
python -m pip install matplotlib==3.10.8 numpy==2.3.5
python Pauseable.docs/assets/readme/plot_evaluation.py
```

- [`build_diagrams.mjs`](build_diagrams.mjs): Node.js 표준 모듈로 SVG 15개와 [`diagram_manifest.json`](diagram_manifest.json) 생성.
- [`plot_evaluation.py`](plot_evaluation.py): 저장된 JSON을 읽어 PNG 3개와 출처 Manifest 생성. 임시 Matplotlib cache는 종료 시 정리.
- 별도 모델·서비스 실행, 네트워크 호출, 개인정보·인증값 접근은 하지 않음.
- 학습 iteration별 Loss 시계열은 선택한 원본에 없어 새 곡선을 만들지 않음.

[Docs 인덱스로 돌아가기](../../README.md) · [AI README](../../../Pauseable.ai/README.md)
