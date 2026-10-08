"""지시서 엔진 버전 — 옛 엔진으로 만든 지시서를 화면이 가려낼 수 있게 (2026-09-29, 운영자 지시).

계기: 발뒤꿈치 편이 영상 배정 수정(#73) 머지 **7분 전**에 만든 지시서로 승인·렌더돼 $5.19 를 썼다.
지시서는 만든 순간의 스냅샷이라 머지가 바꿔 주지 않는다. 그래서:
  ① 정규화가 헤더에 `engine_version` 을 찍는다.
  ② 웹(decision.ts)이 같은 상수와 비교해 옛 것이면 ⛔ + [지시서 재생성] 을 띄운다.
  ③ 프롬프트 문자열이 바뀌었는데 버전을 안 올리면 **여기서 실패한다** — 올리는 것을 잊는 것이 이 장치의
     유일한 구멍이라, 사람 기억 대신 테스트가 잡는다.
"""

from __future__ import annotations

import hashlib
import pathlib
import re

from engine import config, directive as dv, photo_prompt as pp

ROOT = pathlib.Path(__file__).resolve().parents[1]

# ★ 프롬프트를 바꿨으면: config.DIRECTIVE_ENGINE_VERSION 과 web/lib/work/decision.ts 의 같은 상수를 오늘 날짜로
#   올리고, 아래 두 값을 새로 적는다(실패 메시지가 새 지문을 알려 준다).
RECORDED = {"version": "2026-10-08", "prompt_fingerprint": "3fa508a2138d5c49"}


def _fingerprint() -> str:
    blob = "".join(pp.system_prompt(f) + pp.guidance(f) for f in ("paper", "report"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def test_changing_the_prompt_requires_bumping_the_engine_version():
    fp = _fingerprint()
    if fp != RECORDED["prompt_fingerprint"]:
        assert config.DIRECTIVE_ENGINE_VERSION != RECORDED["version"], (
            f"실사형 프롬프트가 바뀌었다(지문 {fp}). config.DIRECTIVE_ENGINE_VERSION 과 web/lib/work/decision.ts 의 "
            f"DIRECTIVE_ENGINE_VERSION 을 올리고, 이 파일의 RECORDED 를 새 버전·지문으로 바꿔라 — 안 올리면 옛 지시서가 "
            f"최신으로 보여 그대로 렌더된다.")
        raise AssertionError(f"버전은 올렸다. RECORDED 를 {{'version': '{config.DIRECTIVE_ENGINE_VERSION}', "
                             f"'prompt_fingerprint': '{fp}'}} 로 바꿔라.")
    assert config.DIRECTIVE_ENGINE_VERSION == RECORDED["version"]


def test_web_and_engine_agree_on_the_version():
    ts = (ROOT / "web" / "lib" / "work" / "decision.ts").read_text(encoding="utf-8")
    m = re.search(r'export const DIRECTIVE_ENGINE_VERSION = "([^"]+)";', ts)
    assert m, "decision.ts 에 DIRECTIVE_ENGINE_VERSION 이 없다"
    assert m.group(1) == config.DIRECTIVE_ENGINE_VERSION


def test_every_new_directive_is_stamped():
    obj = {"header": {"hook_ko": "a", "hook_en": "b"},
           "cuts": [{"cut_no": 1, "narration_ko": "질문?", "narration_en": "q", "estimated_sec": 3,
                     "visual_prompt": "x", "visual_role": "REALITY"}]}
    for version in ("photo", "comic"):
        h = dv.normalize_directive(obj, version, cut_max_sec=8)["header"]
        assert h["engine_version"] == config.DIRECTIVE_ENGINE_VERSION, version
        assert "engine_commit" in h


def test_the_screens_show_the_outdated_warning():
    """판정만 있고 화면이 안 부르면 아무것도 안 바뀐다(이 저장소의 단골 실패)."""
    ws = (ROOT / "web" / "components" / "WorkspaceClient.tsx").read_text(encoding="utf-8")
    assert "decision.outdated" in ws and "isOutdatedEngine(h?.engine_version)" in ws   # 결정 바 + 승인 확인창
    assert "engineVersion: s.directive?.header?.engine_version" in ws
    # ★ 지시서 칸의 배너는 2026-09-30 UI 정리(#81)로 뺐다 — 같은 경고가 결정 바·본문·승인 확인창 **세 번**
    #   나왔다. 결정 바는 스크롤해도 늘 보이므로(sticky) 거기와 승인 확인창 두 곳이면 충분하다(위 두 줄이 지킨다).
    #   본문에 다시 붙이면 3중 반복이 돌아온다.
    se = (ROOT / "web" / "components" / "SequenceEditor.tsx").read_text(encoding="utf-8")
    assert "isOutdatedEngine(directive.header?.engine_version)" not in se
