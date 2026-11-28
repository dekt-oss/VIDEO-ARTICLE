import json
import subprocess
import sys
from pathlib import Path

import pytest

from engine.motion.jjeri_class.compositions import composition
from engine.motion.jjeri_class import build
from engine.motion.jjeri_class.stage import frame_html
from engine.motion.jjeri_class.timeline import build_timeline

SAMPLE = Path(__file__).resolve().parents[1] / "assets/templates/jjeri-class"


def test_hyperframes_subprocess_and_cli_setup_remove_credentials(monkeypatch, tmp_path):
    denied = ["SUPABASE_URL", "SUPABASE_SERVICE_KEY", "NEXT_PUBLIC_SUPABASE_URL", "DEEPSEEK_API_KEY",
              "GITHUB_TOKEN", "NPM_CONFIG_AUTH", "HTTP_PASSWORD", "DATABASE_URL", "SENTRY_DSN"]
    allowed = ["PATH", "TEMP", "NPM_CONFIG_CACHE", "PLAYWRIGHT_BROWSERS_PATH"]
    for name in denied:
        monkeypatch.setenv(name, "mock-credential")
    for name in allowed:
        monkeypatch.setenv(name, "mock-path")
    observed = denied + allowed + ["HYPERFRAMES_NO_TELEMETRY"]
    child = subprocess.run([sys.executable, "-m", "engine.motion.jjeri_class.hf_env", sys.executable, "-c",
                            f"import json, os; print(json.dumps({{k: os.environ[k] for k in {observed!r} if k in os.environ}}))"],
                           capture_output=True, text=True, check=True)
    child_env = json.loads(child.stdout)
    from engine import hf_render

    calls = []

    def record(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(hf_render.subprocess, "run", record)
    hf_render.check_project(tmp_path)
    assert "check" in calls[0][0] and "render" not in calls[0][0]
    for env in (child_env, calls[0][1]["env"]):
        assert set(denied).isdisjoint(env)
        assert all(env[name] == "mock-path" for name in allowed)
        assert env["HYPERFRAMES_NO_TELEMETRY"] == "1"


MUTATIONS = [
    (("left", "question"), "다른질문", ("left", "liquid"), "deep"),
    (("from", "label"), "다른원액", ("from", "icon"), "barrel"),
    (("stamp",), "다른도장", ("stamp_on_beat",), 0),
    (("benefit_chip",), "다른효과", ("multiply_count",), 4),
    (("notes", 2, "label"), "다른향", ("notes", 2, "beat"), 0),
    (("pour", "label"), "다른와인", ("target", "tint"), "amber"),
    (("chips", 0), "다른과일", ("notes", 0, "icon"), "cherries"),
    (("many", "chip"), "다른비교", ("many", "count"), 4),
    (("rows", 0, "label"), "다른방법", ("rows", 0, "steps", 0), "glass:deep"),
    (("exception_chip",), "다른예외", ("exception_on_beat",), 0),
    (("search", "hint"), "다른검색", ("search", "on_beat"), 0),
    (("left", "label"), "다른투표", ("left", "liquid"), "deep"),
]


def loaded():
    def read(relative):
        return json.loads((SAMPLE / relative).read_text(encoding="utf-8"))
    return read("episode.example.json"), read("assets/vo/vo.json")


def change(obj, path, value):
    for key in path[:-1]:
        obj = obj[key]
    obj[path[-1]] = value


@pytest.mark.parametrize("index,mutation", tuple(enumerate(MUTATIONS)))
def test_each_template_responds_to_slot_and_beat_edits(index, mutation):
    episode, voices = loaded()
    scene = episode["scenes"][index]
    original = build_timeline(episode, voices)["scenes"][index]
    before = composition(scene, original, {}, first=index == 0)[0]
    first_path, text, second_path, value = mutation
    change(scene["slots"], first_path, text)
    first = composition(scene, original, {}, first=index == 0)[0]
    assert text in first and text not in before
    change(scene["slots"], second_path, value)
    second = composition(scene, original, {}, first=index == 0)[0]
    assert first != second
    scene["beats"][0]["text"] = "<script>새자막</script>"
    final = composition(scene, original, {}, first=index == 0)[0]
    assert "&lt;script&gt;새자막&lt;/script&gt;" in final and "<script>새자막</script>" not in final


def test_chapter_title_and_timing_follow_input():
    episode, voices = loaded()
    schedule = build_timeline(episode, voices)
    assert "통이 뭐길래?" in frame_html(episode, schedule, [])
    episode["chapters"][1]["title"] = "다른 제목"
    voices[0]["end"] += 0.2
    moved = build_timeline(episode, voices)
    html = frame_html(episode, moved, [])
    assert "다른 제목" in html and "통이 뭐길래?" not in html
    assert f'{moved["scenes"][1]["start"] + .05:.2f}' in html
    assert moved["scenes"][1]["start"] - schedule["scenes"][1]["start"] == pytest.approx(.2)
