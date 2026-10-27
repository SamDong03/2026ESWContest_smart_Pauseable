# Memolink API 서버

[앱/API 전체 안내](../README.md) · [보호자 앱](../guardian/README.md) · [통신 규격](../../Pauseable.contracts/README.md) · [개발환경](../../Pauseable.docs/DEVELOPMENT_ENVIRONMENT_KO.md)

Central·카메라·GPU Worker·보호자 앱의 요청을 연결하는 FastAPI 서버입니다. 사건 이력, 사진, 보호자 설정과 음성 학습 작업을 처리합니다.

## 요청과 책임

| 요청 주체 | 인증 | 주요 요청 |
| --- | --- | --- |
| 보호자 앱 | App Token | 이력·사진 조회, 프로필·지역·음악·알림 설정, 녹음·학습 동의 |
| Pi 장치 | Device Token | 결정 Event·사진 전송, 지역·음악·모델 조회 |
| GPU Worker | Worker Token | 학습 작업 임대·갱신·결과 게시 |

## 코드와 실행

| 위치 | 내용 |
| --- | --- |
| [app/main.py](app/main.py) | API 진입점과 경로 |
| [app/security.py](app/security.py) | 인증 역할·환경 구분 |
| [app](app) | 저장·설정·알림·학습·모델 서비스 |
| [tests](tests) | 요청·인증·중복·저장·Push·모델 처리 회귀 검사 |
| [requirements.txt](requirements.txt) | API 의존성 |

실행 명령과 Windows/Linux 설정은 [로컬 API 실행](../README.md#api-로컬-실행)에 있습니다. 개발 서버는 `127.0.0.1:8000`, API 문서는 `/docs`, 상태 확인은 `/health`를 사용합니다. 로컬 예시는 실행 PC 저장소를 사용하며, 운영 환경에서는 R2 등 영속 저장 설정과 역할별 인증을 준비합니다.

같은 `event_id`의 재전송과 다른 내용의 ID 충돌을 구분합니다. API 접수, 사건 저장, Push 요청과 실제 앱 표시는 서로 다른 확인 단계입니다. [실기 알림 확인](../guardian/docs/REAL_DEVICE_ALERT_VERIFICATION.md)에서 동일 사건을 대조합니다.

공개 서버용 비밀 키·Device/Worker Token을 앱에 포함하지 않습니다. 현재 팀 시험용 공유 Token과 사용자별 인증·접근권한은 구분합니다.
