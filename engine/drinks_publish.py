"""주류 공장 ③ 발행 워커(인스타 카드뉴스·릴스). 2026-10-27. docs/deviation-drinks-publish-loop.md

    python -m engine.drinks_publish            # 계정 대조 → 예약 도래분 게시 → 게시 여부 불명(unknown) 대조

순서(명세 §8.4·§11):
  1. 계정 대조 — 등록된 외부 ID 와 토큰 주인이 같아야 active. 다르면 mismatch, 토큰 문제면 reauth_required(예약은 paused).
  2. 게시 — DB 가 예약 시각이 된 요청을 하나씩 준다(drinks_claim_publication: 늦은 것·막힌 것은 DB 가 paused 로 보낸다).
     캡션 코드 검사(원문에 없는 숫자·양·권고) → 파일 임시 주소 → 컨테이너(캐러셀은 자식 전부 FINISHED 뒤 부모)
     → 게시 직전 재확인(취소·승인 무효) → **게시 호출 단계를 먼저 기록**하고 게시 → 게시물 계정 대조 → 끝.
  3. 대조 — unknown 은 다시 게시하지 않는다. 공급자에게 컨테이너가 게시됐는지 물어 published/failed/canceled 로 정정.

실패의 갈래:
  · 게시 호출 **전** 공급자가 거부를 확정 → failed(재시도 가능). 캡션·계정·공급자 꺼짐 → paused(사람이 고친다).
  · 게시 호출 **뒤** 무엇이든(타임아웃·오류·워커 죽음) → unknown. 정확히-한-번은 보장하지 않는다(§8.4).
공급자: 계정이 fake 연결이면 가짜 공급자, 실제 연결이면 DRINKS_IG_LIVE=1 일 때만 Meta Graph API(운영자 승인 전 꺼짐).
"""

from __future__ import annotations

import argparse
import time
from typing import Any, Callable, Optional

from . import config
from . import drinks_script_check as script_check
from .drinks_collect import DbError, supabase_rpc
from .drinks_produce import Storage
from .drinks_render import RenderError
from .providers.instagram import AuthError, PublishError, PublishTimeout, provider_for
from .util import log

Rpc = Callable[[str, dict[str, Any]], Any]
ProviderFor = Callable[[dict[str, Any]], Any]

CONTAINER_WAIT_SEC = 300      # 컨테이너 처리 대기 상한(영상은 오래 걸린다)
CONTAINER_POLL_SEC = 5


def verify_accounts(rpc: Rpc, providers: ProviderFor) -> list[dict[str, Any]]:
    out = []
    for acc in rpc("drinks_accounts_to_verify", {}) or []:
        try:
            who = providers(acc).verify(acc)
            res = rpc("drinks_account_verified", {"account_id": acc["account_id"], "ok": True,
                                                  "external_account_id": who.get("id"), "username": who.get("username")})
        except PublishError as exc:   # 인증 실패·공급자 꺼짐 — 재인증 필요로 표시
            res = rpc("drinks_account_verified", {"account_id": acc["account_id"], "ok": False, "error_code": exc.code})
        log.info("drinks: 계정 %s 대조 → %s", acc["account_id"], res.get("status"))
        out.append(res)
    return out


def _wait_ready(provider: Any, account: dict[str, Any], cids: list[str], *, wait_sec: float, poll_sec: float) -> None:
    deadline = time.monotonic() + wait_sec
    pending = list(cids)
    while pending:
        nxt = []
        for cid in pending:
            st = provider.container_status(account, cid)
            if st in ("ERROR", "EXPIRED"):
                raise PublishError("container_failed", f"컨테이너 처리 실패({st})")
            if st != "FINISHED":
                nxt.append(cid)
        pending = nxt
        if pending:
            if time.monotonic() > deadline:
                raise PublishError("container_timeout", f"컨테이너 처리가 {int(wait_sec)}초 안에 끝나지 않았습니다(게시 전)")
            time.sleep(poll_sec)


