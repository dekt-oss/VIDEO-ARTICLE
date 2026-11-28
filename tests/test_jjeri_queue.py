from pathlib import Path

import pytest

from engine import drinks_produce
from engine.drinks_collect import DbError
from engine.drinks_render import RenderError, Rendered
from engine.motion.jjeri_class import queue


def job():
    return {"job_id": "j-test", "lease_token": "token", "format": "video", "renderer": "jjeri_class",
            "renderer_version": "jjeri-class-v1"}


def test_renderer_does_not_bypass_evidence_gate(tmp_path, monkeypatch):
    raw = {"format": "jjeri_class", "version": 1}
    monkeypatch.setattr("engine.motion.jjeri_class.build._synthesize",
                        lambda *_: pytest.fail("blocked episode reached Edge"))
    with pytest.raises(RenderError, match="voice_invalid"):
        queue.render_job({**job(), "plan": {"jjeri_class": raw}}, tmp_path, tts="edge")


@pytest.mark.parametrize("mode", ["ok", "canceled", "lease_lost", "storage_failed", "evidence_failed"])
def test_jjeri_worker_storage_and_failure_boundaries(tmp_path, monkeypatch, mode):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"mock-render")
    moves = []
    calls = []

    class Storage(drinks_produce.Storage):
        def put(self, *args):
            moves.append(args)
            if mode == "storage_failed":
                raise RenderError("storage_error", "storage failed")
            return super().put(*args)

    storage = Storage(mode="local", root=str(tmp_path / "storage"))

    def fake_render(*args, **kwargs):
        if mode == "evidence_failed":
            raise RenderError("claim_unknown", "unapproved claim")
        return Rendered([{"role": "final_video", "position": 1, "mime": "video/mp4", "path": str(path)}],
                        {"renderer": "jjeri_class", "rights": {"bgm": "CC BY"}},
                        [{"kind": "render", "provider": "local_hyperframes", "cost_usd": 0}])

    monkeypatch.setattr(queue, "render_job", fake_render)
    monkeypatch.setattr(drinks_produce, "free_script_check", lambda *_: pytest.fail("legacy renderer reached"))

    def rpc(name, payload):
        calls.append((name, payload))
        if name == "drinks_heartbeat_render":
            later = sum(call == name for call, _ in calls) > 1
            if later and mode == "lease_lost":
                raise DbError("lease_lost", "lease lost")
            return {"renderable": True, "cancel_requested": mode == "canceled" and later}
        if name == "drinks_register_asset":
            return {"asset_id": "video"}
        if name == "drinks_finish_render":
            return {"status": payload["outcome"]}

    result = drinks_produce.process_job(job(), rpc, storage)
    assert result["status"] == {"ok": "succeeded", "lease_lost": "lease_lost"}.get(mode, "failed")
    if mode != "ok":
        assert not any(name == "drinks_register_asset" for name, _ in calls)
        assert bool(moves) == (mode == "storage_failed")
        return
    assert Path(storage.root, "drinks", "j-test", "final_video_01.mp4").read_bytes() == b"mock-render"
    costs = [payload["cost"] for name, payload in calls if name == "drinks_record_cost"]
    assert costs[0]["cost_usd"] == 0
    assert calls[-1][1]["qa"]["rights"]["bgm"] == "CC BY"



def test_edge_empty_output_retries_twice_without_silent_fallback(tmp_path, monkeypatch):
    import edge_tts
    from engine.motion.jjeri_class.build import _synthesize

    calls = []

    class Silence:
        def __init__(self, text, voice, rate):
            calls.append((text, voice, rate))

        async def save(self, path):
            Path(path).write_bytes(b"")

    monkeypatch.setattr(edge_tts, "Communicate", Silence)
    with pytest.raises(RuntimeError, match="TTS failed after retries"):
        _synthesize("같은 자막", tmp_path / "b00.mp3")
    assert calls == [("같은 자막", "ko-KR-HyunsuMultilingualNeural", "+10%")] * 3
    assert not list(tmp_path.iterdir())


def test_optional_jjeri_install_does_not_block_shared_workflow():
    import yaml

    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/drinks-produce.yml"
    steps = yaml.safe_load(workflow.read_text(encoding="utf8"))["jobs"]["produce"]["steps"]
    prep_node, prep_browser, produce = steps[-3:]
    assert prep_node["with"]["node-version"] == "22"
    assert prep_node["continue-on-error"] is True and prep_browser["continue-on-error"] is True
    assert prep_node["timeout-minutes"] < 60 and prep_browser["timeout-minutes"] < 60
    assert produce["run"] == "python -m engine.drinks_produce" and "if" not in produce
