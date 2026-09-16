"""유튜브 다채널 업로드 — 공유 타입 계약 (FREEZE).

docs/specs/20260730-youtube-multichannel-upload.md §3-1 의 구현체.

★ 이 파일은 **계약 파일**이다. 두 에이전트가 이 시그니처에만 의존한다.
  - Claude Code: 소유자. 변경 권한은 여기에만 있다.
  - Codex: **읽기 전용.** engine/youtube_meta.py 에서 import 만 하고 수정하지 않는다.
  시그니처가 불편하면 코드를 바꾸지 말고 명세서 §3 을 갱신한 뒤 재동기화한다.

★ 의도적으로 의존성이 없다 — 표준 라이브러리 typing 만 쓴다. googleapiclient·google.auth·
  httpx 를 끌어오지 않으므로 Codex 의 순수 함수 테스트가 유튜브 키 없이 CI 에서 돈다.

용어:
  ChannelKey  하나의 유튜브 채널을 가리키는 내부 키. lang 과 다르다 —
              같은 'ko' 라도 논문 채널(paper_ko)과 금융 채널(report_ko)은 다른 채널이다.
              기존 코드의 lang→토큰 맵(config.YOUTUBE_*_REFRESH_TOKEN_SECRET_BY_LANG)이
              공장별로 갈라져 있던 것을, 채널을 1급 개념으로 올려 하나로 합친다.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

# 채널 1개 = 리프레시 토큰 1개. 계정이 아니라 채널 단위다(명세서 §2).
ChannelKey = Literal["paper_ko", "paper_en", "report_ko"]

Privacy = Literal["private", "unlisted", "public"]


class ChannelSpec(TypedDict):
    """채널 레지스트리 1행. engine/youtube_channels.py 가 소유한다."""

    key: ChannelKey
    title: str        # 사람 확인용 채널명 (예: "하루한편")
    channel_id: str   # UC... — 런타임 가드가 대조하는 기대값
    secret_env: str   # 리프레시 토큰이 담긴 환경변수 이름
    lang: str         # "ko" | "en" — 제목/설명 언어 선택에 쓴다
    tz: str           # 예약 발행 기준 타임존 (예: "Asia/Seoul")


class UploadMeta(TypedDict):
    """업로드 1건의 도메인 입력. YouTube API 스키마를 모른다.

    API body 로의 변환은 engine/youtube_meta.build_video_body 가 전담한다(Codex 소유).
    """

    channel_key: ChannelKey
    title: str
    description: str
    tags: list[str]
    category_id: str                       # 논문/리포트 = "27"(Education) 기본
    privacy: Privacy
    publish_at: NotRequired[str | None]    # RFC3339 UTC. None/미지정이면 즉시 게시
    made_for_kids: bool
    synthetic_media: bool                  # AI 생성물 고지 — 본 파이프라인은 항상 True


class UploadResult(TypedDict):
    """업로드 1건의 결과.

    ★ privacy_final 은 **요청값이 아니라 유튜브가 돌려준 실제 상태**다. 미인증 프로젝트는
      public 요청을 private 으로 되돌리므로(명세서 §2-1), 요청과 다르면 호출자가 경고를 남긴다.
    """

    video_id: str
    channel_id: str
    privacy_final: Privacy
    url: str


class ChannelMismatchError(RuntimeError):
    """토큰이 가리키는 채널이 ChannelSpec.channel_id 와 다르다 — 업로드 진행 금지."""


class MissingTokenError(RuntimeError):
    """채널의 리프레시 토큰 환경변수가 비어 있다. 메시지에 어느 변수를 채울지 담는다."""


class TokenRevokedError(RuntimeError):
    """리프레시 토큰이 만료·폐기됐다(invalid_grant). 재발급 후 시크릿 갱신이 필요하다."""
