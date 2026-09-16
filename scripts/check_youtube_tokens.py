#!/usr/bin/env python3
"""유튜브 자격증명 점검 — 영상을 올리지 않고 토큰만 확인한다.

왜 필요한가:
  GitHub Secret 은 저장하면 다시 볼 수 없다. 그래서 "토큰을 제대로 넣었나"를 확인하려면
  실제로 인증을 시켜보는 수밖에 없는데, 그렇다고 확인하자고 채널에 영상을 올릴 수는 없다.
  이 스크립트는 **토큰 갱신(refresh)까지만** 해본다. 업로드도, 채널 변경도 하지 않는다.

무엇을 잡아내나:
  - `invalid_client` → 클라이언트 ID/비밀번호가 틀렸다(비밀번호 회전 후 깃허브 미갱신).
                        이건 3채널이 **동시에** 죽는 사고라 가장 먼저 봐야 한다.
  - `invalid_grant`  → 그 채널의 리프레시 토큰이 만료·폐기됐다.
  - 채널 불일치      → 토큰이 다른 채널로 발급됐다(업로드하면 엉뚱한 채널로 간다).
  - 미설정           → 시크릿이 아예 없다.

의존성 없음(표준 라이브러리만) — 워크플로에서 pip install 없이 즉시 돈다.
토큰 값은 출력하지 않는다.

실행:  python -m scripts.check_youtube_tokens   /  python scripts/check_youtube_tokens.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

def _load_env_file(path: str = ".env") -> None:
    """로컬 실행용 — `.env` 의 값을 환경변수로 올린다(이미 있는 값은 덮지 않는다).

    ★ 왜 필요한가(2026-09-13 실측): 이 스크립트는 GitHub Actions 에서 시크릿이 환경변수로
      주입되는 것을 전제로 os.getenv 만 봤다. 운영자가 로컬 `.env` 에 키를 제대로 넣었는데도
      "설정되지 않았습니다"가 떠서, 값이 없는 것과 **스크립트가 못 읽는 것**이 구분되지 않았다.
    ★ 의존성 없음 원칙은 지킨다 — python-dotenv 를 쓰지 않고 직접 읽는다(따옴표만 벗긴다).
    """
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and val and not os.environ.get(key):
            os.environ[key] = val


TOKEN_URI = "https://oauth2.googleapis.com/token"
CHANNELS_URI = "https://www.googleapis.com/youtube/v3/channels?part=id,snippet&mine=true"

# engine/youtube_channels.CHANNEL_REGISTRY 와 같은 표(스크립트 단독 실행을 위해 인라인).
# 드리프트는 tests/test_youtube_channels.py 가 잡는다.
CHANNELS: list[dict[str, str]] = [
    {"key": "paper_ko", "title": "하루지식하나",
     "channel_id": "UCHKqm3lkVYkS1xwGjF1M9ug", "secret_env": "YOUTUBE_REFRESH_TOKEN_KO"},
    {"key": "paper_en", "title": "a Paper a Day",
     "channel_id": "UCU9XJcPFQtGXZAENFOMS7QQ", "secret_env": "YOUTUBE_REFRESH_TOKEN_EN"},
    {"key": "report_ko", "title": "하루지식하나",
     "channel_id": "UCHKqm3lkVYkS1xwGjF1M9ug", "secret_env": "YOUTUBE_REFRESH_TOKEN_KO"},
]


def _post_form(url: str, data: dict[str, str]) -> tuple[int, dict]:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"error": raw[:200]}


def _get(url: str, access_token: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"error": raw[:200]}


def check_channel(spec: dict[str, str], client_id: str, client_secret: str) -> tuple[bool, str]:
    """반환: (정상 여부, 사람이 읽는 한 줄)."""
    token = os.getenv(spec["secret_env"], "").strip()
    if not token:
        return False, f"미설정 — {spec['secret_env']} 시크릿이 비어 있습니다"

    status, data = _post_form(TOKEN_URI, {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": token,
        "grant_type": "refresh_token",
    })
    if status != 200:
        err = str(data.get("error", ""))
        if err == "invalid_client":
            return False, ("클라이언트 인증 실패(invalid_client) — YOUTUBE_CLIENT_ID/SECRET 이 "
                           "콘솔 값과 다릅니다. 비밀번호를 회전했다면 깃허브 시크릿을 갱신하세요")
        if err == "invalid_grant":
            return False, ("리프레시 토큰 만료·폐기(invalid_grant) — "
                           f"{spec['secret_env']} 를 재발급해 갱신하세요")
        return False, f"토큰 갱신 실패({status}): {err or data}"

    access_token = str(data.get("access_token") or "")
    if not access_token:
        return False, "토큰 갱신 응답에 access_token 이 없습니다"

    # ★★ 업로드 권한을 **직접 확인한다**(2026-09-14 실측). 종전에는 "갱신이 되고 채널이 맞다"만
    #   보고 ✅ 를 줬다. 그런데 운영자가 넣은 KO·EN 토큰이 둘 다 조회 전용(youtube.readonly·
    #   yt-analytics.readonly)이었고, 이 스크립트는 "3채널 모두 정상"이라 했는데 실제 업로드는
    #   403 insufficient scopes 로 거부됐다. 갱신 성공 ≠ 업로드 가능이다.
    granted = str((data.get("scope") or "")).split()
    if not granted:
        _s, info = _get("https://oauth2.googleapis.com/tokeninfo?access_token="
                        + urllib.parse.quote(access_token), access_token)
        granted = str(info.get("scope") or "").split()
    can_upload = any(s.endswith("/youtube.upload") or s.endswith("/youtube")
                     or s.endswith("/youtube.force-ssl") for s in granted)
    if not can_upload:
        short = ", ".join(s.rsplit("/", 1)[-1] for s in granted) or "(없음)"
        return False, (f"업로드 권한 없음 ✗ — 이 토큰의 권한은 [{short}] 뿐입니다. "
                       f"조회 전용 토큰(분석용)을 넣은 것일 수 있습니다. youtube.upload 를 포함해 "
                       f"{spec['secret_env']} 를 재발급하세요(runbook §3)")

    # 채널 확인은 조회 스코프가 있을 때만 가능하다(업로드 전용 토큰이면 403).
    status, data = _get(CHANNELS_URI, access_token)
    if status == 403:
        return True, "토큰 유효 ✓ (채널 확인 불가 — 업로드 전용 스코프)"
    if status != 200:
        return True, f"토큰 유효 ✓ (채널 조회 실패 {status} — 업로드에는 영향 없음)"

    items = data.get("items") or []
    if not items:
        return True, "토큰 유효 ✓ (채널 조회 결과 없음)"

    actual_id = str(items[0].get("id") or "")
    actual_title = str((items[0].get("snippet") or {}).get("title") or "")
    if actual_id != spec["channel_id"]:
        return False, (f"채널 불일치 ✗ — 이 토큰은 '{actual_title}'({actual_id}) 채널입니다. "
                       f"기대: '{spec['title']}'({spec['channel_id']}). 재발급하세요")
    return True, f"토큰 유효 ✓ · 채널 확인 ✓ ({actual_title})"


def main() -> int:
    _load_env_file()          # 로컬 .env → 환경변수(Actions 에서는 이미 주입돼 있어 무해하다)
    client_id = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print("❌ YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET 이 설정되지 않았습니다.")
        return 1

    # ★ 앞자리도 찍지 않는다(2026-09-15) — 클라이언트 ID 앞 14자는 GCP 프로젝트 번호이고,
    #   부분 문자열은 Actions 시크릿 마스킹을 받지 못해 공개 로그에 그대로 남는다.
    print("클라이언트 ID: 설정됨\n")
    failures = 0
    for spec in CHANNELS:
        ok, message = check_channel(spec, client_id, client_secret)
        mark = "✅" if ok else "❌"
        print(f"{mark} {spec['title']:<14} ({spec['key']:<9}) {message}")
        if not ok:
            failures += 1

    print()
    if failures:
        print(f"실패 {failures}건 — 위 메시지의 조치를 따르세요.")
        return 1
    print("3채널 모두 정상입니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
