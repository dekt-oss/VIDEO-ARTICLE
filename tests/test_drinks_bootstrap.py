"""주류 공장 - 질문 일괄 등록 스크립트(scripts/drinks_bootstrap_topics.py)와 질문 유형(0058) 설정 대조. 네트워크·DB 없음.

DB 동작(복사·가점·검증)은 web/lib/drinks/signals.db.test.ts · publish.db.test.ts 가 PGlite 로 본다.
"""
import pathlib
import re

import pytest

from engine import config
from engine import drinks_strategy as ds
from engine.drinks_collect import DbError
from scripts import drinks_bootstrap_topics as bt

ROOT = pathlib.Path(__file__).resolve().parents[1]
CSV = """category,title,question,lane,question_kind,note
sake,개봉한 사케 보관,개봉한 사케를 냉장고에 두면 며칠까지 마셔도 되나요?,evergreen,storage,보관 질문
whisky,싱글몰트와 블렌디드,싱글몰트와 블렌디드는 무엇이 다른가요?,,selection,
사케,중복 질문,개봉한 사케를  냉장고에 두면 며칠까지 마셔도 되나요,상시,storage,표기만 다른 같은 질문
전통주|사케,두 주종,막걸리와 사케는 같은 술인가요?,reader_question,,
,,,,,
"""


def test_template_csv_parses_cleanly_with_three_example_rows():
    plan = bt.parse_csv((ROOT / "docs" / "drinks-bootstrap" / "questions_template.csv").read_text(encoding="utf-8"))
    assert not plan.errors and not plan.skipped and len(plan.rows) == 3
    assert {r.question_kind for r in plan.rows} <= set(config.DRINKS_QUESTION_KINDS)


def test_parse_normalizes_aliases_dedupes_same_question_and_skips_blank_rows():
    plan = bt.parse_csv(CSV)
    assert not plan.errors
    assert [r.title for r in plan.rows] == ["개봉한 사케 보관", "싱글몰트와 블렌디드", "두 주종"]
    assert len(plan.skipped) == 1 and plan.skipped[0][0] == 4, plan.skipped
    assert "중복" in plan.skipped[0][1]
    by = {r.title: r for r in plan.rows}
    assert by["싱글몰트와 블렌디드"].lane == "evergreen", "lane 을 비우면 evergreen"
    assert by["두 주종"].categories == ["sake", "traditional"] and by["두 주종"].question_kind == "general"
    assert by["개봉한 사케 보관"].payload() == {"title": "개봉한 사케 보관", "question": "개봉한 사케를 냉장고에 두면 며칠까지 마셔도 되나요?",
                                            "categories": ["sake"], "lane": "evergreen", "question_kind": "storage", "reader_value": "보관 질문"}
    assert "reader_value" not in by["싱글몰트와 블렌디드"].payload(), "메모가 없으면 칸을 보내지 않는다"


def test_parse_reports_row_errors_instead_of_guessing():
    plan = bt.parse_csv("category,title,question,lane,question_kind,note\n"
                        "soju,t,질문입니다 정말로?,evergreen,,\n"
                        "sake,,질문,evergreen,,\n"
                        "sake,t,질문 하나 더?,never,,\n"
                        "sake,t,질문 둘 더?,evergreen,mood,\n")
    assert [ln for ln, _ in plan.errors] == [2, 3, 4, 5] and not plan.rows
    assert bt.parse_csv("title,question\nx,y\n").errors[0][0] == 1, "필수 열이 없으면 첫 줄 오류"


def test_dry_run_is_default_and_never_calls_rpc(tmp_path, capsys, monkeypatch):
    f = tmp_path / "q.csv"
    f.write_text(CSV, encoding="utf-8")
    called = []
    assert bt.main([str(f)], rpc=lambda fn, p: called.append(fn)) == 0
    out = capsys.readouterr().out
    assert called == [] and "미리보기" in out and "등록 대상 3건" in out and "중복 건너뜀 1건" in out
    assert bt.main([str(f), "--dry-run"], rpc=lambda fn, p: called.append(fn)) == 0 and called == []


def test_apply_needs_env_and_registers_through_the_dashboards_rpc(tmp_path, capsys, monkeypatch):
    f = tmp_path / "q.csv"
    f.write_text(CSV, encoding="utf-8")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert bt.main([str(f), "--apply"]) == 2, "키가 없으면 아무것도 하지 않고 멈춘다"
    calls = []

    def fake(fn, p):
        calls.append((fn, p))
        if p["title"] == "싱글몰트와 블렌디드":
            raise DbError("duplicate_suggested", "같은 소재가 이미 있습니다")
        return {"topic_id": f"t{len(calls)}"}
    assert bt.main([str(f), "--apply"], rpc=fake) == 0
    out = capsys.readouterr().out
    assert [c[0] for c in calls] == ["drinks_create_topic"] * 3
    assert all("confirm_not_duplicate" not in p for _, p in calls), "DB 중복은 사람이 정한다 - 우리가 '다른 소재'라고 우기지 않는다"
    assert "등록됨 2건, 이미 있어 건너뜀 1건, 실패 0건" in out


def test_apply_refuses_when_csv_has_errors(tmp_path):
    f = tmp_path / "bad.csv"
    f.write_text("category,title,question\nsoju,t,q\n", encoding="utf-8")
    called = []
    assert bt.main([str(f), "--apply"], rpc=lambda fn, p: called.append(fn)) == 1 and called == []


