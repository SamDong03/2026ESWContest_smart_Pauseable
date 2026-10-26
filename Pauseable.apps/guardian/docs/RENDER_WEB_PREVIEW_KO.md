# 실제 Render에 연결하는 노트북 웹 미리보기

이 실행 방식은 팀원의 노트북에서만 사용하는 중계 방식입니다.
공개 웹앱의 로그인·권한 관리 시스템을 대신하지 않습니다.

## 연결 구조

`브라우저(127.0.0.1:18108) → 같은 출처의 로컬 중계 → https://pauseable-api.onrender.com`

- 이름·지역·노래 링크 저장, 녹음 업로드, 알림 조회는 실제 Render에 전달됩니다.
- 거주 지역은 자동 조명용 기상청 격자를 저장하는 입력 기능입니다. 앱에 날씨를 표시하지 않습니다. 조명 장비를 `WEATHER_LOCATION_SOURCE=render`로 설정하면 Device 인증 지역 조회 API를 통해 이 저장값을 사용합니다. 장비에는 App Token이 아닌 Device Token을 설정하며, [장비 적용 안내](../../../Pauseable.docs/integrations/home-assistant/RENDER_REGION_SETUP_KO.md)를 따릅니다. 로컬 웹 중계는 장비 API를 대신 제공하거나 Device Token을 브라우저에 전달하지 않습니다.
- WebSocket의 기존 일회용 접속권과 실시간 메시지도 중계합니다.
- 실제 앱 토큰은 Python 서버만 읽습니다. Flutter 빌드에는 실행마다 생성되는 별개의 로컬 접속값만 넣습니다.
- 중계는 고정 Render 주소와 설정된 대상자만 사용합니다. 다른 대상자, Pi/Worker 이벤트 전송, 가상 감지 이벤트 생성 경로는 차단합니다.
- 사진 URL은 기존 Render 응답 그대로 사용합니다. 기기 설정, 실제 감지, 사진 전송 코드와 알림 ID는 바꾸지 않습니다.
- `127.0.0.1` 바인딩, Host/Origin/접속 주소 검사, 로컬 접속값 확인을 적용합니다. 외부 IP·공개 터널·공유 서버에 노출하지 마세요.

## 최초 실행

`Pauseable.apps/guardian`에서 Python 가상환경에 `../api/requirements.txt`를 설치합니다.
로컬 전용 `render-web.secrets.json` 파일을 아래 형식으로 만들되, 실제 토큰은 에디터에서만 입력합니다.
이 파일은 Git에서 제외되며 `build/web`이나 `assets` 아래 두지 않습니다.

```json
{
  "API_BASE_URL": "https://pauseable-api.onrender.com",
  "PATIENT_ID": "byunwoojin",
  "APP_TOKEN": "여기에 기존 Render PAUSEABLE_APP_TOKEN을 로컬에서 입력"
}
```

```powershell
flutter pub get
python -m tools.serve_render_web --build
```

Flutter가 PATH에 없다면 `--flutter "Flutter SDK의 bin/flutter.bat 경로"`를 지정합니다.
브라우저에서 `http://127.0.0.1:18108/`을 엽니다. 서버를 종료한 뒤 같은 빌드로 다시 실행할 때는
`python -m tools.serve_render_web`을 사용합니다. 포트·대상자가 달라지면 다시 빌드해야 합니다.
`build/local-render-session.json`은 웹 제공 폴더 밖의 로컬 접속 설정이며 Git에 포함하지 않습니다.

`/local-render-status`는 중계 모드와 고정 목적지만 표시하며, 인증값이나 개인정보를 반환하지 않습니다.
Render가 잠들어 있으면 최초 접속에 시간이 걸릴 수 있습니다. 인증 실패는 가상 데이터로 대체하지 않습니다.

## 지역 영구 저장 배포 및 확인

Render의 기존 `STORAGE_BACKEND=r2`와 R2 환경변수를 유지합니다. 앱에 R2 키를 넣지 않습니다.
새 서버는 `patients/{patient_id}/home-environment.json`에서 지역 설정을 읽고 씁니다.
지역 API 응답에 `storage_backend: "r2"`, `is_persistent: true`가 있어야 영구 저장 모드입니다.
이 변경이 날씨 조회나 실내 조명 제어까지 구현하는 것은 아닙니다.

배포 전에 기존 선택만 비공개 `build/` 폴더로 보존하고, 배포 뒤 서버 선택이 비어 있을 때만 복구할 수 있습니다.
기존 대상자의 실제 선택을 그대로 복구하며 테스트 지역으로 덮어쓰지 않습니다.

```powershell
python -m tools.verify_render_region --remember

python -m tools.verify_render_region --restore-if-empty
```

이 확인은 인증 성공 여부·선택 존재 여부·저장 방식만 출력합니다. 토큰·지역명은 출력하지 않습니다.
과거 지역 파일이 이미 사라졌고 백업도 없다면 앱에서 지역을 한 번 다시 선택합니다.

## 알림 관련 주의

중계 서버가 실행 중이면 열린 웹앱은 Render의 실제 WebSocket 알림을 받습니다.
닫힌 탭의 Web Push는 브라우저에서 직접 알림 권한을 허용하고 실제 Render에 구독 등록을 해야 합니다.
로컬 데모 서버에 등록한 예전 구독이 Render로 자동 이전되는 것은 아닙니다.
휴대폰에 설치된 기존 Android 앱의 FCM 등록·알림·사진 경로에는 변경이 없습니다.
