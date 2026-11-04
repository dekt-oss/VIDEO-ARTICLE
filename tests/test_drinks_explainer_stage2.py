"""설명형 2단계 준비(S0.5·S2·S3) — 돈·네트워크·운영 DB 0. docs/deviation-drinks-explainer-stage2.md

본다: ① 대본 지시문이 시각 주장표·motion_prompt·경계 종류를 전부 요구하고 검사가 같은 말을 한다 ② 품질 6항목이 SQL·화면·파이썬에서 같다
③ 세 스크립트가 --yes·결재 문장·스위치 없이는 아무것도 보내지 않고, dry-run 금액이 문서(§3-7·§3-10)와 맞다 ④ 공급자 사전 검증은 무료 GET 이고 키를 주소에 싣지 않는다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from engine import config
from engine import drinks_develop as dd
from engine import drinks_explainer as dx
from engine import drinks_explainer_queue as q
from engine import drinks_script_check as sc
from engine.providers import video as pv
from scripts import explainer_s05 as s05
from scripts import explainer_s2 as s2
from scripts import explainer_s3 as s3
from scripts import explainer_stages as st

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase" / "migrations" / "0067_drinks_explainer_queue.sql").read_text(encoding="utf-8")
WEB_QUEUE = (ROOT / "web" / "lib" / "drinks" / "explainerQueue.ts").read_text(encoding="utf-8")
WEB_SCREEN = (ROOT / "web" / "components" / "drinks" / "ExplainerProduction.tsx").read_text(encoding="utf-8")
FX = json.loads(s05.FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _explainer_contract(monkeypatch):
    monkeypatch.setattr(config, "DRINKS_DEVELOP_EXPLAINER_CONTRACT", True)
    monkeypatch.setattr(config, "DRINKS_DEVELOP_SCENES", (8, 11))
    monkeypatch.setattr(config, "DRINKS_DEVELOP_SECONDS", (48.0, 66.0))


# ── ① 대본 지시문 ↔ 검사 ─────────────────────────────────────

def test_prompt_demands_visual_claims_motion_and_boundary_kinds():
    p = dd.plan_system()
    for must in ("visual_claim_ko", "allowed_simplification", "forbidden_misreading", "depiction_label", "motion_prompt(영어, 필수)", "'ref:N'", "'match'", "'cut'", "2번 이후 필수"):
        assert must in p, must
    assert "motion_prompt(영어, 선택)" not in p, "설명형에서 motion_prompt 는 선택이 아니다"
    assert "첫 번째 mechanism 장면이 훅" in p


@pytest.mark.parametrize("value,n,expect", [("ref:2", 4, ("ref", 2)), ("match", 4, ("ref", 3)), ("cut", 4, ("cut", None)), ("", 4, (None, None)), ("ref:1", 1, (None, None)), ("same", 3, (None, None)), (" REF:1 ", 2, ("ref", 1))])
def test_continuity_kind(value, n, expect):
    assert dd.continuity_kind(value, n) == expect


def test_boundary_checks_block_missing_and_forward_refs():
    scenes = [{"narration": "a"}, {"narration": "b", "continuity": "match"}, {"narration": "c"}, {"narration": "d", "continuity": "ref:9"}, {"narration": "e", "continuity": "cut"}]
    codes = [(f.code, f.scene) for f in dd.explainer_boundary_checks({"scenes": scenes})]
    assert codes == [("boundary_missing", 3), ("invalid_continuity", 4)]


def test_check_plan_blocks_a_scene_without_boundary_but_the_fixture_passes():
    review = {"status": "approved", "claims": FX["claims"], "brief": FX["brief"], "sources": FX["sources"]}
    rep = dd.check_plan(FX["fake_plan"], review, FX["topic"])
    assert rep.ok, sc.summary_ko(rep)
    broken = json.loads(json.dumps(FX["fake_plan"]))
    broken["scenes"][4].pop("continuity")
    rep2 = dd.check_plan(broken, review, FX["topic"])
    assert any(f.code == "boundary_missing" and f.scene == 5 for f in rep2.blocks)
    assert "continuity" in dd.visual_claim_table(FX["fake_plan"])[1]


def test_queue_reads_match_and_cut_declarations():
    scenes = [{"visual_role": "reality"}, {"visual_role": "mechanism", "continuity": "cut"}, {"visual_role": "mechanism", "continuity": "match"}, {"visual_role": "reality", "continuity": "cut"},
              {"visual_role": "reality", "continuity": "ref:4"}, {"visual_role": "reality"}]
    got = [q.scene_boundary(scenes, i) for i in range(1, 7)]
    assert got == [("loop", None), ("cut_to_mechanism", None), ("match", 2), ("cut_to_mechanism", None), ("match", 4), ("cut", None)]
    with pytest.raises(dx.ExplainerStop):
        q.scene_boundary([{"visual_role": "reality"}, {"visual_role": "reality", "continuity": "ref:2"}], 2)


# ── ② 품질 판정 6항목 — SQL·화면·파이썬 ───────────────────────

def _sql_required(stage: str) -> list[str]:
    m = re.search(rf"v_stage = '{stage}' then\s*required := array\[(.*?)\]", SQL, re.S)
    assert m, stage
    return re.findall(r"'(\w+)'", m.group(1))


def _web_keys(const: str) -> list[str]:
    m = re.search(rf"export const {const}: \[string, string\]\[\] = \[(.*?)\];", WEB_QUEUE, re.S)
    assert m, const
    return re.findall(r'\["(\w+)",', m.group(1))


def test_quality_six_items_match_in_sql_screen_and_python():
    assert list(dx.QUALITY_REVIEW_ITEMS) == _sql_required("quality") == _web_keys("QUALITY_CHECKS") == list(config.DRINKS_EXPLAINER_QUALITY_ITEMS)
    assert len(dx.QUALITY_REVIEW_ITEMS) == 6
    assert list(dx.PROCESS_REVIEW_ITEMS) == _sql_required("process") == _web_keys("PROCESS_CHECKS")
    # SQL: 하나라도 거짓이면 합격을 받지 않고, 품질 합격 전에는 ready_to_publish 로 못 간다. 워커는 사람 검수 상태를 올리지 못한다.
    assert "checklist_incomplete" in SQL and "if v_state is distinct from 'quality_review_pass'" in SQL
    assert "사람 검수 상태는 워커가 올리지 않습니다" in SQL
    # 화면: 6항목이 체크박스고 전부 체크돼야 [합격]이 열린다. 자동 검사 통과를 품질 합격이라 부르지 않는다.
    assert 'stage="quality" title="품질 검수 6항목" items={QUALITY_CHECKS}' in WEB_SCREEN
    assert "const all = items.every(([k]) => ck[k]);" in WEB_SCREEN and "disabled={busy || !all}" in WEB_SCREEN
    assert "자동 검사 통과는 품질 합격이 아닙니다" in WEB_SCREEN
    assert config.DRINKS_EXPLAINER_CAPTION_AI_LINE in WEB_SCREEN, "게시 대기 안내가 캡션 'AI 생성 영상' 줄을 말한다"


# ── ③ 스크립트 — 0원, 게이트, 문서 금액 ──────────────────────

@pytest.fixture
def no_env(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key="", supabase_url="", supabase_service_key=""))
    monkeypatch.setattr(config, "DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED", False)
    monkeypatch.setattr(st, "preview_dir", lambda name: (tmp_path / name).mkdir(parents=True, exist_ok=True) or (tmp_path / name))
    return tmp_path


def test_s05_dry_run_passes_end_to_end_and_spends_nothing(no_env):
    rep = s05.dry_run(no_env / "s05", tts="")
    assert rep["ok"] and rep["checks"]["ok"] and rep["rewrites"] == 0 and rep["money_spent_usd"] == 0 and rep["model_calls_made"] == 0
    assert rep["scenes"] == 9 and 40 <= rep["final_sec_planned"] <= 55 and rep["hook_scene"] == 2
    assert rep["boundaries"][0] == "loop" and "match" in rep["boundaries"] and "cut_to_mechanism" in rep["boundaries"]
    d = json.loads((no_env / "s05" / "directive.json").read_text(encoding="utf-8"))
    assert all(s["motion_prompt"] and s["visual_claim_ko"] and s["depiction_label"] for s in d["slots"])
    assert (no_env / "s05" / "prompt_system.txt").exists() and (no_env / "s05" / "source_table.md").exists()
    # 문서 금액과 같은 자리(§3-7 한 편 $7.95·상한 $8.90 / §3-10 S2 약 $2.2·상한 $2.6) — 대본이 짧아 조금 아래다
    assert 6.5 <= d["estimate"]["estimate_usd"] <= 8.9 and d["estimate"]["suggested_cap_usd"] <= 10
    assert rep["s2"]["fits"] and 1.9 <= rep["s2"]["estimate_usd"] <= 2.6 and rep["s2"]["cap_usd"] == 2.6


def test_s2_and_s3_scopes_follow_the_plan_document(no_env):
    s05.dry_run(no_env / "s05", tts="")
    d = json.loads((no_env / "s05" / "directive.json").read_text(encoding="utf-8"))
    sc2 = st.s2_scope(d)
    assert sc2["through_n"] == d["hook_scene"] == 2 and sc2["slots"] == [1, 2] and sum(r["candidates"] for r in sc2["rows"]) == 3
    sc3 = st.s3_scope(d, s2_spent_usd=sc2["estimate_usd"], selected_slots=(1, 2))
    assert [r["n"] for r in sc3["rows"]] == [3, 4, 5, 6, 7, 8, 9] and sc3["cap_usd"] == st.floor_cents(8.90 - sc2["estimate_usd"]) and sc3["fits"]
    assert st.s3_scope(d, s2_spent_usd=8.90)["fits"] is False, "S2 가 다 썼으면 S3 상한은 0 — 사지 않는다"
    assert st.s2_scope({**d, "slots": [dict(s, clip_est_usd=5.0) for s in d["slots"]]})["fits"] is False


def test_scripts_refuse_without_yes_or_env_and_never_touch_network(no_env, monkeypatch, capsys):
    import socket

    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("네트워크에 닿으면 안 된다"))
    monkeypatch.setattr(s2, "DEFAULT_DIRECTIVE", no_env / "s05" / "directive.json")
    s05.dry_run(no_env / "s05", tts="")
    assert s05.main(["plan"]) == 2 and "--yes" in capsys.readouterr().out
    assert s05.main(["evidence", "--yes"]) == 2 and "결재 문장" in capsys.readouterr().out
    assert s05.main(["plan", "--yes", "--approve", "ok"]) == 2 and "SUPABASE" in capsys.readouterr().out
    assert s2.main([]) == 0 and s3.main(["--s2-spent", "2.21", "--selected", "1,2"]) == 0
    assert s2.main(["plan", "--plan-id", "x"]) == 2 and s2.main(["buy", "--plan-id", "x", "--yes", "--approve", "ok"]) == 2
    assert s2.main(["preflight"]) == 2, "키가 없으면 무료 조회도 보내지 않는다"
    assert s3.main(["buy", "--plan-id", "x", "--yes", "--approve", "ok"]) == 2 and s3.main(["assemble", "--plan-id", "x"]) == 2
    out = capsys.readouterr().out
    assert "돈 안 씀" in out
    # 스위치가 켜져 있어도 DB 가 없으면 멈춘다 — 그리고 코드는 스위치를 켜지 않는다
    with pytest.raises(st.StageStop):
        st.require_provider_switch()


def test_scripts_do_not_flip_the_provider_switch_or_print_secrets():
    for name in ("explainer_stages", "explainer_s05", "explainer_s2", "explainer_s3"):
        src = (ROOT / "scripts" / f"{name}.py").read_text(encoding="utf-8")
        assert "DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED = True" not in src and 'PROVIDER_SEND_ENABLED"] = ' not in src, name
        assert not re.search(r"print\([^\n]*gemini_api_key", src) and not re.search(r"print\([^\n]*service_key", src), name
        for m in re.finditer(r'"approver_words":\s*([^,}]+)', src):
            assert m.group(1).strip() == "args.approve", f"{name}: 결재 문장은 운영자가 친 말만 DB 로 간다 — {m.group(0)}"
    env = st.env_summary()
    assert all(isinstance(v, (bool, str)) for v in env.values()) and not any(len(str(v)) > 40 for v in env.values()), "값이 아니라 켜짐 여부만"


def test_caption_draft_has_the_ai_line_under_the_first_line():
    cap = s3.caption_draft({"question": "위스키 병에는 왜 유통기한이 안 보일까?", "categories": ["whisky"]}, "훅")
    lines = cap.splitlines()
    assert lines[0].startswith("위스키") and lines[1] == config.DRINKS_EXPLAINER_CAPTION_AI_LINE == "AI 생성 영상"


# ── ④ 공급자 사전 검증(무료) ─────────────────────────────────

def test_preflight_is_a_free_get_with_header_auth_and_refuses_without_key(monkeypatch):
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key=""))
    assert pv.omni_preflight().ok is False
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key="TEST-not-real"))
    seen = {}

    class C:
        def get(self, url, headers=None):
            seen.update(url=url, headers=headers)

            class R:
                status_code = 200

                def json(self):
                    return {"name": f"models/{config.DRINKS_EXPLAINER_OMNI_MODEL}", "displayName": "Gemini Omni Flash", "version": "1.1", "supportedGenerationMethods": ["interactions"]}
            return R()

        def post(self, *a, **k):
            pytest.fail("사전 검증은 GET 만")
    pre = pv.omni_preflight(C())
    assert pre.ok and pre.methods == ("interactions",) and pre.version == "1.1"
    assert seen["url"] == f"{config.DRINKS_EXPLAINER_OMNI_MODELS_URL}/{config.DRINKS_EXPLAINER_OMNI_MODEL}" and "key=" not in seen["url"]
    assert seen["headers"] == {"x-goog-api-key": "TEST-not-real"}
    assert pv.evaluate_omni_model_listing(404, None).ok is False and pv.evaluate_omni_model_listing(200, {"name": "models/other"}).ok is False


def test_omni_parse_follows_documented_interaction_shape():
    data = {"id": "i1", "status": "completed", "steps": [{"type": "model_output", "content": [{"type": "text", "text": "ok"}, {"type": "video", "mime_type": "video/mp4", "data": "QUJD"}]}],
            "usage": {"total_output_tokens": 100, "output_tokens_by_modality": [{"modality": "text", "tokens": 5}, {"modality": "video", "tokens": 95}]}}
    p = pv.parse_omni_response(data)
    assert p.video_bytes == b"ABC" and p.billed_units == 95.0 and p.request_id == "i1" and p.done
    assert pv.parse_omni_response({"id": "i2", "status": "in_progress"}).done is False
    uri = pv.parse_omni_response({"id": "i3", "status": "completed", "steps": [{"type": "model_output", "content": [{"type": "video", "uri": "https://x/files/f:download"}]}]})
    assert uri.gcs_uri.startswith("https://") and uri.video_bytes == b""
    for bad in ({"id": "x", "status": "failed"}, {"id": "x", "outputs": [{"type": "video", "data": "QUJD"}]}, {"id": "x", "status": "completed", "steps": [{"type": "model_output", "content": [{"type": "video"}]}]}):
        with pytest.raises(pv.ExplainerProviderError):
            pv.parse_omni_response(bad)
    assert pv.omni_duration_value(8) == "8s"
    assert set(pv.OMNI_UNVERIFIED) and set(pv.OMNI_VERIFIED_BY_DOCS), "검증됨/미검증을 코드가 구분해 적는다"



# ── 리뷰 R10(2026-11-04): S3 잔액은 내림 — 편 전체 합산이 $8.90 을 넘지 않는다 ──

def _directive(out):
    s05.dry_run(out / "s05", tts="")
    return json.loads((out / "s05" / "directive.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("s2", [2.2111, 2.2053, 2.0001, 2.60, 0.0, 8.8999])
def test_s3_cap_is_floored_so_the_episode_never_exceeds_the_total(no_env, s2):
    sc3 = st.s3_scope(_directive(no_env), s2_spent_usd=s2)
    assert round(s2 + sc3["cap_usd"], 6) <= 8.90, (s2, sc3["cap_usd"])
    assert sc3["cap_usd"] == st.floor_cents(8.90 - s2)


def test_s3_reports_overspend_and_buys_nothing(no_env):
    sc3 = st.s3_scope(_directive(no_env), s2_spent_usd=9.10)
    assert sc3["cap_usd"] == 0 and sc3["fits"] is False and sc3["over_episode_cap_usd"] == pytest.approx(0.20)


def test_s3_resume_counts_held_and_settled_of_every_approval():
    from scripts import explainer_s3 as s3

    status = {"approvals": [{"spent_usd": 2.2111, "held_usd": 0}, {"spent_usd": 1.50, "held_usd": 0.41}]}
    assert s3.s2_spent_from_status(status) == pytest.approx(4.1211)
