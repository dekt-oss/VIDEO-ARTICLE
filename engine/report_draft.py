"""PF1 오케스트레이터 + report_draft_requests 폴링 워커 (명세 §5).

generate_report_draft: 리포트 1건 → Fact Sheet → 대본 → 자기검증 → 컴플라이언스 게이트 → report_drafts 행.
논문 draft.py 흐름 미러 + 컴플라이언스 게이트 4단계.

실행: ``python -m engine.report_draft``              # 큐 1회 폴링
     ``python -m engine.report_draft <report_id>``  # 특정 리포트 즉시 생성
"""

from __future__ import annotations

import sys
from typing import Any

from . import (
    report_attribution,
    report_compliance,
    report_db,
    report_factsheet,
    report_reasoning,
    report_source,
    report_evidence,
    report_scriptgen,
    report_selfcheck,
)
from . import config, script_polish, script_revision
from .util import log


def revalidate_facts(fact_sheet: dict[str, Any], report: dict[str, Any]) -> None:
    """저장된 원문으로 number_facts 의 validation 을 **다시 계산**한다(제자리 수정).

    ★ 왜 필요한가: hard_blocks 는 `validation.period_match` 같은 **저장된** 판정을 읽는다.
      재검사가 게이트만 다시 돌리고 validation 은 그대로 두면, 검증기 코드를 고쳐도 이미
      만들어진 초안에는 영영 반영되지 않는다 — 실측으로 그랬다. 기간 표기 판정을 고친 뒤
      재검사를 돌렸는데 `number_without_period` 3건이 그대로 남았다.

    원문은 보관된 것을 읽는다(report_source.resolve 가 doc_hash 로 재사용) — 재검사가
    ARIA 를 다시 부르지 않는다. 원문이 없으면 조용히 넘어간다(검증 못 함 = None 유지).
    """
    if not fact_sheet.get("number_facts"):
        return
    try:
        packet = report_source.resolve(report, store=False)
    except Exception as exc:  # noqa: BLE001
        log.warning("재검사: 원문 조회 실패 — validation 을 그대로 둔다: %s", exc)
        return
    report_evidence.attach_evidence(fact_sheet, packet)


def build_evidence_block(fact_sheet: dict[str, Any], script: dict[str, Any]) -> dict[str, Any]:
    """v3 §5-3·§6 근거·논증 게이트 결과. 초안 생성과 [재검사] 가 **같은 함수**를 쓴다.

    ★ 이 함수를 뽑아낸 이유: 예전 주석은 "compliance 앞에 둬서 재검사에도 얹힌다"고 적혀
      있었지만 `recheck_compliance` 는 report_evidence 를 한 번도 부르지 않았다(적대적 리뷰).
      대본을 고치고 재검사를 눌러도 근거 경고가 옛날 것으로 남아 있었다.
    """
    plan = script.get("story_plan") or {}
    block = report_evidence.build_block(fact_sheet, str(plan.get("content_profile") or ""))
    block["story_warnings"] = report_evidence.validate_story_plan(plan, fact_sheet)
    block["density_warnings"] = report_evidence.validate_text_density(script.get("scenes") or [])
    return block


