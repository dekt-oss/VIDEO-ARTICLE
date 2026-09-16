"""drafts.updated_at 은 대본 내용이 바뀔 때만 오른다 (0048, 2026-09-11 리뷰).

updated_at 의 유일한 쓰임새는 "지시서가 옛 대본 기준인가"(web/lib/work/decision.ts::isStale)다.
제목만 저장하거나 리포트 [재검사]가 compliance 를 쓰는 것으로 지시서가 낡은 것으로 뜨면
주 버튼이 유료 [지시서 재생성]으로 바뀌고 승인이 잠긴다. 트리거가 보는 칸을 못박는다.
"""
from pathlib import Path
import re

MIG = Path(__file__).resolve().parents[1] / "supabase" / "migrations" / "0048_updated_at_content_only.sql"


def _fn_body(sql: str, name: str) -> str:
    m = re.search(rf"function {name}\(\).*?\$\$(.*?)\$\$", sql, re.S)
    assert m, name
    return m.group(1)


def test_paper_trigger_watches_script_and_scenes_only():
    body = _fn_body(MIG.read_text(encoding="utf-8"), "drafts_touch_updated_at")
    assert "new.script_md is distinct from old.script_md" in body
    assert "new.video_prompts is distinct from old.video_prompts" in body
    for col in ("upload_title", "self_check", "fact_sheet"):
        assert col not in body, col


def test_report_trigger_watches_script_only():
    # 재검사가 scenes 를 대본에 다시 맞추는 것은 낡음이 아니다(scenes_match_script).
    body = _fn_body(MIG.read_text(encoding="utf-8"), "report_drafts_touch_updated_at")
    assert "new.script_md is distinct from old.script_md" in body
    for col in ("scenes", "compliance", "evidence", "self_check", "fact_sheet"):
        assert col not in body, col


def test_explicit_updated_at_still_respected():
    sql = MIG.read_text(encoding="utf-8")
    for name in ("drafts_touch_updated_at", "report_drafts_touch_updated_at"):
        assert "new.updated_at is not distinct from old.updated_at" in _fn_body(sql, name)
