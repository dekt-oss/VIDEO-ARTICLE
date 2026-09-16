"""버전3 애니(작동원리 도해) — 파라미터 씬 템플릿 (M-V6, DV5).

★ 자유 형식 Manim 코드 생성 금지. 미리 짠 씬 템플릿 4종에 값만 채운다(결정론·컴파일 안정).
템플릿은 Text(pango·한글 OK)·도형·Arrow 와 FadeIn/Create/Write 만 쓴다.
LaTeX 의존(Tex/MathTex/DecimalNumber)은 쓰지 않는다(러너에 LaTeX 없음, 숫자도 Text 로).

이 모듈 상단(select_template 등)은 순수 로직이라 manim 미설치 환경에서도 import 된다.
실제 렌더(render_cut_clip)만 manim 을 지연 import 한다. → 순수 테스트/엔진 import 는 manim 불필요.
그림 산출은 무음 클립(AI 오디오 끔 원칙 — 나레이션은 후단 조립에서).
"""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Any

from . import claim_viz, config
from .util import log

TEMPLATE_NAMES = ("title", "arrow_flow", "step_reveal", "number_compare")

# 템플릿 선택 키워드(visual_prompt 소문자 부분일치).
_ARROW_KEYS = ("arrow", "flow", "→", "화살표", "흐름", "pipeline", "input", "output", "데이터 흐름", "단계별")
_STEP_KEYS = ("step", "단계", "순서", "stage", "절차", "과정")
_NUMBER_KEYS = ("compare", "비교", " vs", "수치", "number", "증가", "감소", "%", "배", "대비")


