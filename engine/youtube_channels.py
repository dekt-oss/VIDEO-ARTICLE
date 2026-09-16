"""유튜브 채널 레지스트리 + 채널 가드 (명세서 §3-3 / A3).

docs/specs/20260730-youtube-multichannel-upload.md

무엇을 푸는가:
  업로드가 **엉뚱한 채널로 가는 사고**는 에러를 내지 않는다. 코드는 "올려라" 했고 유튜브는
  "올렸다" 하고 큐는 done 으로 찍힌다. 유튜브 스튜디오를 열기 전까지 아무도 모른다.
  리프레시 토큰은 채널에 묶여 있으므로, 토큰이 가리키는 실제 채널을 업로드 **전에** 확인한다.

★ (B) 증분 적용 판정(§9-5): 기존 업로드 경로(providers/youtube.py + publish.py +
  report_publish.py — 14일 31건 실적)를 대체하지 않는다. 이 모듈은 그 위에 얹는 가드다.

★ 스코프 제약(§9-6): channels.list 는 youtube.upload 스코프로 부를 수 없다(403
  insufficientPermissions). 기존 논문 채널 토큰은 upload 스코프 하나로 발급돼 있어 가드가
  돌지 않는다. 그래서 **스코프 부족은 경고로 넘기고**(검증된 경로를 깨지 않는다), 그 외의
  불일치는 ChannelMismatchError 로 업로드를 막는다. 새 토큰은 CLI 가 두 스코프로 발급하므로
  처음부터 가드가 켜진다.
"""

from __future__ import annotations

from typing import Any

from . import config
from .util import log
from .youtube_types import (
    ChannelKey,
    ChannelMismatchError,
    ChannelSpec,
    MissingTokenError,
    TokenRevokedError,
)

# 채널 ID 는 2026-07-29 공개 채널 페이지에서 확인(명세서 §9-2). 소유 계정 <운영자 구글 계정>.
# secret_env 는 config.Secrets 필드가 아니라 **환경변수 이름**이다 — 워크플로가 주입하는 이름과 같다.
CHANNEL_REGISTRY: dict[ChannelKey, ChannelSpec] = {
    "paper_ko": {
        "key": "paper_ko",
        "title": "하루지식하나",
        "channel_id": "UCHKqm3lkVYkS1xwGjF1M9ug",
        "secret_env": "YOUTUBE_REFRESH_TOKEN_KO",
        "lang": "ko",
        "tz": config.TIMEZONE,
    },
    "paper_en": {
        "key": "paper_en",
        "title": "a Paper a Day",
        "channel_id": "UCU9XJcPFQtGXZAENFOMS7QQ",
        "secret_env": "YOUTUBE_REFRESH_TOKEN_EN",
        "lang": "en",
        "tz": config.TIMEZONE,
    },
    # ★ 채널 통합 (2026-07-30, docs/specs/20260730-report-merge-into-paper-ko.md)
    #   리포트 공장 산출물도 하루한편 KO 채널(paper_ko)로 발행한다. 아래 3개 값이 paper_ko 와
    #   같은 것은 의도된 것이다 — **키는 출처(공장), 값은 목적지(채널)** 로 역할이 나뉜다.
    #   report_ko 키를 지우지 않는 이유: 지우면 "이 영상이 리포트 공장 산출물"이라는 정보가
    #   소실돼 성과 측정(§5)과 되돌리기(§4)가 불가능해진다.
    #
    #   되돌리려면 아래 3줄만 컨센선스 채널 값으로 되돌린다(코드 로직 변경 0):
    #     title      "하루지식하나"             → "오늘의 컨센선스"
    #     channel_id UCHKqm3lkVYkS1xwGjF1M9ug → UCdxvMA1f8U50d5OUmxoNsDw
    #     secret_env YOUTUBE_REFRESH_TOKEN_KO → YOUTUBE_REFRESH_TOKEN_REPORT_KO
    #   그리고 report-publish.yml 에 그 시크릿 주입을 복원한다. 컨센선스 채널·시크릿은
    #   삭제하지 않고 남겨 뒀다(재발급 생략용).
    "report_ko": {
        "key": "report_ko",
        "title": "하루지식하나",
        "channel_id": "UCHKqm3lkVYkS1xwGjF1M9ug",
        "secret_env": "YOUTUBE_REFRESH_TOKEN_KO",
        "lang": "ko",
        "tz": config.TIMEZONE,
    },
}

# 환경변수 이름 → config.Secrets 속성명. 기존 코드가 Secrets 를 통해 토큰을 읽으므로 그대로 잇는다.
# (YOUTUBE_REFRESH_TOKEN_REPORT_KO 는 채널 통합으로 코드 참조 0건 — 되돌릴 때 함께 복원한다.)
_SECRET_ATTR_BY_ENV: dict[str, str] = {
    "YOUTUBE_REFRESH_TOKEN_KO": "youtube_refresh_token_ko",
    "YOUTUBE_REFRESH_TOKEN_EN": "youtube_refresh_token_en",
}


def get_channel(key: ChannelKey) -> ChannelSpec:
    """채널 키 → ChannelSpec. 없는 키는 조용히 넘기지 않는다."""
    spec = CHANNEL_REGISTRY.get(key)
    if spec is None:
        known = ", ".join(sorted(CHANNEL_REGISTRY))
        raise KeyError(f"등록되지 않은 채널 키: {key!r} (등록됨: {known})")
    return spec


