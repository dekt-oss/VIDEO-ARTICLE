"""시각 컴포넌트 레지스트리 (작업지시서 영상엔진품질 v3 §7).

무엇을 푸는가: 지금 "어떤 화면을 그릴지"가 `board_render._draw_frame` 안의 보드 이름 if 분기
4개에 하드코딩돼 있다. 새 표현을 넣으려면 그 분기를 늘려야 하고, **어떤 수치가 어떤 파라미터로
들어가야 하는지**를 아무도 선언하지 않아서 근거 없는 값이 화면에 그려지는 것을 막을 지점이 없다.

이 모듈은 그 계약을 데이터로 만든다:
  · 컴포넌트마다 **필수 파라미터**와 **근거 필수 여부**를 선언한다
  · 의도(intent) → 컴포넌트 라우팅 표를 둔다(보드 이름 if 분기를 대체할 자리)
  · 실패 시 내려갈 `fallback_component` 를 선언한다(§8-2 실패 정책의 재료)

★ 어휘를 새로 만들지 않는다 — 이것이 이 파일의 가장 중요한 설계 결정이다.
  지시서 §7-1 은 `core_v1` 8종(step_line_chart·progress_vs_target·counter_number…)을 요구했지만,
  저장소에는 **같은 역산 결과가 이미 두 벌 있다**: `config.FIN_CHART_TEMPLATES` 5종과
  `engine/fin_charts/types.py` 의 파라미터 dataclass 들. 여기에 §7-1 이름을 더하면 어휘가 세 벌이
  된다. 그래서 **기존 이름(step_climb·dual_marker·gauge_fill·number_count·race_bar)을 정본**으로
  삼고, 지시서 이름은 `spec_alias` 로 문서에만 남긴다.

★ `fin_charts` 의 산출 계약(`ManimSceneSpec`)은 쓰지 않는다. 저장소는 Manim 을 의도적으로
  배제했고(board_render.py 헤더), CLAUDE.md 가 `data_viz`→Manim 경로 제거를 이미 기록했다.
  **파라미터 어휘만 재사용하고 렌더는 PIL(board_render)로 통일한다.**

★ 순수 모듈이다 — PIL·네트워크·DB 를 모른다. 그리기는 board_render 가 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import config

# ─────────────────────────────────────────────────────────────
# 레코드 타입
# ─────────────────────────────────────────────────────────────
# 애니메이션 계약(§7-2). board_motion.Step.progress 가 측정 지점이다.
#   type            — 이 컴포넌트가 시간에 따라 무엇을 하는가
#   min_change_ratio— 첫 프레임 대비 끝 프레임이 최소 이만큼은 달라져야 한다.
#                     0 이면 "움직이지 않아도 된다"(정적 카드류). §9 Q3 이 이 값으로 판정한다.
@dataclass(frozen=True)
class AnimationContract:
    type: str
    min_change_ratio: float = 0.0


@dataclass(frozen=True)
class ComponentSpec:
    """컴포넌트 1종의 계약. **값이 아니라 계약만** 담는다(값은 Fact Sheet 에서 온다)."""

    component: str
    version: str
    supported_intents: tuple[str, ...]
    required_params: tuple[str, ...]
    optional_params: tuple[str, ...] = ()
    # ★ 수치를 화면에 그리는 파라미터. 이 이름들은 **evidence_refs 없이 통과할 수 없다**(§7-2 B2).
    #   "근거 없는 숫자를 크게 띄우지 않는다"를 타입 레벨에서 강제하는 지점이다.
    evidence_backed_params: tuple[str, ...] = ()
    fallback_component: str | None = None
    # ★ §8-2 실패 정책의 나머지 절반이다. fallback_component 가 "못 그렸을 때 뭘로 내려가나"
    #   라면 이쪽은 "그것마저 없을 때 얼마나 큰일인가"다 — 둘이 붙어 있어야 한다.
    #   지시서 기본값: 핵심 수치·차트·회사명·출처·자막=critical / 맥락·로고·인용 배지=important
    #   / 입자·글로우=decorative. 기본이 critical 인 이유는, 새 컴포넌트를 등록하면서 값을
    #   빼먹었을 때 **덜 위험한 쪽으로 조용히 새지 않게** 하기 위해서다.
    criticality: str = "critical"
    animation: AnimationContract = field(default_factory=lambda: AnimationContract("none"))
    # 지시서 §7-1 이 쓴 이름. 정본이 아니라 **문서 상호참조용**이다.
    spec_alias: str = ""
    # 아직 그리는 코드가 없는 것은 True. 라우터가 fallback 으로 내린다(§8-2).
    draft: bool = False


# ─────────────────────────────────────────────────────────────
# core 등록표
# ─────────────────────────────────────────────────────────────
CORE_COMPONENTS: dict[str, ComponentSpec] = {
    # ── 이미 PIL 로 구현돼 있는 것들 ───────────────────────────
    "number_count": ComponentSpec(
        component="number_count",
        version="v1",
        spec_alias="counter_number / big_number_card",
        supported_intents=("headline_number", "valuation"),
        required_params=("value_ref",),
        optional_params=("warn", "count_dur_sec", "label", "compare_ref"),
        evidence_backed_params=("value_ref", "compare_ref"),
        fallback_component="text_core",
        # 카운트업은 숫자가 0 → 목표값까지 오른다. 거의 전 구간이 바뀐다.
        animation=AnimationContract("count_up", 0.6),
    ),
    "race_bar": ComponentSpec(
        component="race_bar",
        version="v1",
        spec_alias="dual_fact_align",
        supported_intents=("compare", "growth"),
        required_params=("entry_refs", "attribution_badge"),
        optional_params=("breakaway_index", "unit"),
        evidence_backed_params=("entry_refs",),
        fallback_component="number_count",
        animation=AnimationContract("bar_grow", 0.5),
    ),
    "dual_marker": ComponentSpec(
        component="dual_marker",
        version="v1",
        spec_alias="progress_vs_target",
        supported_intents=("target_vs_current",),
        required_params=("current_ref", "target_ref"),
        optional_params=("badge",),
        evidence_backed_params=("current_ref", "target_ref"),
        fallback_component="number_count",
        # ★ 그리는 코드가 **없다** — board_render.draw_component 에 dual_marker 분기가 없어
        #   끝의 `return None` 으로 떨어진다. draft=True 를 안 달아 두면 allow_draft=False
        #   가드가 이걸 못 막아서, target_vs_current 로 라우팅하는 순간 빈 화면이 나간다.
        #   (등록만 하고 구현을 안 한 컴포넌트는 여기 표시가 유일한 방어선이다.)
        draft=True,
        animation=AnimationContract("marker_travel", 0.4),
    ),
    # 일반 텍스트 코어 — `_draw_frame` 의 else 분기(`_draw_text_core`)가 이것이다.
    # ★ **최종 폴백은 반드시 구현돼 있어야 한다.** 폴백 사슬 끝이 미구현이면 폴백이 빈 화면을
    #   만든다 — 지금 고치려는 결함(CORE 충전율 0.235 가 통과)과 같은 계열이다.
    "text_core": ComponentSpec(
        component="text_core",
        version="v1",
        spec_alias="(기존 _draw_text_core)",
        supported_intents=("context", "transition", "claim"),
        required_params=("text",),
        optional_params=("metric", "sowhat"),
        fallback_component=None,          # 사슬의 끝
        animation=AnimationContract("fade_in", 0.2),
    ),
    "source_badge": ComponentSpec(
        component="source_badge",
        version="v1",
        spec_alias="quote_source_badge",
        supported_intents=("attribution", "evidence"),
        required_params=("text",),
        optional_params=("speaker", "quote"),
        fallback_component=None,          # 출처는 폴백이 없다 — 없으면 그 자체가 실패다
        animation=AnimationContract("mask_reveal", 0.3),
    ),

    # ── 신규(P2-d 에서 그리기 구현) ───────────────────────────
    "step_climb": ComponentSpec(
        component="step_climb",
        version="v1",
        spec_alias="step_line_chart",
        supported_intents=("trend", "history"),
        required_params=("history_ref",),
        optional_params=("accelerate", "impact_shake_on_last"),
        evidence_backed_params=("history_ref",),
        fallback_component="race_bar",
        animation=AnimationContract("path_draw", 0.5),
    ),
    "gauge_fill": ComponentSpec(
        component="gauge_fill",
        version="v1",
        spec_alias="progress_vs_target",
        supported_intents=("progress_vs_goal",),
        required_params=("item_refs", "goal_ref"),
        optional_params=("twitch_at_end",),
        evidence_backed_params=("item_refs", "goal_ref"),
        # ★ 예전엔 dual_marker 였다. 그런데 dual_marker 는 그리는 코드가 없어(draft) 폴백
        #   사슬의 한 단계가 헛돈다 — 실패했을 때 한 번 더 튕겨야 화면이 나온다.
        #   number_count 는 dual_marker 자신의 폴백이기도 하니 같은 목적지로 바로 간다.
        fallback_component="number_count",
        animation=AnimationContract("gauge_fill", 0.5),
    ),
    "strike_reveal": ComponentSpec(
        component="strike_reveal",
        version="v1",
        spec_alias="strikethrough_reveal",
        supported_intents=("correction", "myth_bust"),
        required_params=("wrong_text", "right_text"),
        optional_params=(),
        fallback_component="text_core",
        animation=AnimationContract("strike_then_reveal", 0.4),
    ),
    "section_kicker": ComponentSpec(
        component="section_kicker",
        version="v1",
        spec_alias="section_kicker",
        supported_intents=("transition", "context"),
        required_params=("text",),
        optional_params=("eyebrow",),
        fallback_component="text_core",   # 아직 안 그려진다 — 구현된 텍스트 코어로 내려간다
        # META 밴드 장식이다. 없어도 화면은 성립한다 — 지시서의 "인용 배지·로고=important".
        criticality="important",
        animation=AnimationContract("wipe_in", 0.3),
    ),
}


# 의도(intent) → 컴포넌트. `_draw_frame` 의 보드 이름 if 분기를 대체할 자리다.
# ★ 보드 이름을 지우지 않는다 — 기존 지시서 데이터가 그 이름으로 저장돼 있다. 보드 → intent
#   파생만 두고, intent 로 컴포넌트를 고른다. 두 단계로 나눠야 새 표현을 넣을 때 저장된
#   데이터를 건드리지 않는다.
INTENT_BY_BOARD: dict[str, str] = {
    "NUMBER_BOARD": "headline_number",
    "VALUATION_BOARD": "valuation",
    "CHART_BOARD": "compare",
    "COMPARISON_BOARD": "compare",
    "EVIDENCE_BOARD": "evidence",
    # ★ MECHANISM·HOOK 은 지금 `context`(→ text_core)다. 이 둘의 자연스러운 의도는
    #   progress_vs_goal·trend 지만, 그 컴포넌트(gauge_fill·step_climb)가 아직 안 그려진다.
    #   P2-e 의 합격기준이 **화면 불변**이라 오늘 실제로 나가는 화면(텍스트 코어)에 맞춰 둔다.
    #   → P2-d 에서 두 컴포넌트를 구현하면 그때 progress_vs_goal·trend 로 넘긴다.
    "MECHANISM_BOARD": "context",
    "HOOK_BOARD": "context",
    "CLAIM_BOARD": "context",
    "REPORT_REASON_BOARD": "context",
    "WATCHPOINT_BOARD": "context",
    "CONTEXT_BOARD": "context",
}

COMPONENT_BY_INTENT: dict[str, str] = {
    "headline_number": "number_count",
    "valuation": "number_count",
    "compare": "race_bar",
    "growth": "race_bar",
    "target_vs_current": "dual_marker",
    "evidence": "source_badge",
    "attribution": "source_badge",
    "trend": "step_climb",
    "history": "step_climb",
    "progress_vs_goal": "gauge_fill",
    "correction": "strike_reveal",
    "myth_bust": "strike_reveal",
    # ★ 이 표는 **CORE 밴드에 무엇을 그릴지**를 고른다. section_kicker 는 META 밴드 장식이라
    #   여기 오면 안 된다 — 실제로 잠깐 넣었더니 CORE 가 통째로 비었고 골든 대조가 잡았다.
    #   META·SOURCE 밴드는 CORE 와 **함께** 그려지는 것이지 대신 그려지는 것이 아니다(P2-f).
    "transition": "text_core",
    "context": "text_core",
}

# CORE 밴드 라우팅 대상이 아닌 컴포넌트. 자기 밴드에 CORE 와 나란히 그려진다.
BAND_COMPONENTS: dict[str, str] = {
    "META": "section_kicker",
    "SOURCE": "source_badge",
}


# ─────────────────────────────────────────────────────────────
# 조회
# ─────────────────────────────────────────────────────────────
def get_component(name: str) -> ComponentSpec:
    """이름 → 스펙. 등록되지 않은 이름은 조용히 넘기지 않는다(youtube_channels.get_channel 관례)."""
    spec = CORE_COMPONENTS.get(str(name or ""))
    if spec is None:
        known = ", ".join(sorted(CORE_COMPONENTS))
        raise KeyError(f"등록되지 않은 컴포넌트: {name!r} (등록됨: {known})")
    return spec


def intent_for_board(board: str) -> str:
    """보드 이름 → 의도. 모르는 보드는 'context'(가장 안전한 최종 폴백)로 본다."""
    return INTENT_BY_BOARD.get(str(board or "").upper(), "context")


# 보드가 의미를 **강하게** 규정하는 것들. 데이터 모양으로 뒤집지 않는다 —
# NUMBER_BOARD 는 이름 그대로 숫자가 주인공이고, EVIDENCE_BOARD 는 인용 귀속이다.
FIXED_INTENT_BOARDS: frozenset[str] = frozenset({
    "NUMBER_BOARD", "VALUATION_BOARD", "CHART_BOARD", "COMPARISON_BOARD", "EVIDENCE_BOARD",
})

# 시계열이라고 부르려면 점이 몇 개여야 하는가. 2개는 '비교'지 '추이'가 아니다 —
# step_climb 은 2개로도 그려지지만, 그걸 추이로 읽히게 하면 화면이 과장한다.
TREND_MIN_SERIES: int = 3


def resolve_for_cut(board: str, *, series_len: int = 0, period_like: bool = False,
                    allow_draft: bool = False) -> ComponentSpec:
    """컷 하나가 실제로 그릴 컴포넌트 (§7-3 의미 라우팅).

    ★ 지시서 §7-3 은 보드 이름 표가 아니라 **의미** 표다("시계열→step_line_chart …").
      그래서 서술형 보드는 컷이 **선언한 데이터의 모양**으로 의도를 정한다. 선언이 없으면
      오늘과 똑같이 text_core 다 — 데이터가 없는데 차트를 그리는 일은 없다.

    ★★ 지금 승격하는 것은 **trend → step_climb 하나뿐이다.** 나머지를 안 켠 이유를 남긴다:
       · gauge_fill(progress_vs_goal) — number_claims 에 **'목표' 필드가 없다.** 있는 것은
         comparison_basis/value(비교)뿐이고, items[-1] 을 목표로 가정하면 리포트에 없는
         "현재 → 목표"를 화면이 주장하게 된다. 데이터 모델에 목표가 생긴 뒤에 켠다.
       · race_bar(compare) — 서술형 보드는 DEFAULT_STEPS(title·core·metric)라 이 컴포넌트가
         요구하는 axis·bar0·bar1·diff 단계가 **없다.** 진행률이 전부 0 이라 막대가 안 자라고
         **빈 리스트**를 돌려준다(None 이 아니라서 폴백도 안 걸린다). 그 보드들에 차트
         단계를 주면 stride 가 바뀌어 기존 보드들의 프레임 타이밍이 전부 이동한다.
       · strike_reveal(correction) — 지시서에 "통념 반전" 신호가 없다. §7-4 의 "억지 취소선
         금지"와 정면 충돌한다.
       · dual_marker — 그리는 코드가 없다(draft=True).
       step_climb 만 안전한 이유: 진행률이 `prog("bar1") or prog("core")` 라 core 단계로
       떨어지고, 서술형 보드는 전부 core 를 갖는다.

    series_len  — 컷이 **선언한** number_claims 에서 해소된 계열 수(board_render._chart_items).
    period_like — 그 라벨들이 기간처럼 보이는가(1Q26·2026년·FY26 …). 시계열의 최소 조건이다.
    """
    b = str(board or "").upper()
    if b in FIXED_INTENT_BOARDS:
        return resolve_for_board(b, allow_draft=allow_draft)
    if series_len >= TREND_MIN_SERIES and period_like:
        return resolve("trend", allow_draft=allow_draft)
    return resolve_for_board(b, allow_draft=allow_draft)


def resolve(intent: str, *, allow_draft: bool = True) -> ComponentSpec:
    """의도 → 실제로 그릴 컴포넌트.

    ★ allow_draft=False 면 아직 그리는 코드가 없는 컴포넌트(draft=True)를 fallback 으로 내린다.
      P2-d 가 끝나기 전에도 라우터를 켤 수 있게 하는 스위치다 — 미구현 컴포넌트로 라우팅해
      **빈 화면**이 나가는 것이 지금 고치려는 결함(CORE 충전율 0.235)과 같은 계열이다.
    """
    name = COMPONENT_BY_INTENT.get(str(intent or ""), "section_kicker")
    spec = get_component(name)
    seen = {spec.component}
    while not allow_draft and spec.draft and spec.fallback_component:
        if spec.fallback_component in seen:
            break                      # 폴백 순환 — 더 내려가지 않는다
        seen.add(spec.fallback_component)
        spec = get_component(spec.fallback_component)
    return spec


def resolve_for_board(board: str, *, allow_draft: bool = True) -> ComponentSpec:
    return resolve(intent_for_board(board), allow_draft=allow_draft)


# ─────────────────────────────────────────────────────────────
# 검증 — §7-2 B2 "근거 없는 param 0"
# ─────────────────────────────────────────────────────────────
def validate_params(component: str, params: dict[str, Any],
                    known_fact_ids: set[str] | None = None) -> list[str]:
    """컴포넌트 파라미터 검증. 반환은 토큰 문자열 리스트(report_evidence 관례).

    세 가지를 본다:
      ① 필수 파라미터 누락
      ② 등록되지 않은 파라미터(오타로 값이 조용히 버려지는 것을 막는다)
      ③ **수치 파라미터가 실재하는 fact_id 를 가리키는가** — 이것이 §7-2 B2 의 핵심이다.
         known_fact_ids 를 주지 않으면 ③은 건너뛴다(참조 대조는 호출자가 재료를 줄 때만).
    """
    spec = get_component(component)
    out: list[str] = []
    given = dict(params or {})

    for key in spec.required_params:
        val = given.get(key)
        if val is None or val == "" or val == []:
            out.append(f"param_missing:{key}")

    allowed = set(spec.required_params) | set(spec.optional_params)
    for key in given:
        if key not in allowed:
            out.append(f"param_unknown:{key}")

    if known_fact_ids is not None:
        for key in spec.evidence_backed_params:
            for ref in _as_refs(given.get(key)):
                if ref not in known_fact_ids:
                    out.append(f"evidence_ref_unknown:{key}:{ref}")
    return sorted(set(out))


def _as_refs(value: Any) -> list[str]:
    """단일 ref 든 ref 목록이든 문자열 목록으로."""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v or "").strip()]
    return [str(value)]


def registered_names() -> tuple[str, ...]:
    return tuple(sorted(CORE_COMPONENTS))


def implemented_names() -> tuple[str, ...]:
    """그리는 코드가 실제로 있는 것만. P2-d 가 끝나면 registered_names 와 같아진다."""
    return tuple(sorted(n for n, s in CORE_COMPONENTS.items() if not s.draft))


# 기존 어휘와의 연결을 코드로 고정한다 — 이름이 갈라지면 여기서 먼저 깨진다.
CANONICAL_CHART_TEMPLATES: tuple[str, ...] = config.FIN_CHART_TEMPLATES
