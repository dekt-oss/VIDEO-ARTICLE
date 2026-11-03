"""카드뉴스 릴스 음원 시험 게시 — 운영자 승인 뒤 한 명령으로 1건만 올린다(총괄 §4-2·§6 3단계). docs/deviation-drinks-stage3-4.md

    python -m scripts.card_reel_trial_publish            # 보기만: 음원이 붙은 카드 릴스 발행 요청을 찾아 내용·금액·게시 성격을 보여 준다(DB 읽기만, 게시 0)
    python -m scripts.card_reel_trial_publish --yes      # 그 1건을 게시 워커(engine/drinks_publish.run)로 올린다. ★ 공개 게시다 — 아래 경고를 읽고 누른다
    python -m scripts.card_reel_trial_publish --yes --allow-fake   # 가짜 공급자 계정(connection=fake)도 허용(리허설)

★ 인스타 Graph API 로 올리는 릴스는 **비공개로 올릴 수 없다**(게시 API 에 공개 범위 칸이 없다). 이 명령은 공개 게시다. 시험이라도 팔로워에게 보인다.
  올린 뒤 지우려면 앱에서 직접 지운다(API 삭제 불가 — memory/drinks-loop-live). 그래서 --yes 없이는 아무 것도 올리지 않는다.
★ 이 스크립트는 게시 워커 코드를 고치지 않는다. 워커의 점유 함수(drinks_claim_publication)는 예약 시각이 가장 이른 요청을 가져가므로,
  --yes 는 "지금 가져갈 요청이 바로 이 1건"일 때만 돈다. 다른 예약이 앞에 있으면 멈추고 이유를 말한다.
★ 실제 공급자는 DRINKS_IG_LIVE=1 이 있어야 켜진다(engine/providers/instagram.provider_for). 없으면 요청이 paused(provider_disabled)로 멈춘다 — 올라가지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from engine import config

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "docs" / "preview-2026-11-02" / "card-reel-trial"

CHECKLIST = [
    "앱에서 릴스가 보인다(피드·릴스 탭) — 주소: 아래 external_url",
    "음원 이름이 영상 아래에 붙어 있다(고른 음원 그대로인가, '원본 오디오'로 바뀌지 않았나)",
    "음원이 어디서 시작하는지 귀로 기록한다(시작 위치는 API 로 못 정한다 — 기획 v2 §7-2)",
    "음원 볼륨과 영상 볼륨이 설정값(기본 90/10)처럼 들리는가 — 다르면 다음 편의 기본값을 바꾼다(§7-4 귀로 판정)",
    "첫 화면 훅 제목이 위 20~25% 안에 있고 앱 UI(오른쪽 버튼·아래 캡션)에 가리지 않는다(안전 영역 340px/120px 실측)",
    "마지막 화면의 저장/보내기 한 줄이 캡션에 가리지 않는다",
    "페이지 넘김이 끊김 없이 보인다(정지 화면으로 보이는 구간이 없다)",
    "캡션이 승인한 글 그대로다",
    "표지(커버) 그림이 설정한 것인가",
    "확인한 것을 docs/deviation-drinks-stage3-4.md '음원 시험 게시 결과' 에 날짜와 함께 적는다",
]


def _rows(res: Any) -> list[dict[str, Any]]:
    return list(getattr(res, "data", None) or [])


def find_candidates(cli: Any) -> list[dict[str, Any]]:
    """음원이 붙은 릴스 발행 요청 중 승인·예약된 것. 읽기만."""
    reqs = _rows(cli.table("drink_publication_requests")
                 .select("id, topic_id, manifest_id, post_type, caption, publish_at, status, audio, audio_verified_at, account_id, approved_at, pause_code, pause_reason, cancel_requested")
                 .eq("post_type", "reel").in_("status", ["approved", "scheduled", "paused", "awaiting_approval"]).order("publish_at").limit(50).execute())
    out = []
    for r in reqs:
        if not r.get("audio"):
            continue
        man = _rows(cli.table("drink_asset_manifests").select("id, format").eq("id", r["manifest_id"]).limit(1).execute())
        fmt = man[0]["format"] if man else None
        roles = {x["role"] for x in _rows(cli.table("drink_manifest_assets").select("role").eq("manifest_id", r["manifest_id"]).execute())}
        if fmt != "carousel" or "final_video" not in roles:
            continue   # 카드 묶음(캐러셀 묶음 안의 세로 영상)만 — 설명형 영상은 이 시험이 아니다
        acc = _rows(cli.table("drink_social_accounts").select("id, display_name, connection, external_account_id, status, publish_enabled").eq("id", r["account_id"]).limit(1).execute())
        topic = _rows(cli.table("drink_topics").select("title").eq("id", r["topic_id"]).limit(1).execute())
        out.append({**r, "account": acc[0] if acc else None, "topic_title": topic[0]["title"] if topic else None, "manifest_format": fmt, "roles": sorted(roles)})
    return out


def first_claimable(cli: Any) -> Optional[dict[str, Any]]:
    """워커 점유 순서의 맨 앞(예약 시각 지났고 scheduled). 이게 우리 1건이 아니면 --yes 를 돌리지 않는다."""
    now = datetime.now(timezone.utc).isoformat()
    rows = _rows(cli.table("drink_publication_requests").select("id, post_type, publish_at, status").eq("status", "scheduled").lte("publish_at", now)
                 .order("publish_at").order("id").limit(1).execute())
    return rows[0] if rows else None


def describe(r: dict[str, Any]) -> str:
    a = r.get("audio") or {}
    acc = r.get("account") or {}
    return "\n".join([
        f"요청 {r['id']}  상태 {r['status']}  예약 {r.get('publish_at')}  {('멈춤: ' + str(r.get('pause_code'))) if r.get('pause_code') else ''}",
        f"  소재: {r.get('topic_title')}",
        f"  계정: {acc.get('display_name')} ({acc.get('connection')}, {acc.get('external_account_id')}) 상태 {acc.get('status')} 발행 스위치 {acc.get('publish_enabled')}",
        f"  음원: {a.get('title_snapshot') or a.get('audio_id')} — {a.get('artist_snapshot') or ''} · 음원 {a.get('audio_volume')} / 영상 {a.get('video_volume')} · {a.get('sync_grade')} · 재조회 {r.get('audio_verified_at') or '아직'}",
        f"  캡션: {(r.get('caption') or '')[:200]!r}",
        f"  파일: {', '.join(r.get('roles') or [])}",
    ])


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="카드뉴스 릴스 음원 시험 게시 — --yes 없이는 게시 0")
    ap.add_argument("--yes", action="store_true", help="실제 게시(공개). 운영자 승인 뒤에만")
    ap.add_argument("--allow-fake", action="store_true", help="가짜 공급자 계정도 허용(리허설)")
    ap.add_argument("--request", default=None, help="요청 id 를 지정(여럿일 때)")
    ap.add_argument("--out", default=str(PREVIEW))
    args = ap.parse_args(argv)
    from engine import db

    cli = db.client()
    cands = find_candidates(cli)
    print("★ 인스타 API 게시는 비공개로 올릴 수 없습니다 — 이 명령이 올리는 릴스는 공개 게시입니다. API 로 지울 수도 없습니다(앱에서 직접).")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if not cands:
        print("음원이 붙은 카드 릴스 발행 요청이 없습니다. 발행 화면에서 카드 묶음 → 릴스 발행안 → 음원 고르기 → 승인·예약을 먼저 하세요(0065 운영 적용 필요).")
        (out / "candidates.json").write_text(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(), "candidates": [], "published": 0,
            "note": "음원 붙은 카드 릴스 발행 요청 없음(0065 운영 미적용 상태). 게시 0."}, ensure_ascii=False, indent=1), encoding="utf-8")
        return 1
    if args.request:
        cands = [c for c in cands if c["id"] == args.request]
        if not cands:
            print("그 id 의 요청이 후보에 없습니다.")
            return 1
    for c in cands:
        print(describe(c))
    target = cands[0]
    (out / "candidates.json").write_text(json.dumps(cands, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if not args.yes:
        print("\n--yes 가 없어 게시하지 않았습니다. 올리려면 운영자 승인 뒤:")
        print(f"  DRINKS_IG_LIVE=1 python -m scripts.card_reel_trial_publish --yes --request {target['id']}")
        print("게시 뒤 앱에서 확인할 것:")
        for i, line in enumerate(CHECKLIST, 1):
            print(f"  [ ] {i}. {line}")
        return 0
    # ── 실제 게시 ──
    if len(cands) > 1 and not args.request:
        print("\n후보가 여럿입니다 — --request <id> 로 하나를 지정하세요. 게시하지 않았습니다.")
        return 2
    acc = target.get("account") or {}
    if acc.get("connection") == "fake" and not args.allow_fake:
        print("\n가짜 공급자 계정입니다. 리허설이면 --allow-fake 를 붙이세요. 게시하지 않았습니다.")
        return 2
    if acc.get("connection") != "fake" and os.getenv("DRINKS_IG_LIVE") != "1":
        print("\nDRINKS_IG_LIVE=1 이 없어 실제 공급자가 꺼져 있습니다 — 돌려도 provider_disabled 로 멈춥니다. 게시하지 않았습니다.")
        return 2
    if target["status"] != "scheduled":
        print(f"\n요청 상태가 {target['status']} 입니다(scheduled 여야 워커가 가져갑니다). 발행 화면에서 승인·예약을 먼저 하세요. 게시하지 않았습니다.")
        return 2
    head = first_claimable(cli)
    if not head or head["id"] != target["id"]:
        print(f"\n워커가 지금 가져갈 요청이 이 건이 아닙니다(맨 앞: {head['id'] if head else '없음 — 예약 시각이 아직 안 됨'}). 게시하지 않았습니다.")
        return 2
    from engine import drinks_publish as pub
    from engine.drinks_collect import supabase_rpc
    from engine.drinks_produce import Storage
    from engine.providers.instagram import provider_for

    print("\n게시합니다(1건). 공개 게시입니다.")
    res = pub.run(supabase_rpc(), Storage(), provider_for, worker_id=f"trial-{config.WORKER_ID}", max_items=1)
    (out / "publish_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    pubs = res.get("published") or []
    for p in pubs:
        print(f"결과: {p.get('request_id')} → {p.get('status')}  {p.get('external_url') or ''}  {p.get('error_code') or ''} {p.get('error_message') or ''}")
    print("\n앱에서 확인할 것(결과를 deviation 문서에 적는다):")
    for i, line in enumerate(CHECKLIST, 1):
        print(f"  [ ] {i}. {line}")
    return 0 if pubs and pubs[0].get("status") == "published" else 1


if __name__ == "__main__":
    sys.exit(main())
