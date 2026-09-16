"""비용 원장 배선 (작업지시서 영상엔진품질 v3 §8-4 P3-c).

무엇을 고정하는가: Phase 0 이 실측한 결함 ③ — `generation_attempts` 가 **0행**이었다.
원인은 불린 하나다:

    use_cache = bool(directive_id) and PROVIDER not in ("placeholder", "")

"캐시를 쓸까"와 "원장에 적을까"가 한 변수에 묶여 있어, `directive_id=None` 으로 부르는
리포트 라인(`report_render.py`)은 기록 3곳이 **전부** 건너뛰어졌다.

여기서는 그 분리가 유지되는지, 그리고 실패·폴백·재시도가 실제로 남는지 본다.
"""

from __future__ import annotations

import pytest

from engine import render


@pytest.fixture()
def ledger(monkeypatch):
    rows: list[dict] = []
    monkeypatch.setattr(render.cost_ledger, "record", lambda a: rows.append(a))
    monkeypatch.setattr(render.db, "get_render_asset", lambda *a, **kw: None)
    monkeypatch.setattr(render.db, "upload_render", lambda *a, **kw: "https://x/y")
    monkeypatch.setattr(render.db, "upsert_render_asset", lambda *a, **kw: None)
    return rows


# ── 핵심: directive_id 가 없어도 원장에는 남는다 ────────────────
def test_report_line_without_directive_id_still_records(tmp_path, monkeypatch, ledger):
    """이 한 줄이 generation_attempts 0행의 원인이었다."""
    monkeypatch.setattr(render.config, "IMAGE_PROVIDER", "gemini")

    def ok(cut, header, path, model="", ref_path=None):
        open(path, "w").close()
        return path, 0.02

    monkeypatch.setattr(render.image_provider, "generate_image", ok)
    monkeypatch.setattr(render.image_provider, "measure_aspect", lambda p: None)

    render._gen_still({"cut_no": 3}, {"version_type": "explainer"},
                      str(tmp_path / "a.png"), directive_id=None, render_job_id="job-77")

    assert len(ledger) == 1, "directive_id 가 없다고 원장을 건너뛰면 안 된다"
    assert ledger[0]["directive_id"] is None
    assert ledger[0]["render_job_id"] == "job-77", "언어별 귀속이 이것 없이는 불가능하다"
    assert ledger[0]["cut_no"] == 3


def test_placeholder_provider_is_still_excluded(tmp_path, monkeypatch, ledger):
    """placeholder 는 무료라 원장을 채울 이유가 없다 — 분리해도 이 제외는 유지된다."""
    monkeypatch.setattr(render.config, "IMAGE_PROVIDER", "placeholder")

    def ok(cut, header, path, model="", ref_path=None):
        open(path, "w").close()
        return path, 0.0

    monkeypatch.setattr(render.image_provider, "generate_image", ok)
    monkeypatch.setattr(render.image_provider, "measure_aspect", lambda p: None)

    render._gen_still({"cut_no": 1}, {}, str(tmp_path / "a.png"), directive_id="d1")
    assert ledger == []


# ── 실패·폴백·재시도가 남는가 ─────────────────────────────────
def test_image_retries_are_each_recorded(tmp_path, monkeypatch, ledger):
    """attempt_no 파라미터는 cost.py 에 있었는데 호출 4곳이 전부 기본값 1만 썼다."""
    monkeypatch.setattr(render.config, "IMAGE_PROVIDER", "gemini")
    monkeypatch.setattr(render.config, "ASSET_RETRY", 2)

    def boom(cut, header, path, model="", ref_path=None):
        # 폴백 단계에서 render 가 IMAGE_PROVIDER 를 placeholder 로 바꿔 다시 부른다.
        # 그때까지 raise 하면 폴백 자체가 죽어 검사 대상(폴백 행)이 안 생긴다.
        if render.config.IMAGE_PROVIDER == "placeholder":
            open(path, "w").close()
            return path, 0.0
        raise RuntimeError("429 rate limited")

    monkeypatch.setattr(render.image_provider, "generate_image", boom)
    monkeypatch.setattr(render.image_provider, "measure_aspect", lambda p: None)

    render._gen_still({"cut_no": 5}, {}, str(tmp_path / "a.png"),
                      directive_id="d1", render_job_id="job-9")

    failed = [r for r in ledger if r["status"] == "failed"]
    assert [r["attempt_no"] for r in failed] == [1, 2, 3], "재시도마다 한 행씩"
    assert all(r["error_class"] == "RuntimeError" for r in failed)
    assert all(float(r["actual_cost_usd"]) == 0.0 for r in failed), "실패는 미과금"


