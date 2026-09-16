"""YouTube Data API v3 업로드 클라이언트 (engine.publish 워커 전용).

채널 업로드는 서비스계정으로 불가(채널을 소유할 수 없음) → OAuth2 리프레시 토큰 흐름을 쓴다.
클라이언트 ID/시크릿은 채널 공통(같은 GCP 프로젝트), 리프레시 토큰은 채널(언어)마다 다르다.
config.YOUTUBE_REFRESH_TOKEN_SECRET_BY_LANG 로 lang → 리프레시 토큰(=채널)을 고른다.

google-api-python-client·google-auth 는 무겁고 이 워커에만 필요하므로 지연 임포트한다
(db.client() 의 supabase 지연 임포트와 같은 규칙 — 순수 로직 임포트를 깨지 않게).
requirements.txt 에는 두지 않고 .github/workflows/publish.yml 에서만 설치한다(manim 선례).
"""

from __future__ import annotations

from typing import Any

from .. import config
from ..util import log


def _refresh_token_for_lang(lang: str, secret_by_lang: dict[str, str] | None = None) -> str:
    """lang → 채널 리프레시 토큰. 없으면 명확한 에러(어느 채널이 미설정인지).

    secret_by_lang 로 채널 맵을 바꿀 수 있다(기본=논문 채널, 리포트는 별도 금융 채널 맵을 넘김).
    """
    token_map = secret_by_lang or config.YOUTUBE_REFRESH_TOKEN_SECRET_BY_LANG
    attr = token_map.get(lang)
    if not attr:
        raise RuntimeError(f"지원하지 않는 업로드 언어: {lang!r}")
    token = getattr(config.SECRETS, attr, "")
    if not token:
        raise RuntimeError(
            f"유튜브 리프레시 토큰 누락({lang} 채널): 환경변수 "
            f"{attr.upper()} 를 채우세요(docs/deviation-youtube-upload.md 의 OAuth 설정)."
        )
    return token


def _credentials_for_lang(lang: str, secret_by_lang: dict[str, str] | None = None) -> Any:
    """언어별 채널 OAuth 자격증명. access token 은 리프레시 토큰으로 자동 갱신된다."""
    from google.oauth2.credentials import Credentials

    config.SECRETS.require("youtube_client_id", "youtube_client_secret")
    return Credentials(
        token=None,
        refresh_token=_refresh_token_for_lang(lang, secret_by_lang),
        token_uri=config.YOUTUBE_TOKEN_URI,
        client_id=config.SECRETS.youtube_client_id,
        client_secret=config.SECRETS.youtube_client_secret,
        scopes=[config.YOUTUBE_UPLOAD_SCOPE],
    )


def _analytics_refresh_token_for_lang(lang: str) -> str:
    """lang → 성과 조회 리프레시 토큰. 전용 토큰이 없으면 업로드 토큰으로 폴백.

    폴백 토큰이 조회 스코프를 포함하지 않으면 API 가 403 을 낸다 — 그때 사용자가
    docs/deviation-youtube-analytics.md 절차로 조회 스코프 토큰을 재발급한다.
    """
    attr = config.YOUTUBE_ANALYTICS_TOKEN_SECRET_BY_LANG.get(lang)
    if not attr:
        raise RuntimeError(f"지원하지 않는 성과 조회 언어: {lang!r}")
    token = getattr(config.SECRETS, attr, "")
    if token:
        return token
    # 폴백: 같은 채널의 업로드 토큰(사용자가 조회 스코프 포함해 재발급했을 수 있음).
    fallback_attr = config.YOUTUBE_REFRESH_TOKEN_SECRET_BY_LANG.get(lang)
    fallback = getattr(config.SECRETS, fallback_attr, "") if fallback_attr else ""
    if not fallback:
        raise RuntimeError(
            f"유튜브 성과 조회 토큰 누락({lang} 채널): 환경변수 {attr.upper()} 를 채우세요"
            f"(docs/deviation-youtube-analytics.md 의 조회 스코프 OAuth 설정)."
        )
    return fallback


def _analytics_client_credentials() -> tuple[str, str]:
    """조회 전용 OAuth 클라이언트(id, secret). 전용 클라이언트가 없으면 업로드 클라이언트로 폴백.

    분리해두면 업로드 GCP 프로젝트를 몰라도(또는 건드리고 싶지 않아도) 완전히 새 프로젝트에서
    조회 전용 클라이언트를 만들어 쓸 수 있다 — 운영 중인 자동업로드와 무관하게 독립 동작.
    """
    client_id = config.SECRETS.youtube_analytics_client_id or config.SECRETS.youtube_client_id
    client_secret = config.SECRETS.youtube_analytics_client_secret or config.SECRETS.youtube_client_secret
    if not client_id or not client_secret:
        raise RuntimeError(
            "유튜브 성과 조회 OAuth 클라이언트 누락: YOUTUBE_ANALYTICS_CLIENT_ID/SECRET "
            "(또는 YOUTUBE_CLIENT_ID/SECRET) 를 채우세요(docs/deviation-youtube-analytics.md)."
        )
    return client_id, client_secret


