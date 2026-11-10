"""설명형 사진클레이 버전(0079) — 돈·네트워크·공급자 호출 0. docs/deviation-drinks-explainer-clay.md

① 순수: 자막 줄 나누기, 단어 시각 → 자막 시각, 그림 주문 문장·해시, 지시서.
② 가짜 RPC·저장소·공급자로 구매 → 조립 → 파일 등록까지(ffmpeg 가 있을 때). 실제 SQL 규칙은 web/lib/drinks/explainerQueue.db.test.ts 가 본다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from engine import config
from engine import drinks_clay as clay
from engine import drinks_explainer_queue as q
from scripts import explainer_queue_rehearsal as qr

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "engine" / "drinks_explainer_queue.py").read_text(encoding="utf-8")
SQL = (ROOT / "supabase" / "migrations" / "0079_drinks_explainer_clay.sql").read_text(encoding="utf-8")
PLAN = "22222222-2222-4222-8222-222222222222"
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg 없음")


def job(renderer="explainer_plan"):
    scenes = qr._scenes()
    return {"job_id": "j1", "lease_token": "t", "renderer": renderer, "plan_revision_id": PLAN, "spend_approval_id": "ap",
            "plan": {"scenes": scenes}, "topic": {"title": "준마이·긴조·다이긴조, 뭐가 다를까?", "question": "뭐가 다를까?"},
            "brief": {"audience_question": "왜"}, "sources": [],
            "claims": [{"claim_id": "c1", "text": "물", "source_refs": [{"snapshot_id": "s", "original_quote": qr.QUOTE}]}]}


def directive(sec=5.0):
    j = job()
    return q.build_clay_directive(PLAN, j, qr.visual_claims(j["plan"]["scenes"]), {i: sec for i in range(1, len(j["plan"]["scenes"]) + 1)})


# ── ① 순수 ──────────────────────────────────────────────

def test_lines_break_on_meaning_not_on_width():
    assert clay.split_lines("쌀알 겉을 깎아 내고 가운데만 남겨서 술을 빚는데요, 60% 이하만 남기면 긴조, 50% 이하만 남기면 다이긴조. 거의 극한 다이어트죠.") == [
        "쌀알 겉을 깎아 내고 가운데만", "남겨서 술을 빚는데요,", "60% 이하만 남기면 긴조,", "50% 이하만 남기면 다이긴조.", "거의 극한 다이어트죠."]
    assert clay.split_lines("준마이, 긴조, 다이긴조. 1등급, 2등급, 3등급인 줄 알았죠? 땡. 이건 등급표가 아니라 사진 편집이에요.")[-1] == "이건 등급표가 아니라 사진 편집이에요."
    for text in (s["narration"] for s in qr._scenes()):
        lines = clay.split_lines(text)
        assert "".join(lines).replace(" ", "") == text.replace(" ", ""), "글자를 빼거나 더하지 않는다"
        assert all(len(x) <= config.DRINKS_CLAY_LINE_MAX_CHARS or " " not in x for x in lines)


def test_caption_starts_follow_spoken_words_or_fall_back_to_length():
    words = [("준마이,", 0.0, .5), ("긴조,", .5, .9), ("다이긴조.", .9, 1.5), ("1등급,", 2.0, 2.4), ("2등급", 2.4, 2.8)]
    assert clay.line_starts(["준마이, 긴조, 다이긴조.", "1등급, 2등급"], words, 3.0) == [0.0, 2.0]
    assert clay.line_starts(["가나", "다라마바"], [], 6.0) == [0.0, 2.0], "단어 시각이 없으면 글자 수 비례"


def test_image_order_has_no_text_mascot_first_and_last_and_hash_follows_reference():
    first, mid, last = (clay.image_item(n, 5, "A bottle on a table", "ref") for n in (1, 3, 5))
    assert "mascot" in first.prompt and "mascot" in last.prompt and "Jjeri" not in mid.prompt
    for it in (first, mid, last):
        assert "no text" in it.prompt.lower() and it.aspect == config.DRINKS_CLAY_ASPECT == "1:1" and it.kind == "image"
        assert it.cut["raw_prompt"] == it.prompt, "엔진 실사형 화풍 문장이 붙지 않는다"
    assert clay.image_item(3, 5, "A bottle", "sha-a").prompt_hash != clay.image_item(3, 5, "A bottle", "sha-b").prompt_hash, "1번 그림이 바뀌면 다른 주문"
    with pytest.raises(Exception, match="visual_prompt"):
        clay.image_item(2, 5, " ", "ref")


def test_directive_is_images_only_with_screen_lines():
    d = directive()
    assert d["provider"] == "clay" and d["estimate"]["clips_usd"] == 0
    n = len(d["slots"])
    assert d["estimate"]["images_usd"] == pytest.approx(n * config.DRINKS_CLAY_IMAGE_USD)
    assert d["estimate"]["suggested_cap_usd"] >= d["estimate"]["images_usd"]
    assert [s["mascot_in_scene"] for s in d["slots"]] == [True] + [False] * (n - 2) + [True]
    for s in d["slots"]:
        assert s["lines"] and s["clip_sec"] == 0 and s["candidates_planned"] == 0 and s["slot_id"] == f"{PLAN}:A{s['n']}"
        assert s["image_prompt"] == clay.image_item(s["n"], n, s["visual_prompt"], clay.MASCOT_REF_ID).prompt
    assert d["hook_text"] == "준마이·긴조·다이긴조, 뭐가 다를까?"
    assert q.directive_hash(d) == q.directive_hash(directive()), "같은 대본이면 같은 지시서"


def test_directive_stops_outside_length_range_and_without_visual_table():
    with pytest.raises(Exception) as e:
        directive(sec=1.0)
    assert "duration_out_of_range" in str(getattr(e.value, "problems", e.value))
    j = job()
    with pytest.raises(Exception, match="시각 주장표"):
        q.build_clay_directive(PLAN, j, None, dict.fromkeys(range(1, 10), 5.0))


def test_sql_allows_clay_only_for_images_and_keeps_clip_rules():
    code = "\n".join(l.split("--", 1)[0] for l in SQL.splitlines())
    assert re.search(r"provider in \('omni','veo_fast','clay'\)", code)
    assert "when e.provider = 'clay' then array['image'] else array['image','video']" in code
    assert "if e.provider <> 'clay' then" in code and "selection_incomplete" in code, "클립 편의 선택 규칙은 그대로"
    assert config.DRINKS_CLAY_PROVIDER == "clay" and "운영 적용은 따로 결재" in SQL


def _fn_body(src: str, name: str) -> str:
    m = re.search(rf"^def {name}\(.*?(?=^def |^class |^[A-Z_]+ = )", src, re.S | re.M)
    assert m, name
    return m.group(0)


def test_clay_render_has_no_way_to_buy():
    for fn in ("_run_render_clay", "_fetch_clay_images"):
        body = _fn_body(SRC, fn)
        code = "\n".join(l.split("#", 1)[0] for l in body.splitlines() if not l.strip().startswith('"""'))
        for bad in ("adapter", "dpaid.buy", "drinks_hold_spend", "ClayAdapter", "_generate(", ".image("):
            assert bad not in code, (fn, bad)