def test_image_fallback_to_placeholder_is_recorded(tmp_path, monkeypatch, ledger):
    """'이 컷은 생성이 아니라 폴백이었다'가 화면 품질을 설명하는 가장 중요한 한 줄이다."""
    monkeypatch.setattr(render.config, "IMAGE_PROVIDER", "gemini")
    monkeypatch.setattr(render.config, "ASSET_RETRY", 0)

    calls = {"n": 0}

    def maybe(cut, header, path, model="", ref_path=None):
        calls["n"] += 1
        if render.config.IMAGE_PROVIDER == "placeholder":
            open(path, "w").close()
            return None, 0.0
        raise RuntimeError("boom")

    monkeypatch.setattr(render.image_provider, "generate_image", maybe)

    render._gen_still({"cut_no": 7}, {}, str(tmp_path / "a.png"), directive_id="d1")

    fb = [r for r in ledger if r["status"] == "fallback"]
    assert len(fb) == 1
    assert fb[0]["provider"] == "placeholder"
    assert fb[0]["cut_no"] == 7


# ── 개념 분리가 코드에 남아 있는가 ────────────────────────────
def test_cache_and_ledger_are_separate_decisions():
    """다시 한 불린으로 합치면 리포트 라인 원장이 조용히 0행으로 돌아간다."""
    import inspect

    for fn in (render._gen_still, render._gen_veo_clip):
        src = inspect.getsource(fn)
        assert "record_ledger" in src, f"{fn.__name__}: 원장 판정이 분리되지 않았다"
        assert "use_cache = bool(directive_id) and paid" in src
        assert "record_ledger = paid" in src


def test_ledger_failure_does_not_block_render():
    """원장 기록 실패가 렌더를 막으면 관측을 켠 것이 사고가 된다."""
    import inspect

    from engine import cost as cost_ledger

    assert "렌더를 막지 않는다" in inspect.getsource(cost_ledger.record)