def publish_one(req: dict[str, Any], rpc: Rpc, storage: Storage, providers: ProviderFor, *,
                wait_sec: float = CONTAINER_WAIT_SEC, poll_sec: float = CONTAINER_POLL_SEC) -> dict[str, Any]:
    lease = {"request_id": req["request_id"], "lease_token": req["lease_token"]}
    account = req["account"]
    called = False   # 게시 호출 단계를 기록했나 — 그 뒤 실패는 전부 unknown

    def finish(outcome: str, **kw: Any) -> dict[str, Any]:
        return rpc("drinks_finish_publication", {**lease, "outcome": outcome, **kw})

    try:
        rep = script_check.check_caption(req.get("caption") or "", req.get("claims") or [], sources=req.get("sources"))
        if not rep.ok:
            return finish("paused", error_code="caption_check",
                          error_message="캡션 검사에서 막혔습니다: " + "; ".join(f"{f.code}: {f.message}" for f in rep.blocks)[:1500])
        provider = providers(account)
        files = req.get("files") or []
        if req["post_type"] == "carousel":
            pages = sorted((f for f in files if f["role"] == "page"), key=lambda f: f["position"])
            child_urls = [storage.signed_url(f["storage_key"]) for f in pages]
            children = [provider.create_container(account, kind="image", url=u) for u in child_urls]
            rpc("drinks_publication_step", {**lease, "stage": "containers_created", "container_ids": children})
            _wait_ready(provider, account, children, wait_sec=wait_sec, poll_sec=poll_sec)   # 자식 전부 준비된 뒤에만 부모
            parent = provider.create_container(account, kind="carousel", children=children, caption=req.get("caption"))
            cids = children + [parent]
        else:
            video = next(f for f in files if f["role"] == "final_video")
            cover = next((f for f in files if f["role"] == "cover"), None)
            parent = provider.create_container(account, kind="reel", url=storage.signed_url(video["storage_key"]),
                                               caption=req.get("caption"),
                                               cover_url=storage.signed_url(cover["storage_key"]) if cover else None)
            cids = [parent]
        rpc("drinks_publication_step", {**lease, "stage": "containers_created", "container_ids": cids})
        _wait_ready(provider, account, [parent], wait_sec=wait_sec, poll_sec=poll_sec)
        rpc("drinks_publication_step", {**lease, "stage": "containers_ready", "container_ids": cids})
        gate = rpc("drinks_publication_step", {**lease, "stage": "before_publish"}) or {}
        if not gate.get("proceed"):
            block = gate.get("block") or "blocked"
            if block == "cancel_requested":
                return finish("canceled", error_code="cancel_requested")
            return finish("paused", error_code=block, error_message=f"게시 직전 재확인에서 막혔습니다: {block}")
        # ★ 기록을 먼저 한다. 이 줄 뒤에서 무슨 일이 나도 '게시됐을 수 있음'이 DB 에 남는다.
        rpc("drinks_publication_step", {**lease, "stage": "publish_called", "container_ids": cids})
        called = True
        media_id = provider.publish(account, parent)
        try:
            m = provider.media(account, media_id)
        except PublishError as exc:
            return finish("unknown", error_code="confirm_failed", error_message=f"게시는 응답했지만 확인 조회가 실패했습니다: {exc.code}")
        return finish("published", external_post_id=m.id, external_url=m.permalink, owner_account_id=m.owner_id)
    except DbError as exc:
        if exc.code == "lease_lost":
            log.warning("drinks: 발행 %s 임대를 잃었습니다 — 결과는 다음 대조가 정합니다", req["request_id"])
            return {"status": "lease_lost"}
        raise
    except (PublishTimeout, PublishError, RenderError, StopIteration, Exception) as exc:  # noqa: BLE001
        code = getattr(exc, "code", None) or type(exc).__name__
        msg = getattr(exc, "message", None) or f"워커 예외: {type(exc).__name__}"
        try:
            if called:
                return finish("unknown", error_code=code, error_message=f"게시 호출 뒤 오류 — 게시 여부를 조회로 대조합니다: {msg}")
            if isinstance(exc, AuthError) or code in ("provider_disabled", "provider_mismatch", "file_missing",
                                                       "storage_mode", "signed_url_failed"):
                res = finish("paused", error_code="account_reauth" if isinstance(exc, AuthError) else code, error_message=msg)
                if isinstance(exc, AuthError):   # 이 요청을 먼저 닫고, 계정을 재인증 필요로 — 같은 계정의 다른 예약도 멈춘다
                    rpc("drinks_account_verified", {"account_id": account["account_id"], "ok": False, "error_code": code})
                return res
            if isinstance(exc, PublishTimeout):
                # 게시 호출 전의 타임아웃 = 컨테이너 단계. 게시는 일어나지 않았다 → 확정 실패(재시도 가능)
                return finish("failed", error_code=code, error_message=msg)
            if isinstance(exc, PublishError):
                return finish("failed", error_code=code, error_message=msg)
            log.exception("drinks: 발행 %s 예외", req["request_id"])
            return finish("paused", error_code="worker_error", error_message=msg)
        except DbError:
            return {"status": "lease_lost"}


def reconcile(rpc: Rpc, providers: ProviderFor) -> list[dict[str, Any]]:
    out = []
    for u in rpc("drinks_unknown_publications", {}) or []:
        try:
            verdict, media = providers(u["account"]).find_published(u["account"], list(u.get("container_ids") or []),
                                                                     u.get("caption") or "")
        except PublishError as exc:
            log.warning("drinks: 대조 %s 조회 실패(%s) — unknown 유지", u["request_id"], exc.code)
            continue
        p: dict[str, Any] = {"request_id": u["request_id"]}
        if verdict == "published" and media is not None:
            p.update(found=True, external_post_id=media.id, external_url=media.permalink, owner_account_id=media.owner_id)
        elif verdict == "not_published":
            p.update(found=False, confirmed_not_published=True)
        else:
            p.update(found=False)
        res = rpc("drinks_reconcile_publication", p)
        log.info("drinks: 대조 %s → %s", u["request_id"], res.get("status"))
        out.append(res)
    return out


def run(rpc: Rpc, storage: Storage, providers: ProviderFor, *, worker_id: str, max_items: int = 10,
        wait_sec: float = CONTAINER_WAIT_SEC, poll_sec: float = CONTAINER_POLL_SEC) -> dict[str, Any]:
    verified = verify_accounts(rpc, providers)
    published = []
    for _ in range(max_items):
        got = rpc("drinks_claim_publication", {"worker_id": worker_id}) or {}
        req = got.get("request")
        if not req:
            break
        log.info("drinks: 발행 %s 시작(%s)", req["request_id"], req["post_type"])
        res = publish_one(req, rpc, storage, providers, wait_sec=wait_sec, poll_sec=poll_sec)
        log.info("drinks: 발행 %s → %s", req["request_id"], (res or {}).get("status"))
        published.append({"request_id": req["request_id"], **(res or {})})
    return {"verified": verified, "published": published, "reconciled": reconcile(rpc, providers)}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="주류 공장 인스타 발행 워커")
    ap.add_argument("--max", type=int, default=10)
    args = ap.parse_args(argv)
    res = run(supabase_rpc(), Storage(), provider_for, worker_id=config.WORKER_ID, max_items=args.max)
    bad = [r for r in res["published"] if r.get("status") in ("unknown", "lease_lost")]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
