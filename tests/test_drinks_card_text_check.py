"""리뷰 R7(2026-11-04) — 사람이 고친 카드 글도 렌더 직전에 같은 근거 검사를 받는다(캐러셀·카드 릴스). 0원·네트워크 0."""
from __future__ import annotations

import pytest

from engine import drinks_produce as dp
from engine import drinks_script_check as sc

QUOTE1 = "大吟醸酒は精米歩合50%以下の白米を使う"
CLAIMS = [{"claim_id": "c1", "text": "정미율 50% 이하", "claim_type": "process", "source_refs": [{"snapshot_id": "s", "original_quote": QUOTE1}]},
          {"claim_id": "c2", "text": "양조 알코올 무첨가", "claim_type": "product_fact", "source_refs": [{"snapshot_id": "s", "original_quote": "醸造アルコールを加えない"}]}]


def plan(**over):
    pages = [{"position": 1, "role": "cover", "heading": "다이긴조는 왜 비쌀까", "body": "", "claim_ids": []},
             {"position": 2, "role": "explain", "heading": "쌀을 깎는다", "body": "정미율 50% 이하로 깎아요", "claim_ids": ["c1"]},
             {"position": 3, "role": "checklist", "heading": "라벨 체크", "body": "양조 알코올 무첨가", "claim_ids": ["c2"]}]
    for pos, fields in over.items():
        pages[int(pos[1:]) - 1].update(fields)
    return {"pages": pages}


def test_original_based_edit_passes():
    assert sc.check_card_texts(plan(p2={"body": "쌀을 50% 이하만 남기고 깎아요"}), CLAIMS).blocks == []


@pytest.mark.parametrize("edit,code", [
    ({"p2": {"body": "정미율 35% 이하로 깎아요"}}, "number_unsupported"),            # 원문에 없는 숫자(근거 표시는 그대로)
    ({"p3": {"body": "한 잔에 물 세 방울 넣어 보세요"}}, "quantity_unsupported"),      # 음주 처방(양)
    ({"p3": {"body": "차갑게 드세요"}}, "advice_unsupported"),                       # 근거 없는 권고
    ({"p2": {"claim_ids": ["c9"]}}, "claim_unknown"),
    ({"p1": {"heading": "다이긴조 70% 가 비싼 이유"}}, "number_unsupported"),          # 근거 없는 표지 숫자
])
def test_human_edits_beyond_the_source_are_blocked(edit, code):
    rep = sc.check_card_texts(plan(**edit), CLAIMS)
    assert code in [f.code for f in rep.blocks], rep.blocks


def test_card_reel_hook_and_share_line_are_checked_too():
    p = plan()
    p["reel"] = {"hook_title": "다이긴조, 99% 가 모르는 이유", "share_line": "오늘 한 번 마셔 보세요"}
    codes = [f.code for f in sc.check_card_texts(p, CLAIMS).blocks]
    assert "number_unsupported" in codes and "advice_unsupported" in codes
    p["reel"] = {"hook_title": "다이긴조는 왜 비쌀까", "share_line": "친구에게도 알려 줄 만한 이야기"}
    assert sc.check_card_texts(p, CLAIMS).blocks == []


def test_blocked_card_text_stops_the_render_before_any_file(tmp_path, monkeypatch):
    calls = []

    class Rpc:
        def __call__(self, fn, p):
            calls.append((fn, p))
            return {} if fn == "drinks_heartbeat_render" else {"status": "failed", **p}

    import engine.drinks_cards as cards

    monkeypatch.setattr(cards, "render_carousel", lambda *a, **k: pytest.fail("막힌 글은 그리지 않는다"))
    job = {"job_id": "j" * 8, "lease_token": "l", "format": "carousel", "plan": plan(p2={"body": "정미율 35% 이하"}), "claims": CLAIMS, "sources": [],
           "topic": {"title": "t"}}
    res = dp.process_job(job, Rpc(), dp.Storage("local", str(tmp_path)))
    assert res["error_code"] == "card_text_unsupported" and "35" in res["error_message"]
    assert [c[0] for c in calls if c[0] in ("drinks_register_asset", "drinks_record_cost")] == []
