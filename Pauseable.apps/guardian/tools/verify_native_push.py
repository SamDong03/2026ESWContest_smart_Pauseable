#!/usr/bin/env python3


from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
import re
import sys
from urllib import error, parse, request
import warnings


class VerificationError(Exception):
    pass


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_config(path: Path) -> tuple[str, str, str]:
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise VerificationError("설정 JSON 파일을 읽을 수 없습니다.") from None
    if not isinstance(config, dict):
        raise VerificationError("설정 JSON은 객체여야 합니다.")
    base_url = config.get("API_BASE_URL", "https://pauseable-api.onrender.com")
    patient_id = config.get("PATIENT_ID", "byunwoojin")
    app_token = config.get("APP_TOKEN")
    if not isinstance(base_url, str):
        raise VerificationError("API_BASE_URL은 문자열이어야 합니다.")
    try:
        url = parse.urlsplit(base_url)
        _ = url.port
    except ValueError:
        raise VerificationError("API_BASE_URL이 올바른 주소가 아닙니다.") from None
    is_local = url.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        url.scheme not in {"https", "http"}
        or (url.scheme == "http" and not is_local)
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
        or any(character.isspace() for character in base_url)
    ):
        raise VerificationError("API_BASE_URL은 HTTPS 서버의 기본 주소여야 합니다.")
    if not isinstance(patient_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", patient_id):
        raise VerificationError("PATIENT_ID가 올바르지 않습니다.")
    if (
        not isinstance(app_token, str)
        or not app_token
        or any(character.isspace() for character in app_token)
        or "REPLACE" in app_token.upper()
        or "PLACEHOLDER" in app_token.upper()
    ):
        raise VerificationError("APP_TOKEN에 Render의 실제 앱 토큰을 입력하세요.")
    return base_url.rstrip("/"), patient_id, app_token


def call_api(url: str, app_token: str, timeout: int, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    api_request = request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {app_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="GET" if payload is None else "POST",
    )
    try:
        with request.build_opener(NoRedirect()).open(api_request, timeout=timeout) as response:
            raw = response.read(16385)
    except error.HTTPError as exc:
        reasons = {
            401: "앱 인증 토큰을 확인하세요.",
            403: "앱 인증 토큰을 확인하세요.",
            404: "서버 배포 또는 시험 휴대폰 등록을 확인하세요.",
            422: "입력한 휴대폰 토큰 형식을 확인하세요.",
            503: "Render의 FCM 환경변수와 서비스 계정을 확인하세요.",
        }
        reason = reasons.get(exc.code, "서버 상태를 확인하세요.")
        raise VerificationError(f"HTTP {exc.code}: {reason}") from None
    except (error.URLError, TimeoutError, OSError, ValueError):
        raise VerificationError("서버 연결에 실패했습니다. 주소, 네트워크, Render 상태를 확인하세요.") from None
    if len(raw) > 16384:
        raise VerificationError("서버 응답이 예상보다 큽니다.")
    try:
        result = json.loads(raw)
    except ValueError:
        raise VerificationError("서버가 올바른 JSON을 반환하지 않았습니다.") from None
    if not isinstance(result, dict):
        raise VerificationError("서버 응답 형식이 올바르지 않습니다.")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="로컬 *.secrets.json 빌드 설정")
    parser.add_argument("--timeout", type=int, default=90, help="연결 제한 시간(초), 기본 90")
    parser.add_argument("--send-test", action="store_true", help="이미 등록된 휴대폰에 시험 알림 1건 전송")
    parser.add_argument("--delay-seconds", type=int, default=0, help="시험 전송 대기(0~15초), --send-test와 함께 사용")
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.timeout <= 180:
            raise VerificationError("timeout은 1~180초여야 합니다.")
        if not 0 <= args.delay_seconds <= 15:
            raise VerificationError("delay-seconds는 0~15초여야 합니다.")
        if args.delay_seconds and not args.send_test:
            raise VerificationError("delay-seconds는 --send-test와 함께 사용하세요.")
        if args.send_test and args.timeout <= args.delay_seconds:
            raise VerificationError("timeout은 시험 전송 대기 시간보다 길어야 합니다.")
        base_url, patient_id, app_token = load_config(args.config)
        endpoint = f"{base_url}/api/patients/{patient_id}/native-push"
        result = call_api(f"{endpoint}/config", app_token, args.timeout)
        configured = result.get("configured")
        if not isinstance(configured, bool):
            raise VerificationError("서버의 configured 응답 형식이 올바르지 않습니다.")
        print(f"Render FCM 설정: {'준비됨' if configured else '준비되지 않음'}")
        if not configured:
            return 1
        if args.send_test:

            if not sys.stdin.isatty() or not sys.stderr.isatty():
                raise VerificationError("시험 전송은 대화형 터미널에서 실행하세요. 앱의 시험 알림 버튼도 사용할 수 있습니다.")
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", getpass.GetPassWarning)
                    token = getpass.getpass("이미 등록된 휴대폰의 FCM 토큰(입력 숨김): ")
            except (getpass.GetPassWarning, EOFError):
                raise VerificationError("토큰을 숨겨 입력할 수 없습니다. 앱의 시험 알림 버튼을 사용하세요.") from None
            if not token or len(token) > 4096 or any(character.isspace() for character in token):
                raise VerificationError("휴대폰 토큰 형식이 올바르지 않습니다.")
            payload = {"token": token}
            if args.delay_seconds:
                payload["delay_seconds"] = args.delay_seconds
                print(f"{args.delay_seconds}초 뒤 시험 알림을 보냅니다. 휴대폰을 홈 화면이나 잠금 상태로 전환하세요.")
            result = call_api(f"{endpoint}/test", app_token, args.timeout, payload)
            attempted, accepted = result.get("attempted"), result.get("accepted")
            if (
                type(attempted) is not int
                or type(accepted) is not int
                or attempted != 1
                or accepted not in {0, 1}
            ):
                raise VerificationError("시험 전송 응답 형식이 올바르지 않습니다.")
            print(f"시험 알림: 전송 시도 {attempted}건, FCM 접수 {accepted}건")
            print("FCM 접수는 휴대폰 화면 표시를 보장하지 않습니다. 실제 휴대폰에서 확인하세요.")
            return 0 if accepted == 1 else 1
        print("읽기 확인만 수행했습니다. 실제 전송은 앱의 '시험 알림 보내기' 버튼을 사용하세요.")
        return 0
    except VerificationError as exc:
        print(f"확인 실패: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