def generate_report_draft(report: dict[str, Any], instruction: str = "") -> dict[str, Any]:
    """4단계 파이프라인(초안 3단계 + 컴플라이언스 게이트). 반환: report_drafts 행 dict.

    instruction: ④ 화면에서 운영자가 적은 세부 수정 요청("리스크를 더 강조" 등). 큐가
      유일한 전달 통로다(0038) — 예전에는 화면에 입력칸만 있고 값이 버려졌다.
      환각 방지 불변식은 그대로다: 지시는 **표현 방향**만 바꾸고, 화면에 나가는 수치·주장은
      Fact Sheet 안에서만 나온다(report_scriptgen.script_user_prompt 가 못박는다).
    """
    # ★ packet 을 받아 두는 이유(지시서 §4-2): 대본 단계도 원문 전문을 받아야 한다. 추출이
    #   이미 확보한 것을 넘겨받아 쓴다 — 초안이 report_source.resolve 를 다시 부르면 같은 편의
    #   추출과 초안이 서로 다른 원문을 볼 여지가 생긴다.
    packet: dict[str, Any] = {}
    fact_sheet = report_factsheet.extract(report, packet_out=packet)
    # 출처 블록(검증 가능 메타 — LLM 아님)을 Fact Sheet에 부착(환각 방지 불변식 + 출처 귀속).
    fact_sheet["source"] = report_attribution.build_source(report)
    # ★ 논증 단위는 **대본보다 먼저** 만든다(설명엔진 v2 D2). 대본 뒤에 논리를 끼워 맞추면
    #   이미 쓴 문장을 정당화하는 사슬이 나온다 — 그건 논증이 아니라 사후 변명이다.
    #   실패해도 빈 블록으로 내려간다(품질 계층이지 필수 경로가 아니다).
    reasoning = report_reasoning.build(fact_sheet, packet)
    script = report_scriptgen.generate(fact_sheet, instruction, packet=packet,
                                       reasoning=reasoning)
    # 자기검증은 나레이션만 대상(이미지/영상 프롬프트는 시각화 지시라 근거 대조 대상 아님).
    # ★ scene_role 을 반드시 함께 넘긴다 — 여기서 빠뜨리면 §5-4 면제가 검증관에 도달하지 못해
    #   훅·마무리 오탐이 그대로 남는다(이 깎는 지점이 면제 배선의 급소다).
    narr_scenes = [
        {"scene": s["scene"], "scene_role": s.get("scene_role", ""),
         "narration_ko": s["narration_ko"]}
        for s in script["scenes"]
    ]
    self_check = report_selfcheck.check(fact_sheet, narr_scenes)
    # ★ 한국어가 어색하다고 찍힌 씬만 **한 번 다시 쓰게** 한다(운영자 지시 2026-09-10 —
    #   논문 라인 `draft.py` 와 같은 배선). 사실은 코드가 지킨다: 숫자·뜻 갈래·줄기 보존율이
    #   어긋난 교정은 버리고 원문을 둔다. 읽기용 대본(script_md)에도 같은 교정을 반영한다 —
    #   ⑤ 지시서는 둘 다 입력으로 받는다.
    # ★★ **재검사(recheck_compliance)에서는 부르지 않는다.** 거기 대본은 운영자가 손으로 고친
    #   것이라 기계가 다시 다듬으면 운영자의 말을 덮어쓴다. 새로 만들 때만 다듬는다.
    before_text = {int(sc.get("scene") or 0): str(sc.get("narration_ko") or "")
                   for sc in script["scenes"]}
    polish_report = script_polish.polish(script["scenes"], self_check)
    if polish_report.get("applied"):
        after_text = {int(sc.get("scene") or 0): str(sc.get("narration_ko") or "")
                      for sc in script["scenes"]}
        script["script_md"], synced = script_polish.rewrite_script_md(
            script["script_md"],
            [(before_text.get(no, ""), after_text.get(no, "")) for no in polish_report["applied"]])
        polish_report["script_md_synced"] = synced
        log.info("리포트 대본 다듬기: 적용 %s · 버림 %s · 대본반영 %s",
                 polish_report["applied"],
                 [r["reason"] for r in polish_report.get("rejected") or []], synced)
    self_check["korean_polish"] = polish_report
    evidence = build_evidence_block(fact_sheet, script)
    # ★ 컴플라이언스 게이트(3층). blocked=True 면 대시보드가 승인 잠금.
    compliance = report_compliance.check(
        fact_sheet, script, self_check, broker=report.get("broker") or "",
    )
    return {
        "report_id": report["id"],
        "fact_sheet": fact_sheet,
        "upload_title_ko": script["upload_title_ko"],
        "upload_title_en": script["upload_title_en"],
        "script_md": script["script_md"],
        "video_flow": script["video_flow"],
        "story_plan": script.get("story_plan") or {},
        # ★ 논증 단위(0042). claim_chain 을 대체하지 않고 나란히 저장한다 — 근거 게이트가
        #   claim_chain 을 이미 참조하고 있고, 둘은 서로 다른 것을 담는다(주장 순서 vs 인과 단계).
        "financial_reasoning": reasoning,
        "scenes": script["scenes"],
        "self_check": self_check,
        "evidence": evidence,
        "compliance": compliance,
        # ★ 이 대본이 방금 검증을 받았다는 표식(PR #94 후속 P1-3). ④ 화면이 이 값과 현재
        #   대본의 지문을 비교해 "검증 이후 수정됨"을 알린다.
        "validated_script_hash": script_revision.fingerprint(script["script_md"]),
    }