def test_switch_off_buys_nothing(monkeypatch):
    monkeypatch.setattr(config, "DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED", False)
    with pytest.raises(Exception, match="provider_send_disabled|스위치"):
        clay.ClayAdapter().check_ready({"status": "open", "expired": False})
    monkeypatch.setattr(config, "DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED", True)
    with pytest.raises(Exception, match="열린 결재"):
        clay.ClayAdapter().check_ready({"status": "closed", "expired": False})


# ── ② 가짜 공급자로 구매 → 조립 ───────────────────────────────

class FakeStorage:
    def __init__(self, root: Path):
        self.root = root

    def put(self, path, key, mime):
        dest = self.root / key.replace(":", "_")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        return key

    def get(self, key, dest):
        shutil.copyfile(self.root / key.replace(":", "_"), dest)


class FakeRpc:
    def __init__(self, d):
        self.d, self.state, self.generated, self.calls = d, "approved", {}, []

    def __call__(self, fn, p):
        self.calls.append(fn)
        if fn == "drinks_explainer_job_context":
            return {"episode": {"provider": "clay", "state": self.state, "directive": self.d, "buy_through_n": None}, "approval": {"status": "open", "expired": False}}
        if fn == "drinks_explainer_episode_event":
            self.state = p["to_state"]
        if fn == "drinks_find_generated":
            h = p["prompt_hashes"][0]
            return [self.generated[h]] if h in self.generated else []
        if fn == "drinks_hold_spend":
            return {"hold_id": f"h{len(self.calls)}"}
        if fn == "drinks_register_generated":
            self.generated[p["prompt_hash"]] = {**p["asset"], "asset_id": f"g{len(self.generated)}"}
            return {"asset_id": f"g{len(self.generated)}"}
        if fn == "drinks_register_asset":
            return {"asset_id": f"a{len(self.calls)}"}
        if fn == "drinks_finish_render":
            return {"status": "succeeded", "assets": p["assets"], "qa": p["qa"]}
        return {}