def _short(s: str, n: int = 16) -> str:
    s = (s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _steps_from(narration: str, max_steps: int = 3) -> list[str]:
    """나레이션을 짧은 불릿으로 분할(근거 밖 내용 생성 없이 원문 조각만).

    ★ 숫자 사이의 마침표·쉼표(예 "40.5%", "1,000")로는 쪼개지 않는다 — 문장부호로만 분할.
    """
    import re
    # . , 는 앞뒤가 숫자가 아닐 때만 분할점. 。!?·〕 개행은 항상 분할.
    parts = [p.strip() for p in re.split(r"(?<!\d)[.,](?!\d)|[。!?·\n]", narration or "") if p and p.strip()]
    steps = [_short(p, 20) for p in parts[:max_steps]]
    return steps or [_short(narration, 20) or "핵심"]


def select_template(cut: dict[str, Any], index: int, lang: str = "ko",
                    fact_sheet: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    """컷 → (템플릿 이름, params). 순수·결정론적.

    labels 는 narration/visual_prompt(이미 Fact Sheet 근거) 조각만 사용 — 새 사실 생성 금지.
    도해는 '구조'를 보여주고 구체 주장은 나레이션/자막(근거)이 담당한다.
    lang: ⑤클립에 얹히는 텍스트를 언어별로(narration_{lang}, 없으면 ko 폴백) — 언어별 재렌더.

    ★ fact_sheet(Claim Ledger)를 주면 number_compare 의 수치를 원장에서 **해소**한다.
      주지 않거나 해소에 실패하면 수치 차트를 만들지 않는다 — 예전 하드코딩 값(40/75)이
      화면에 그려지면 논문에 없는 숫자가 영상에 박힌다(환각 방지 불변식 위반).
    """
    vp = (cut.get("visual_prompt") or "").lower()
    narr = str(cut.get(f"narration_{lang}") or cut.get("narration_ko") or "")
    if index == 0:
        return "title", {"title": _short(narr or cut.get("title") or "오늘의 논문", 20)}
    if any(k in vp for k in _ARROW_KEYS):
        return "arrow_flow", {"nodes": ["입력", "처리", "출력"], "caption": _short(narr, 18)}
    if any(k in vp for k in _NUMBER_KEYS):
        params = claim_viz.number_compare_params(cut, fact_sheet)
        if params:
            return "number_compare", {**params, "title": params["title"] or _short(narr, 18)}
        # 원장에서 수치를 못 얻으면 수치 차트를 포기한다("그럴듯한 기본값" 금지).
        return "step_reveal", {"title": _short(narr, 18), "steps": _steps_from(narr)}
    if any(k in vp for k in _STEP_KEYS):
        return "step_reveal", {"title": _short(narr, 18), "steps": _steps_from(narr)}
    return "step_reveal", {"title": "", "steps": _steps_from(narr)}


# ─────────────────────────────────────────────────────────────
# 실제 Manim 렌더 (지연 import) — manim 설치된 곳(CI 러너/로컬)에서만.
# ─────────────────────────────────────────────────────────────
def _scene_classes() -> dict[str, Any]:
    """manim 을 지연 import 하고 파라미터 씬 클래스 4종을 정의해 반환."""
    from manim import (
        Arrow, Create, FadeIn, RoundedRectangle, Rectangle, Scene, Text, VGroup, Write,
        BLUE, GREEN, WHITE, DOWN, UP, LEFT, RIGHT,
    )

    font = config.MANIM_FONT
    bg = config.MANIM_BG_COLOR

    def _t(txt: str, scale: float = 0.6) -> Any:
        return Text(txt or "", font=font).scale(scale)

    class _Base(Scene):
        params: dict[str, Any] = {}

        def setup(self) -> None:
            self.camera.background_color = bg

    class TitleCard(_Base):
        def construct(self) -> None:
            title = _t(self.params.get("title") or "오늘의 논문", 0.95)
            self.play(FadeIn(title, shift=UP * 0.4))
            self.play(Write(title))  # 이중 강조
            self.wait(1.0)

    class ArrowFlow(_Base):
        def construct(self) -> None:
            nodes = self.params.get("nodes") or ["입력", "처리", "출력"]
            boxes = VGroup()
            labels = VGroup()
            colors = [BLUE, GREEN, WHITE]
            for i, name in enumerate(nodes[:3]):
                box = RoundedRectangle(width=4, height=1.6, corner_radius=0.25,
                                       color=colors[i % len(colors)])
                box.shift(DOWN * (i * 2.4 - 2.4))
                boxes.add(box)
                labels.add(_t(str(name), 0.7).move_to(box))
            for i, (box, lab) in enumerate(zip(boxes, labels)):
                self.play(FadeIn(box), Write(lab), run_time=0.7)
                if i < len(boxes) - 1:
                    pass
            for i in range(len(boxes) - 1):
                self.play(Create(Arrow(boxes[i].get_bottom(), boxes[i + 1].get_top(),
                                       color=WHITE)), run_time=0.5)
            self.wait(0.8)

    class StepReveal(_Base):
        def construct(self) -> None:
            title = self.params.get("title") or ""
            steps = self.params.get("steps") or ["핵심"]
            group = VGroup()
            if title:
                group.add(_t(title, 0.8))
            for s in steps[:4]:
                group.add(_t("• " + str(s), 0.55))
            group.arrange(DOWN, aligned_edge=LEFT, buff=0.5)
            for m in group:
                self.play(FadeIn(m, shift=RIGHT * 0.3), run_time=0.6)
            self.wait(0.8)

    class NumberCompare(_Base):
        def construct(self) -> None:
            title = self.params.get("title") or ""
            # ★ 기본값을 두지 않는다. 예전엔 [("전", 40), ("후", 75)] 가 폴백이었는데, 그러면
            #   원장에 없는 숫자가 화면에 그려진다 — 시청자는 그걸 논문의 수치로 읽는다.
            #   값이 없으면 막대 없이 제목만 나간다(select_template 이 애초에 여기 오지 않게 막는다).
            items = self.params.get("items") or []
            grp = VGroup()
            if title:
                grp.add(_t(title, 0.7))
            bars = VGroup()
            for label, val in items[:3]:
                try:
                    h = max(0.5, min(5.0, float(val) / 20.0))
                except (TypeError, ValueError):
                    h = 1.0
                bar = Rectangle(width=1.4, height=h, color=BLUE, fill_opacity=0.7)
                col = VGroup(bar, _t(str(val), 0.5), _t(str(label), 0.45))
                col.arrange(DOWN, buff=0.2)
                bars.add(col)
            bars.arrange(RIGHT, buff=1.2, aligned_edge=DOWN)
            grp.add(bars)
            grp.arrange(DOWN, buff=0.8)
            if title:
                self.play(Write(grp[0]))
            for col in bars:
                self.play(FadeIn(col, shift=UP * 0.3), run_time=0.6)
            self.wait(0.8)

    return {"title": TitleCard, "arrow_flow": ArrowFlow,
            "step_reveal": StepReveal, "number_compare": NumberCompare}


def render_cut_clip(cut: dict[str, Any], header: dict[str, Any],
                    out_path: str, duration: int, lang: str = "ko",
                    fact_sheet: dict[str, Any] | None = None) -> str:
    """컷 → Manim 무음 클립 mp4. select_template 로 씬·params 선택 후 렌더. 반환: out_path."""
    from manim import tempconfig

    name, params = select_template(cut, int(cut.get("cut_no", 1)) - 1, lang, fact_sheet)
    scene_cls = _scene_classes()[name]
    configured = type(f"{name}_cfg", (scene_cls,), {"params": params})

    work = tempfile.mkdtemp(prefix="manim_")
    base = "clip"
    with tempconfig({
        "pixel_width": config.RENDER_WIDTH,
        "pixel_height": config.RENDER_HEIGHT,
        "frame_rate": config.RENDER_FPS,
        "media_dir": work,
        "output_file": base,
        "format": "mp4",
        "disable_caching": True,
        "verbosity": "ERROR",
        "background_color": config.MANIM_BG_COLOR,
    }):
        configured().render()

    produced = None
    for root, _dirs, files in os.walk(work):
        for f in files:
            if f.endswith(".mp4"):
                produced = os.path.join(root, f)
                break
    if not produced:
        raise RuntimeError(f"Manim 출력 mp4 없음(template={name})")
    shutil.copy(produced, out_path)
    log.info("Manim 클립: template=%s cut=%s → %s", name, cut.get("cut_no"), out_path)
    return out_path