def process_report(report_id: str, instruction: str = "") -> dict[str, Any]:
    report = report_db.get_report(report_id)
    if not report:
        raise ValueError(f"report 없음: {report_id}")
    row = generate_report_draft(report, instruction)
    report_db.upsert_report_draft(row)
    flagged = len(row["compliance"]["rule_flags"])
    log.info("report_draft 생성: report=%s scenes=%d 컴플라이언스플래그=%d blocked=%s 지시=%s",
             report_id, len(row["scenes"]), flagged, row["compliance"]["blocked"],
             (instruction[:40] + "…") if len(instruction) > 40 else (instruction or "없음"))
    return row


def recheck_compliance(report_id: str) -> dict[str, Any]:
    """편집된 대본으로 **전체를 다시 검증**한다([재검사] 버튼). Fact Sheet 재생성은 안 한다.

    ★ 2026-08-20 (PR #94 후속 리뷰 P1-2) — 예전에는 두 군데가 옛것이었다:
      ① 저장된 `self_check` 를 **그대로 재사용**했다 → 대본을 고쳐도 "근거 불충분 씬" 표시가
         고치기 전 판정이었다.
      ② 저장된 `scenes` 로 근거·밀도를 계산했다 → ④ 는 `script_md` 만 저장하므로, 고친 문장이
         아니라 **옛 문장**이 검사 대상이었다.
      이제 편집된 대본으로 씬을 먼저 맞추고(script_revision.sync_scenes), 그 위에서 자기검증을
      **다시 돌린다**. 그래야 self_check·evidence·compliance 셋이 같은 대본을 본다.
    """
    draft = report_db.get_report_draft(report_id)
    if not draft:
        raise ValueError(f"report_draft 없음: {report_id}")
    report = report_db.get_report(report_id) or {}
    fact_sheet = draft.get("fact_sheet") or {}
    script_md = draft.get("script_md") or ""
    # ① 편집된 대본으로 씬을 맞춘다(근거·역할·길이는 보존, LLM 호출 없음).
    scenes = script_revision.sync_scenes(draft.get("scenes") or [], script_md)
    script = {
        "script_md": script_md,
        "scenes": scenes,
        "story_plan": draft.get("story_plan") or {},
    }
    # ② 자기검증을 **다시 돌린다**(재사용 금지). 면제 배선을 위해 scene_role 을 함께 넘긴다.
    narr_scenes = [
        {"scene": s.get("scene"), "scene_role": s.get("scene_role", ""),
         "narration_ko": s.get("narration_ko") or ""}
        for s in scenes
    ]
    self_check = report_selfcheck.check(fact_sheet, narr_scenes)
    compliance = report_compliance.check(
        fact_sheet, script, self_check, broker=report.get("broker") or "",
    )
    # ★ 근거 게이트도 함께 다시 돈다 — 대본을 고쳤으면 밀도·논증 경고도 달라져야 한다.
    #   validation 부터 다시 계산한다(게이트가 저장된 판정을 읽으므로 이걸 빼면 검증기 수정이
    #   기존 초안에 영영 안 닿는다).
    revalidate_facts(fact_sheet, report)
    evidence = build_evidence_block(fact_sheet, script)
    # ③ 맞춘 씬·새 자기검증·지문을 함께 저장한다. 지문이 없으면 ⑤ 가 "이 씬이 지금 대본의
    #    것인지"를 알 수 없고, ④ 화면도 "검증 이후 수정됨"을 표시할 수 없다.
    report_db.update_report_draft_compliance(
        report_id, compliance, evidence, fact_sheet,
        scenes=scenes, self_check=self_check,
        validated_script_hash=script_revision.fingerprint(script_md))
    log.info("report 컴플라이언스 재검사: report=%s blocked=%s 근거경고=%d",
             report_id, compliance["blocked"],
             len(evidence["block_reasons"]) + len(evidence["warnings"]))
    return compliance


