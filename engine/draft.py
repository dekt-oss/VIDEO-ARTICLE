"""P1 오케스트레이터 + draft_requests 폴링 워커 (명세 5, 트리거 D4).

generate_draft: 논문 1편 → Fact Sheet → 대본/영상프롬프트 → 자기검증 → drafts 행.
poll_once: 'queued' 요청을 집어 처리하고 상태 갱신(대시보드가 요청 행을 쓰면 여기서 소비).

실행: ``python -m engine.draft``            # 큐 1회 폴링
     ``python -m engine.draft <paper_id>``  # 특정 논문 즉시 생성
"""

from __future__ import annotations

import sys
from typing import Any

from . import (attribution, config, db, factsheet, paper_evidence, paper_source,
               script_polish, scriptgen, selfcheck)
from .util import log


def generate_draft(paper: dict[str, Any]) -> dict[str, Any]:
    """3단계 파이프라인. 반환: drafts 테이블 행 dict."""
    # ★ 낙점 이후에 원문을 확보한다(설명엔진 v2 §3). 수집 때는 부르지 않는다 — 전 논문
    #   원문 확보는 저장소·시간 낭비다. 보관된 것이 있으면 재사용해 외부 호출이 0 이 된다.
    #   확보 실패는 예외가 아니라 depth=abstract_only 인 packet 으로 돌아온다: 논문 열 편 중
    #   네 편은 원문이 없고(실측 확보율 63%), 그 네 편에서 초안 생성이 멈추면 안 된다.
    packet: dict[str, Any] = {}
    if config.PAPER_SOURCE_ENABLED:
        try:
            packet = paper_source.resolve(paper)
        except Exception as exc:  # noqa: BLE001 — 확보 실패가 초안을 막지 않는다
            log.warning("원문 확보 실패(초록만으로 진행) %s: %s",
                        paper.get("external_id"), exc)
            packet = {}
    fact_sheet = factsheet.extract(
        paper.get("title") or "", paper.get("venue"), paper.get("abstract") or "",
        packet=packet,
    )
    # ★ 그리고 **코드가 대조한다.** 모델이 붙인 evidence_grade 는 자기보고라 믿지 않는다.
    #   2026-08-29 실측: 초록에 없는 "이중맹검·위약대조"가 Fact Sheet 를 통해 화면까지 갔다.
    #   화면 계약(photo_contract)은 "그림이 설명을 하는가"를 볼 뿐 "이 주장이 출처에 있는가"는
    #   보지 않는다 — 그 구멍을 여기서 막는다.
    # ★ 전문이 없으면 **초록을 원문으로 삼아** 대조한다. 확보 실패가 "검증 포기"가 되면
    #   잡을 수 있는 것도 못 잡는다 — 오늘의 사고("이중맹검·위약대조")가 정확히 그 경우다.
    verify_packet = paper_evidence.verification_packet(packet, paper.get("abstract"))
    paper_evidence.attach_evidence(fact_sheet, verify_packet)
    audit = paper_evidence.audit(fact_sheet)
    log.info("주장 대조: %s개 중 %s개 검증(판정불가 %s) depth=%s",
             audit["claims"], audit["verified"], audit["unverifiable"], audit["source_depth"])
    # ★ 출처 블록(검증 가능 메타 — LLM 아님)을 Fact Sheet에 부착. 대본은 "Fact Sheet만" 입력이므로
    #   기관/저자를 구체적으로 쓰려면 여기 담겨야 한다(환각 방지 불변식 유지).
    fact_sheet["source"] = attribution.build_source(paper)
    script = scriptgen.generate(fact_sheet)
    # 자기검증은 '나레이션'만 대상으로 한다. 이미지/영상 프롬프트는 사실주장이 아니라
    # 시각화 지시라 근거 대조 대상이 아니며, 넣으면 빨간깃발 오탐이 난다.
    # claim_ids·evidence_role 은 산문이 아니라 메타데이터라 오탐을 만들지 않고, 없으면
    # 검증관이 "이 씬이 어느 주장을 지불하는지"를 대조할 수 없다(수정명세 §4-3).
    narr_scenes = [
        {
            "scene": s["scene"],
            "narration_ko": s["narration_ko"],
            "claim_ids": s.get("claim_ids") or [],
            "evidence_role": s.get("evidence_role") or "",
        }
        for s in script["scenes"]
    ]
    plan = (script.get("video_flow") or {}).get("content_plan")
    total_sec = sum(int(s.get("duration_sec") or 0) for s in script["scenes"])
    check = selfcheck.check(fact_sheet, narr_scenes, plan, total_sec)
    # ★ 한국어가 어색하다고 찍힌 씬만 **한 번 다시 쓰게** 한다(운영자 지시 2026-09-10).
    #   ★★ 사실은 코드가 지킨다 — 숫자·단서·길이가 어긋난 교정은 버리고 원문을 둔다
    #     (`script_polish.rejection_reason`). "사실을 바꾸지 마라"는 프롬프트 문장만으로는
    #     안 막힌다는 것이 이 저장소의 반복된 실측이다.
    #   ★★★ 씬만 고치면 `script_md` 와 어긋난다 — ⑤ 지시서는 **둘 다** 입력으로 받는다.
    #     그래서 읽기용 대본에도 같은 교정을 반영한다(못 찾으면 손대지 않는다).
    before_text = {int(sc.get("scene") or 0): str(sc.get("narration_ko") or "")
                   for sc in script["scenes"]}
    polish_report = script_polish.polish(script["scenes"], check)
    if polish_report.get("applied"):
        after_text = {int(sc.get("scene") or 0): str(sc.get("narration_ko") or "")
                      for sc in script["scenes"]}
        pairs = [(before_text.get(no, ""), after_text.get(no, ""))
                 for no in polish_report["applied"]]
        script["script_md"], synced = script_polish.rewrite_script_md(
            script["script_md"], pairs)
        polish_report["script_md_synced"] = synced
        log.info("대본 다듬기: 적용 %s · 버림 %s · 대본반영 %s/%s",
                 polish_report["applied"],
                 [r["reason"] for r in polish_report.get("rejected") or []],
                 synced, len(pairs))
    check["korean_polish"] = polish_report
    # 대조 결과를 자기검증 옆에 남긴다 — 승인 화면과 로그가 같은 숫자를 본다.
    check["claim_evidence"] = audit
    check["claim_evidence_blocks"] = paper_evidence.block_reasons(fact_sheet)
    return {
        "paper_id": paper["id"],
        "fact_sheet": fact_sheet,
        "upload_title_ko": script["upload_title_ko"],  # 유튜브 업로드용 자극적 제목(한)
        "upload_title_en": script["upload_title_en"],  # 유튜브 업로드용 자극적 제목(영)
        "script_md": script["script_md"],
        "video_flow": script["video_flow"],   # 전체 세부 영상 흐름(스토리보드)
        "video_prompts": script["scenes"],    # 씬별(이미지+영상 프롬프트, 나레이션)
        "self_check": check,
    }