class FakeAdapter:
    def __init__(self):
        self.refs: list[str] = []

    def check_ready(self, approval):
        assert approval["status"] == "open"

    def image(self, item, out, ref_path):
        from PIL import Image

        self.refs.append(Path(ref_path).name)
        Image.new("RGB", (1024, 1024), (180 + item.position * 5, 120, 90)).save(out)
        return 0.039


def _tts(text, path):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=44100:duration=5", "-c:a", "pcm_s16le", path], check=True)


@needs_ffmpeg
def test_buy_then_render_with_fake_provider(tmp_path):
    d = directive()
    rpc, storage, adapter = FakeRpc(d), FakeStorage(tmp_path / "store"), FakeAdapter()
    deps = q.Deps(adapter=adapter, tts_fn=_tts)
    bought = q.process_explainer_job(job("explainer_buy"), rpc, storage, deps=deps)
    assert rpc.state == "assets_complete" and len(rpc.generated) == len(d["slots"])
    assert adapter.refs[0] == "jjeri_ref.png" and set(adapter.refs[1:]) == {"ref_sheet.png"}, "1번은 째리, 나머지는 1번+째리 한 장"
    assert "drinks_explainer_verdict" not in rpc.calls and "drinks_explainer_open_attempt" not in rpc.calls, "클립 후보를 만들지 않는다"
    assert bought is not None

    again = FakeAdapter()   # 다시 돌려도 이미 산 그림은 다시 사지 않는다
    rpc.state = "approved"
    q.process_explainer_job(job("explainer_buy"), rpc, storage, deps=q.Deps(adapter=again, tts_fn=_tts))
    assert again.refs == []

    rpc.state = "assets_complete"
    out = q.process_explainer_job(job("explainer_render"), rpc, storage, deps=q.Deps(tts_fn=_tts))
    assert out["status"] == "succeeded", out
    assert rpc.state == "auto_qa_pass"
    assert [a["role"] for a in out["assets"]] == ["final_video", "cover"]
    assert out["qa"]["variant"] == "clay" and out["qa"]["probe"]["width"] == 1080 and out["qa"]["probe"]["height"] == 1920
    assert out["qa"]["auto_qa"]["signals"]["total_sec"] == pytest.approx(len(d["slots"]) * (5 + config.DRINKS_CLAY_SCENE_GAP_SEC), abs=0.3)
    assert "drinks_hold_spend" not in rpc.calls[rpc.calls.index("drinks_explainer_job_context", len(rpc.calls) - 40):], "조립 중 결재 가잡기 없음"