def requested_versions(req: dict[str, Any]) -> list[str]:
    """요청 행의 `version_types` 중 허용된 버전만(논문 라인 draft.requested_versions 미러)."""
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


def chain_directives(report_id: str, versions: list[str]) -> dict[str, str]:
    """초안 저장 뒤 같은 실행에서 버전별 리포트 지시서를 이어서 만든다 → {버전: done|error}.

    지시서 실패는 초안을 실패로 만들지 않는다(논문 라인 draft.chain_directives 와 같은 계약).
    """
    from . import report_directive  # 순환 import 회피

    results: dict[str, str] = {}
    for v in versions:
        req_id = ""
        try:
            req_id = report_db.insert_report_directive_request(report_id, v)
            report_directive.process_report(report_id, v)
            if req_id:
                report_db.update_report_directive_request(req_id, "done")
            results[v] = "done"
        except Exception as exc:  # noqa: BLE001
            log.exception("리포트 초안→지시서 연쇄 실패 report=%s version=%s: %s", report_id, v, exc)
            if req_id:
                report_db.update_report_directive_request(req_id, "error", str(exc)[:500])
            results[v] = "error"
    return results


def poll_once(limit: int = 5) -> int:
    """큐 1회 폴링. 처리 건수 반환.

    ★ mode 로 두 가지를 나른다(0035): 'draft' = 초안 전체 생성, 'recheck' = 편집된 대본으로
      컴플라이언스·근거 게이트만 재실행. 재검사가 여기로 온 이유는 근거 게이트 재계산이
      recheck_compliance 에만 있고 엣지에는 없기 때문이다 — 엣지로 보내면 대본을 고쳐도
      근거 경고가 옛날 것으로 남는다.
    """
    reqs = report_db.claim_report_draft_requests(limit)
    if not reqs:
        log.info("report_draft_requests: 대기 없음")
        return 0
    for r in reqs:
        mode = str(r.get("mode") or "draft")
        try:
            if mode == "recheck":
                recheck_compliance(r["report_id"])
            else:
                process_report(r["report_id"], str(r.get("instruction") or ""))
                # ★ 초안이 저장된 뒤 같은 실행에서 지시서를 잇는다(0046, 논문 라인 draft.py 미러).
                #   재검사(recheck)에서는 잇지 않는다 — 운영자가 손으로 고친 대본을 기계가
                #   새 지시서로 덮어쓰면 안 된다.
                versions = requested_versions(r)
                if versions:
                    log.info("리포트 초안→지시서 연쇄: report=%s %s",
                             r["report_id"], chain_directives(r["report_id"], versions))
            report_db.update_report_draft_request(r["id"], "done")
        except Exception as exc:  # noqa: BLE001
            log.exception("report_draft 요청 실패 id=%s mode=%s: %s", r["id"], mode, exc)
            report_db.update_report_draft_request(r["id"], "error", str(exc))
    return len(reqs)


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1:
            process_report(sys.argv[1], " ".join(sys.argv[2:]))
        else:
            poll_once()
    except Exception as exc:  # noqa: BLE001
        log.exception("report_draft 실패: %s", exc)
        sys.exit(1)
