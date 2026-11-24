"""주류 릴스 → 유튜브 쇼츠 공급자 (2026-11-24, docs/deviation-drinks-youtube-channel.md).

인스타 공급자(engine/providers/instagram.py)와 **같은 모양**이라 발행 워커(engine.drinks_publish)는 그대로 쓴다:
  create_container = 올릴 파일 주소·캡션을 기억만 한다(유튜브에는 컨테이너가 없다)
  container_status = 기억한 것이 있으면 FINISHED
  publish          = 실제 업로드(이 호출 앞에 워커가 'publish_called' 를 먼저 기록한다 — 뒤 실패는 unknown)
  media            = 올라간 영상(쇼츠 주소)
계정의 credential_ref = 리프레시 토큰을 둔 환경변수 이름. 클라이언트 ID/비밀은 논문 채널과 같은 YOUTUBE_CLIENT_ID/SECRET.
업로드 스코프만 있는 토큰으로도 채널 확인(channels.list mine)은 된다 — scripts/check_youtube_tokens.py 가 2026-11-24 실측.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from typing import Any, Optional

from .. import config
from .instagram import AuthError, Media, PublishError


def video_title(caption: str) -> str:
    """캡션 첫 줄(해시태그 줄 제외) → 유튜브 제목. 유튜브는 '<' '>' 를 받지 않고 100자까지다."""
    lines = [ln.strip() for ln in (caption or "").splitlines()]
    first = next((ln for ln in lines if ln and not ln.startswith("#")), "")
    title = first.replace("<", "").replace(">", "").strip()
    title = title[: config.YOUTUBE_TITLE_MAX].rstrip()
    return title or config.DRINKS_YT_FALLBACK_TITLE


class DrinksYouTube:
    def __init__(self) -> None:
        self._pending: dict[str, dict[str, Any]] = {}   # 컨테이너 ID → {url, caption} (이 워커 실행 안에서만)
        self._uploaded: dict[str, dict[str, str]] = {}  # 영상 ID → {channel_id, caption}
        self._services: dict[str, Any] = {}
        self._channels: dict[str, dict[str, Any]] = {}

    def _service(self, account: dict[str, Any]) -> Any:
        """채널 확인까지 마친 API 클라이언트. 토큰 갱신 실패는 AuthError(계정 재인증), 다른 채널이면 provider_mismatch."""
        key = account.get("account_id") or account.get("credential_ref")
        if key in self._services:
            return self._services[key]
        try:
            from google.auth.exceptions import RefreshError
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:   # 워크플로가 라이브러리를 안 깔았다 — 워커 전체(인스타 포함)를 죽이지 않는다
            raise PublishError("provider_disabled", "유튜브 라이브러리(google-api-python-client)가 설치되지 않았습니다") from exc

        token = os.getenv(account.get("credential_ref") or "", "")
        cid, secret = os.getenv("YOUTUBE_CLIENT_ID", ""), os.getenv("YOUTUBE_CLIENT_SECRET", "")
        if not token or not cid or not secret:
            raise AuthError("credential_missing", f"유튜브 토큰 비밀({account.get('credential_ref')}) 또는 클라이언트 ID/비밀이 없습니다")
        # scope 를 싣지 않는다 — 업로드만 승인된 토큰이 갱신에서 invalid_scope 로 죽는다(youtube_channels.load_credentials 와 같은 이유).
        creds = Credentials(token=None, refresh_token=token, token_uri=config.YOUTUBE_TOKEN_URI, client_id=cid, client_secret=secret)
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
        try:
            items = yt.channels().list(part="snippet", mine=True).execute().get("items") or []
        except RefreshError as exc:
            raise AuthError("token_refresh_failed", f"유튜브 토큰 갱신 실패: {str(exc)[:200]}") from exc
        except Exception as exc:  # noqa: BLE001 — 403·쿼터·네트워크: 계정 대조 루프를 뚫고 워커 전체를 멈추지 않게
            raise PublishError("youtube_api_error", f"유튜브 채널 확인 실패({type(exc).__name__}): {str(exc)[:200]}") from exc
        if not items:
            raise AuthError("no_channel", "이 토큰에 연결된 유튜브 채널이 없습니다")
        self._services[key] = yt
        self._channels[key] = {"id": items[0]["id"], "username": (items[0].get("snippet") or {}).get("title")}
        return yt

    def verify(self, account: dict[str, Any]) -> dict[str, Any]:
        self._service(account)
        return self._channels[account.get("account_id") or account.get("credential_ref")]

    def check_audio(self, account: dict[str, Any], audio_id: str) -> dict[str, Any]:
        raise PublishError("audio_unsupported", "유튜브에는 인스타 음원을 붙일 수 없습니다 — 음악을 깐 렌더(licensed_mix)나 나레이션 릴스만 올립니다")

    def create_container(self, account: dict[str, Any], *, kind: str, url: Optional[str] = None,
                         caption: Optional[str] = None, **_: Any) -> str:
        if kind != "reel" or not url:
            raise PublishError("unsupported_post_type", "유튜브는 릴스(쇼츠) 영상만 올립니다")
        # ★ 채널 가드는 게시 호출 **전**에 — 토큰이 다른 채널 것이면 에러 없이 엉뚱한 채널에 올라간다.
        if self.verify(account)["id"] != account.get("external_account_id"):
            raise PublishError("provider_mismatch", "토큰의 유튜브 채널이 등록된 채널 ID 와 다릅니다")
        # 파일도 게시 호출 **전**에 받아 둔다 — 다운로드 실패가 '게시 여부 불명(unknown)'이 되지 않게.
        path = os.path.join(tempfile.mkdtemp(prefix="drinks_yt_"), "reel.mp4")
        try:
            _download(url, path)
        except Exception as exc:  # noqa: BLE001
            raise PublishError("file_download_failed", f"릴스 파일을 받지 못했습니다: {type(exc).__name__}") from exc
        cid = f"yt-{uuid.uuid4().hex}"
        self._pending[cid] = {"path": path, "caption": caption or ""}
        return cid

    def container_status(self, account: dict[str, Any], cid: str) -> str:
        return "FINISHED" if cid in self._pending else "ERROR"

    def publish(self, account: dict[str, Any], cid: str) -> str:
        from googleapiclient.http import MediaFileUpload

        job = self._pending.get(cid)
        if job is None:
            raise PublishError("container_missing", "올릴 파일 정보를 잃었습니다(워커 재시작)")
        yt = self._service(account)
        path = job["path"]
        body = {
            "snippet": {"title": video_title(job["caption"]), "description": job["caption"][: config.YOUTUBE_DESC_MAX],
                        "categoryId": config.DRINKS_YT_CATEGORY_ID},
            "status": {"privacyStatus": config.DRINKS_YT_PRIVACY, "selfDeclaredMadeForKids": False},
        }
        req = yt.videos().insert(part="snippet,status", body=body,
                                 media_body=MediaFileUpload(path, mimetype="video/mp4", chunksize=-1, resumable=True))
        resp = None
        while resp is None:
            _st, resp = req.next_chunk()
        vid = str(resp["id"])
        self._uploaded[vid] = {"channel_id": str((resp.get("snippet") or {}).get("channelId") or ""), "caption": job["caption"]}
        return vid

    def media(self, account: dict[str, Any], media_id: str) -> Media:
        up = self._uploaded.get(media_id)
        if up is None or not up["channel_id"]:
            raise PublishError("confirm_failed", "업로드 응답에서 채널을 읽지 못했습니다")
        return Media(id=media_id, owner_id=up["channel_id"], permalink=f"https://youtube.com/shorts/{media_id}", caption=up["caption"])

    def find_published(self, account: dict[str, Any], container_ids: list[str], caption: str) -> tuple[str, Optional[Media]]:
        # 업로드 스코프로는 채널 영상 목록을 볼 수 없다 — 사람이 유튜브 스튜디오에서 확인한다(unknown 유지).
        return "unknown", None

    def insights(self, account: dict[str, Any], media_id: str, post_type: str) -> tuple[dict[str, float], dict[str, str]]:
        raise PublishError("metrics_unsupported", "유튜브 쇼츠 성과 수집은 아직 없습니다")


def _download(url: str, dest: str) -> None:
    import httpx

    with httpx.stream("GET", url, timeout=config.HTTP_TIMEOUT_SEC, follow_redirects=True) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
