"""실사형(photo) 화면 계약의 **결정론적 검사** (2026-08-29 리뷰 §4·§5).

무엇을 푸는가: 실사형 계약은 프롬프트 문장으로만 존재했다. 모델이 안 지켜도 아무도 몰랐고,
승인 게이트는 비용·길이·claim 커버리지만 봤다. 2026-08-28 실측에서 한 지시서가 계약을
여섯 곳에서 어겼는데 게이트가 잡은 것은 `series_split_required` 하나였다
(`docs/리뷰요청_지시서렌더엔진_v1.md` §3).

이 저장소의 일관된 자세는 **"모델의 자기보고를 믿지 않고 코드가 판정한다"** 이다. 근거 등급·
인용 대조·claim 참조·비용 원장이 전부 그렇게 돼 있는데 **화면 계약만 빠져 있었다.** 여기서 메운다.

설계 원칙 셋:

1. **차단과 경고를 나눈다.** 오탐이 나면 운영자가 게이트를 무시하기 시작하고, 그러면 게이트가
   있으나 마나가 된다. 기계가 확신할 수 있는 것만 차단한다(빈 훅·역할 누락·구조 누락·금지
   프롬프트). 판단이 섞이는 것(도해가 장식적인가)은 경고로 두되, **근거가 둘 이상 겹치면** 차단한다.
2. **사유 코드는 Python 이 정본**이고 web/lib/blockLabels.ts 가 표시 문자열만 미러한다.
   `tests/test_prompt_sync.py` 가 어긋남을 잡는다.
3. **순수 함수.** 네트워크·DB 없음. 지시서 dict 만 보고 판정한다.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from . import config, visual_sequence

# ─────────────────────────────────────────────────────────────
# 사유 코드 (정본). web/lib/blockLabels.ts 가 표시 문자열을 미러한다.
# ─────────────────────────────────────────────────────────────
BLOCK_REASONS: tuple[str, ...] = (
    "photo_hook_missing",              # 상단 고정 부제가 비었다
    "photo_visual_role_missing",       # 역할 선언이 없는 컷이 있다
    "photo_forbidden_screen_request",  # 차트·라벨·화면 숫자를 이미지에 요구했다
    "photo_number_without_overlay",    # 숫자를 말하는데 화면 카드가 없다
    "photo_cut_count_low",             # 목표 길이에 비해 컷이 너무 적다
    "photo_mechanism_missing",         # 도해 컷이 하나도 없다
    "photo_mechanism_spec_missing",    # 도해 컷에 구조(무엇→무엇) 서술이 없다
    "photo_mechanism_decorative",      # 도해가 배경·장식에 그친다(근거 2개 이상 겹칠 때)
    "photo_skeleton_shortfall",        # 코드가 만든 컷 골격보다 컷이 적다(모델이 칸을 합쳤다)
    "photo_role_name_in_prompt",       # 역할명(MECHANISM/REALITY)이 프롬프트에 남아 그림에 글자로 박힌다
    "photo_overlay_year_unverified",   # 화면 카드의 연도가 Fact Sheet 에 없다(지어낸 연도)
    "photo_reuse_without_state_change",  # 재사용인데 화면에서 무엇이 변하는지 안 밝혔다
    "photo_reuse_identical_render",      # 렌더 결과가 기준 컷과 사실상 같은 그림이었다
    "photo_text_request_conflict",       # 같은 프롬프트가 글자를 요구하면서 동시에 금지한다
    "photo_style_word_in_prompt",        # 장면 묘사가 화풍·렌즈 기법을 지시한다(화풍은 코드가 정한다)
    "photo_quoted_label_in_prompt",      # 따옴표 친 라벨 이름 — 그림에 글자로 구워진다
    "photo_mechanism_prompt_detached",   # 도해 구조와 visual_prompt 가 서로 딴 것을 말한다(연구 T1-b)
)
WARNING_REASONS: tuple[str, ...] = (
    "photo_role_balance_off",          # 도해/실사 비율이 권장에서 벗어남
    "photo_video_cut_count_off",       # 영상 컷 수가 권장 범위 밖
    "photo_video_cuts_not_adjacent",   # 영상 컷이 흩어져 I2V 연쇄가 끊긴다
    "photo_cut_too_long",              # 한 컷이 권장 상한보다 길다
    "photo_mechanism_thin",            # 도해가 장식적일 수 있다(근거 1개)
    "photo_mechanism_spec_inherited",  # 재사용 컷이 기준 컷의 구조를 물려받았다(면제)
    "photo_mechanism_structured",       # 어휘는 장식적이나 stage 가 진행을 구조로 선언했다
    "photo_reuse_base_overused",       # 한 기준 컷에서 파생이 너무 많다(그 대상이 화면을 지배)
    "photo_narrative_no_mechanism",    # 대본이 원리를 한 번도 설명하지 않는다(그림만 도해)
    "photo_world_churn",               # 시퀀스마다 새 세계를 만든다(컷 나열이지 시퀀스가 아니다)
    "photo_no_close_scale",            # 축척 사다리에 근접 시점이 없다(크기 대비가 안 생긴다)
    "photo_number_punch_is_a_sentence",  # number_punch 가 수치가 아니라 문장이다
    "photo_source_has_no_mechanism",   # 논문 자체가 왜인지를 말하지 않는다(선별 단계 문제)
    "photo_video_cut_never_moves",     # 영상비를 냈는데 카메라가 HOLD 뿐이다
    "photo_visual_role_backfilled",    # 역할이 비어 코드가 REALITY 로 채웠다
    "photo_video_camera_repaired",     # 영상 컷이 HOLD 뿐이라 코드가 푸시인을 넣었다
    "photo_hook_visual_repeated",      # 훅 두 컷이 같은 그림이다(한 장짜리 훅)
    "photo_subject_dominates",         # 연구 대상(동물·장비)이 화면 시간의 상한을 넘겼다
    "photo_undrawable_difference",     # 차이를 판정 어휘로 적었다(모델은 "건강함"을 못 그린다)
    "photo_optics_normalized",         # 렌즈 어휘를 코드가 배치 표현으로 바꿨다(조용히 하지 않는다)
    "photo_prompt_number_removed",     # 카드가 이미 그리는 퍼센트를 이미지 프롬프트에서 지웠다
    "photo_world_lead_disagrees",      # 세계를 여는 컷이 그 세계를 안 그린다(세계 선언이 죽는다)
    "photo_mechanism_starts_late",     # 원리 설명이 너무 늦게 시작한다(전반부가 통째로 소개)
    "photo_role_claim_mismatch",       # 컷의 역할 라벨이 가리키는 근거와 맞지 않는다
    "photo_mechanism_unlabeled",       # 기전 시퀀스에 범례·캡션이 없다(어느 쪽이 무엇인지 화면이 안 말한다)
)

# ─────────────────────────────────────────────────────────────
# 어휘 (대소문자·복수형·동의어)
# ─────────────────────────────────────────────────────────────
# 화면에 "가짜 숫자·라벨"을 그려 달라는 요구. 생성 모델이 그린 숫자는 근거가 없다.
_FORBIDDEN_SCREEN = re.compile(
    r"\b("
    r"bar\s*charts?|pie\s*charts?|line\s*charts?|charts?|graphs?|plots?|"
    r"dashboards?|infographics?|diagrams?\s+of\s+data|data\s+visuali[sz]ations?|"
    # ★ `axis` 도 **맨몸으로 두지 않는다**(2026-09-03 실측, `meters` 와 같은 계열).
    #   실사형 컷 6 의 "a glowing ring around its axis"(로켓의 **회전축**)가 걸려 승인이
    #   막혔다 — 도표 축을 요구한 적이 없고, 그 컷은 "No on-screen text" 까지 적어 뒀다.
    #   회전축·대칭축·장축은 3D 도해가 당연히 쓰는 말이라 막으면 옳게 한 컷을 벌한다.
    #   도표 축은 아래 형태로만 잡는다. 진짜 차트는 charts?|graphs?|gridlines?|tick marks?
    #   |legends? 가 이미 독립적으로 잡는다.
    r"[xyz]-\s?ax[ei]s|(?:horizontal|vertical|plot|chart|graph|labell?ed|numbered)\s+ax[ei]s|"
    r"ax[ei]s\s+(?:labels?|lines?|ticks?|scales?|showing|marked)|"
    r"legends?|gridlines?|tick\s*marks?|"
    r"labell?ed|labels?|captions?|subtitles?|"
    r"percentage\s*signs?|percent\s*signs?|"
    r"scoreboards?|tickers?|stock\s*tickers?|spreadsheets?|tables?\s+of\s+numbers?|"
    # ★ 로고·워터마크·상표는 **글자를 그려 달라는 요구**다(2026-08-30 Mini Render 실측).
    #   골든B 컷3 이 "research paper with 'arXiv' logo visible" 을 요구했고 화면에
    #   'arXiv' 가 그대로 박혔다. 부정문 목록(_BANNED_NOUN)에는 logos 가 있었는데
    #   **요구 탐지 목록에는 없었다** — 금지는 인정하면서 요구는 못 잡고 있었다.
    r"logos?|watermarks?|brand\s*names?|wordmarks?|"
    # ★ 지도·지구본은 **지리와 지명을 그려 달라는 요구**다(2026-09-14 운영자 실측).
    #   "A world map with Western countries highlighted" 를 요구했더니 ① 나라 경계가 엉망이고
    #   ② "gene marker"·"italy" 같은 **지어낸 글자**가 박혔고 ③ 나레이션은 "서구 데이터"인데
    #   핀이 **전 세계에** 찍혔다. 생성 모델은 지리를 모른다 — 경계·위치가 곧 사실 주장인데
    #   그걸 근거 없이 그린다. 저장 지시서 333컷 중 10컷(3%)이 지도류였다.
    #   ★ "highlighted region" 은 넣지 않는다 — 뇌 도해의 "강조된 영역"이 같은 말을 쓴다.
    r"world\s*maps?|maps?\s+of\s+(?:the\s+)?(?:world|globe|earth|europe|asia|africa|america|countries)|"
    r"(?:political|geographic(?:al)?|country|continent(?:al)?)\s+maps?|globes?|"
    r"highlighted\s+(?:countries|continents?|nations?)|"
    # ★ 디지털 표시장치는 **숫자를 그려 달라는 요구**다(2026-08-30 채팅 실측).
    #   "a digital timer overlay next to it displays a consistent rotation period" 가
    #   통과했고 화면에 `3.456 s` 가 그대로 박혔다. Phase 0 의 `35°` 번인과 같은 계열이다.
    #   차트·라벨은 잡으면서 계기판·타이머는 못 잡고 있었다.
    r"timers?|counters?|stopwatch(?:es)?|readouts?|gauges?|dials?|"
    # ★ `meters?` 를 **맨몸으로 두지 않는다**(2026-09-02 실측). 계기판을 잡으라고 넣은
    #   단어인데 영어에서 meter 는 압도적으로 **길이 단위**다. 실측: 실사형 컷 12 의
    #   "a large, circular crater, approximately 40 meters in diameter" 가 걸려
    #   승인이 막혔다 — 분화구의 실제 크기를 말한 것이고 화면에 계기판을 요구한 적이 없다.
    #   물리적 크기 서술은 실사형이 **권장하는** 표현이라(크기 대비·스케일 비교) 이걸
    #   막으면 게이트가 옳게 한 컷을 벌한다. 그래서 **계기 의미일 때만** 잡는다.
    #   원래 목표였던 "digital timer overlay … displays" 는 timers?·displays\s+showing
    #   이 그대로 잡는다(아래 테스트가 이 두 가지를 같이 박아 둔다).
    r"(?:power|light|pressure|volt|amp|VU|level|speed)\s+meters?|"
    r"meters?\s+(?:showing|reading|displaying|indicating)|"
    r"digital\s+displays?|displays?\s+(?:showing|reading)|numeric\s+displays?"
    r")\b", re.I)
# 숫자를 화면에 써 달라는 요구("15%", "showing 42", "with numbers")
_FORBIDDEN_NUMBER_ON_SCREEN = re.compile(
    r"(\d+\s*%|\bpercent\b|\bnumbers?\s+(?:on\s+screen|displayed|shown)|"
    r"\bwith\s+the\s+(?:number|figure)\b|\btext\s+overlay\b)", re.I)

# 도해가 "설명을 하는" 구조를 요구하는 어휘. 하나도 없으면 그림이 배경일 가능성이 높다.
_STRUCTURAL = re.compile(
    r"\b("
    r"cutaways?|cross[-\s]?sections?|sectional|"
    r"exploded(?:\s+views?)?|dissect(?:ed|ion)?|peeled|"
    r"layers?|layered|internal|inside|interior\s+structure|"
    r"step[-\s]?by[-\s]?step|sequences?|stages?|assembl(?:y|ing|ed)|"
    r"flows?|flowing|pathways?|routes?|traced?|tracing|"
    r"before\s+and\s+after|side[-\s]?by[-\s]?side|comparisons?|"
    r"scale\s+comparison|"
    r"mechanisms?|how\s+it\s+works"
    r")\b", re.I)
# 스키마 역할명이 프롬프트 본문에 남은 것. 이미지 모델은 대문자 토큰을 "화면에 쓸 라벨"로 읽는다.
#
# ★ 대소문자를 **가린다**(re.I 를 쓰지 않는다). 소문자 "mechanism" 은 평범한 영어 낱말이고,
#   바로 위 _STRUCTURAL 이 그것을 **좋은 신호로 세고 있다**("cutaway showing the mechanism of…").
#   대소문자를 무시하면 이 게이트가 옳게 쓴 프롬프트를 차단하게 되고, 그러면 운영자가 게이트를
#   무시하기 시작한다 — 이 파일 맨 위 설계원칙 1이 막으려는 바로 그 실패다.
#   실제로 그림에 박힌 것은 스키마 값 그대로의 대문자 토큰이었다.
_ROLE_NAME_LEAK = re.compile(r"\b(MECHANISM|REALITY)\b")
# 장식·분위기 어휘. 도해에 이것만 있으면 "관련 있는 그림"이지 설명이 아니다.
_DECORATIVE = re.compile(
    r"\b("
    r"abstract|conceptual|symbolic|metaphor(?:ical)?|"
    r"glowing|glow|aura|particles?|floating|swirling|ethereal|"
    r"atmospheric|moody|cinematic\s+mood|dramatic\s+lighting|"
    r"wide\s+shots?\s+of|establishing\s+shots?|"
    r"modern\s+(?:office|factory|laboratory|lab)\s+interior|"
    r"pristine|neatly\s+arranged|out\s+of\s+focus|blurred\s+background"
    r")\b", re.I)

# 나레이션이 "소리 내 읽는 수치"인가. 연도·순번은 제외하려고 단위를 요구한다.
# ★ EN 도 함께 본다(Fable Review 2026-08-29): KO 만 검사하면 **영어 나레이션에만 숫자를 두는
#   것으로 게이트를 우회**할 수 있었다. EN 영상도 같은 화면으로 렌더되므로 같은 규칙이 필요하다.
_SPOKEN_NUMBER = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:%|퍼센트|프로|배|명|건|개|억|조|만|천|원|달러|초|분|시간|년|개월|일|배로|배나)")
#   ★ `\b` 는 **단어 단위에만** 붙인다. `%` 뒤에 붙이면 "15%" 가 매치되지 않는다
#     (`%` 는 비단어 문자라 문자열 끝과의 사이에 경계가 없다 — Fable Review 에서 이 정규식이
#     조용히 아무것도 안 잡는 것을 잡아냈다).
_SPOKEN_NUMBER_EN = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:%|(?:percent|percentage\s+points?|times|fold|"
    r"people|participants?|patients?|subjects?|cases?|"
    r"dollars?|won|billion|million|trillion|"
    r"seconds?|minutes?|hours?|days?|weeks?|months?)\b)", re.I)


def _speaks_a_number(cut: dict[str, Any]) -> bool:
    """KO/EN 어느 쪽이든 숫자를 소리 내 읽으면 화면 카드가 필요하다."""
    return bool(_SPOKEN_NUMBER.search(str(cut.get("narration_ko") or ""))
                or _SPOKEN_NUMBER_EN.search(str(cut.get("narration_en") or "")))
# 화면 카드로 인정하는 오버레이 종류.
# ★ 목록을 **직접 쓰지 않고 config.OVERLAY_TYPES 에서 가져온다**(2026-08-29 실측 오탐):
#   내가 손으로 적은 목록에 `scope_tag` 가 빠져 있어서, "359명"을 말하며 화면에
#   "Population: 359 low-trusting men" 카드를 띄운 정상 컷이 위반으로 잡혔다.
#   오탐은 게이트를 불신하게 만든다 — 어휘는 한 곳에서만 정의한다.
# ※ caveat_tag 는 제외한다. 그건 "다만 …" 단서 카드라 숫자를 화면에 내보내는 카드가 아니다.
_NUMBER_OVERLAY_TYPES = tuple(t for t in config.OVERLAY_TYPES if t != "caveat_tag")


# 부정문 안의 금지어는 **위반이 아니라 준수**다. 이 저장소는 프롬프트 끝에 "no on-screen text"
# 를 붙이는 것이 관례이고(config.BURN_IN_NEGATIVE_PROMPT), 실사형 계약도 그렇게 쓰라고 한다.
# ★ 2026-08-29 실측: 모델이 "…identical framing. no labels." 라고 **옳게** 썼는데 게이트가
#   'labels' 한 단어만 보고 차단했다. 옳게 한 것을 벌하는 게이트는 반드시 무시당한다.
# ★ 요구 탐지 목록(_FORBIDDEN_SCREEN)과 **같은 어휘를 담아야 한다**(2026-08-30).
#   한쪽에만 넣으면 게이트가 반쪽이 된다 — 두 방향 모두 실측으로 겪었다:
#     · logos 가 부정어에만 있어서 "'arXiv' logo visible" 요구를 못 잡았다
#     · timers 를 요구 목록에만 넣었더니 "No timers or gauges." 라고 **옳게 쓴 것**이 차단됐다
_BANNED_NOUN = (r"(?:labell?ed|labels?|texts?|captions?|subtitles?|numbers?|digits?|"
                r"charts?|graphs?|dashboards?|infographics?|watermarks?|logos?|letters?|words?|"
                r"timers?|counters?|readouts?|gauges?|dials?|meters?|displays?)")
# ★ 목록형 부정문까지 삼킨다: "No on-screen text **or labels**" 에서 앞부분만 지우면 뒤에
#   남은 'labels' 가 위반으로 잡힌다(실측). 쉼표·or·and 로 이어지는 꼬리를 함께 먹는다.
_NEGATED = re.compile(
    r"\b(?:no|without|avoid|free\s+of)\s+(?:[\w-]+\s+){0,3}?" + _BANNED_NOUN
    + r"(?:\s*(?:,|/|or|and)\s*(?:[\w-]+\s+){0,2}?" + _BANNED_NOUN + r")*",
    re.I)


# 화면에 **글자·그래픽을 그려 달라는** 적극적 요구. 부정문을 지운 뒤에도 남으면 진짜 요구다.
#
# ★★ 2026-08-31 실측으로 넓혔다. 골든B 컷5 의 이 문장이 **게이트를 그냥 통과했다**:
#
#     "…then a graphic overlay appears indicating a crater diameter, whip-pan up"
#
#   그 컷으로 만든 클립 **넷 전부**가 달 표면 실사에서 "받침대 위 분화구 다이어그램"
#   으로 끝났고, 화면에 `DIAMETER`·`AGENT ZERO` 같은 지어낸 글자가 박혔다
#   (docs/실측_품질/G2·G4/결과.md). 종전 목록은 `text overlay` 만 알았지
#   **`graphic overlay` 를 몰랐다.**
#
# ★ 두 가지를 같이 막는다. 화면 그래픽 요구는
#     ① 글자 번인을 부르고(수치를 담으니 필연이다)
#     ② **세계를 떠나게 한다**(다이어그램은 그 장면이 아니다).
#   수치·라벨은 `overlay_plan`(코드 렌더)의 몫이라는 계약이 이미 있는데,
#   생성 프롬프트가 그 계약을 스스로 어기고 있었다.
#
# ★ 한계(정직하게): 유한 목록이라 같은 요구를 다른 말로 쓰면 통과한다
#   (§9-9 Q7 이 `DETAIL_SPECIFICITY_TERMS` 에 대해 인정한 것과 같은 한계다).
#   그래서 게이트만 믿지 않고 지시서 프롬프트에서도 금지한다(양쪽 고침).
_TEXT_REQUEST = re.compile(
    r"\b(?:text\s+overlay|overlay\s+text|title\s+card|caption\s+card"
    r"|(?:the\s+)?(?:word|words|text|title|headline)\s+['“\"]"
    # ── 아래부터 2026-08-31 추가 ──
    r"|(?:graphic|data|info|numeric|number|measurement)\s+overlay"
    r"|overlay\s+(?:appears?|showing|indicating|with)"
    r"|(?:annotation|callout|readout|dimension\s+line|measurement\s+line)s?\b"
    r"|label\s+(?:appears?|showing|indicating)"
    r"|\bHUD\b|heads-up\s+display"
    r"|diagram\s+(?:appears?|overlay))", re.I)


def _has_structured_progression(cut: dict[str, Any]) -> bool:
    """이 컷이 **구조로** 진행을 선언하는가 (v3 State Ledger).

    ★ 어휘 추정보다 강한 근거다: 무엇이(entity_id) 어떻게(operation) 바뀌고 그것이 눈에
      보이는지(visible_change)를 stage 가 구조로 적었으면, 프롬프트에 `glowing` 이 있든
      없든 그 컷은 진행을 그린다. 정본은 resolved_visual_plan 이다(코덱스 리뷰 R3).
    """
    plan = cut.get("resolved_visual_plan")
    if not isinstance(plan, dict) or plan.get("base") != "MECHANISM_SEQUENCE":
        return False
    return any(m.get("visible_change") for m in (cut.get("stage_mutations") or []))


def _raw_text_of(cut: dict[str, Any]) -> str:
    """부정문을 **지우지 않은** 원문. 모순 검사는 금지문이 있었는지도 알아야 한다.

    ★ 장면 묘사(visual_prompt·motion_prompt)만이다. 도해 구조 문장은 여기 넣지 않는다 —
      구조·장식 판정(⑧)은 **장면이** 설명을 하는지를 보는 것이라, 구조 문장이 섞이면 배경
      사진에 구조만 좋은 컷이 통과한다. 구조 문장이 실제로 그림에 가는 데 따른 검사는
      `_image_text_of` 를 쓰는 곳(따옴표 라벨)에서 따로 한다.
    """
    return " ".join(str(cut.get(k) or "") for k in ("visual_prompt", "motion_prompt"))


def _image_text_of(cut: dict[str, Any]) -> str:
    """이미지 모델에 **실제로 가는** 문장 전부 — 장면 묘사 + 도해 구조 문장(2026-09-18).
    구조 필드가 프롬프트에 실리기 시작했으므로(visual_sequence.mechanism_prose) 글자로
    구워질 위험을 보는 검사는 이것을 봐야 한다."""
    mech = visual_sequence.mechanism_prose(cut)
    base = _raw_text_of(cut)
    return f"{base} {mech}" if mech else base


def _text_of(cut: dict[str, Any]) -> str:
    """검사 대상 텍스트. **부정문 구간은 지운 뒤** 본다."""
    return _NEGATED.sub(" ", _raw_text_of(cut))


def mechanism_spec_of(cut: dict[str, Any]) -> dict[str, Any]:
    """컷의 도해 구조(§5). 없으면 빈 dict."""
    spec = cut.get("mechanism")
    return spec if isinstance(spec, dict) else {}


def mechanism_spec_complete(spec: dict[str, Any]) -> bool:
    """구조가 "무엇이 무엇을 어떻게 바꾸는가"를 담고 있는가.

    ★ 필드가 있기만 하면 통과시키지 않는다 — components 가 2개 미만이면 관계가 성립하지 않고,
      transformation 이 비면 그냥 정물이다. `visual_role=MECHANISM` 이라는 enum 하나로는
      "빛나는 큐브를 든 추상적 인간"을 막을 수 없다는 것이 리뷰의 지적이었다.
    """
    if not spec:
        return False
    comps = spec.get("components")
    if not isinstance(comps, list) or len([c for c in comps if str(c).strip()]) < 2:
        return False
    for field in ("subject", "relationship", "transformation"):
        if not str(spec.get(field) or "").strip():
            return False
    # 전·후 중 하나는 있어야 "바뀐다"가 화면에 성립한다.
    return bool(str(spec.get("initial_state") or "").strip()
                or str(spec.get("final_state") or "").strip())


def _overlay_types_of(cut: dict[str, Any]) -> set[str]:
    return {str((o or {}).get("type") or "") for o in (cut.get("overlay_plan") or [])
            if isinstance(o, dict)}


def mechanism_unlabeled_cuts(header: dict[str, Any], cuts: list[dict[str, Any]]) -> list[Any]:
    """범례·캡션이 빠진 기전 컷 번호(연구 T3). 순수 — 지시서 dict 만 본다.

    ▸ 시퀀스 단위: MECHANISM 컷을 2개 이상 담은 시퀀스에 `legend` 가 하나도 없으면
      그 시퀀스의 첫 MECHANISM 컷을 적는다(어디에 넣으라는 뜻).
    ▸ stage 단위: 상태가 바뀌는 stage(`stage_changes_state`)의 컷에 `label_pair` 가 없으면 적는다 —
      그 컷은 전·후 분할 스틸로 나가므로 위·아래가 무엇인지 캡션이 있어야 한다.
    """
    seqs = [x for x in (header.get("visual_sequences") or []) if isinstance(x, dict)]
    if not seqs:
        return []
    by_no = {int(c.get("cut_no") or 0): c for c in cuts if str(c.get("cut_no") or "").isdigit()}
    out: list[Any] = []
    for seq in seqs:
        mech_cuts: list[dict[str, Any]] = []
        has_legend = False
        for st in seq.get("stages") or []:
            for ref in st.get("cut_refs") or []:
                c = by_no.get(int(ref)) if str(ref).isdigit() else None
                if not c or str(c.get("visual_role") or "") != "MECHANISM":
                    continue
                mech_cuts.append(c)
                types = _overlay_types_of(c)
                has_legend = has_legend or ("legend" in types)
                if (visual_sequence.stage_changes_state(st) and "label_pair" not in types
                        and c["cut_no"] not in out):
                    out.append(c["cut_no"])
        if len(mech_cuts) >= 2 and not has_legend and mech_cuts[0]["cut_no"] not in out:
            out.append(mech_cuts[0]["cut_no"])
    return out


def effective_runtime(cuts: list[dict[str, Any]], total_sec: int) -> int:
    """컷 수 역산에 쓸 **실효 길이** — 등급제가 준 추가 시간을 빼고 센다.

    ★★ 왜 필요한가(2026-09-03 실측): `photo_cut_count_low` 는 전체 길이를
      `PHOTO_CUT_SEC_MAX`(5초)로 나눠 최소 컷 수를 구한다. 그런데 **시퀀스 등급제가
      invest 컷에 8초를 준다**(`TIER_PROFILE["invest"]["clip_sec"]=8`). 즉 등급제를
      제대로 쓴 지시서일수록 컷이 길어지고, 길어진 만큼 "컷이 모자라다"고 차단됐다.
      실측: 13컷 71초(8초 컷 4개 포함)가 `photo_cut_count_low:13<14` 로 막혔다.
      저장소 스스로 8초를 허용한다는 증거도 있다 — `PHOTO_CUT_SEC_WARN` 이 8 이라
      8초까지는 경고조차 안 난다. **한 상수는 8을 허용하고 다른 상수는 5로 나누고 있었다.**
      "승인 예산이 등급제를 막았다"(2026-08-31)와 같은 계열의 어긋남이다.

    ★ 그래서 컷마다 **최대 (WARN − MAX)초까지만** 크레딧을 준다. 그 이상 긴 컷은
      크레딧이 없다 — 안 그러면 14초짜리 5컷 슬라이드쇼가 통과한다(실제로 계산해 봤다).
      길이 자체가 과한 컷은 `photo_cut_too_long` 경고가 따로 잡는다.
    """
    credit_cap = max(0, config.PHOTO_CUT_SEC_WARN - config.PHOTO_CUT_SEC_MAX)
    credit = sum(min(max(0, int(c.get("estimated_sec") or 0) - config.PHOTO_CUT_SEC_MAX),
                     credit_cap)
                 for c in cuts or [])
    return max(0, int(total_sec) - credit)


def overlay_text_lines(text: str, font: int = 0, usable_px: int = 0) -> int:
    """오버레이 한 줄에 안 들어가면 몇 줄이 되는가(ASS 근사).

    ★ 근사인 이유: 실제 줄바꿈은 libass 가 폰트 메트릭으로 한다. 여기서는
      **한글·전각 ≈ font px, ASCII ≈ 0.5 font px** 로 잡는다. 정확한 값이 목적이 아니라
      "이건 숫자가 아니라 문장이다"를 가르는 것이 목적이다.
    ★ 실측(2026-09-04): number_punch 48건 중 최장이 28자였다 —
      'AI 데이터센터 ESS 수요 2030년까지 20배↑'. 이건 펀치가 아니라 요약문이다.
    """
    t = str(text or "").strip()
    if not t:
        return 0
    font = int(font or config.OVERLAY_NUMBER_FONT_SIZE)
    usable = int(usable_px or (config.RENDER_WIDTH - 2 * config.OVERLAY_SIDE_MARGIN_PX))
    width = sum(font if ord(ch) > 0x1100 else font * 0.5 for ch in t)
    return max(1, math.ceil(width / float(max(1, usable))))


def worlds_per_minute(sequences: list[dict[str, Any]], total_sec: int) -> float:
    """분당 **고유 세계 수**. 낮을수록 한 곳에 머물며 축척만 바꾼다는 뜻이다.

    ★ 이름이 world_reset_rate 가 아닌 이유: visual_sequence_contract 에 같은 이름의
      **다른 지표**가 있다(new_worlds / stage 수). 같은 이름으로 다른 숫자를 말하면
      이 저장소가 반복해 겪은 이중 정의 사고가 된다.

    ★ 실측이 이 지표를 지지한다(2026-09-04, 지시서 18건):
        발행 벤치마크 0.57/분 · 좋았던 달 클립 지시서 0.86~1.25/분
        화면이 나빴던 성격조합 지시서 3.38~6.12/분
      즉 **알려진 좋은 것과 나쁜 것을 실제로 가른다.**
    """
    seqs = [x for x in (sequences or []) if isinstance(x, dict)]
    sec = float(total_sec or 0)
    if not seqs or sec <= 0:
        return 0.0
    worlds = {str((x.get("world") or {}).get("world_id") or "").strip() for x in seqs}
    worlds.discard("")
    if not worlds:
        return 0.0
    return round(len(worlds) / (sec / 60.0), 2)


def source_supplies_mechanism(fact_sheet: dict[str, Any] | None) -> bool:
    """이 논문이 **왜 그런지**를 말하는가. Fact Sheet 의 claim_kind 로 판정한다.

    ★★ 왜 필요한가(2026-09-04, 실측이 가르쳐 준 것): 기전 컷을 요구하는 게이트를 만들었는데,
      고정 대상 논문의 **원문 전문 46,952자에 'mechanism' 이 0회**였다. 'we argue' 0회,
      'driven by' 0회, 'the reason' 0회, 'why' 0회. 'because' 5회는 광고비 배분에 대한
      방법론 각주다. Fact Sheet 의 주장 12개도 전부 main_result·subgroup —
      "A 조합이 B 품질을 냈다"뿐이고 **왜인지는 논문 자체가 말하지 않는다.**

    ★ 즉 그 게이트는 **존재할 수 없는 것을 요구하고 있었다.** 그대로 두면 모델은 둘 중
      하나를 한다: 지어내거나(제1 불변식 위반), 못 채우고 영원히 경고를 받거나.
      둘 다 나쁘다 — 그리고 후자가 "고쳤다는데 또 실패"의 무한반복을 만든다.

    ★ 그래서 **소재가 지불할 수 있을 때만** 기전을 요구한다. 판정은 자기보고가 아니라
      Fact Sheet 의 claim_kind 다(코드가 데이터로 확정하는 것만 쓴다는 규율 그대로).
      기전을 말하는 종류는 'mechanism' 과 'author_interpretation' 둘이다 —
      후자는 "연구진은 …로 봅니다"로 화면에 나갈 수 있는 해석이다.
    """
    return mechanism_claim_count(fact_sheet) > 0


def mechanism_claim_count(fact_sheet: dict[str, Any] | None) -> int:
    """소재가 지불할 수 있는 **원리 설명의 개수**.

    ★★ 이 함수가 기전 요구량의 **천장**이다(2026-09-04). 임의 문턱을 하나 더 만드는 대신
      "출처가 대는 것보다 많이 설명할 수는 없다"는 자명한 규칙을 쓴다.
      실측: 고정 대상 논문은 이 값이 1이다(author_interpretation 한 건). 그런데 길이에서
      역산한 요구는 2였다 — **1을 가진 소재에 2를 요구**하고 있었고, 그건 지어내라는 말이다.
    """
    fs = fact_sheet if isinstance(fact_sheet, dict) else {}
    wanted = set(config.MECHANISM_CLAIM_KINDS)
    return sum(1 for c in (fs.get("claims") or [])
               if isinstance(c, dict)
               and str(c.get("claim_kind") or "").strip().lower() in wanted)


def min_mechanism_cuts(total_sec: int) -> int:
    """영상 길이 → 기전(원리 설명) 컷 최소 개수. **고정값이 아니다.**

    ★ 왜 유동인가(운영자 지시 2026-09-04): 길이와 소스 내용에 따라 영상 길이가 달라지는데
      고정 2개를 요구하면 짧은 영상은 기전으로 꽉 차 훅·결과가 밀리고, 긴 영상은
      2개만 채우고 나머지를 결과 나열로 되돌린다.

    ★ 간격은 발행 벤치마크 실측이다 — 105초에 기전 3회(원인·재정의·해법) = 35초당 1회.
      40초→1 · 60초→2 · 80초→2 · 105초→3(벤치와 일치).

    ★ 상한을 두는 이유는 비용이 아니라 **환각 방지**다. 기전이 얇은 소스에 더 많이
      요구하면 모델이 원문에 없는 인과를 지어낸다.
    """
    if total_sec <= 0:
        return config.PHOTO_MIN_MECHANISM_CUTS_FLOOR
    n = round(int(total_sec) / float(config.PHOTO_MECHANISM_SEC_PER_CUT))
    return max(config.PHOTO_MIN_MECHANISM_CUTS_FLOOR,
               min(config.PHOTO_MIN_MECHANISM_CUTS_CAP, int(n)))


def target_cut_range(total_sec: int) -> tuple[int, int]:
    """목표 길이 → 권장 컷 수 범위. 계약: 한 컷 = 한 문장(2~4초), 40~50초면 10~14컷."""
    lo = max(config.PHOTO_MIN_CUTS, round(total_sec / config.PHOTO_CUT_SEC_MAX))
    hi = max(lo, round(total_sec / config.PHOTO_CUT_SEC_MIN))
    return lo, hi


_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")


def unverified_overlay_years(cuts: list[dict[str, Any]],
                             fact_sheet: dict[str, Any] | None) -> list[int]:
    """오버레이 카드에 **원장에 없는 연도**를 쓴 컷 번호들.

    ★ 실측 사고(2026-08-29): 출처 카드가 `Source: Vogt et al., PNAS (2023)` 로 나왔다.
      그 논문의 실제 발표일은 2026-08-06 이다 — 모델이 연도를 **지어냈다.** 오버레이는
      화면에 그대로 나가는 코드 그래픽이라 이게 통과하면 시청자는 틀린 연도를 본다.
      Fact Sheet 에 연도가 없으면 모델은 비워 두는 게 아니라 채워 넣는다는 것이 증명됐다.

    ★ 왜 연도만 보는가: 오탐을 만들지 않기 위해서다. 다른 수치(+15% 같은)는 근거 오버레이
      경로가 이미 claim 을 참조하게 돼 있고, 자유 문자열까지 대조하면 정상 표기(반올림·단위
      변환)를 벌하게 된다. 연도는 4자리 정수라 **문자열 그대로 원장에 있거나 없거나**다.

    ★ 원장이 없으면(fact_sheet=None) 검사하지 않는다 — 근거 없이 차단하지 않는다.
    """
    if not fact_sheet:
        return []
    haystack = json.dumps(fact_sheet, ensure_ascii=False)
    bad: list[int] = []
    for c in cuts:
        for ov in (c.get("overlay_plan") or []):
            if not isinstance(ov, dict):
                continue
            for y in _YEAR.findall(str(ov.get("text") or "")):
                if y not in haystack:
                    bad.append(int(c.get("cut_no") or 0))
                    break
            else:
                continue
            break
    return sorted(set(bad))


def _terms_re(terms: tuple[str, ...]) -> re.Pattern[str]:
    """어휘 목록 → 경계 있는 정규식. 여러 낱말 어휘(`depth of field`)도 그대로 받는다.

    ★ `\\b` 를 **양끝에만** 붙인다. 목록 안에 `low-poly`·`photo-realistic` 처럼 하이픈이
      든 항목이 있는데, 하이픈은 비단어라 그 자리에 경계가 없다 — 낱말마다 `\\b` 를 붙이면
      매치되지 않는다. 이 저장소는 `%` 에서 이미 같은 실수를 두 번 했다
      (`_SPOKEN_NUMBER_EN`, `visual_sequence_contract._QUANTITATIVE_VISUAL` 주석).
    """
    return re.compile(r"\b(" + "|".join(re.escape(t) for t in terms) + r")\b", re.I)


_RENDER_STYLE_RE = _terms_re(config.PHOTO_RENDER_STYLE_TERMS)
_UNDRAWABLE_RE = _terms_re(config.PHOTO_UNDRAWABLE_QUALITY_TERMS)


_OPTICS_REWRITES = tuple((re.compile(p, re.I), r) for p, r in config.PHOTO_OPTICS_REWRITES)
_STYLE_WORD_REWRITES = tuple((re.compile(p, re.I), r) for p, r in config.PHOTO_STYLE_WORD_REWRITES)


def strip_style_words(text: str) -> str:
    """화풍 형용사(`stylized`)를 지운다. 정리 규칙은 strip_optics 와 같다(같은 함수를 쓴다)."""
    return strip_optics(text, _STYLE_WORD_REWRITES)


def normalize_style_words(header: dict[str, Any], cuts: list[dict[str, Any]]) -> list[str]:
    """world 선언과 컷 프롬프트에서 `stylized` 를 **제자리에서** 지운다 → 고친 자리 목록.

    ★ 2026-09-11 운영자 지시. 근거는 config.PHOTO_STYLE_WORD_REWRITES 주석.
      normalize_optics 와 같은 자리(world.style·lighting·background, visual_prompt·
      motion_prompt)를 본다 — 검사하는 자리와 고치는 자리가 다르면 게이트가 계속 막는다.
    """
    touched: list[str] = []
    for seq in (header.get("visual_sequences") or []):
        if not isinstance(seq, dict):
            continue
        world = seq.get("world")
        if not isinstance(world, dict):
            continue
        wid = str(world.get("world_id") or seq.get("sequence_id") or "?")
        for k in ("style", "lighting", "background"):
            before = str(world.get(k) or "")
            after = strip_style_words(before)
            if after != before:
                world[k] = after
                touched.append(f"세계 {wid}.{k}")
    for c in cuts:
        if not isinstance(c, dict):
            continue
        for k in ("visual_prompt", "motion_prompt"):
            before = str(c.get(k) or "")
            after = strip_style_words(before)
            if after != before:
                c[k] = after
                touched.append(f"컷{c.get('cut_no')}")
    return sorted(set(touched))


_PROMPT_PERCENT_OF = re.compile(
    r"\b(?:(?:about|approximately|nearly|around|roughly|almost|over|up\s+to)\s+)?"
    r"(\d+(?:[.,]\d+)?)\s*(?:%|percent\b)\s+of\b", re.I)
_PROMPT_PERCENT = re.compile(
    r"\s*\b(?:(?:to|at|by|of|reaching|about|approximately|nearly|around|roughly|almost|"
    r"over|up\s+to)\s+)?(\d+(?:[.,]\d+)?)\s*(?:%|percent\b)", re.I)


def _overlay_numbers(cut: dict[str, Any]) -> set[str]:
    """이 컷의 화면 카드가 **이미 그리는** 숫자들(쉼표 없이)."""
    out: set[str] = set()
    for ov in (cut.get("overlay_plan") or []):
        if isinstance(ov, dict) and str(ov.get("type") or "") in _NUMBER_OVERLAY_TYPES:
            blob = " ".join(str(v) for v in ov.values() if isinstance(v, (str, int, float)))
            out |= {n.replace(",", "") for n in re.findall(r"\d+(?:[.,]\d+)?", blob)}
    return out


def normalize_prompt_numbers(cuts: list[dict[str, Any]]) -> list[str]:
    """visual_prompt/motion_prompt 의 퍼센트 수치를 **같은 숫자를 카드가 그리는 컷에서만** 지운다.

    ★ 2026-09-14 실측: 성격 유전(372055db) 지시서 **세 편 연속**이 같은 자리에서
      `photo_forbidden_screen_request` 로 막혔다 — "rises to 13.3%", "13.3% of variance".
      세 번 다 운영자가 숫자만 지웠고, 그 숫자는 그 컷의 number_punch 가 이미 그리고 있었다.
      계약(숫자는 오버레이가 말한다)이 이미 정한 답이라 코드가 한다.
    ★ 카드에 없는 숫자는 지우지 않는다 — 그러면 수치가 화면에서 **사라진다.** 그 경우는
      게이트가 막고 되먹임이 "number_punch 로 옮겨라"라고 되묻는다(photo_number_without_overlay).
    ★ "N% of X" 는 "a share of X" 로 바꾼다 — 통째로 지우면 "represent of variance" 가 된다.
    """
    touched: list[str] = []
    for c in cuts:
        if not isinstance(c, dict):
            continue
        shown = _overlay_numbers(c)
        if not shown:
            continue

        def _of(m: re.Match) -> str:
            return "a share of" if m.group(1).replace(",", "") in shown else m.group(0)

        def _bare(m: re.Match) -> str:
            return "" if m.group(1).replace(",", "") in shown else m.group(0)

        rewrites = ((_PROMPT_PERCENT_OF, _of), (_PROMPT_PERCENT, _bare))
        for k in ("visual_prompt", "motion_prompt"):
            before = str(c.get(k) or "")
            after = strip_optics(before, rewrites)
            if after != before:
                c[k] = after
                touched.append(f"컷{c.get('cut_no')}")
    return sorted(set(touched))


def strip_optics(text: str, rewrites: tuple = _OPTICS_REWRITES) -> str:
    """렌즈·광학 어휘 → 배치 표현. **정보는 남기고 렌즈 지시만 뺀다.**

    ★ 왜 코드가 하는가: 프롬프트에 금지와 대안을 둘 다 적고 실측했는데 모델이 부분만
      지켰다(2026-09-07 재생성 2회 — world 3개 중 1개만 고쳐졌다). 어휘 치환은 기계가
      확실히 할 수 있는 일이고, 모델에게 반복시키며 재시도 비용을 내는 것은 설계 실패다.
      이 저장소가 이미 쓰는 자세다(`photo_video_camera_repaired` 처럼 고치고 경고를 남긴다).
    """
    original = str(text or "")
    if not original.strip():
        return original
    t = original
    for pat, rep in rewrites:
        t = pat.sub(rep, t)
    # ★ 아무것도 안 바뀌었으면 **손대지 않고 돌려준다.** 정리 규칙이 멀쩡한 프롬프트의
    #   공백·대문자를 건드리면, 고칠 것이 없는 컷까지 우리가 바꾸는 셈이 된다.
    if t == original:
        return original
    # 치환이 남긴 자국 정리 — 이중 공백·앞뒤 쉼표·쉼표 중복.
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"\s+([.,])", r"\1", t)
    t = re.sub(r"(,\s*){2,}", ", ", t)
    # ★ 같은 **문장 안**에 "further back" 이 두 번 남는 것을 접는다(2026-09-07 실측).
    #   모델이 이미 거리로 적어 둔 문장 뒤에 흐림 어휘를 덧붙이면
    #   "Lab equipment further back along the far wall, further back." 이 된다.
    #   치환이 만든 군더더기를 그대로 발주하면 우리가 프롬프트를 더럽히는 셈이다.
    t = re.sub(r"(further back)([^.]*?),?\s*further back\b", r"\1\2", t, flags=re.I)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"\s+([.,])", r"\1", t)
    # ★ 문장 첫 글자 복원 — "Blurred trays" → "more distant trays" 가 문장 머리에 오면
    #   소문자로 시작한다. 치환한 문장에만 적용한다(위 조기 반환).
    # 문장 머리의 단어를 지우면 앞 공백이 남아 `^` 가 소문자를 못 본다("Stylized brain" → " brain").
    t = t.lstrip()
    t = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t)
    return t.strip().strip(",").strip()


def normalize_optics(header: dict[str, Any], cuts: list[dict[str, Any]]) -> list[str]:
    """world 선언과 컷 프롬프트에서 렌즈 어휘를 **제자리에서** 걷어낸다 → 고친 자리 목록.

    ★ 화풍이 정해지는 세 자리 중 둘을 여기서 청소한다(셋째는 코드의 VISUAL_ROLE_STYLE).
      `world` 를 빠뜨리면 안 된다 — 실측에서 `background: "A blurred, neutral studio
      backdrop"` 이 재생성 두 번을 버텼다.
    """
    touched: list[str] = []
    for seq in (header.get("visual_sequences") or []):
        if not isinstance(seq, dict):
            continue
        world = seq.get("world")
        if not isinstance(world, dict):
            continue
        wid = str(world.get("world_id") or seq.get("sequence_id") or "?")
        for k in ("style", "lighting", "background"):
            before = str(world.get(k) or "")
            after = strip_optics(before)
            if after != before:
                world[k] = after
                touched.append(f"세계 {wid}.{k}")
    for c in cuts:
        if not isinstance(c, dict):
            continue
        for k in ("visual_prompt", "motion_prompt"):
            before = str(c.get(k) or "")
            after = strip_optics(before)
            if after != before:
                c[k] = after
                touched.append(f"컷{c.get('cut_no')}")
    return sorted(set(touched))


def style_vocabulary_hits(header: dict[str, Any],
                          cuts: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """화풍·렌즈 기법 어휘와 **그릴 수 없는 판정 어휘**를 찾는다 → (차단표시, 경고표시).

    무엇을 푸는가: "화풍은 코드가 정한다. visual_prompt 에 화풍 형용사를 쓰지 마라" 는
    지시가 `directive.py` 에 **이미 있었는데 검사가 없었다.** 화풍 전환 실측 4회가 전부
    같은 자리에서 졌다 — 장면 묘사의 긍정 어휘가 코드의 부정어를 이긴다.

    ★★ **`world` 선언까지 본다.** 화풍이 정해지는 곳은 셋이고 그 셋째가 world 다
      (`docs/핸드오프_화풍전환_2026-09-07.md` §3-④). 실측에서 세포 세계 선언이
      "Microscopic, detailed 3D rendering … Soft, internal glow … blurred cellular matrix"
      였고, **성공·실패가 정확히 이 선언과 갈렸다.** cuts 만 검사하면 원인을 놓친다.

    ★ 지금 `world_prose` 가 죽어 있어 이 문자열이 이미지 모델에 직접 가지는 않는다.
      그래도 검사한다 — 같은 LLM 이 같은 생각으로 `visual_prompt` 를 쓰기 때문이다.
      선언이 삽화 기법이면 장면 묘사도 삽화가 된다(실측).
    """
    blocked: list[str] = []
    warned: list[str] = []

    def _scan(text: str, where: str) -> None:
        t = str(text or "")
        if not t.strip():
            return
        hard = sorted({m.group(1).lower() for m in _RENDER_STYLE_RE.finditer(t)})
        soft = sorted({m.group(1).lower() for m in _UNDRAWABLE_RE.finditer(t)})
        if hard:
            blocked.append(f"{where}({', '.join(hard[:3])})")
        if soft:
            warned.append(f"{where}({', '.join(soft[:3])})")

    for seq in (header.get("visual_sequences") or []):
        if not isinstance(seq, dict):
            continue
        world = seq.get("world") or {}
        wid = str(world.get("world_id") or seq.get("sequence_id") or "?")
        # style·lighting·background 를 **합쳐서** 본다 — 셋 다 화풍을 정하는 자리이고,
        # 실측에서 발광은 lighting 에, 흐림은 background 에 들어 있었다.
        _scan(" ".join(str(world.get(k) or "") for k in ("style", "lighting", "background")),
              f"세계 {wid}")

    for c in cuts:
        if not isinstance(c, dict):
            continue
        _scan(" ".join(str(c.get(k) or "") for k in ("visual_prompt", "motion_prompt")),
              f"컷{c.get('cut_no')}")

    return blocked, warned


_QUOTED_LABEL = re.compile(config.PHOTO_QUOTED_LABEL_PATTERN)


def quoted_label_cuts(cuts: list[dict[str, Any]]) -> list[str]:
    """따옴표 친 라벨 이름을 쓴 컷 → "컷8(Calorie Restriction, Semaglutide)" 목록.

    ★ 실측(2026-09-07 시퀀스 렌더): 컷8 의 `represents 'Calorie Restriction'` 다섯 개가
      완성된 그림에 **영어 글자로 그대로 박혔다.** 이미지는 한국어판·영어판이 공유하므로
      글자가 구워지면 언어 공유가 깨진다.

    ★★ 기존 `_TEXT_REQUEST` 는 이것을 못 잡는다. 그 정규식은 "글자를 그려 달라"는 **요구**를
      찾는데, 여기는 요구가 없다 — 대상에 이름을 붙였을 뿐이고 모델이 그 이름을 그렸다.
      요구가 없어도 결과는 같으므로 검사가 따로 있어야 한다.
    """
    out: list[str] = []
    for c in cuts:
        if not isinstance(c, dict):
            continue
        # ★ 도해 구조 문장도 본다 — 그 문장이 이미지에 가므로(2026-09-18) 거기 따옴표가 있으면
        #   장면에 있는 것과 똑같이 글자로 구워진다.
        text = _image_text_of(c)
        hits = sorted({m.group(1) for m in _QUOTED_LABEL.finditer(text)})
        if hits:
            out.append(f"컷{c.get('cut_no')}({', '.join(hits[:3])})")
    return out


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", str(text or "").lower())
            if w not in config.PHOTO_WORLD_OVERLAP_STOPWORDS}


def world_lead_disagreements(header: dict[str, Any],
                             cuts: list[dict[str, Any]]) -> list[str]:
    """**세계를 여는 컷**이 그 세계를 안 그리는 경우 → stage 목록.

    ★ 왜 NEW_WORLD 만 보는가: 그 stage 의 그림이 곧 세계다. 뒤 stage 들은 그것을 참조로
      물려받으므로(`sequence_render.reference_decision`), 여는 컷이 딴 것을 그리면
      **세계 선언이 통째로 죽고** 그 오해가 시퀀스 끝까지 간다.
      실측: world 는 "cutaway teaching model of an animal cell" 인데 컷8 이 벤 다이어그램을
      그렸고, 세포 모형이 영상에서 사라졌다.

    ★★ **경고다.** 낱말 겹침은 거친 대리 판정이라 오탐이 있다 — 근접 촬영(주사 펜 클로즈업이
      실험실을 안 적는다)과 동의어(satellite imagery ↔ Moon's far side)가 걸린다.
      실측 히트율 14.7%(NEW_WORLD 34개 중 5개)에 그중 일부가 오탐이었다.
      차단으로 올리면 옳게 한 컷을 벌한다(설계원칙 1).
    """
    if not config.PHOTO_WORLD_LEAD_OVERLAP_WARNS:
        return []
    by_no = {int(c.get("cut_no") or 0): c for c in cuts if isinstance(c, dict)}
    out: list[str] = []
    for seq in (header.get("visual_sequences") or []):
        if not isinstance(seq, dict):
            continue
        style = str((seq.get("world") or {}).get("style") or "")
        if not style.strip():
            continue
        for st in (seq.get("stages") or []):
            if str(st.get("continuity_mode") or "") != "NEW_WORLD":
                continue
            refs = st.get("cut_refs") or []
            lead = by_no.get(int(refs[0])) if refs else None
            if not lead:
                continue
            if not (_content_words(style) & _content_words(lead.get("visual_prompt"))):
                out.append(str(st.get("stage_id") or "?"))
    return out


def _entity_words(text: str) -> set[str]:
    """개체를 **특정하는** 낱말만. 총칭(model·marker·molecule)과 기능어는 버린다.

    ★ `_content_words` 와 따로 두는 이유: 저기는 4글자 이상만 본다. 개체 이름에는
      `NAD` 처럼 3글자 핵심어가 있고, 그것을 버리면 NAD_MOLECULE 이 총칭 `molecule`
      하나만 남아 여는 컷의 "a cell model" 에 통과해 버린다(실측에서 그렇게 샜다).
      대신 3글자를 허용하면 `and`·`the` 가 들어오므로 총칭표가 그것까지 막는다.
    """
    words = {w for w in re.split(r"[^a-z0-9]+", str(text or "").lower()) if len(w) >= 3}
    return words - config.PHOTO_WORLD_OVERLAP_STOPWORDS - config.PHOTO_ENTITY_GENERIC_WORDS


def unstaged_lead_entities(header: dict[str, Any],
                           cuts: list[dict[str, Any]]) -> list[str]:
    """**여는 컷이 무대에 세우지 않은 배우** → "S5(SENESCENCE_MARKERS)" 목록.

    규칙: NEW_WORLD stage 의 여는 컷 `visual_prompt` 에, 같은 시퀀스의 **뒤 stage** 가
    `APPEAR` 가 아닌 변이로 건드리는 개체가 물체로 등장해야 한다.

    ★ 왜 이것이 결함인가: 여는 컷의 그림이 그 세계의 유일한 새 그림이고, 뒤 stage 는
      그것을 첨부해 "이것만 바꿔라"로 만든다(`sequence_render.reference_decision`).
      첨부 그림에 없는 물체는 **줄일 수도 키울 수도 없다** — 모델은 장면을 그대로 두고,
      그래서 여러 컷이 같은 화면이 된다.
      실측(4baede40): 여는 컷4 가 세포 모형만 그렸는데 뒤 stage 가 SENESCENCE_MARKERS 를
      SHRINK 하라고 했다. 없는 것은 줄일 수 없어 컷 7·8·9 가 사실상 같은 화면이 됐다.

    ★★ **`APPEAR` 는 뺀다.** 그것만은 없던 것을 등장시키는 연산이고, 코드가 그 개체의
      외형을 참조 프롬프트에 실어 준다(`sequence_render.appearing_entity_prose`).
      실측에서도 정당한 설계가 걸렸다 — 실험실 세계(S1)에 연구원 손이 S2 에서 APPEAR 하는
      것은 옳다. 옳게 한 것을 벌하는 게이트는 무시당한다(설계원칙 1).
      ※ 여는 컷에 없는 것이 **색으로 구별되지 않는** 문제는 이 검사의 몫이 아니다
        (NAD 분자가 앰버 하나로 눌린 것 — `docs/수정안_기전도해_2026-09-09.md` C).

    ★★★ **필요조건만 본다**(`role_claim_mismatches` 와 같은 자세). 개체 **이름**의 특정
      낱말이 여는 컷·세계 선언에 하나도 없고, `visual_identity` 의 특정 낱말도 2개 미만이
      겹칠 때만 낸다. 애매하면 아무것도 내지 않는다:
        · 이름에 특정 낱말이 없으면(총칭뿐이면) 판정하지 않는다
        · 여는 컷을 못 찾으면 판정하지 않는다
        · 시퀀스에 뒤 stage 가 없으면 검사할 것이 없다

    ★ 보는 것은 `visual_prompt` 와 그 세계 선언(world)뿐이다 — 그림을 만드는 것이 그 둘이기
      때문이다(`providers/image._build_image_prompt`). `motion_prompt` 는 영상 단계의 말이라
      **첫 프레임에 물체를 만들어 주지 못한다.**
    """
    if not config.PHOTO_LEAD_STAGES_ENTITIES:
        return []
    by_no = {int(c.get("cut_no") or 0): c for c in cuts if isinstance(c, dict)}
    out: list[str] = []
    for seq in (header.get("visual_sequences") or []):
        if not isinstance(seq, dict):
            continue
        stages = [st for st in (seq.get("stages") or []) if isinstance(st, dict)]
        identity = {str(e.get("entity_id") or ""): str(e.get("visual_identity") or "")
                    for e in (seq.get("entities") or []) if isinstance(e, dict)}
        world = seq.get("world") or {}
        world_text = " ".join(str(world.get(k) or "")
                              for k in ("style", "lighting", "background"))
        for i, st in enumerate(stages):
            if str(st.get("continuity_mode") or "") != "NEW_WORLD":
                continue
            refs = st.get("cut_refs") or []
            lead = by_no.get(int(refs[0])) if refs else None
            if not lead:
                continue                  # 판정 불가 — 여는 컷을 못 찾았다
            staged = _entity_words(str(lead.get("visual_prompt") or "") + " " + world_text)
            missing: list[str] = []
            # ★ 뒤 stage 에서 APPEAR 로 **먼저 등장한** 개체는 그 뒤에 SHRINK·MOVE 돼도 정상이다 —
            #   그 stage 의 참조 그림(앞 stage 결과)에 이미 있다. 여는 컷에 없다고 벌하면
            #   "S5 에 등장 → S6 에 줄어듦"이라는 옳은 설계를 막는다(2026-09-11 리뷰).
            appeared: set[str] = set()
            for later in stages[i + 1:]:
                for m in (later.get("mutations") or []):
                    if not isinstance(m, dict):
                        continue
                    eid = str(m.get("entity_id") or "").strip()
                    if str(m.get("operation") or "").upper() == "APPEAR":
                        appeared.add(eid)
                        continue          # 없던 것을 등장시키는 연산 — 여기서 벌하지 않는다
                    if not eid or eid in missing or eid in appeared:
                        continue
                    named = _entity_words(eid)
                    if not named:
                        continue          # 판정 불가 — 특정 낱말이 없는 개체
                    if named & staged:
                        continue
                    looks = _entity_words(identity.get(eid, "")) & staged
                    if len(looks) >= config.PHOTO_ENTITY_LOOKS_MIN_OVERLAP:
                        continue          # 이름은 안 나와도 생김새로 무대에 서 있다
                    missing.append(eid)
            if missing:
                out.append(f"{st.get('stage_id') or '?'}({', '.join(sorted(missing)[:4])})")
    return out


def stage_scale_repeat_share(header: dict[str, Any]) -> float:
    """같은 시퀀스에서 **인접 stage 가 같은 축척**인 비율. **판정하지 않는다 — 재기만 한다.**

    ★ 왜 문턱이 없나(2026-09-10 실측): 저장된 photo 지시서 20건의 인접 stage 쌍 45개 중
      39개(86.7%)가 같은 `camera_base` 였다 — 지시서 13/20 이 걸린다. 이 비율로 경고를
      울리면 거의 모든 지시서에서 울리고, 그러면 운영자가 게이트를 무시하기 시작한다
      (`series_split` 이 근거 있는 초안 100%를 막았던 사고와 같은 모양).
      프롬프트(`directive.PHOTO_NARRATIVE_ARC`)로 먼저 요구하고, **이 지표가 실제로
      내려가는지** 본 뒤에 문턱을 판단한다.

    ★★ stage 에 `camera_base` 가 비어 있으면 world 의 값을 쓴다(렌더와 같은 규칙).
    """
    pairs = same = 0
    for seq in (header.get("visual_sequences") or []):
        if not isinstance(seq, dict):
            continue
        base = str((seq.get("world") or {}).get("camera_base") or "")
        eff = [str((st or {}).get("camera_base") or "") or base
               for st in (seq.get("stages") or []) if isinstance(st, dict)]
        for a, b in zip(eff, eff[1:]):
            pairs += 1
            if a and a == b:
                same += 1
    return round(same / pairs, 3) if pairs else 0.0


def role_time_shares(cuts: list[dict[str, Any]]) -> dict[str, float]:
    """역할별 화면시간 지표. **판정하지 않는다 — 재기만 한다**(2026-09-09).

    ★ 왜 문턱이 없나: 이 값들은 `evidence_role` 에서 나오는데 그 라벨은 **모델이 스스로
      붙이고 코드가 내용 정합을 검증하지 않는다.** 문턱을 걸면 내용을 그대로 두고 라벨만
      바꿔 통과할 수 있다(외부 리뷰 지적). 라벨 정합 검사(`role_claim_mismatches`)를
      세운 뒤, 새 표본에서 분포와 사람 평가를 함께 보고 문턱을 정한다.
    """
    total = sum(int(c.get("estimated_sec") or 0) for c in cuts if isinstance(c, dict))
    if total <= 0:
        return {"reference_role_share": 0.0, "mechanism_share": 0.0,
                "first_mechanism_start_share": None}
    ref = mech = 0
    first: float | None = None
    t = 0
    for c in cuts:
        if not isinstance(c, dict):
            continue
        d = int(c.get("estimated_sec") or 0)
        role = str(c.get("evidence_role") or config.DEFAULT_EVIDENCE_ROLE).strip().lower()
        if role in config.REFERENCE_EVIDENCE_ROLES:
            ref += d
        if role == "mechanism":
            mech += d
            if first is None:
                first = t / float(total)
        t += d
    return {"reference_role_share": round(ref / total, 3),
            "mechanism_share": round(mech / total, 3),
            "first_mechanism_start_share": (round(first, 3) if first is not None else None)}


def role_claim_mismatches(cuts: list[dict[str, Any]],
                          fact_sheet: dict[str, Any] | None) -> list[str]:
    """역할 라벨이 **명백히 거짓인** 컷 → "컷N(role)" 목록.

    ★ 의미 분류기가 아니다. `config.ROLE_CLAIM_REQUIREMENTS` 의 **필요조건**만 본다 —
      그 역할이라면 연결된 claim 이 최소한 무엇을 갖고 있어야 하는가.
      예: `mechanism` 이라면 연결 claim 중 하나는 claim_kind 가 mechanism 이거나
      author_interpretation 이어야 한다. 아니면 그 라벨은 거짓이다.

    ★★ **애매하면 아무것도 내지 않는다.** 컷에 claim_ids 가 없거나 원장에서 못 찾으면
      판정 불가로 두고 넘어간다 — 판정 불가와 위반을 섞지 않는다. Fact Sheet 가 아예
      없으면 전체를 건너뛴다(대조할 원장이 없다).

    ★ 왜 필요한가: 역할 비중을 규제하려면 라벨을 믿을 수 있어야 한다. 이 검사가 없으면
      비중 규칙은 "라벨만 바꾸면 통과"가 되고, 지표는 좋아지는데 영상은 그대로다.
    """
    claims = {str(c.get("claim_id") or ""): c
              for c in ((fact_sheet or {}).get("claims") or []) if isinstance(c, dict)}
    if not claims:
        return []
    out: list[str] = []
    for cut in cuts:
        if not isinstance(cut, dict):
            continue
        role = str(cut.get("evidence_role") or "").strip().lower()
        req = config.ROLE_CLAIM_REQUIREMENTS.get(role)
        if not req:
            continue
        linked = [claims[i] for i in (cut.get("claim_ids") or [])
                  if isinstance(i, str) and i in claims]
        if not linked:
            continue                      # 판정 불가 — 위반으로 세지 않는다
        ok = False
        for cl in linked:
            kind = str(cl.get("claim_kind") or "").strip().lower()
            if kind in req.get("kinds", ()):
                ok = True
                break
            if any(str(cl.get(f) or "").strip() and str(cl.get(f)).strip().lower() != "null"
                   for f in req.get("fields", ())):
                ok = True
                break
        if not ok:
            out.append(f"컷{cut.get('cut_no')}({role})")
    return out


def evaluate(header: dict[str, Any], cuts: list[dict[str, Any]],
             fact_sheet: dict[str, Any] | None = None) -> dict[str, Any]:
    """실사형 지시서 → {block_reasons, warnings, stats}. 순수 함수."""
    blocks: list[str] = []
    warns: list[str] = []
    cuts = [c for c in cuts if isinstance(c, dict)]
    n = len(cuts)

    # ① 상단 고정 부제 — 비면 화면 위쪽이 통째로 빈다.
    if not str(header.get("hook_ko") or "").strip():
        blocks.append("photo_hook_missing")

    # ② 역할 선언 — 실사형의 모든 컷은 자기가 무엇을 하는 컷인지 밝혀야 한다.
    roleless = [c["cut_no"] for c in cuts if not str(c.get("visual_role") or "").strip()]
    if roleless:
        blocks.append("photo_visual_role_missing:" + ",".join(str(x) for x in roleless[:6]))

    mech = [c for c in cuts if str(c.get("visual_role") or "") == "MECHANISM"]
    real = [c for c in cuts if str(c.get("visual_role") or "") == "REALITY"]

    # ③ 도해가 아예 없으면 이 버전을 고른 의미가 없다.
    if n and not mech:
        blocks.append("photo_mechanism_missing")
    elif mech and real:
        ratio = len(mech) / n
        if not (config.PHOTO_MECHANISM_RATIO_MIN <= ratio <= config.PHOTO_MECHANISM_RATIO_MAX):
            warns.append(f"photo_role_balance_off:{len(mech)}/{n}")

    # ④-2 를 **먼저** 계산한다 — 같은 컷이 두 사유로 두 번 뜨면 노이즈가 되고,
    #   노이즈가 되면 무시당한다. 더 구체적인 쪽(모순)이 이긴다.
    conflicted_nos = {c["cut_no"] for c in cuts
                      if _NEGATED.search(_raw_text_of(c))
                      and _TEXT_REQUEST.search(_text_of(c))}

    # ④ 금지 요구 — 차트·라벨·화면 숫자·**화면 그래픽**을 그려 달라고 했는가.
    #
    # ★★ `_TEXT_REQUEST` 를 여기에 합쳤다(2026-08-31 실측). 종전에는 이 패턴을
    #   ④-2(모순)에서만 봤다 — 즉 **같은 컷에 금지문이 함께 있을 때만** 잡았다.
    #   그런데 금지문은 `build_motion_prompt` 가 발주 직전에 붙이므로 컷의 저장된
    #   프롬프트에는 없다. 그래서 골든B 컷5 의
    #     "…a graphic overlay appears indicating a crater diameter…"
    #   가 **아무 사유 없이 통과했고**, 그 컷으로 만든 클립 넷이 전부 세계를 떠나
    #   글자 범벅이 됐다. 요구는 모순이 아니어도 요구다.
    bad_screen = [c["cut_no"] for c in cuts
                  if c["cut_no"] not in conflicted_nos
                  and (_FORBIDDEN_SCREEN.search(_text_of(c))
                       or _FORBIDDEN_NUMBER_ON_SCREEN.search(_text_of(c))
                       or _TEXT_REQUEST.search(_text_of(c)))]
    if bad_screen:
        blocks.append("photo_forbidden_screen_request:"
                      + ",".join(str(x) for x in bad_screen[:6]))

    # ④-2 프롬프트가 **스스로 모순**된 경우 (코덱스 리뷰 §13, 2026-08-30).
    #   골든A 컷7: "Minimalist text overlay: 'Crucial Detail' … No on-screen text."
    #   글자를 그리라고 하면서 같은 문장에서 글자를 금지한다. 모델은 둘 중 하나를 고르고,
    #   어느 쪽을 골랐는지 우리는 모른다 — 사유를 갈라야 운영자가 무엇을 고칠지 안다.
    #   ★ 위 ④와 다른 코드인 이유: ④는 "그리지 말아야 할 것을 요구했다"이고
    #     여기는 "요구와 금지가 충돌한다"다. 고치는 법이 다르다.
    conflicted = sorted(conflicted_nos)
    if conflicted:
        blocks.append("photo_text_request_conflict:"
                      + ",".join(str(x) for x in conflicted[:6]))

    # ⑤ 숫자를 말하는 컷에는 화면 카드가 있어야 한다(계약: 숫자는 오버레이가 담당).
    #
    # ★★ 정본이 **정밀 레이어를 선언한 컷**도 여기서 함께 본다(2026-08-30).
    #   코덱스 리뷰 R1 의 간판 변경이 "수치는 세계를 끊지 않고 코드 오버레이로 얹힌다"인데,
    #   `precision_layer` 를 읽는 곳이 **비용 계산 한 군데뿐**이었다 — 그리는 코드가 없다.
    #   실제로 숫자를 화면에 올리는 것은 기존 `overlay_plan` 이다. 즉 기능이 없는 게 아니라
    #   **둘이 따로 놀고 있었다.** 따로 놀면 언젠가 어긋난다 — 오늘 하루에 같은 모양의
    #   결함이 여섯 번 나왔고 전부 "만들어 놓고 한쪽만 연결"이었다.
    #   정본이 레이어를 선언했으면 그것을 채우는 카드가 **반드시** 있어야 한다.
    def _wants_precision(cut: dict[str, Any]) -> bool:
        plan = cut.get("resolved_visual_plan")
        return bool(isinstance(plan, dict) and plan.get("precision_layer"))

    # ★★ 오버레이를 끄면 이 검사도 끈다(2026-09-08). 켜 두면 "숫자를 말했으니 카드를
    #   넣어라"고 막으면서 그 카드를 **렌더가 그리지 않는다** — 통과할 수 없는 함정이 된다.
    #   게이트는 셋이 함께 있어야 한다: 검사 · 모델 고지 · 되먹임. 렌더가 안 그리는 것을
    #   요구하면 셋 다 무의미하다.
    missing_overlay = [
        c["cut_no"] for c in cuts
        if config.EVIDENCE_OVERLAY_ENABLED
        and (_speaks_a_number(c) or _wants_precision(c)) and not _has_number_overlay(c)
    ]
    if missing_overlay:
        blocks.append("photo_number_without_overlay:"
                      + ",".join(str(x) for x in missing_overlay[:6]))

    # ⑥ 컷 수·컷 길이 — 목표 길이에서 역산한다(대본 씬 개수가 아니라).
    total_sec = int(header.get("total_estimated_sec") or 0) or sum(
        int(c.get("estimated_sec") or 0) for c in cuts)
    # ★ 등급제가 준 추가 시간을 빼고 역산한다(effective_runtime 주석).
    lo, hi = target_cut_range(effective_runtime(cuts, total_sec))
    if n and n < lo:
        blocks.append(f"photo_cut_count_low:{n}<{lo}")
    long_cuts = [c["cut_no"] for c in cuts
                 if int(c.get("estimated_sec") or 0) > config.PHOTO_CUT_SEC_WARN]
    if long_cuts:
        warns.append("photo_cut_too_long:" + ",".join(str(x) for x in long_cuts[:6]))

    # ⑦ 영상 컷 수·연속 배치 — I2V 연쇄는 **연달아 붙은** 영상 컷끼리만 이어진다.
    video_idx = [i for i, c in enumerate(cuts) if c.get("motion_source") == "video"]
    if n:
        if not (config.PHOTO_VIDEO_CUTS_MIN <= len(video_idx) <= config.PHOTO_VIDEO_CUTS_MAX):
            warns.append(f"photo_video_cut_count_off:{len(video_idx)}")
        if len(video_idx) >= 2 and _longest_run(video_idx) < 2:
            warns.append("photo_video_cuts_not_adjacent")

    # ⑧ 도해가 실제로 설명을 하는가(§5).
    for c in mech:
        spec = mechanism_spec_of(c)
        if not mechanism_spec_complete(spec):
            # ★ 재사용 컷은 면제한다(운영자 결정 2026-08-29). 구조를 요구하는 목적은
            #   **새 그림을 그릴 때 인과를 먼저 확정시키는 것**이다. 앞 컷의 이미지를 그대로
            #   쓰는 컷(reuse_*)은 새로 그리지 않으므로 같은 요구를 할 근거가 약하다 —
            #   기준 컷이 이미 구조를 통과했다. 대신 경고로 남겨 화면에서 보이게 한다.
            if str(c.get("asset_strategy") or "") in config.ASSET_STRATEGY_REUSE:
                warns.append(f"photo_mechanism_spec_inherited:{c['cut_no']}")
                continue
            blocks.append(f"photo_mechanism_spec_missing:{c['cut_no']}")
            continue
        # ★ [구조와 장면이 서로 딴 말을 한다] 2026-09-18, 연구 T1-b. components 를 적어 놓고
        #   visual_prompt 에는 그중 하나도 안 그리는 컷 — 구조는 게이트용, 장면은 따로 지은 것.
        #   실측 117컷 중 4컷(3.4%)·오탐 0 이라 차단이다. 한글 구성요소는 그림에 못 가므로
        #   영어 구성요소가 2개 미만이면 같은 사유다(지시서 프롬프트가 영어를 요구한다).
        hits, english_comps = visual_sequence.mechanism_component_hits(c)
        if english_comps < 2 or hits < config.PHOTO_MECHANISM_PROMPT_MIN_HITS:
            blocks.append(f"photo_mechanism_prompt_detached:{c['cut_no']}")
        text = _text_of(c)
        signals = 0
        if not _STRUCTURAL.search(text):
            signals += 1
        if _DECORATIVE.search(text):
            signals += 1
        # ★ 구조화된 진행 선언이 있으면 문자열 판정을 **덮는다**(코덱스 리뷰 §14, 2026-08-30).
        #
        #   이 검사는 "설명하는 그림인가"를 어휘로 추정한다 — glow·abstract 가 있고
        #   cutaway·flow 가 없으면 장식으로 본다. 추정이므로 틀릴 수 있고, v3 에서는 더
        #   나은 근거가 생겼다: stage 가 **무엇이 어떻게 바뀌는지를 구조로 선언**하면
        #   그 컷은 진행을 그리는 컷이다. 어휘가 무엇이든.
        #
        #   ★ 리뷰가 옳게 지적한 방향이기도 하다: 문자열 게이트는 `glowing line` 같은
        #     스타일 단어를 잡느라 정작 위험한 "원문에 없는 관계 추가"는 놓친다. 관계는
        #     claim·operation 연결로 판단해야 한다 — 그 이관의 첫 걸음이 이 면제다.
        if signals and _has_structured_progression(c):
            warns.append(f"photo_mechanism_structured:{c['cut_no']}")
        elif signals >= 2:
            blocks.append(f"photo_mechanism_decorative:{c['cut_no']}")
        elif signals == 1:
            warns.append(f"photo_mechanism_thin:{c['cut_no']}")

    # ⑧-B 기전 시퀀스가 **어느 쪽이 무엇인지** 말하는가(2026-09-18, 연구 T3).
    #   두 뇌를 나란히 그려도 범례가 없으면 시청자는 어느 쪽이 손상인지 모른다. 이미지에
    #   글자는 금지이므로 말할 길은 overlay_plan 의 legend/label_pair 뿐이다.
    #   ▸ 기전 시퀀스(stage 를 가진 MECHANISM 컷 묶음)마다 legend 가 하나는 있어야 하고,
    #   ▸ 상태가 바뀌는 stage(전·후 분할 스틸로 나가는 컷)에는 label_pair 가 있어야 한다.
    #   경고다 — 새 어휘라 첫 실측 전엔 차단하지 않는다(재생성은 되묻는다: RETRYABLE).
    #   ★ 범례·캡션 스위치(MECHANISM_LABEL_OVERLAYS_ENABLED)가 꺼져 있으면 이 검사도 끈다
    #     (위 number_without_overlay 와 같은 이유 — 렌더가 안 그리는 것을 요구하면 함정이다).
    #     수치·출처 카드 스위치(EVIDENCE_OVERLAY_ENABLED)와는 별개다 — 9/8 에 그 카드만 뺐다.
    unlabeled = (mechanism_unlabeled_cuts(header, cuts)
                 if config.MECHANISM_LABEL_OVERLAYS_ENABLED else [])
    if unlabeled:
        warns.append("photo_mechanism_unlabeled:" + ",".join(str(x) for x in unlabeled[:6]))

    # ⑧-A 오버레이 연도가 원장에 있는가 (2026-08-29 실측: 없는 연도를 지어냈다).
    bad_years = unverified_overlay_years(cuts, fact_sheet)
    if bad_years:
        blocks.append("photo_overlay_year_unverified:"
                      + ",".join(str(x) for x in bad_years[:6]))

    # ⑧-B 역할 이름이 그림으로 새어 나갔는가 (2026-08-29 실측).
    #
    #   실측 사고: 완성된 영상의 컷1 에 **"MECHANISM" 이라는 글자가 두 번** 그려져 있었고,
    #   컷5·6 의 가짜 모니터에는 그것이 제목으로 박혀 있었다. 코드는 이 단어를 프롬프트에
    #   넣지 않는다(`providers/image._build_image_prompt` 는 역할로 화풍만 고른다) — 즉
    #   지시서 LLM 이 visual_prompt 에 직접 써 넣었고, 이미지 모델이 그것을 라벨로 읽었다.
    #   `no text, no labels` 네거티브가 있어도 프롬프트 본문에 대문자 단어가 있으면 진다.
    leak = [c["cut_no"] for c in cuts if _ROLE_NAME_LEAK.search(_text_of(c))]
    if leak:
        blocks.append("photo_role_name_in_prompt:" + ",".join(str(x) for x in leak[:6]))

    # ⑨ 재사용이 **진행**인가 **반복**인가 (2026-08-29 운영자 지시).
    #
    #   실측 사고: 11컷 지시서에서 컷1=10=11 · 2=8 · 5=6 · 7=9 가 나왔고, 그 중 5→6 은
    #   기준 컷과 **바이트까지 동일한 파일**이었다. 같은 인물이 다시 나온 것 자체는 죄가
    #   아니다 — 서사가 진행돼서 같은 대상이 다음 단계로 다시 나오는 것은 옳다. 죄는
    #   **화면에서 아무것도 변하지 않은 채** 또 나온 것이다. 시청자에게는 영상이 멈춘 것으로
    #   보인다.
    #
    #   그래서 재사용 컷에는 "무엇이 눈에 보이게 달라지는가"를 요구한다. 여기서 잡는 것은
    #   **선언 누락**이고, 선언이 참인지(정말 화면이 달라졌는지)는 렌더가 픽셀로 판정한다
    #   (engine/render.py, config.REUSE_MIN_PIXEL_DELTA) — 이 저장소의 자세 그대로,
    #   모델의 자기보고는 근거가 아니다.
    reuse_cuts = [c for c in cuts
                  if str(c.get("asset_strategy") or "") in config.ASSET_STRATEGY_REUSE]
    thin_delta = [c["cut_no"] for c in reuse_cuts
                  if len(str(c.get("state_change") or "").strip())
                  < config.REUSE_STATE_DELTA_MIN_CHARS]
    if thin_delta:
        blocks.append("photo_reuse_without_state_change:"
                      + ",".join(str(x) for x in thin_delta[:6]))
    # 같은 기준 컷을 여러 번 파생하면 그 대상이 화면을 지배한다. 셋 이상이면 경고.
    from collections import Counter
    base_counts = Counter(str(c.get("base_asset_ref") or "").strip() for c in reuse_cuts)
    crowded = [b for b, k in base_counts.items() if b and k >= config.REUSE_MAX_PER_BASE]
    if crowded:
        warns.append("photo_reuse_base_overused:" + ",".join(sorted(crowded)[:6]))

    # ★★ [서사에 원리가 있는가] 그림에는 MECHANISM 도해를 5~7개 요구하면서 **대본에는
    #   기전을 한 번도 요구하지 않았다**. 그 어긋남이 "3D 도해도 원리 설명도 아닌 의미 없는
    #   화면"의 뿌리다(운영자 지적 2026-09-03). 그림이 설명할 원리를 말이 먼저 말해야 한다.
    #
    # ★ **차단이 아니라 경고다.** 실측에서 저장소의 지시서 20개가 **전부**(20/20)
    #   evidence_role='mechanism' 0개였다. 지금 차단으로 걸면 생산이 통째로 멈춘다 —
    #   series_split 이 근거 있는 초안 10건을 100% 막았던 것과 같은 사고다(§8-2 교훈).
    #   먼저 프롬프트(directive.PHOTO_NARRATIVE_ARC)가 기전 컷을 요구하게 고쳤고,
    #   재생성 표본이 실제로 mechanism 을 내는지 본 뒤에 차단 승격을 판단한다.
    # ★ 승격 조건을 미리 적어 둔다: 새 지시서 10건 중 8건 이상이 mechanism 컷을 2개 이상
    #   낼 때. 그때 이 경고를 block_reasons 로 옮기고 이 주석을 지운다.
    mech_evidence = [c["cut_no"] for c in cuts
                     if str(c.get("evidence_role") or "").strip().lower() == "mechanism"]
    # ★★ 소재가 기전을 가지고 있을 때만 기전 컷을 요구한다(2026-09-04 실측 교훈).
    #   원문에 'why' 가 0회인 논문에 원리 설명을 요구하면 지어내거나 영원히 실패한다.
    #   대신 **선별 단계의 문제**로 신호를 바꾼다 — 화면 엔진이 풀 수 있는 문제가 아니다.
    # ★ 천장은 **소재가 대는 개수**다. 길이에서 역산한 값이 그보다 크면 그 초과분은
    #   "지어내라"는 요구가 된다. 실측: 이 논문은 1을 대는데 길이는 2를 요구했다.
    supply = mechanism_claim_count(fact_sheet)
    has_mech_source = supply > 0
    need_mech = min(min_mechanism_cuts(total_sec), supply)
    if not has_mech_source:
        warns.append("photo_source_has_no_mechanism")
    elif len(mech_evidence) < need_mech:
        warns.append(f"photo_narrative_no_mechanism:{len(mech_evidence)}<{need_mech}")

    # ★ [세계 재사용] 벤치는 105초 내내 세계가 하나였다(시화호). 바뀌는 건 축척뿐이다.
    #   우리 실측은 71초에 세계 4개 — 컷 경계마다 화면이 갈아엎어져 "시퀀스"가 아니라
    #   컷 나열이 됐다. `vseq_world_reset_high` 가 이미 울리고 있었지만 실사형 기준선이
    #   없었다(일반 0.6 vs 여기 0.5). 경고다 — 물리적 장소가 없는 주제를 가두면 안 된다.
    sequences = [x for x in (header.get("visual_sequences") or []) if isinstance(x, dict)]

    # ★★ [화풍을 장면 묘사가 정해 버린다] 2026-09-07 실측 4회의 공통 원인.
    #   지시("화풍은 코드가 정한다")는 있었고 검사가 없었다 — 그래서 매번 졌다.
    #   `world` 선언까지 함께 본다(화풍이 정해지는 셋째 자리).
    style_blocked, style_warned = style_vocabulary_hits(header, cuts)
    if style_blocked:
        blocks.append("photo_style_word_in_prompt:" + ", ".join(style_blocked[:4]))
    if style_warned:
        # ★ 기본은 경고다. 목록에 오탐이 있다("more active mice" 는 자세로 그릴 수 있다).
        #   히트율을 재기 전에 차단으로 올리지 않는다 — series_split 이 100% 를 막은 사고를
        #   이 저장소는 이미 겪었다. 재고 나서 PHOTO_UNDRAWABLE_BLOCKS 로 올린다.
        code = "photo_undrawable_difference:" + ", ".join(style_warned[:4])
        (blocks if config.PHOTO_UNDRAWABLE_BLOCKS else warns).append(code)

    # ★★ [따옴표 라벨이 그림에 글자로 구워진다] 실측 히트 4.5%·오탐 0 이라 차단이다.
    labeled = quoted_label_cuts(cuts)
    if labeled:
        blocks.append("photo_quoted_label_in_prompt:" + ", ".join(labeled[:4]))

    # ★ [세계를 여는 컷이 그 세계를 안 그린다] 경고 — 낱말 겹침은 거친 대리 판정이다.
    disagree = world_lead_disagreements(header, cuts)
    if disagree:
        warns.append("photo_world_lead_disagrees:" + ", ".join(disagree[:4]))

    # ★★ [여는 컷이 배우를 무대에 세우지 않았다] 위 검사의 형제다 — 저기는 "세계를 그렸는가",
    #   여기는 "뒤에 움직일 물체를 그렸는가". 뒤 stage 는 여는 그림을 첨부해 "이것만 바꿔라"로
    #   만들므로, 없는 물체는 줄일 수도 키울 수도 없다(실측: 세 컷이 같은 화면이 됐다).
    unstaged = unstaged_lead_entities(header, cuts)
    if unstaged:
        warns.append("photo_lead_cut_missing_entity:" + ", ".join(unstaged[:4]))

    churn = worlds_per_minute(sequences, total_sec)
    if churn > config.PHOTO_MAX_WORLDS_PER_MIN:
        warns.append(f"photo_world_churn:{churn}/분")

    # ★ [축척 사다리] 벤치는 광역(방조제 12.7km)에서 손바닥(물 한 컵)까지 3초 만에 내려온다.
    #   크기 대비가 "이게 진짜 있는 일"을 만든다. 실측 히트율 94% 라 경고다.
    #   시퀀스가 하나뿐이면 검사하지 않는다 — 세계가 하나면 camera_base 도 하나다.
    # ★★ 축척은 **stage 까지** 본다(2026-09-04 정정). 종전에는 world 의 camera_base 만
    #   보고, 시퀀스가 하나면 검사를 건너뛰었다. 그런데 우리는 프롬프트로 **세계를 하나로
    #   유지하라**고 지시한다 — 그러면 이 검사는 영영 돌지 않는다. 두 지시가 서로를
    #   무력화하고 있었다(실측: 세마글루타이드 지시서가 세계 1개라 근접 검사가 통째로 생략).
    #   벤치마크가 하는 일이 정확히 "한 세계 안에서 축척을 바꾸는 것"이므로, 검사도
    #   그 층위로 내린다.
    bases = {str((x.get("world") or {}).get("camera_base") or "").strip() for x in sequences}
    for x in sequences:
        for st in (x.get("stages") or []):
            b = str((st or {}).get("camera_base") or "").strip()
            if b:
                bases.add(b)
    if sequences and config.PHOTO_CLOSE_CAMERA_BASE not in bases:
        warns.append("photo_no_close_scale")

    # ★★ [연구 대상이 화면을 먹는다] 실측: 쥐 실험 영상에서 쥐가 86초 중 42초(49%).
    #   운영자: "생쥐 이미지를 사람들이 그렇게 오래 보고 싶어 할 것 같냐." 대상은 훅·규모
    #   실감에만 짧게, 나머지는 원리·맥락·의미로. 컷 길이로 가중해 비율을 잰다.
    subj_re = re.compile(r"\b(" + "|".join(map(re.escape, config.PHOTO_SUBJECT_TERMS)) + r")\b", re.I)
    subj_sec = sum(int(c.get("estimated_sec") or 0) for c in cuts
                   if subj_re.search(str(c.get("visual_prompt") or "")))
    subj_share = (subj_sec / float(total_sec)) if total_sec else 0.0
    if subj_share > config.PHOTO_SUBJECT_SHARE_WARN:
        warns.append(f"photo_subject_dominates:{subj_share:.2f}")

    # ★★ [역할 라벨이 내용과 맞는가] 2026-09-09 외부 리뷰. 역할 비중을 규제하려면 라벨을
    #   믿을 수 있어야 하는데, `evidence_role` 은 모델 자기보고이고 코드가 검증하지 않았다.
    #   명백한 거짓 라벨만 잡는다 — 판정 불가(claim 연결 없음)는 위반으로 세지 않는다.
    mislabeled = role_claim_mismatches(cuts, fact_sheet)
    if mislabeled:
        warns.append("photo_role_claim_mismatch:" + ", ".join(mislabeled[:4]))

    # ★ [첫 기전이 너무 늦다] 총량이 충분해도 기전이 뒤로 몰리면 전반부가 통째로 설정이 된다.
    #   실측(f7dcb61e): 기전 총량 28% 인데 첫 기전이 51% 지점이라 전반부에 원리가 0개였다.
    #   ★ 소재가 기전을 지불할 때만 본다 — 없는 것을 앞당기라고 할 수는 없다.
    #   ★★ 40% 는 **calibration 값**이다(표본 5편). 차단으로 올리지 않는다.
    _shares = role_time_shares(cuts)
    _first = _shares.get("first_mechanism_start_share")
    if has_mech_source and _first is not None and _first > config.MECHANISM_START_SHARE_WARN:
        warns.append(f"photo_mechanism_starts_late:{_first:.0%}")

    # ★★ [훅 두 컷이 같은 그림] 실측 22%(지시서 27개 중 6개). 같은 이미지를 8초 붙여 두면
    #   그건 한 장짜리 훅이고, 벤치마크 문법(대비를 넓게 → 한쪽으로 급속 푸시인)이 죽는다.
    #   실측(세마글루타이드 v6): 컷1·2 가 '우리 속 쥐 한 마리'로 동일했고, 정작 대비 화면인
    #   '두 우리를 나란히'는 컷3 출처 소개에 가 있었다.
    if len(cuts) >= 2:
        a = str(cuts[0].get("visual_prompt") or "").strip()
        b = str(cuts[1].get("visual_prompt") or "").strip()
        if a and a == b:
            warns.append("photo_hook_visual_repeated")

    # ★★ [영상비를 내고 정지 화면을 받는다] motion_source='video' 인데 temporal_plan 의
    #   카메라가 전부 HOLD 인 컷. 연출 계약(temporal_plan.evaluate)은 **invest 등급만**
    #   검사하는데, 등급이 standard 로 강등되면 그 검사가 통째로 빠진다.
    #   실측(세마글루타이드 v3): 컷 7·11 이 강등된 뒤 HOLD 하나만 남았다.
    #   기전 컷이 아니어도 **영상을 산 컷은 움직여야 한다** — 이건 등급과 무관하다.
    still_video = [c["cut_no"] for c in cuts
                   if str(c.get("motion_source") or "") == "video"
                   and (c.get("temporal_plan") or [])
                   and all(str(b.get("camera") or "").upper() == "HOLD"
                           for b in c["temporal_plan"])]
    if still_video:
        warns.append("photo_video_cut_never_moves:"
                     + ",".join(str(x) for x in still_video[:6]))

    # ★ [수치 펀치가 문장이 됐다] 실측: number_punch 최대 28자였다. 크게 키우면 화면을
    #   3~4줄로 덮는다. 설명은 evidence_card 로 가고 여기엔 수치와 단위만 남아야 한다.
    wordy = [c["cut_no"] for c in cuts
             for o in (c.get("overlay_plan") or [])
             if isinstance(o, dict) and str(o.get("type") or "") == "number_punch"
             and overlay_text_lines(o.get("text") or o.get("value") or "")
             > config.OVERLAY_NUMBER_MAX_LINES]
    if wordy:
        warns.append("photo_number_punch_is_a_sentence:"
                     + ",".join(str(x) for x in sorted(set(wordy))[:6]))

    return {
        "block_reasons": sorted(set(blocks)),
        "warnings": sorted(set(warns)),
        "stats": {
            "cuts": n, "mechanism": len(mech), "reality": len(real),
            "mechanism_evidence": len(mech_evidence),
            "mechanism_evidence_required": need_mech,
            "source_supplies_mechanism": has_mech_source,
            "mechanism_claims_available": supply,
            "worlds_per_minute": churn,
            "subject_share": round(subj_share, 3),
            # ★ 축척 반복 — **지표만**이다(문턱 없음). 실측 86.7% 라 경고로 올리면
            #   거의 모든 지시서에서 울린다. 프롬프트가 먼저 이 값을 내려야 한다.
            "stage_scale_repeat_share": stage_scale_repeat_share(header),
            # ★ 역할별 화면시간 — **지표만**이다(문턱 없음). 자기보고 라벨에
            #   문턱을 걸면 라벨 세탁으로 통과할 수 있어서, 정합 검사가 선다.
            **role_time_shares(cuts),
            "video_cuts": len(video_idx), "total_sec": total_sec,
            "target_cut_range": [lo, hi],
        },
    }


def _has_number_overlay(cut: dict[str, Any]) -> bool:
    for ov in (cut.get("overlay_plan") or []):
        if isinstance(ov, dict) and str(ov.get("type") or "") in _NUMBER_OVERLAY_TYPES:
            return True
    return False


def _longest_run(indexes: list[int]) -> int:
    """연속으로 붙은 인덱스의 최대 길이."""
    best = run = 1
    for prev, cur in zip(indexes, indexes[1:]):
        run = run + 1 if cur == prev + 1 else 1
        best = max(best, run)
    return best if indexes else 0


def feedback_prompt(block_reasons: list[str], warnings: list[str] | None = None) -> str:
    """차단 사유 → 재생성 프롬프트에 덧붙일 **구체적 처방**(§7).

    ★ "다시 만들어라"로는 같은 결함이 반복된다. 무엇이 왜 틀렸고 어떻게 고치는지를 준다.
    """
    # ★ 빈 입력에는 아무 말도 하지 않는다(2026-08-31, visual_sequence_contract 와 같은 계약).
    #   종전에는 일반문("계약 위반을 고쳐라")을 뱉었다. photo 는 통과하고 시각 시퀀스만
    #   위반한 지시서에서 그 문장이 **시퀀스 처방 위에 얹혀** 무엇을 고칠지를 흐렸다.
    #
    # ★★ **재생성 가능 경고만 있을 때도 말한다**(2026-09-09 외부 리뷰). 종전에는 차단이
    #   없으면 여기서 바로 빈 문자열이었다 — 그래서 `photo_subject_dominates` 처럼 정확한
    #   처방을 **이미 갖고 있는 경고가 모델에게 한 번도 전달되지 않았다.**
    #   이번 문제("연구 대상이 화면의 51%")를 감지하고 고칠 말도 있었는데 말을 안 걸었다.
    retryable = [w for w in (warnings or [])
                 if w.split(":", 1)[0] in config.RETRYABLE_QUALITY_WARNINGS]
    if not block_reasons and not retryable:
        return ""
    fixes: list[str] = []
    codes = {r.split(":", 1)[0] for r in block_reasons}
    if "photo_hook_missing" in codes:
        fixes.append("- header.hook_ko 를 채워라(20자 내외, 1컷 나레이션과 다른 문장).")
    if "photo_visual_role_missing" in codes:
        fixes.append("- 모든 컷에 visual_role 을 MECHANISM 또는 REALITY 로 선언하라.")
    if "photo_forbidden_screen_request" in codes:
        fixes.append(
            "- visual_prompt/motion_prompt 에서 차트·그래프·축·라벨·화면 숫자 요구를 **삭제**하라."
            " 생성 모델이 그린 숫자는 근거가 없다. 그 숫자는 overlay_plan 의 number_punch 로 옮겨라."
            " ★ **지도·지구본도 여기 걸린다** — 생성 모델은 나라 경계와 위치를 모르고 지명을 지어낸다."
            " 지역·집단의 편중은 **물체의 양**으로 보여줘라: '시료관 선반에서 한 색이 대부분이고"
            " 다른 색은 몇 개뿐', '두 연구실 탁자 위 시료 더미의 크기 차이'. 어느 지역인지는 오버레이 카드가 말한다.")
    if "photo_number_without_overlay" in codes:
        fixes.append(
            "- 숫자를 말하는 컷마다 overlay_plan 에 number_punch 카드를 넣어라"
            " (값·단위·비교 기준). 화면 숫자는 코드가 그린다.")
    if "photo_cut_count_low" in codes:
        fixes.append(
            "- 컷을 더 쪼개라. **한 컷 = 나레이션 한 문장**이고 문장이 끝나는 지점에서 화면이"
            " 바뀐다. 긴 문장은 의미 단위로 나눠 컷을 늘려라(문장을 길게 쓰고 컷을 줄이지 마라).")
    if "photo_mechanism_missing" in codes:
        fixes.append("- MECHANISM 컷을 만들어라. 이 버전은 화면이 원리를 설명하는 것이 목적이다.")
    if "photo_mechanism_spec_missing" in codes:
        fixes.append(
            "- MECHANISM 컷마다 mechanism 구조를 채워라:"
            " subject / components(2개 이상) / relationship / initial_state / transformation /"
            " final_state / highlighted_element / claim_ids."
            " visual_prompt 는 **그 구조에서 파생**되어야 한다(구조에 없는 것을 그리지 마라).")
    if "photo_mechanism_decorative" in codes:
        fixes.append(
            "- 도해 컷의 visual_prompt 가 배경·분위기에 그친다. **무엇을 잘라서 무엇을 보여주는지**"
            " 를 적어라(cutaway / cross-section / exploded view / step sequence / before-and-after)."
            " 'abstract', 'glowing', 'wide shot of' 같은 분위기 어휘를 빼라.")
    if "photo_mechanism_prompt_detached" in codes:
        fixes.append(
            "- 도해 컷의 mechanism.components 와 visual_prompt 가 **서로 딴 것을 말한다.**"
            " components 에는 화면에 실제로 보일 물체를 **영어로** 2개 이상 적어라(entity_id·데이터셋"
            " 이름·한글 금지). visual_prompt 는 그 물체들을 **이름 그대로** 써서 그려라 —"
            " 구조에 있는 것이 장면에 없으면 그 구조는 그림에 닿지 않는다."
            " (subject / initial_state / transformation / final_state / highlighted_element 도"
            " 영어로. 사람이 읽을 요약은 mechanism_ko 에 한글로.)")
    # ★★ 아래 여섯은 **처방이 비어 있었다**(2026-08-31). 차단은 하면서 고치는 법을 안 주면
    #   재시도가 같은 결함을 반복한다 — 실제로 `photo_text_request_conflict` 는 재생성
    #   실측에서 차단 사유로 나왔는데 되먹임 문장이 없었다.
    #   `test_feedback_covers_every_block_reason` 가 이 목록의 완결성을 고정한다.
    if "photo_style_word_in_prompt" in codes:
        fixes.append(
            "- 장면 묘사가 **어떻게 그릴지**를 지시하고 있다(화풍·렌즈 기법)."
            " 화풍은 코드가 역할(MECHANISM/REALITY)에 따라 붙인다 — 네가 쓰면 충돌해서"
            " 네 쪽이 이긴다(실측 4회). 해당 단어를 **삭제**하라:"
            " stylized / photorealistic / 3D render / illustration / cinematic /"
            " cel shading / line art, 그리고 렌즈 어휘 depth of field / bokeh /"
            " macro detail / blurred / out of focus / film grain."
            " ★ `world.style`·`world.lighting`·`world.background` 도 같은 규칙이다 —"
            " world 는 **어디인가**만 적어라(장소·공간·놓인 것). 'Microscopic 3D rendering'"
            " 은 장소가 아니라 그리는 방법이다. 'A cell culture room with incubators' 처럼"
            " 실제로 서 있을 수 있는 장소를 적어라."
            " ★★ **금지만 듣고 대안 없이 고치려 하지 마라**(그러면 같은 말을 다시 쓰게 된다):"
            " ① 배경이 뒤에 있다는 것은 흐림이 아니라 **거리**로 적는다 —"
            " 'blurred lab equipment' → 'lab equipment further back along the far wall'."
            " ② 장소가 없는 주제(세포·분자)는 **스튜디오 탁자 위의 물리적 모형**으로 적는다 —"
            " 'Microscopic view of a cell' → 'A plain studio tabletop holding a cutaway"
            " teaching model of an animal cell, with small painted resin pieces beside it'.")
    if "photo_undrawable_difference" in codes:
        fixes.append(
            "- 차이를 **판정 어휘**로 적었다(healthier / more active / improved / vibrant /"
            " glowing). 생성 모델은 '건강함'을 그릴 수 없다 — 실측: '더 건강하고 활동적인"
            " 세포'라고 썼더니 두 세포가 **똑같이** 나왔다."
            " 눈으로 셀 수 있는 물리적 차이로 바꿔라: 형태·색·자세·개수·거리·높이·기울기."
            " 나쁨 — 'the right cell looks healthier'."
            " 좋음 — 'the right model is assembled from whole, tightly packed parts;"
            " the left one has gaps and two pieces lying detached beside it'.")
    if "photo_quoted_label_in_prompt" in codes:
        fixes.append(
            "- 대상에 **따옴표로 이름을 붙였다**(예: the left model represents 'Calorie"
            " Restriction'). 요구하지 않아도 생성 모델은 그 이름을 **글자로 그린다** —"
            " 실측에서 다섯 개가 그대로 화면에 박혔다. 이미지는 한국어판·영어판이 공유하므로"
            " 영어가 구워지면 언어 공유가 깨진다."
            " 따옴표와 이름을 **지우고**, 두 대상을 **생김새로** 구별되게 적어라"
            " (왼쪽은 낮고 평평한 접시, 오른쪽은 높고 칸이 나뉜 접시). 어느 쪽이 무엇인지는"
            " overlay_plan 의 group_compare 카드가 말한다 — 그건 코드가 그리고 언어마다 바뀐다.")
    if "photo_text_request_conflict" in codes:
        fixes.append(
            "- 같은 프롬프트가 글자를 **요구하면서 동시에 금지**한다"
            " (예: \"text overlay: 'Crucial Detail' … No on-screen text\")."
            " 부정문은 생성 모델에 통하지 않는다 — 금지를 덧붙이지 말고 **요구 자체를 지워라.**"
            " 그 글자가 필요하면 overlay_plan 카드로 옮겨라(코드가 그린다).")
    if "photo_skeleton_shortfall" in codes:
        fixes.append(
            "- 코드가 문장 경계로 만들어 준 **컷 골격보다 컷이 적다** — 칸을 합쳤다는 뜻이다."
            " 골격의 칸은 나레이션 한 문장이다. 합치지 말고 칸마다 컷을 하나씩 채워라.")
    if "photo_role_name_in_prompt" in codes:
        fixes.append(
            "- visual_prompt 에 역할 이름(MECHANISM/REALITY)이 남아 있다. 실측 사고:"
            " 그 대문자 단어가 **화면에 제목으로 그려졌다**('no text' 네거티브가 있어도 진다)."
            " 역할은 role 필드로만 선언하고 프롬프트 본문에서는 지워라.")
    if "photo_overlay_year_unverified" in codes:
        fixes.append(
            "- 화면 카드의 **연도가 Fact Sheet 에 없다** — 지어낸 연도다. Fact Sheet 가"
            " 지불하는 연도만 쓰거나, 연도를 빼고 카드를 써라.")
    if "photo_reuse_without_state_change" in codes:
        fixes.append(
            "- 재사용 컷인데 **무엇이 눈에 보이게 달라지는지**(state_change)가 비었거나 너무 짧다."
            " 같은 대상이 다시 나오는 것은 옳다 — 아무것도 변하지 않은 채 다시 나오는 것이"
            " 문제다(시청자에게는 영상이 멈춘 것으로 보인다). 무엇이 달라지는지 적어라.")
    if "photo_reuse_identical_render" in codes:
        fixes.append(
            "- 재사용 컷이 기준 컷과 **사실상 같은 그림**으로 나왔다. 선언한 변화가 화면에"
            " 나타나지 않았다는 뜻이다. 카메라·상태·구도 중 무엇이 달라지는지 프롬프트에"
            " 구체적으로 적거나, 재사용을 포기하고 새로 그려라.")
    # ★ 차단이 없고 품질 경고만 있으면 **머리말을 바꾼다.** "계약 위반"이라고 말하면
    #   모델이 없는 위반을 찾아 구조를 갈아엎는다(2026-09-03 실측: 되먹임을 쌓았더니
    #   재생성이 1차 3건 → 2차 14건으로 악화됐다). 품질 교정은 요구가 더 좁아야 한다.
    if block_reasons:
        head = "\n\n★ 아래 계약 위반을 고쳐 **전체 지시서를 다시** 출력하라(부분 수정 금지):\n"
        body = "\n".join(fixes) or "- 계약 위반을 고쳐라."
    else:
        head = ("\n\n★ 계약 위반은 없다. 아래 **화면 구성 문제만** 고쳐 전체 지시서를 다시"
                " 출력하라 — 통과한 것은 그대로 두고 구조를 갈아엎지 마라:\n")
        body = ""
    if warnings:
        # ★ 경고는 코드 이름만 나열하면 모델이 무엇을 어떻게 고칠지 모른다 — 이 저장소가
        #   차단 쪽에서 이미 겪은 "되먹임이 반쪽"이다. 처방이 있는 경고는 문장으로 준다.
        wcodes = {w.split(":", 1)[0] for w in warnings}
        wfix: list[str] = []
        if "photo_narrative_no_mechanism" in wcodes:
            wfix.append(
                "- **대본이 원리를 설명하지 않는다.** evidence_role='mechanism' 컷이 모자란다"
                " (필요 개수는 [기전 컷 수] 블록에 있다). 결과를 한 번 더 말하는 컷을"
                " **과정을 말하는 컷으로 바꿔라**: '무엇이 무엇에 작용해서 무엇이 된다'."
                " 그리고 MECHANISM 도해 컷을 바로 그 나레이션 위에 놓아라 —"
                " 그림이 설명하는 원리와 말이 설명하는 원리가 같아야 한다."
                " 소스에 기전이 없으면 지어내지 말고 연구진의 해석을 그 자리에 놓아라.")
        if "photo_world_lead_disagrees" in wcodes:
            wfix.append(
                "- **세계를 여는 컷이 그 세계를 안 그린다.** NEW_WORLD stage 의 첫 컷이 곧"
                " 그 세계의 그림이고, 뒤 stage 들은 그것을 참조로 물려받는다 — 여는 컷이 딴"
                " 것을 그리면 world 선언이 통째로 죽고 그 오해가 시퀀스 끝까지 간다."
                " 실측: world 가 '세포 단면 모형'인데 여는 컷이 벤 다이어그램을 그려"
                " **세포가 영상에서 사라졌다.**"
                " 여는 컷의 visual_prompt 에 world 가 말한 장소와 물건을 **실제로 적어라.**")
        if "photo_mechanism_unlabeled" in wcodes:
            fixes.append(
                "- 기전 시퀀스에 **범례·캡션이 없다.** 두 집단·전후를 나란히 그려도 어느 쪽이"
                " 무엇인지 시청자가 모른다. 이미지에 글자는 금지이니 overlay_plan 으로 말하라:"
                " 시퀀스의 첫 도해 컷에 legend(payload.items = [{color: amber|blue|coral, label: 한글"
                " 낱말}]) 하나, 상태가 바뀌는 stage 의 컷에는 label_pair(payload.top / payload.bottom"
                " = 위·아래 화면이 무엇인지 한글 짧게). 색은 규약대로 — amber=설명하는 부분,"
                " blue=첫 집단·전, coral=둘째 집단·후 — visual_prompt 도 같은 색으로 칠하라.")
        if "photo_mechanism_starts_late" in wcodes:
            wfix.append(
                "- **원리 설명이 너무 늦게 시작한다.** 총량이 충분해도 뒤로 몰리면 전반부가"
                " 통째로 연구 소개가 된다 — 시청자는 그 전에 떠난다."
                " 기전 컷을 **앞으로 당겨라**: 결과와 숫자를 말한 직후에 '왜 그런가'를 한 번"
                " 넣고, 대상·기간 같은 연구 조건은 그 뒤로 미루거나 한 컷으로 합쳐라."
                " ★ 2초짜리 기전 컷을 앞에 끼워 형식만 맞추지 마라 — 그건 고친 것이 아니다.")
        if "photo_lead_cut_missing_entity" in wcodes:
            wfix.append(
                "- **세계를 여는 컷이, 뒤에서 움직일 물체를 그리지 않았다.** 뒤 컷들은 이"
                " 그림을 그대로 첨부하고 \"이것만 바꿔라\"로 만들어진다 — 첨부한 그림에 없는"
                " 것은 줄일 수도 키울 수도 없고, 그러면 모델이 장면을 그대로 둬서 여러 컷이"
                " **같은 화면**이 된다(실측: 붉은 조각·노란 조각·NAD 분자를 줄이라고 했는데"
                " 여는 컷에 셋 다 없어서 세 컷이 똑같이 나왔다)."
                " 여는 컷의 visual_prompt 에 그 개체들을 **모양과 색이 있는 물체로** 적어라"
                " ('small red irregular resin pieces scattered around the cell model' 처럼)."
                " ★ '염증의 징후'처럼 **판정**으로 적지 마라 — 그건 물체가 아니라서 안 그려진다."
                " 뒤 컷에서 없앨 생각이면 여는 컷에는 **많이** 놓아라(줄어드는 것이 보여야 한다).")
        if "photo_role_claim_mismatch" in wcodes:
            wfix.append(
                "- **컷의 evidence_role 이 그 컷이 가리키는 근거와 맞지 않는다.**"
                " 예: role='mechanism' 인데 연결된 claim 이 기전을 말하지 않는다."
                " 라벨을 바꾸지 말고 **내용을 바꾸거나**, 그 컷이 실제로 하는 일에 맞는"
                " 역할로 정직하게 적어라. 라벨만 고치면 지표는 좋아지고 영상은 그대로다.")
        if "photo_source_has_no_mechanism" in wcodes:
            wfix.append(
                "- **이 논문은 '왜 그런지'를 말하지 않는다**(Fact Sheet 에 기전·연구진 해석"
                " 주장이 없다). 그러니 원리 설명 컷을 억지로 만들지 마라 — 지어내는 것이 된다."
                " 대신 **무엇이 관측됐는지를 또렷하게** 보여줘라: 조건 대비, 전후 비교,"
                " 규모 실감. 화면은 '원리 도해'가 아니라 '관측 현장'을 앵커한다.")
        if "photo_world_churn" in wcodes:
            wfix.append(
                "- **시퀀스마다 새 세계를 만들고 있다.** 발행 벤치마크는 105초 내내 같은 장소에"
                " 머물고 바뀌는 건 축척뿐이다(광역 ↔ 중경 ↔ 근접). 앞 시퀀스의 world_id 를"
                " 재사용하고 camera_base·카메라 동작만 바꿔라. 연결·평가 문장 때문에 세계를"
                " 새로 만들지 마라 — 그릴 것이 없어서 화면이 글자로 채워진다.")
        if "photo_subject_dominates" in wcodes:
            wfix.append(
                "- **연구 대상(동물·장비)이 화면을 너무 오래 차지한다.** 대상은 훅과 규모 실감에서만"
                " 짧게 보이고, 나머지 컷은 원리(도해)·맥락(약이 쓰이는 현장)·의미(시청자의 세계)로"
                " 옮겨라. 절차 컷(주사·케이지·측정)은 한 컷을 넘기지 마라.")
        if "photo_hook_visual_repeated" in wcodes:
            wfix.append(
                "- **훅 두 컷이 같은 그림이다.** 컷1 에서는 대비를 넓게 보여 주고"
                " (나란히 놓기·전후), 컷2 에서는 한쪽으로 **급속 푸시인**하며 숫자를 얹어라."
                " 설정 샷(연구실 전경·우리 속 동물 한 마리·현미경 보는 연구자)은 훅이 아니다.")
        if "photo_no_close_scale" in wcodes:
            wfix.append(
                "- **근접 시점이 하나도 없다.** stage 마다 camera_base 를 적고, 그중"
                " **최소 하나를 close_detail** 로 하라(세계를 새로 만들지 말고 축척만 바꾼다)."
                " 크기 대비가 있어야 실감이 난다 — 벤치마크는 광역 12.7km 에서 손바닥의"
                " 물 한 컵까지 3초 만에 내려온다.")
        if "photo_number_punch_is_a_sentence" in wcodes:
            wfix.append(
                "- **number_punch 에 문장이 들어 있다.** 거기엔 수치와 단위만 남겨라"
                " ('254MW', '+16.9%'). 설명은 evidence_card 로 옮겨라 —"
                " number_punch 는 화면 폭을 크게 차지해서 문장을 넣으면 여러 줄로 감긴다.")
        if "photo_stage_no_transformation" in wcodes:
            wfix.append(
                "- **이 stage 들은 '나타났다·빛난다'만 선언했다.** 둘 다 정지 화면으로도 성립해서"
                " 원리를 설명하지 못하고, 그 컷은 8초 대신 4초를 받아 화면이 거의 멈춘다"
                " (실측 2026-09-12: 13컷 중 12컷이 이 이유 하나로 강등됐다)."
                " 각 stage 의 mutations 에 **실제로 변형되는 것**을 최소 하나 넣어라:"
                " MOVE · GROW · SHRINK · ROTATE · TRANSFORM · SPLIT_OFF · MERGE_INTO ·"
                " REVERSE_TRACE · IMPACT."
                " ★ 라벨만 바꾸지 마라 — 무엇이 어디로 움직이고 무엇이 무엇으로 바뀌는지"
                " state_after 와 visual_prompt 에도 그 변화가 보여야 한다."
                " 예: '유전자 표지가 켜진다(APPEAR)' → '표지들이 전전두엽 쪽으로 모여든다(MOVE)',"
                " '피질이 빛난다(HIGHLIGHT)' → '단면이 열리며 회로가 드러난다(TRANSFORM)'.")
        # ★ 처방 문장을 이미 준 경고는 아래 "가능하면 함께" 목록에서 뺀다 — 같은 사유를
        #   두 번 나열하면 무엇이 중요한지 흐려진다(2026-09-09: subject_dominates 가
        #   처방과 목록에 동시에 나왔다).
        _handled = {"photo_narrative_no_mechanism", "photo_world_churn",
                    "photo_source_has_no_mechanism", "photo_subject_dominates",
                    "photo_hook_visual_repeated", "photo_world_lead_disagrees",
                    "photo_undrawable_difference", "photo_optics_normalized",
                    "photo_mechanism_starts_late", "photo_role_claim_mismatch",
                    "photo_lead_cut_missing_entity", "photo_stage_no_transformation",
                    "photo_no_close_scale", "photo_number_punch_is_a_sentence"}
        rest = sorted(set(warnings) - {w for w in warnings
                                       if w.split(":", 1)[0] in _handled})
        if wfix:
            body += "\n(경고 — 함께 고쳐라)\n" + "\n".join(wfix)
        if rest:
            body += "\n(경고 — 가능하면 함께 고쳐라: " + ", ".join(rest[:5]) + ")"
    return head + body