# ── QA 는 기록 전용이다 — 렌더를 죽이면 안 된다 ────────────────
def test_report_render_qa_failure_does_not_kill_the_job():
    """run_qa 는 ffprobe/ffmpeg subprocess 를 부르고, _ffprobe_json 은 JSONDecodeError 만 잡는다.

    ★ 이 호출이 upload_render **앞**에 있어서, 감싸지 않으면 바이너리 부재·타임아웃 하나로
      잘 만들어진 mp4 를 잃고 잡이 실패한다. 관측을 켜다가 사고를 내는 꼴이다.
      0036 주석이 "기록 전용 — 차단하지 않는다"고 적었으므로 코드가 그 약속을 지켜야 한다.
    """
    import inspect

    from engine import report_render

    src = inspect.getsource(report_render.process_job)
    # ★ 주석 문장이 아니라 **실제 코드 줄**만 본다. 처음엔 src.index("upload_render") 로
    #   순서를 봤는데, 바로 위 주석에 그 단어가 들어 있어 주석을 먼저 찾아 오판했다.
    lines = [ln.strip() for ln in src.splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    qa_i = next(i for i, ln in enumerate(lines) if "render_qa.run_qa" in ln)
    up_i = next(i for i, ln in enumerate(lines) if "upload_render(" in ln)

    # ★ "바로 윗줄이 try:" 로 보지 않는다 — 그 사이에 다른 with 가 들어오면(§10 단계 계측이
    #   실제로 그렇게 들어왔다) 보호는 그대로인데 검사만 깨진다. 구문 트리로 **정말 try 안에
    #   있는지**를 본다. 형식이 아니라 불변식을 고정하는 것이 이 검사의 목적이다.
    import ast
    import textwrap

    fn = ast.parse(textwrap.dedent(src)).body[0]
    call_lines = {n.lineno for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and "run_qa" in ast.dump(n.func)}
    guarded = any(
        node.handlers
        and any(call_lines & set(range(b.lineno, (b.end_lineno or b.lineno) + 1))
                for b in node.body)
        for node in ast.walk(fn) if isinstance(node, ast.Try))
    assert guarded, "run_qa 가 try 로 감싸이지 않았다"
    assert "qa_error" in src, "실패를 조용히 삼키지 말고 기록에 남긴다"
    assert qa_i < up_i, "QA 가 업로드 뒤로 밀리면 이 가드의 전제가 바뀐다"


def test_cache_hit_does_not_double_count_the_ledger(tmp_path, monkeypatch, ledger):
    """공유 에셋(언어 간 재사용)이 매번 원장에 잡히면 편당 비용이 부풀려진다(§6.3)."""
    monkeypatch.setattr(render.config, "IMAGE_PROVIDER", "gemini")
    monkeypatch.setattr(render.db, "get_render_asset",
                        lambda *a, **kw: {"content_hash": "X", "asset_url": "http://x"})
    monkeypatch.setattr(render.assemble, "cache_hit", lambda existing, h: True)
    monkeypatch.setattr(render, "_download_to", lambda url, path: open(path, "w").close())

    render._gen_still({"cut_no": 1}, {}, str(tmp_path / "a.png"), directive_id="d1")
    assert ledger == [], "캐시 재사용은 생성이 아니다"


def test_insert_generation_attempt_actually_runs(monkeypatch):
    """★ 실측 사고 회귀(2026-08-03): 이 함수만 datetime 지역 import 가 빠져 NameError 가 났고,
    cost.record 가 그것을 삼켜 generation_attempts 가 계속 0행이었다.

    운영 로그의 실제 문구:
      `WARNING engine: 비용 원장 기록 실패(무시): name 'datetime' is not defined`

    그래서 '삽입을 시도한다'가 아니라 **함수가 끝까지 도는지**를 본다. 예전 테스트는 전부
    cost.record 를 거쳐서, 삼켜진 예외를 성공과 구분하지 못했다.
    """
    from engine import db

    captured: dict = {}

    class _Tbl:
        def insert(self, payload):
            captured["payload"] = payload
            return self

        def execute(self):
            return None

    monkeypatch.setattr(db, "client", lambda: type("C", (), {"table": lambda _s, _n: _Tbl()})())
    # conftest 가 운영 원장 쓰기를 전역 차단한다(2026-08-29). 이 테스트는 **그 함수 자체가
    # 끝까지 도는지**를 보는 것이고 위에서 클라이언트를 스텁했으므로 네트워크로 나가지 않는다.
    monkeypatch.setattr(db, "insert_generation_attempt", db.real_insert_generation_attempt)
    db.insert_generation_attempt({"asset_type": "image", "provider": "gemini"})

    # 스탬프가 찍혔다는 것은 datetime 이 실제로 해석됐다는 뜻이다.
    assert captured["payload"]["completed_at"]
    assert captured["payload"]["price_verified_at"]
    assert captured["payload"]["asset_type"] == "image"


def test_ledger_failure_is_still_swallowed():
    """위 수정이 '원장 때문에 렌더가 죽는다'로 뒤집히면 안 된다 — 삼키는 것은 설계다."""
    from engine import cost as cost_ledger

    # 존재하지 않는 컬럼을 넣어 실제로 실패시키는 대신, record 가 예외를 밖으로 내지 않는지만 본다.
    cost_ledger.record({"__will_fail__": object()})   # 예외가 새어 나오면 테스트 실패