def _analytics_credentials_for_lang(lang: str) -> Any:
    """언어별 채널 읽기 전용 OAuth 자격증명(youtube.readonly + yt-analytics.readonly)."""
    from google.oauth2.credentials import Credentials

    client_id, client_secret = _analytics_client_credentials()
    return Credentials(
        token=None,
        refresh_token=_analytics_refresh_token_for_lang(lang),
        token_uri=config.YOUTUBE_TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=list(config.YOUTUBE_ANALYTICS_SCOPES),
    )


def list_channel_shorts(lang: str, since_date: str) -> list[dict[str, Any]]:
    """채널 업로드 중 since_date(YYYY-MM-DD, UTC) 이후 게시된 쇼츠 메타 목록.

    Data API 로 채널 업로드 재생목록을 since_date 까지 페이지네이션하며 훑고, videos.list
    contentDetails 의 길이가 config.YOUTUBE_SHORTS_MAX_SEC 이하인 것만 쇼츠로 남긴다.
    반환 각 항목: {video_id, title, published_at, duration_sec, view_count, like_count, comment_count}.
    """
    from googleapiclient.discovery import build

    from .. import analytics  # 순수 헬퍼(길이 파싱/쇼츠 판정) 재사용

    creds = _analytics_credentials_for_lang(lang)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)

    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    items = ch.get("items") or []
    if not items:
        return []
    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # 업로드 재생목록은 최신순 — since_date 보다 오래된 게시물이 나오면 중단.
    recent_ids: list[str] = []
    page_token: str | None = None
    stop = False
    while not stop:
        pl = yt.playlistItems().list(
            part="contentDetails", playlistId=uploads_playlist,
            maxResults=50, pageToken=page_token,
        ).execute()
        for it in pl.get("items") or []:
            published_at = it["contentDetails"].get("videoPublishedAt", "")
            if published_at and published_at[:10] < since_date:
                stop = True
                break
            recent_ids.append(it["contentDetails"]["videoId"])
        page_token = pl.get("nextPageToken")
        if not page_token:
            break

    shorts: list[dict[str, Any]] = []
    for chunk in analytics.chunked(recent_ids, 50):  # videos.list 는 한 번에 50개
        vids = yt.videos().list(
            part="snippet,contentDetails,statistics", id=",".join(chunk),
        ).execute()
        for v in vids.get("items") or []:
            duration_sec = analytics.parse_iso8601_duration(
                v["contentDetails"].get("duration", ""))
            if not analytics.is_short(duration_sec):
                continue
            stats = v.get("statistics") or {}
            shorts.append({
                "video_id": v["id"],
                "title": v["snippet"].get("title", ""),
                "published_at": v["snippet"].get("publishedAt", ""),
                "duration_sec": duration_sec,
                "view_count": int(stats.get("viewCount", 0) or 0),
                "like_count": int(stats.get("likeCount", 0) or 0),
                "comment_count": int(stats.get("commentCount", 0) or 0),
            })
    return shorts


def fetch_video_analytics(
    lang: str, video_ids: list[str], start_date: str, end_date: str,
) -> dict[str, dict[str, float]]:
    """YouTube Analytics reports.query 로 영상별 지표 조회. 반환: {video_id: {metric: value}}.

    dimensions=video, filters=video==id1,id2,…, metrics=config.YOUTUBE_ANALYTICS_METRICS.
    날짜는 YYYY-MM-DD(채널 타임존 기준). id 는 chunk 로 나눠 호출한다.
    """
    from googleapiclient.discovery import build

    from .. import analytics

    if not video_ids:
        return {}
    creds = _analytics_credentials_for_lang(lang)
    yta = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)

    metrics = ",".join(config.YOUTUBE_ANALYTICS_METRICS)
    out: dict[str, dict[str, float]] = {}
    for chunk in analytics.chunked(video_ids, config.YOUTUBE_ANALYTICS_ID_CHUNK):
        resp = yta.reports().query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics=metrics,
            dimensions="video",
            filters="video==" + ",".join(chunk),
            maxResults=len(chunk),
        ).execute()
        headers = [h["name"] for h in resp.get("columnHeaders") or []]
        for row in resp.get("rows") or []:
            record = dict(zip(headers, row))
            vid = str(record.pop("video", ""))
            if vid:
                out[vid] = {k: float(v) for k, v in record.items()}
    return out