def test_apply_reports_other_failures_without_stopping_the_rest(tmp_path):
    f = tmp_path / "q.csv"
    f.write_text(CSV, encoding="utf-8")

    def fake(fn, p):
        if p["title"] == "두 주종":
            raise DbError("invalid_input", "주종을 다시 고르세요")
        return {"topic_id": "ok"}
    assert bt.main([str(f), "--apply"], rpc=fake) == 1


# ── 질문 유형 목록: 파이썬 설정 = SQL 체크 = 전략 라벨 ──

def _sql() -> str:
    return (ROOT / "supabase" / "migrations" / "0058_drinks_topic_signals.sql").read_text(encoding="utf-8")


def test_question_kinds_match_between_config_sql_and_strategy_labels():
    m = re.search(r"drink_topics_question_kind_ck\s+check \(question_kind in \(([^)]*)\)\)", _sql())
    assert m, "체크 제약을 찾지 못함"
    assert tuple(re.findall(r"'([a-z]+)'", m.group(1))) == config.DRINKS_QUESTION_KINDS
    assert set(config.DRINKS_QUESTION_KINDS) <= set(ds.VALUE_KO), "전략 화면 라벨이 빠진 질문 유형"
    # 신호 우선순위: SQL 함수와 같은 순서
    pick = re.search(r"unnest\(array\[([^\]]*)\]\) with ordinality", _sql())
    assert tuple(re.findall(r"'([a-z_]+)'", pick.group(1))) == config.DRINKS_QUESTION_KIND_PRIORITY
    assert set(config.DRINKS_QUESTION_KIND_PRIORITY) <= set(config.DRINKS_QUESTION_KINDS)
    # 후보 신호 목록(0052)에 있는 이름만 우선순위에 쓴다
    sig = re.search(r"signals <@ array\[([^\]]*)\]", (ROOT / "supabase" / "migrations" / "0052_drinks_discovery.sql").read_text(encoding="utf-8"))
    assert set(config.DRINKS_QUESTION_KIND_PRIORITY) <= set(re.findall(r"'([a-z_]+)'", sig.group(1)))


def test_every_replaced_function_is_covered_by_the_search_path_loop():
    sql = _sql()
    assert "alter function %s set search_path = public, pg_temp" in sql, "0056 과 같은 반복문이 있어야 한다"
    assert sql.index("alter function %s set search_path") > sql.rindex("create or replace function"), "함수 정의 뒤에 고정해야 지워지지 않는다"
    assert "되돌리기" in sql.split("alter table drink_topics add column")[0]


# ── 전략: 질문 유형 묶음 ──

LIM = {"strategy_bucket": "72h", "strategy_min_group": 3, "strategy_min_total": 6, "strategy_max_step": 0.2, "strategy_max_lift": 0.5}


def _p(kind, saved, **kw):
    d = {"categories": ["sake"], "post_type": "carousel", "lane": "evergreen", "slot": "evening",
         "values": {"reach": 1000, "saved": saved, "shares": 0}}
    if kind is not None:
        d["question_kind"] = kind
    return {**d, **kw}


def test_strategy_proposal_groups_by_question_kind_with_the_same_thresholds():
    posts = [_p("storage", 80), _p("storage", 90), _p("storage", 70), _p("debate", 10), _p("debate", 12), _p("debate", 8),
             _p("howto", 50)]
    out = ds.propose({"limits": LIM, "active": {"id": "v0", "weights": {}}, "posts": posts})
    assert out["sufficient"] and out["sample_total"] == 7
    w = out["weights"]["question_kind"]
    assert w["storage"] == 0.2 and w["debate"] == -0.2, "한 번에 ±0.2"
    assert "howto" not in w and out["basis"]["groups"]["question_kind"]["howto"]["enough"] is False, "표본 1편 묶음은 그대로"
    assert "질문 유형 보관 +0.00→+0.20" in out["summary_ko"]
    assert ds.DIM_KO["question_kind"] == "질문 유형"


def test_strategy_without_question_kind_data_does_not_send_an_unknown_dimension():
    """0058 적용 전 DB 는 question_kind 를 모른다 - 입력에 그 칸이 없으면 제안 가중치에도 넣지 않는다."""
    posts = [_p(None, 80)] * 6
    out = ds.propose({"limits": LIM, "active": {"id": "v0", "weights": {"category": {}}}, "posts": posts})
    assert "question_kind" not in out["weights"]
    v0 = {d: {} for d in ("category", "post_type", "lane", "slot")}
    assert set(ds.propose({"limits": LIM, "active": {"id": "v0", "weights": v0}, "posts": posts})["weights"]) == set(v0)
    # 이미 그 칸이 있는 전략이면 그대로 둔다
    keep = ds.propose({"limits": LIM, "active": {"id": "v1", "weights": {"question_kind": {"storage": 0.1}}}, "posts": posts})
    assert keep["weights"]["question_kind"] == {"storage": 0.1}


@pytest.mark.parametrize("bad", ["", "   "])
def test_norm_question_ignores_spacing_and_punctuation(bad):
    assert bt.norm_question(bad) == ""
    assert bt.norm_question("왜 비싼가요?") == bt.norm_question("왜  비싼가요")