def process_paper(paper_id: str) -> dict[str, Any]:
    paper = db.get_paper(paper_id)
    if not paper:
        raise ValueError(f"paper 없음: {paper_id}")
    row = generate_draft(paper)
    db.upsert_draft(row)
    flagged = sum(len(s.get("unsupported", [])) for s in row["self_check"]["scenes"])
    log.info("draft 생성: paper=%s scenes=%d 빨간깃발=%d",
             paper_id, len(row["video_prompts"]), flagged)
    return row


def requested_versions(req: dict[str, Any]) -> list[str]:
    """요청 행의 `version_types` 중 **허용된 버전만**, 순서·중복 정리해서.

    ★ 웹이 이미 거르지만 여기서 또 거른다 — 큐 행은 손으로도 들어올 수 있고, 미허용 값이
      지시서 생성기까지 가면 `VERSION_GUIDANCE` 가 기본 버전으로 조용히 갈아치운다
      (2026-08-20 엣지 배포본 사고와 같은 모양).
    """
    if not config.DRAFT_CHAINS_DIRECTIVE:
        return []
    raw = req.get("version_types") or []
    if isinstance(raw, str):
        raw = [raw]
    out: list[str] = []
    for v in raw:
        s = str(v or "").strip()
        if s in config.VIDEO_VERSIONS and s not in out:
            out.append(s)
    return out


def chain_directives(paper_id: str, versions: list[str]) -> dict[str, str]:
    """초안 저장 뒤 **같은 실행에서** 버전별 지시서를 이어서 만든다 → {버전: done|error}.

    ★ 왜 여기서 하나(설계안 v2 §3): 운영자가 초안을 만들 때 버전을 고르면 초안이 끝나는 즉시
      지시서까지 와 있어야 한다. 큐에만 넣고 다음 폴링을 기다리면 하루 3번 크론에 걸려
      몇 시간이 빈다.
    ★★ 지시서 실패는 초안을 실패로 만들지 않는다. 초안은 이미 저장됐고, 지시서 요청 행만
      error 로 남아 ⑤ 에서 다시 누를 수 있다 — 지금 동선 그대로.
    """
    from . import directive as directive_mod  # 순환 import 회피 — 호출 시점에만 필요하다

    results: dict[str, str] = {}
    for v in versions:
        req_id = ""
        try:
            req_id = db.insert_directive_request(paper_id, v)
            directive_mod.process_paper(paper_id, v)
            if req_id:
                db.update_directive_request(req_id, "done")
            results[v] = "done"
        except Exception as exc:  # noqa: BLE001
            log.exception("초안→지시서 연쇄 실패 paper=%s version=%s: %s", paper_id, v, exc)
            if req_id:
                db.update_directive_request(req_id, "error", str(exc)[:500])
            results[v] = "error"
    return results


def poll_once(limit: int = 5) -> int:
    """큐 1회 폴링. 처리 건수 반환."""
    reqs = db.claim_draft_requests(limit)
    if not reqs:
        log.info("draft_requests: 대기 없음")
        return 0
    for r in reqs:
        try:
            process_paper(r["paper_id"])
            # ★ 초안이 저장된 뒤에야 지시서를 잇는다. 초안 실패면 여기까지 오지 않는다.
            versions = requested_versions(r)
            if versions:
                chained = chain_directives(r["paper_id"], versions)
                log.info("초안→지시서 연쇄: paper=%s %s", r["paper_id"], chained)
            db.update_draft_request(r["id"], "done")
        except Exception as exc:  # noqa: BLE001
            log.exception("draft 요청 실패 id=%s: %s", r["id"], exc)
            db.update_draft_request(r["id"], "error", str(exc))
    return len(reqs)


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1:
            process_paper(sys.argv[1])
        else:
            poll_once()
    except Exception as exc:
        log.exception("draft 실패: %s", exc)
        sys.exit(1)