def fetch_channel_daily(
    lang: str, start_date: str, end_date: str,
) -> list[dict[str, Any]]:
    """채널 단위 날짜별 지표(dimensions=day). 일간/주간/월간 리포트의 시계열 원천.

    per-video(fetch_video_analytics)와 달리 채널 전체를 하루 단위로 집계한다 —
    reports.query 한 번으로 [start, end] 전체 일별 시계열을 받는다. 반환 각 항목:
    {day, views, estimatedMinutesWatched, averageViewPercentage, likes, comments, shares, subscribersGained}.
    """
    from googleapiclient.discovery import build

    creds = _analytics_credentials_for_lang(lang)
    yta = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)

    metrics = ",".join(config.YOUTUBE_ANALYTICS_DAILY_METRICS)
    resp = yta.reports().query(
        ids="channel==MINE",
        startDate=start_date,
        endDate=end_date,
        metrics=metrics,
        dimensions="day",
        sort="day",
    ).execute()
    headers = [h["name"] for h in resp.get("columnHeaders") or []]
    out: list[dict[str, Any]] = []
    for row in resp.get("rows") or []:
        record = dict(zip(headers, row))
        day = str(record.pop("day", ""))
        if not day:
            continue
        item: dict[str, Any] = {"day": day}
        item.update({k: float(v) for k, v in record.items()})
        out.append(item)
    return out


def _fit_tags(tags: list[str]) -> list[str]:
    """태그 정리 + YouTube 합계 500자 제한 준수(명세서 §3-3).

    순수 함수. 앞뒤 공백 제거·빈 태그 제거·중복 제거(입력 순서 보존)한 뒤, 합계
    (쉼표 포함 = sum(len) + n - 1)가 상한을 넘기 직전까지만 담는다. 앞쪽 태그가
    우선이므로 호출부는 공통 태그를 앞에 둔다.

    ※ Codex 가 youtube_meta.sanitize_tags 를 내면 이 함수는 그쪽으로 위임한다(PY 명세서 §3-2).
    """
    out: list[str] = []
    seen: set[str] = set()
    total = 0
    for raw in tags:
        t = str(raw).strip()
        if not t or t in seen:
            continue
        add = len(t) + (1 if out else 0)
        if total + add > config.YOUTUBE_TAGS_TOTAL_MAX:
            break
        out.append(t)
        seen.add(t)
        total += add
    return out


def upload_video(
    file_path: str,
    *,
    title: str,
    description: str,
    tags: list[str] | None = None,
    privacy_status: str,
    category_id: str,
    lang: str,
    made_for_kids: bool = False,
    refresh_token_secret_by_lang: dict[str, str] | None = None,
    channel_key: str | None = None,
) -> dict[str, str]:
    """mp4 파일을 해당 채널에 업로드(resumable). 반환: {video_id, url, channel_id}.

    실패는 예외로 전파(워커가 잡아 upload_requests.status='error' 기록). 부분 업로드는
    YouTube 가 미게시 상태로 남기며, 우리 DB 는 done 이 아니므로 사람이 확인 후 재시도한다.

    channel_key: 'paper_ko' | 'paper_en' | 'report_ko'. 주면 CHANNEL_REGISTRY 로 자격증명을
      만들고 **업로드 전에 채널 가드**(assert_correct_channel)를 통과시킨다. 채널을 잘못 고른
      토큰은 에러 없이 엉뚱한 채널에 올려버리므로, 이 가드가 유일한 사전 방어선이다.
    refresh_token_secret_by_lang: channel_key 를 안 줄 때 쓰는 레거시 lang→토큰 맵.
    """
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    if channel_key:
        from .. import youtube_channels as yc
        # ★ 스코프를 **요청하지 않는다.** 여기서 upload+readonly 를 요청하면, readonly 없이
        #   발급된 토큰(=채널 통합 후 report_ko 가 쓰는 YOUTUBE_REFRESH_TOKEN_KO)은 갱신
        #   단계에서 `invalid_scope: Bad Request` 로 죽는다 — 업로드가 아예 못 나간다.
        #   §9-6 이 설계한 "스코프 부족이면 가드만 WARN 하고 업로드는 계속"은 channels.list
        #   403 을 전제로 한 것이라, 갱신에서 먼저 죽으면 그 폴백이 돌지 못한다.
        #   scope 를 빼면 승인받은 범위 그대로 토큰이 나와 두 종류 토큰이 모두 살아난다.
        creds = yc.load_credentials(channel_key)
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
        yc.assert_correct_channel(youtube, channel_key)
    else:
        creds = _credentials_for_lang(lang, refresh_token_secret_by_lang)
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": _fit_tags(tags or []),
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }
    media = MediaFileUpload(file_path, mimetype="video/mp4", chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _status, response = request.next_chunk()
    video_id = str(response["id"])
    url = f"https://youtu.be/{video_id}"
    # 실제로 올라간 채널을 응답에서 읽어 기록한다(사후 감사 — 어느 채널로 갔는지 DB 로 추적 가능).
    channel_id = str((response.get("snippet") or {}).get("channelId") or "")
    log.info("유튜브 업로드 완료: channel=%s id=%s (%s) channel_id=%s",
             channel_key or lang, video_id, privacy_status, channel_id or "미상")
    return {"video_id": video_id, "url": url, "channel_id": channel_id}