def refresh_token_for(key: ChannelKey) -> str:
    """채널의 리프레시 토큰. 비어 있으면 '무엇을 어떻게 채우라'는 메시지로 실패한다."""
    spec = get_channel(key)
    env = spec["secret_env"]
    token = getattr(config.SECRETS, _SECRET_ATTR_BY_ENV[env], "")
    if not token:
        raise MissingTokenError(
            f"{env} 미설정 — 채널 '{spec['title']}'({key}) 업로드 불가. "
            f"docs/runbook-youtube-token.md 절차로 발급 후 GitHub Secret 에 등록하세요."
        )
    return token


def load_credentials(key: ChannelKey, *, scopes: list[str] | None = None) -> Any:
    """채널별 OAuth 자격증명. 클라이언트 ID/시크릿은 3채널 공유, 토큰만 채널별이다(§2).

    ★ scopes 를 주지 않으면 **갱신 요청에 scope 를 싣지 않는다.** 이게 기본이어야 한다:
      RFC 6749 §6 은 갱신 시 요청 scope 가 최초 승인 범위를 넘을 수 없다고 정하고, 구글은
      넘으면 `invalid_scope` 로 **갱신 자체를 거부**한다(google-auth 는 self.scopes 를 그대로
      refresh body 의 scope 로 보낸다 — google/oauth2/_client.py:refresh_grant).
      scope 를 빼면 토큰이 **실제로 승인받은 범위** 그대로 access token 이 나오므로,
      upload 만 있는 토큰도 upload+readonly 토큰도 둘 다 갱신에 성공한다.
    ★ 그래서 여기에 "필요한 스코프"를 적어 넣지 마라. 스코프가 모자란 상황은 그 API 를 부를 때
      403 으로 드러나야 하고(assert_correct_channel 이 WARN 후 통과), 갱신 단계에서 죽으면
      업로드 자체가 못 나간다.
    """
    from google.oauth2.credentials import Credentials  # 지연 임포트(워커에만 필요)

    config.SECRETS.require("youtube_client_id", "youtube_client_secret")
    return Credentials(
        token=None,
        refresh_token=refresh_token_for(key),
        token_uri=config.YOUTUBE_TOKEN_URI,
        client_id=config.SECRETS.youtube_client_id,
        client_secret=config.SECRETS.youtube_client_secret,
        scopes=scopes,
    )


def classify_auth_error(exc: Exception, key: ChannelKey) -> Exception:
    """토큰 갱신 실패를 원인 추적 가능한 예외로 바꾼다.

    invalid_grant 는 "토큰이 폐기/만료됐다"는 뜻인데 원문 메시지만으로는 무엇을 해야 할지
    알 수 없다. 어느 채널의 어느 시크릿을 어떻게 되살리는지까지 메시지에 담는다.
    """
    text = str(exc)
    if "invalid_grant" not in text:
        return exc
    spec = get_channel(key)
    return TokenRevokedError(
        f"채널 '{spec['title']}'({key}) 토큰 만료/폐기(invalid_grant). "
        f"docs/runbook-youtube-token.md §6-2 로 재발급한 뒤 {spec['secret_env']} 를 갱신하세요."
    )


def _is_scope_error(exc: Exception) -> bool:
    """403 insufficientPermissions 인가 — 스코프 부족(§9-6)은 차단이 아니라 경고다."""
    text = str(exc)
    return "insufficientPermissions" in text or "insufficient authentication scopes" in text.lower()


def assert_correct_channel(youtube: Any, key: ChannelKey) -> None:
    """토큰이 가리키는 실제 채널이 레지스트리 기대값과 같은지 확인한다.

    - 일치: 조용히 통과.
    - 불일치: ChannelMismatchError — **업로드 진행 금지.**
    - 스코프 부족(§9-6): WARN 만 남기고 통과. 기존 upload-only 토큰을 깨지 않기 위해서다.
    - 그 외 조회 실패(네트워크 등): WARN 만 남기고 통과. 가드 때문에 업로드가 멈추면 안 된다.

    ★ quota: channels.list 는 1유닛이고 업로드 버킷과 별개다(§2-1). 가드 비용은 무시 가능.
    ★ search.list 는 절대 쓰지 않는다(별도 버킷 하루 100회, 명세서 DoD).
    """
    spec = get_channel(key)
    try:
        resp = youtube.channels().list(part="id,snippet", mine=True).execute()
    except Exception as exc:  # noqa: BLE001
        if _is_scope_error(exc):
            log.warning(
                "채널 가드 미작동(토큰 스코프 부족) — %s(%s). "
                "docs/runbook-youtube-token.md §6-2 로 재발급하면 가드가 켜집니다.",
                spec["title"], key,
            )
            return
        log.warning("채널 가드 조회 실패(업로드는 계속) — %s(%s): %s", spec["title"], key, exc)
        return

    items = resp.get("items") or []
    if not items:
        log.warning("채널 가드: channels.list 가 빈 응답 — %s(%s). 확인 없이 진행합니다.",
                    spec["title"], key)
        return

    actual_id = str(items[0].get("id") or "")
    actual_title = str((items[0].get("snippet") or {}).get("title") or "")
    if actual_id != spec["channel_id"]:
        raise ChannelMismatchError(
            f"채널 불일치 — 업로드를 중단합니다. "
            f"기대: '{spec['title']}'({spec['channel_id']}), "
            f"실제 토큰의 채널: '{actual_title}'({actual_id}). "
            f"{spec['secret_env']} 가 다른 채널로 발급된 토큰입니다 — "
            f"docs/runbook-youtube-token.md §6-2 로 재발급하세요."
        )
    log.info("채널 가드 통과: %s(%s) → %s", spec["title"], key, actual_id)
