"""Instagram 게시·조회 공급자 (주류 공장 ③ 발행·④ 성과 워커 전용). 2026-10-27. docs/deviation-drinks-publish-loop.md

두 가지가 같은 모양으로 있다:
  · FakeInstagram   — 시험용. 외부 호출 0. 상태를 JSON 파일 하나에 둬서 발행 워커와 성과 워커(다른 실행)가 같은
                      '가짜 인스타'를 본다. 실패·타임아웃을 한 번씩 주입할 수 있다(unknown·failed 경로 시험).
  · GraphInstagram  — Meta 공식 Graph API. **계정 유형·연결 방식이 정해지기 전에는 켜지 않는다**
                      (DRINKS_IG_LIVE=1 이 있어야 워커가 고른다). 엔드포인트·필드 이름은 명세 §16.2 의 공식 컬렉션 기준이고
                      실제 계정으로는 한 번도 부르지 않았다 — 첫 연결 때 필드 이름부터 실측한다(미검증).

규칙(명세 §11):
  · 토큰은 환경변수(credential_ref 가 그 이름)에서만 읽고, **URL·로그·예외 문장에 넣지 않는다** — Authorization 헤더로만 보낸다.
  · 캐러셀은 자식 컨테이너가 전부 FINISHED 가 된 뒤에만 부모를 만들고 게시한다(워커가 지킨다).
  · 게시 호출 중 타임아웃·연결 끊김은 PublishTimeout — 게시됐을 수 있다(워커가 unknown 으로 보낸다).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

GRAPH_VERSION = os.getenv("DRINKS_IG_GRAPH_VERSION", "v23.0")
# 우리가 저장하는 지표 이름(공급자 이름을 그대로 쓰지 않는다 — 이름만 바꿔 다른 뜻으로 쓰지 않게, 명세 §3).
METRIC_SCHEMA_VERSION = "ig-media-v1"
CAROUSEL_METRICS = ("reach", "saved", "shares", "likes", "comments", "total_interactions")
REEL_METRICS = CAROUSEL_METRICS + ("views", "avg_watch_time_ms")
# 우리 이름 → Graph API 지표 이름(미검증: 첫 연결 때 실측해 고친다)
_GRAPH_METRIC = {"reach": "reach", "saved": "saved", "shares": "shares", "likes": "likes", "comments": "comments",
                 "total_interactions": "total_interactions", "views": "views", "avg_watch_time_ms": "ig_reels_avg_watch_time"}


class PublishError(Exception):
    """공급자가 거부를 확정한 오류(응답이 왔다). code 는 짧은 기계 코드, message 는 비밀 없는 한국어 문장."""

    def __init__(self, code: str, message: str, *, response_code: Optional[str] = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.response_code = response_code


class PublishTimeout(PublishError):
    """응답을 못 받았다 — 요청이 처리됐는지 모른다."""


class AuthError(PublishError):
    """토큰 만료·권한 철회. 계정을 reauth_required 로 보낸다."""


@dataclass
class Media:
    id: str
    owner_id: str
    permalink: Optional[str]
    caption: str = ""


# ─────────────────────────────────────────────────────────────
# 가짜 공급자
# ─────────────────────────────────────────────────────────────

class FakeInstagram:
    """상태 = {accounts:{ext_id:{username,token_ok}}, containers:{id:{...}}, media:{id:{...}}, faults:{op:kind}, metrics:{media:{...}}}.

    faults 는 한 번 쓰면 사라진다. 지원: publish=timeout_after(게시는 되고 응답만 잃음) | timeout_before(게시 안 되고 응답 잃음)
    | error(거부 확정) · container=error · verify=auth_error · insights=error.
    """

    name = "fake"

    def __init__(self, state_path: Optional[str] = None):
        self.path = state_path or os.getenv("DRINKS_FAKE_IG_STATE") or os.path.join(tempfile.gettempdir(), "drinks_fake_ig.json")

    # 상태 파일 ─────────────────────────
    def _load(self) -> dict[str, Any]:
        if not os.path.exists(self.path):
            return {"accounts": {}, "containers": {}, "media": {}, "faults": {}, "metrics": {}}
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def _save(self, st: dict[str, Any]) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def _fault(self, st: dict[str, Any], op: str) -> Optional[str]:
        kind = st.get("faults", {}).pop(op, None)
        if kind:
            self._save(st)
        return kind

    def inject(self, op: str, kind: str) -> None:
        st = self._load()
        st.setdefault("faults", {})[op] = kind
        self._save(st)

    def add_account(self, ext_id: str, username: str) -> None:
        assert ext_id.startswith("fake_"), "가짜 공급자는 fake_ 계정만 안다"
        st = self._load()
        st.setdefault("accounts", {})[ext_id] = {"username": username}
        self._save(st)

    def set_metrics(self, media_id: str, values: dict[str, Any]) -> None:
        st = self._load()
        st.setdefault("metrics", {})[media_id] = values
        self._save(st)

    @staticmethod
    def _check(account: dict[str, Any]) -> str:
        ext = str(account.get("external_account_id") or "")
        if account.get("connection") != "fake" or not ext.startswith("fake_"):
            raise PublishError("provider_mismatch", "가짜 공급자로 실제 계정을 다루지 않습니다")
        return ext

    # 공급자 동작 ─────────────────────────
    def verify(self, account: dict[str, Any]) -> dict[str, Any]:
        ext = self._check(account)
        st = self._load()
        if self._fault(st, "verify") == "auth_error":
            raise AuthError("auth_failed", "토큰이 만료됐습니다(가짜)")
        if ext not in st.get("accounts", {}):
            raise AuthError("unknown_account", "가짜 인스타에 없는 계정입니다")
        return {"id": ext, "username": st["accounts"][ext]["username"]}

    def create_container(self, account: dict[str, Any], *, kind: str, url: Optional[str] = None,
                         children: Optional[list[str]] = None, caption: Optional[str] = None,
                         cover_url: Optional[str] = None) -> str:
        ext = self._check(account)
        st = self._load()
        if self._fault(st, "container") == "error":
            raise PublishError("container_rejected", "컨테이너 생성 거부(가짜)", response_code="400")
        if kind in ("image", "reel") and not url:
            raise PublishError("media_url_missing", "파일 주소가 없습니다")
        if kind == "carousel":
            kids = children or []
            if any(st["containers"].get(c, {}).get("status") != "FINISHED" for c in kids):
                raise PublishError("children_not_ready", "자식 컨테이너가 준비되지 않았습니다")
        cid = "c_" + uuid.uuid4().hex[:12]
        st["containers"][cid] = {"owner": ext, "kind": kind, "url": url, "children": children or [], "caption": caption or "",
                                 "cover_url": cover_url, "status": "FINISHED", "media_id": None}
        self._save(st)
        return cid

    def container_status(self, account: dict[str, Any], cid: str) -> str:
        self._check(account)
        c = self._load()["containers"].get(cid)
        return "EXPIRED" if c is None else c["status"]

    def publish(self, account: dict[str, Any], cid: str) -> str:
        ext = self._check(account)
        st = self._load()
        fault = self._fault(st, "publish")
        c = st["containers"].get(cid)
        if c is None or c["owner"] != ext:
            raise PublishError("container_missing", "컨테이너가 없습니다", response_code="400")
        if fault == "error":
            raise PublishError("publish_rejected", "게시 거부(가짜)", response_code="400")
        if fault == "timeout_before":
            raise PublishTimeout("publish_timeout", "응답 없음(가짜 — 게시 안 됨)")
        if c["status"] == "PUBLISHED":
            return c["media_id"]
        mid = "m_" + uuid.uuid4().hex[:12]
        c["status"], c["media_id"] = "PUBLISHED", mid
        st["media"][mid] = {"owner": ext, "caption": c["caption"], "kind": c["kind"],
                            "permalink": f"https://www.instagram.com/p/{mid}/", "published_at": time.time()}
        self._save(st)
        if fault == "timeout_after":
            raise PublishTimeout("publish_timeout", "응답 없음(가짜 — 실제로는 게시됨)")
        return mid

    def media(self, account: dict[str, Any], media_id: str) -> Media:
        self._check(account)
        m = self._load()["media"].get(media_id)
        if m is None:
            raise PublishError("media_missing", "게시물이 없습니다")
        return Media(id=media_id, owner_id=m["owner"], permalink=m["permalink"], caption=m["caption"])

    def find_published(self, account: dict[str, Any], container_ids: list[str], caption: str) -> tuple[str, Optional[Media]]:
        """('published', Media) | ('not_published', None) | ('unknown', None). 컨테이너 상태로 확정한다."""
        self._check(account)
        st = self._load()
        known = [st["containers"][c] for c in container_ids if c in st["containers"]]
        for c in known:
            if c["status"] == "PUBLISHED" and c["media_id"]:
                return "published", self.media(account, c["media_id"])
        if known and len(known) == len(container_ids):
            return "not_published", None
        return "unknown", None

    def insights(self, account: dict[str, Any], media_id: str, post_type: str) -> tuple[dict[str, float], dict[str, str]]:
        self._check(account)
        st = self._load()
        if self._fault(st, "insights") == "error":
            raise PublishError("insights_failed", "지표 조회 실패(가짜)")
        wanted = REEL_METRICS if post_type == "reel" else CAROUSEL_METRICS
        given = st.get("metrics", {}).get(media_id)
        if given is None:   # 정해 둔 값이 없으면 게시물 ID 에서 결정적으로 만든다(시험 재현용)
            h = int(hashlib.sha256(media_id.encode()).hexdigest()[:8], 16)
            given = {"reach": 500 + h % 1500, "saved": h % 40, "shares": h % 25, "likes": 20 + h % 200, "comments": h % 15}
        values = {k: float(given[k]) for k in wanted if isinstance(given.get(k), (int, float))}
        values["total_interactions"] = values.get("total_interactions") or sum(
            values.get(k, 0.0) for k in ("saved", "shares", "likes", "comments"))
        unavailable = {k: "not_provided" for k in wanted if k not in values}
        return values, unavailable


# ─────────────────────────────────────────────────────────────
# Meta Graph API 공급자 (미검증 — 실제 계정 연결 전)
# ─────────────────────────────────────────────────────────────

class GraphInstagram:
    name = "instagram_graph"

    def __init__(self, *, client: Any = None, timeout: float = 30.0, poll_sec: float = 3.0):
        import httpx

        self.http = client or httpx.Client(timeout=timeout)
        self.poll_sec = poll_sec

    @staticmethod
    def _base(account: dict[str, Any]) -> str:
        conn = account.get("connection")
        if conn == "instagram_login":
            return f"https://graph.instagram.com/{GRAPH_VERSION}"
        if conn == "facebook_login":
            return f"https://graph.facebook.com/{GRAPH_VERSION}"
        raise PublishError("provider_mismatch", "실제 Graph API 로 가짜 계정을 다루지 않습니다")

    @staticmethod
    def _token(account: dict[str, Any]) -> str:
        ref = str(account.get("credential_ref") or "")
        tok = os.getenv(ref) if ref else None
        if not tok:
            raise AuthError("credential_missing", f"토큰 비밀({ref or '이름 없음'})이 이 실행 환경에 없습니다")
        return tok

    def _call(self, method: str, account: dict[str, Any], path: str, *, params: Optional[dict[str, Any]] = None,
              data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        import httpx

        headers = {"Authorization": f"Bearer {self._token(account)}"}   # 토큰은 헤더로만(URL·로그 금지)
        try:
            r = self.http.request(method, self._base(account) + path, params=params, data=data, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise PublishTimeout("network_timeout", f"응답을 받지 못했습니다({type(exc).__name__})") from None
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code >= 400:
            err = (body or {}).get("error") or {}
            code = str(err.get("code") or r.status_code)
            # 190 = 토큰 무효, 10/200번대 = 권한 — 계정 재인증으로 보낸다. 메시지는 비밀이 섞일 수 있어 그대로 싣지 않는다.
            if code in ("190", "10") or (code.isdigit() and 200 <= int(code) < 300):
                raise AuthError("auth_failed", f"인증·권한 오류(코드 {code})", response_code=str(r.status_code))
            if r.status_code >= 500:
                raise PublishTimeout("provider_5xx", f"공급자 서버 오류({r.status_code})")
            raise PublishError("provider_rejected", f"공급자가 거부했습니다(코드 {code})", response_code=str(r.status_code))
        return body

    def verify(self, account: dict[str, Any]) -> dict[str, Any]:
        if account.get("connection") == "instagram_login":
            b = self._call("GET", account, "/me", params={"fields": "user_id,username"})
            return {"id": str(b.get("user_id") or ""), "username": b.get("username")}
        b = self._call("GET", account, f"/{account['external_account_id']}", params={"fields": "id,username"})
        return {"id": str(b.get("id") or ""), "username": b.get("username")}

    def create_container(self, account: dict[str, Any], *, kind: str, url: Optional[str] = None,
                         children: Optional[list[str]] = None, caption: Optional[str] = None,
                         cover_url: Optional[str] = None) -> str:
        if url is not None and not url.startswith("https://"):
            raise PublishError("media_url_invalid", "공급자가 가져갈 수 있는 https 주소가 아닙니다")
        data: dict[str, Any] = {}
        if kind == "image":
            data = {"image_url": url, "is_carousel_item": "true"}
        elif kind == "carousel":
            data = {"media_type": "CAROUSEL", "children": ",".join(children or []), "caption": caption or ""}
        elif kind == "reel":
            data = {"media_type": "REELS", "video_url": url, "caption": caption or ""}
            if cover_url:
                data["cover_url"] = cover_url
        else:
            raise PublishError("invalid_kind", f"알 수 없는 컨테이너 종류: {kind}")
        b = self._call("POST", account, f"/{account['external_account_id']}/media", data=data)
        return str(b["id"])

    def container_status(self, account: dict[str, Any], cid: str) -> str:
        return str(self._call("GET", account, f"/{cid}", params={"fields": "status_code"}).get("status_code") or "IN_PROGRESS")

    def publish(self, account: dict[str, Any], cid: str) -> str:
        b = self._call("POST", account, f"/{account['external_account_id']}/media_publish", data={"creation_id": cid})
        return str(b["id"])

    def media(self, account: dict[str, Any], media_id: str) -> Media:
        b = self._call("GET", account, f"/{media_id}", params={"fields": "id,permalink,caption,owner"})
        owner = str((b.get("owner") or {}).get("id") or "")
        # ★ Instagram 로그인 토큰은 게시물 주인을 **앱 전용 ID**(/me 의 id)로 준다 — 계정 ID(/me 의 user_id)와 다르다
        #   (2026-10-28 실측: 29421…≠17841…). 그 둘을 이어 주지 않으면 매 게시가 '계정 불일치 → unknown' 이 된다.
        if account.get("connection") == "instagram_login" and owner:
            me = self._call("GET", account, "/me", params={"fields": "id,user_id"})
            if owner == str(me.get("id") or ""):
                owner = str(me.get("user_id") or "")
        return Media(id=str(b.get("id")), owner_id=owner, permalink=b.get("permalink"), caption=b.get("caption") or "")

    def find_published(self, account: dict[str, Any], container_ids: list[str], caption: str) -> tuple[str, Optional[Media]]:
        statuses = []
        for cid in container_ids[-1:]:   # 부모(마지막) 컨테이너가 게시 단위다
            try:
                statuses.append(self.container_status(account, cid))
            except PublishError:
                statuses.append("UNKNOWN")
        if "PUBLISHED" in statuses:
            b = self._call("GET", account, f"/{account['external_account_id']}/media",
                           params={"fields": "id,caption,permalink", "limit": 25})
            for m in b.get("data") or []:
                if (m.get("caption") or "") == caption:
                    return "published", Media(id=str(m["id"]), owner_id=account["external_account_id"],
                                              permalink=m.get("permalink"), caption=caption)
            return "unknown", None
        if statuses and all(s in ("FINISHED", "ERROR", "EXPIRED") for s in statuses):
            return "not_published", None
        return "unknown", None

    def insights(self, account: dict[str, Any], media_id: str, post_type: str) -> tuple[dict[str, float], dict[str, str]]:
        wanted = REEL_METRICS if post_type == "reel" else CAROUSEL_METRICS
        values: dict[str, float] = {}
        unavailable: dict[str, str] = {}
        for k in wanted:   # 하나씩 묻는다 — 지원 안 하는 지표 하나가 전체를 실패시키지 않게
            try:
                b = self._call("GET", account, f"/{media_id}/insights", params={"metric": _GRAPH_METRIC[k]})
            except AuthError:
                raise
            except PublishError as exc:
                unavailable[k] = exc.code
                continue
            data = (b.get("data") or [{}])[0]
            v = (data.get("values") or [{}])[0].get("value") if data.get("values") else data.get("total_value", {}).get("value")
            if isinstance(v, (int, float)):
                values[k] = float(v)
            else:
                unavailable[k] = "no_value"
        return values, unavailable


def provider_for(account: dict[str, Any], *, fake: Optional[FakeInstagram] = None) -> Any:
    """계정 연결 방식 → 공급자. 실제 Graph API 는 DRINKS_IG_LIVE=1 일 때만(운영자 승인 전 꺼짐)."""
    if account.get("connection") == "fake":
        return fake or FakeInstagram()
    if os.getenv("DRINKS_IG_LIVE") != "1":
        raise PublishError("provider_disabled", "실제 인스타 게시는 아직 꺼져 있습니다(DRINKS_IG_LIVE 미설정 — 운영자 승인 대기)")
    return GraphInstagram()
