#!/usr/bin/env python3
r"""유튜브 채널 리프레시 토큰 발급 CLI (명세서 §5-A / A2).

docs/specs/20260730-youtube-multichannel-upload.md

왜 이 도구가 있나:
  채널을 3개 운영하면 실수가 나는 지점은 딱 하나 — **동의 화면에서 엉뚱한 채널을 고르는 것**이다.
  그렇게 만든 토큰을 넣어도 에러는 안 난다. 그냥 금융 영상이 논문 채널에 올라간다.
  그래서 이 CLI 는 발급 직후 channels.list 로 **실제 채널을 찍어 보여주고**, 레지스트리
  기대값과 다르면 종료 코드 1 로 멈춘다. 실수를 잡는 1차 방어선이다.

★ 이 파일은 **단독 실행된다.** engine 패키지를 임포트하지 않는다 — 운영자 노트북에서
  저장소를 받지 않고 이 파일 하나만 내려받아 돌릴 수 있어야 하기 때문이다. 그 대가로
  채널 레지스트리가 engine/youtube_channels.py 와 이중 관리되므로,
  tests/test_youtube_channels.py 가 두 표의 불일치를 잡는다(한쪽만 고치면 테스트가 깨진다).

사용법:
    pip install google-auth-oauthlib google-api-python-client
    python get_youtube_refresh_token.py --channel-key report_ko --client-secret ./client_secret.json

    # 인자만 검증(브라우저 안 염)
    python get_youtube_refresh_token.py --channel-key report_ko --client-secret ./client_secret.json --dry-run

    # JSON 파일 없이 .env 의 YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET 로(저장소 루트에서 실행)
    python tools/get_youtube_refresh_token.py --channel-key paper_ko --from-env

    # PowerShell 에서 줄을 나눌 때는 역슬래시(\)가 아니라 백틱(`)을 쓴다. 한 줄로 쓰는 편이 안전하다.

주의:
  - 토큰은 **stdout 에만** 출력한다. 파일로 저장하지 않는다.
  - 출력된 토큰은 GitHub Secret 에 바로 넣는다. 채팅·이슈·커밋에 붙여넣지 않는다.
  - OAuth 클라이언트 유형이 "웹 애플리케이션"이면(현 저장소가 그렇다 — 명세서 §9-2)
    승인된 리디렉션 URI 에 http://localhost 를 먼저 추가해야 이 흐름이 동작한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 업로드 + 채널 조회. readonly 가 있어야 channels.list 로 채널을 대조할 수 있다(명세서 §9-6).
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

# engine/youtube_channels.CHANNEL_REGISTRY 의 사본(단독 실행용). 드리프트는 테스트가 잡는다.
CHANNELS: dict[str, dict[str, str]] = {
    "paper_ko": {
        "key": "paper_ko",
        "title": "하루지식하나",
        "channel_id": "UCHKqm3lkVYkS1xwGjF1M9ug",
        "secret_env": "YOUTUBE_REFRESH_TOKEN_KO",
    },
    "paper_en": {
        "key": "paper_en",
        "title": "a Paper a Day",
        "channel_id": "UCU9XJcPFQtGXZAENFOMS7QQ",
        "secret_env": "YOUTUBE_REFRESH_TOKEN_EN",
    },
    "report_ko": {
        "key": "report_ko",
        "title": "하루지식하나",
        "channel_id": "UCHKqm3lkVYkS1xwGjF1M9ug",
        "secret_env": "YOUTUBE_REFRESH_TOKEN_KO",
    },
}


def get_channel(key: str) -> dict[str, str]:
    spec = CHANNELS.get(key)
    if spec is None:
        raise SystemExit(f"등록되지 않은 채널 키: {key!r} (등록됨: {', '.join(sorted(CHANNELS))})")
    return spec


def load_client_config(path: str) -> dict:
    """client_secret.json 을 읽는다. 'installed'(데스크톱)·'web'(웹) 둘 다 받는다."""
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"파일을 찾을 수 없습니다: {path}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        # 스택트레이스 대신 무엇을 하라는 안내로 끝낸다(명세서 DoD).
        raise SystemExit(
            f"{path}: JSON 을 읽지 못했습니다({exc}). GCP 콘솔 → 사용자 인증 정보 → "
            "OAuth 클라이언트 → [JSON 다운로드] 로 받은 파일을 지정하세요."
        ) from exc
    if not isinstance(data, dict) or ("installed" not in data and "web" not in data):
        raise SystemExit(
            f"{path}: 'installed' 또는 'web' 키가 없습니다 — "
            "GCP 콘솔의 OAuth 클라이언트에서 받은 JSON 이 맞는지 확인하세요."
        )
    if "web" in data and "installed" not in data:
        print(
            "ℹ️  웹 애플리케이션 유형 클라이언트입니다. GCP 콘솔의 '승인된 리디렉션 URI' 에\n"
            "   http://localhost 가 등록돼 있어야 아래 흐름이 동작합니다.\n",
            file=sys.stderr,
        )
    return data


def load_client_config_from_env(env_path: str = ".env") -> dict:
    """`.env`(또는 환경변수)의 YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET 로 클라이언트 설정을 만든다.

    ★ 왜(2026-09-14 실측): 운영자가 JSON 파일이 없어 "파일을 찾을 수 없습니다"에서 멈췄다.
      같은 값이 이미 .env 에 있다 — 파일을 내려받게 할 이유가 없다.
    ★ 단독 실행 원칙은 지킨다(engine·python-dotenv 미사용). 이미 있는 환경변수를 우선한다.
    ★ 값은 출력하지 않는다.
    """
    import os

    vals: dict[str, str] = {}
    p = Path(env_path)
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip().strip('"').strip("'")
    cid = os.environ.get("YOUTUBE_CLIENT_ID") or vals.get("YOUTUBE_CLIENT_ID", "")
    sec = os.environ.get("YOUTUBE_CLIENT_SECRET") or vals.get("YOUTUBE_CLIENT_SECRET", "")
    if not cid or not sec:
        raise SystemExit(
            f"YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET 을 찾지 못했습니다({env_path} · 환경변수). "
            "저장소 루트에서 실행하거나 --client-secret 으로 JSON 파일을 지정하세요.")
    return {"installed": {
        "client_id": cid, "client_secret": sec,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }}


def main() -> int:
    ap = argparse.ArgumentParser(description="유튜브 채널별 리프레시 토큰 발급")
    ap.add_argument("--channel-key", required=True, choices=sorted(CHANNELS),
                    help="발급할 채널 키")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--client-secret",
                     help="GCP 콘솔에서 내려받은 client_secret.json 경로")
    src.add_argument("--from-env", action="store_true",
                     help=".env 의 YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET 을 쓴다(파일 불필요)")
    ap.add_argument("--port", type=int, default=0,
                    help="로컬 콜백 포트(기본 0=임의). 웹 유형 클라이언트면 콘솔에 등록한 포트로 맞춘다")
    ap.add_argument("--dry-run", action="store_true",
                    help="브라우저를 열지 않고 인자·설정만 검증")
    args = ap.parse_args()

    spec = get_channel(args.channel_key)
    client_config = (load_client_config_from_env() if args.from_env
                     else load_client_config(args.client_secret))

    print("─" * 60)
    print(f"발급 대상 채널 : {spec['title']}  ({spec['key']})")
    print(f"기대 채널 ID   : {spec['channel_id']}")
    print(f"등록할 시크릿  : {spec['secret_env']}")
    print("─" * 60)

    if args.dry_run:
        print("\n[dry-run] 인자·클라이언트 JSON 검증까지만 수행했습니다. 브라우저는 열지 않았습니다.")
        return 0

    from google_auth_oauthlib.flow import InstalledAppFlow

    print(
        "\n⚠️  브라우저가 열리면 반드시 아래를 지키세요.\n"
        "   1) 이미 다른 채널로 로그인돼 있으면 채널 선택 화면이 안 뜰 수 있습니다.\n"
        "      → 출력되는 URL 을 복사해 **시크릿(프라이빗) 창**에 붙여넣으세요.\n"
        f"   2) 채널 선택 화면에서 반드시 '{spec['title']}' 을(를) 고르세요.\n"
    )

    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    creds = flow.run_local_server(port=args.port, access_type="offline", prompt="consent")

    if not creds.refresh_token:
        print(
            "\n❌ 리프레시 토큰이 발급되지 않았습니다.\n"
            "   https://myaccount.google.com/permissions 에서 이 앱 접근을 삭제(revoke)한 뒤 재실행하세요.",
            file=sys.stderr,
        )
        return 1

    # ★ 발급 직후 실제 채널 확인 — 여기가 채널 오선택을 잡는 지점이다.
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    resp = youtube.channels().list(part="id,snippet", mine=True).execute()
    items = resp.get("items") or []
    if not items:
        print("\n❌ channels.list 응답이 비었습니다 — 채널을 확인할 수 없어 중단합니다.", file=sys.stderr)
        return 1

    actual_id = str(items[0].get("id") or "")
    actual_title = str((items[0].get("snippet") or {}).get("title") or "")

    print("\n" + "=" * 60)
    print(f"  동의한 채널 : {actual_title}")
    print(f"  채널 ID     : {actual_id}")
    print("=" * 60)

    if actual_id != spec["channel_id"]:
        print(
            f"\n❌ 채널이 다릅니다. 기대: '{spec['title']}'({spec['channel_id']}).\n"
            "   이 토큰을 등록하면 영상이 엉뚱한 채널로 올라갑니다. 등록하지 마세요.\n"
            "   시크릿 창에서 다시 실행해 올바른 채널을 선택하세요.",
            file=sys.stderr,
        )
        return 1

    print("\n✅ 채널 일치. 아래 값을 GitHub Secret 에 등록하세요(파일로 저장하지 않았습니다).")
    print(f"\n   이름 : {spec['secret_env']}")
    print(f"   값   : {creds.refresh_token}\n")
    print("   GitHub → Settings → Secrets and variables → Actions → New repository secret")
    return 0


if __name__ == "__main__":
    sys.exit(main())
