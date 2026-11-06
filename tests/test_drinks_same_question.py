"""비슷한 질문 묶기(2026-11-06) — engine.drinks_discover.same_question · scripts/drinks_merge_candidates.py. 순수 로직, DB·API 없음."""

from __future__ import annotations

import itertools

import pytest

from engine import drinks_discover as dd
from scripts import drinks_merge_candidates as mc

SAKE = ["사케 유통기한 은?", "22년도에 받은 사케 유통기한 이 있나요?", "사케 유통기한 이 어떻게 될까요?"]
WHISKY = ["위스키 는 정말 유통기한 이 없을까?", "개봉 한 위스키 몇 년까지 괜찮을까?", "개봉 후 위스키 , 오래두면 맛이 변할까?"]


def _groups(qs: list[str]) -> list[set[str]]:
    out: list[set[str]] = []
    for q in qs:
        g = next((g for g in out if any(dd.same_question(q, o) for o in g)), None)
        (g.add(q) if g is not None else out.append({q}))
    return out


def test_operator_examples_merge_into_exactly_two_groups():
    groups = _groups(SAKE + WHISKY)
    assert sorted(map(sorted, groups)) == sorted([sorted(SAKE), sorted(WHISKY)])
    for a, b in itertools.combinations(SAKE, 2):
        assert dd.same_question(a, b)
    for a, b in itertools.combinations(WHISKY, 2):
        assert dd.same_question(a, b)


@pytest.mark.parametrize("a,b", [
    ("위스키 개봉 후 냉장 보관", "막걸리 유통기한"),
    ("하이볼 만들어도 괜찮을까?", "위스키 유통기한"),
    ("사케 정미율 낮으면 좋을까", "사케 유통기한"),
    ("위스키 개봉 후 냉장 보관 해야 하나요?", "위스키 유통기한"),      # 같은 칸이라도 주제가 다르다(보관법 ↔ 유통기한)
    ("위스키 상온 보관 괜찮을까?", "위스키 유통기한 이 있나요?"),      # '괜찮을' 은 약한 낱말 — 보관법이 이긴다
    ("준마이 다이긴조 차이", "준마이 혼조 차이"),                       # 칸 낱말(준마이·차이)만 겹친다
])
def test_different_questions_stay_separate(a, b):
    assert not dd.same_question(a, b)
    assert not dd.same_question(b, a)


def test_cross_category_never_merges():
    qs = SAKE + WHISKY + ["막걸리 유통기한 은?", "막걸리 유통기한 이 어떻게 될까요?"]
    for a, b in itertools.combinations(qs, 2):
        if dd.question_cell(a)[0] != dd.question_cell(b)[0]:
            assert not dd.same_question(a, b), (a, b)
    # 문장이 주종 이름만 다르고 똑같아도 묶지 않는다
    assert not dd.same_question("사케 유통기한 이 어떻게 될까요?", "위스키 유통기한 이 어떻게 될까요?")
    assert dd.same_question("사케 유통기한", "사케 유통기한")   # 같은 주종이면 묶인다(위 거부가 규칙이 꺼져서가 아님을 확인)


def test_unknown_category_never_merges():
    assert not dd.same_question("유통기한 이 어떻게 될까요?", "유통기한 은?")


def test_generic_cell_needs_a_strong_shared_word():
    # 보관 밖의 칸: 내용 낱말 겹침. 칸 낱말·주종 이름·질문 끝말은 세지 않는다.
    assert dd.content_words("사케 유통기한 이 어떻게 될까요?") == set()
    assert dd.same_question("준마이 다이긴조 맛 차이 있나요?", "준마이 다이긴조 차이 궁금해요")


def test_cluster_merges_same_question_items_within_a_cell():
    items = [{"id": str(i), "title": q, "questions": [q], "platform": "naver_cafe", "channel_name": f"c{i}"}
             for i, q in enumerate(SAKE + WHISKY + ["위스키 개봉 후 냉장 보관 해야 하나요?"])]
    groups = dd.cluster(items)
    assert sorted(len(g) for g in groups) == [1, 3, 3]


def test_suggest_adds_to_open_candidate_when_same_question():
    calls = []

    def rpc(fn, p):
        calls.append((fn, p))
        if fn == "drinks_discovery_backlog":
            if sum(1 for f, _ in calls if f == fn) == 1:
                return {"items": [{"id": "i2", "title": SAKE[2], "questions": [SAKE[2]], "platform": "naver_cafe", "channel_name": "b"}],
                        "candidates": [{"id": "c1", "key_question": SAKE[0], "version": 1,
                                        "items": [{"id": "i1", "title": SAKE[0], "questions": [SAKE[0]], "platform": "naver_cafe",
                                                   "channel_name": "a"}]}],
                        "topics": []}
            return {"candidates": []}
        return {"candidate_id": p.get("candidate_id") or "new"}

    out = dd.suggest_candidates(rpc)
    assert out["added"] == 1 and out["new"] == 0
    sug = [p for f, p in calls if f == "drinks_suggest_candidate"]
    assert sug[0]["candidate_id"] == "c1"


def _cand(cid, q, items, score, created="2026-11-01"):
    return {"id": cid, "key_question": q, "version": 3, "status": "suggested", "items": items,
            "provisional_score": score, "created_at": created}


def test_merge_script_picks_survivor_and_dry_run_writes_nothing(tmp_path, capsys):
    cands = [_cand("a" * 8, SAKE[0], 1, 60), _cand("b" * 8, SAKE[1], 3, 40), _cand("c" * 8, SAKE[2], 3, 55),
             _cand("d" * 8, WHISKY[0], 2, 50), _cand("e" * 8, WHISKY[1], 2, 50, "2026-10-01"),
             _cand("f" * 8, "위스키 개봉 후 냉장 보관 해야 하나요?", 1, 30)]
    groups = mc.group_candidates(cands)
    multi = sorted((g for g in groups if len(g) > 1), key=lambda g: g[0]["id"])
    assert [g[0]["id"] for g in multi] == ["c" * 8, "e" * 8]      # 자료 수 동률이면 점수, 점수 동률이면 먼저 만든 것
    assert len(multi[0]) == 3 and len(multi[1]) == 2

    def boom(fn, p):
        raise AssertionError("미리보기는 쓰면 안 된다")

    out = tmp_path / "preview.md"
    assert mc.main(["--out", str(out)], rpc=boom, candidates=cands) == 0
    text = out.read_text(encoding="utf-8")
    assert "합쳐질 후보 3건" in text and "합친 뒤 3건" in text and "★" in text
    assert "미리보기" in capsys.readouterr().out


def test_merge_script_apply_requires_yes_and_calls_the_app_rpc():
    cands = [_cand("a" * 8, SAKE[0], 1, 60), _cand("b" * 8, SAKE[1], 3, 40)]
    calls = []
    assert mc.main(["--apply"], rpc=lambda f, p: calls.append((f, p)), candidates=cands) == 2
    assert calls == []
    assert mc.main(["--apply", "--yes"], rpc=lambda f, p: calls.append((f, p)) or {}, candidates=cands) == 0
    assert calls == [("drinks_candidate_action", {"candidate_id": "a" * 8, "expected_version": 3, "action": "merge",
                                                  "into_candidate_id": "b" * 8, "reason": mc.MERGE_REASON})]


def test_merge_script_without_env_explains_what_is_missing(monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert mc.main([]) == 2
    assert "SUPABASE_SERVICE_KEY" in capsys.readouterr().err
