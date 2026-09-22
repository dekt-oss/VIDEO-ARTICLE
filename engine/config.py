"""모든 튜닝 상수의 단일 출처(Single Source of Truth).

CLAUDE.md 규약: 가중치·윈도우·정규화식·컷오프 등 매직넘버는 전부 여기에 둔다.
코드 다른 곳에 숫자 상수를 흩뿌리지 않는다. 결정 항목 D1~D7(docs/기획안_리뷰.md)을 반영한다.

환경에서 덮어쓸 수 있는 값은 os.getenv 로 읽되, 합리적 기본값을 코드에 둔다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# 설명판형 시각 계약(v3.4 §22-1) — 밴드 좌표·폰트 역할의 **규범 원본**. 여기서는 렌더 해상도에
# 맞춰 픽셀로 해소만 한다. PIL 은 그 모듈 안에서 지연 import 되므로 수집·채점 잡에 영향 없다.
from . import visual_contract

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


# ─────────────────────────────────────────────────────────────
# 타임존 / 수집 윈도우  (D5, D2)
# ─────────────────────────────────────────────────────────────
TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Seoul")
# 최근 N일 롤링 윈도우. "어제 1일"만 보면 신선 논문은 buzz/피인용이 0이라 필터가 비므로
# 윈도우를 넓혀 buzz 가 붙을 시간을 확보한다(리뷰 2-1).
COLLECT_WINDOW_DAYS: int = _get_int("COLLECT_WINDOW_DAYS", 10)


# ─────────────────────────────────────────────────────────────
# 1차 필터  (D2 — buzz 는 필수조건이 아니라 가점)
# ─────────────────────────────────────────────────────────────
# 통과 조건: 초록이 존재하고, 언어가 아래 집합에 속할 것. buzz 유무는 통과조건이 아님.
PRIMARY_FILTER_LANGS: tuple[str, ...] = ("en", "ko")
PRIMARY_FILTER_MIN_ABSTRACT_CHARS: int = 80
# 2차 LLM 채점으로 넘길 모수 상한(발행 최신순 + buzz 가점으로 정렬 후 상위 N).
SCORE_CUTOFF_N: int = _get_int("SCORE_CUTOFF_N", 150)


# ─────────────────────────────────────────────────────────────
# 5축 점수 가중치  (명세 3-1)
# ─────────────────────────────────────────────────────────────
# 재미 지수 = w_surprise*① + w_explain*② + w_relate*③
FUN_WEIGHTS: dict[str, float] = {
    "surprise": 0.40,
    "explainability": 0.35,
    "relatability": 0.25,
}
# 중요성 지수 = w_significance*④ + w_buzz*⑤
IMPORTANCE_WEIGHTS: dict[str, float] = {
    "significance": 0.70,
    "buzz": 0.30,
}

# ─────────────────────────────────────────────────────────────
# 제작 준비도 루브릭 (수정지시서 v2 §6) — 선별 위 얹는 "제작 게이트"
# ─────────────────────────────────────────────────────────────
# 기존 4축(0~10, 정렬용)은 그대로 두고, 제작 여부를 가르는 5축·각 0~2점(총 10) 게이트를 추가한다.
# 각 축에 한 문장 근거를 함께 저장(가짜 정밀도 방지 — 100점표 대신 거친 0~2). 대시보드에 게이트 배지.
PRODUCTION_AXES: tuple[str, ...] = (
    "novelty",        # 놀라움 — 기존 상식과 다른가
    "audience_value",  # 시청자 영향 — 개인·사회·산업에 의미 있나
    "hook_fit",       # 근거-훅 정합 — 논문 결론과 훅이 일치하나
    "explain_60s",    # 60초 설명력 — 원인→결과를 60초에 설명 가능한가
    "visualizable",   # 시각화 가능성 — 수치·비교·움직임으로 보일 수 있나
    # ★★ 2026-09-04 추가 — **선별이 화면 품질의 상한을 정한다**.
    #   우리는 "3D 도해로 원리를 설명하는 영상"을 만드는데, 선별은 그동안
    #   "이 논문이 왜인지를 설명하는가"를 **한 번도 묻지 않았다.**
    #   실측: 고정 대상 논문(PNAS, 성격 조합)의 원문 전문 46,952자에
    #   mechanism 0회·we argue 0회·driven by 0회·the reason 0회·why 0회.
    #   그 논문으로 원리 영상을 만들려다 "화면이 겉돈다 → 프롬프트 수정 →
    #   또 겉돈다"를 반복했다. 화면 엔진이 풀 수 있는 문제가 아니었다.
    #   ★ explain_60s 와 다르다: 그건 "60초에 설명 가능한가"이고 결과만 있는 논문도
    #     높게 받는다("이 조합이 나빴다"는 쉽다). 이 축은 **논문이 설명을 제공하는가**다.
    "mechanism",      # 원리 제공 — 논문이 "왜 그런지"를 스스로 설명하는가
)
PRODUCTION_AXIS_MAX: int = 2  # 각 축 0~2
PRODUCTION_SCORE_MAX: int = PRODUCTION_AXIS_MAX * len(PRODUCTION_AXES)  # 12
# 게이트 컷 — **비율이 정본이다**(2026-09-04). 종전에는 정수 총점(8/6/4, 만점 10)이었다.
#
# ★★ 왜 비율로 바꿨나: mechanism 축을 더해 만점이 10 → 12 가 되자, 정수 문턱으로는
#   같은 논문의 등급이 저절로 움직였다. 실측으로 **저장된 3,976행 중 1,284행**이 바뀌었고
#   그중 `make → redesign` 이 681행이었다. 그 논문들은 아무것도 나빠지지 않았다 —
#   자만 바뀌었다. 정수로 옮기려 해도 0.8 × 12 = 9.6 이라 **정확히 옮길 수가 없다**
#   (올림하면 조여지고 내림하면 헐거워진다. 올림해 보니 508행이 여전히 움직였다).
#   비율로 두면 축을 더 늘려도 이 사고가 구조적으로 사라진다.
# ★ 옛 행(만점 10)은 옛 만점으로 나눠 판정한다 — scoring.stored_scale 참조.
PRODUCTION_GATE_MAKE_RATIO: float = _get_float("PRODUCTION_GATE_MAKE_RATIO", 0.8)
PRODUCTION_GATE_REDESIGN_RATIO: float = _get_float("PRODUCTION_GATE_REDESIGN_RATIO", 0.6)
PRODUCTION_GATE_BACKLOG_RATIO: float = _get_float("PRODUCTION_GATE_BACKLOG_RATIO", 0.4)


# ─────────────────────────────────────────────────────────────
# ④ 학술중요성 보정  (D6 — P0 기본 off, 데이터로 on/off 비교)
# ─────────────────────────────────────────────────────────────
ENABLE_SIGNIFICANCE_BOOST: bool = _get_bool("ENABLE_SIGNIFICANCE_BOOST", False)
SIGNIFICANCE_BOOST_TOP_VENUE: float = 2.0   # Nature/Science/Cell/주요 학회
SIGNIFICANCE_BOOST_PRESS_PICKUP: float = 1.0  # 과학 보도(EurekAlert 등)
SIGNIFICANCE_MAX: float = 10.0
# 최상위 게재처 판정에 쓰는 키워드(소문자 부분일치).
TOP_VENUE_KEYWORDS: tuple[str, ...] = (
    "nature", "science", "cell", "lancet", "new england journal",
    "pnas", "neurips", "icml", "cvpr",
)


# ─────────────────────────────────────────────────────────────
# ⑤ buzz 정규화  (D7 — 로그 스케일 권장)
# ─────────────────────────────────────────────────────────────
# buzz_raw(예: HN points + Reddit score 합) → 0~10.
# score10 = min(10, BUZZ_LOG_COEFF * log1p(raw))  형태.
BUZZ_LOG_COEFF: float = 2.5
BUZZ_SCORE_MAX: float = 10.0


# ─────────────────────────────────────────────────────────────
# daily_batch  (명세 3-4)
# ─────────────────────────────────────────────────────────────
DAILY_BATCH_SIZE: int = _get_int("DAILY_BATCH_SIZE", 20)
SORT_MODES: tuple[str, ...] = ("fun", "importance", "golden")  # 재미 / 중요 / 황금(곱)

# 한 바퀴에 각 정렬이 가져가는 자리 수. 목록 **순서**가 아니라 **구성**을 정한다
# (화면은 이미 황금순으로 보여 준다 — `web/components/CandidateList.tsx`).
#
# ★ 왜 균등이 아닌가(2026-09-22 실측, `scripts/score_axis_audit.py`).
#   사람 판정 256건에 대고 재 보니 세 정렬의 성적이 다르다:
#       golden 이 데려온 후보의 낙점률 20.8%(71/342)
#       fun        13.3%(53/399)   ·   importance 12.0%(48/399)
#   낙점/탈락 판별력도 황금지수 AUC 0.695 로 재미 0.623·중요 0.609 보다 높다.
#   그런데 균등 라운드로빈이라 **가장 잘 맞히는 정렬이 자리의 1/3만** 받고 있었다.
#
# ★ 셋을 유지하는 이유: 황금은 곱이라 한쪽이 낮으면 통째로 깎인다. "재미는 없지만
#   중요한" 논문은 황금 단독 정렬에서 영영 안 올라온다 — 다양성의 값을 0으로 만들지 않는다.
BATCH_MODE_SLOTS: dict[str, int] = {"golden": 2, "fun": 1, "importance": 1}
# 신선도: 이전 후보 리스트(과거 daily_batch)에 오른 논문은 다음 리스트 후보에서 제외.
# 매일 선별하되 날마다 같은 논문이 반복 등장하는 것을 막는다. env 로 끌 수 있다.
BATCH_EXCLUDE_PRIOR: bool = os.getenv("BATCH_EXCLUDE_PRIOR", "1").strip() not in ("0", "false", "False", "")

# 후보(그리고 채점) 대상의 나이 상한. **오늘 새로 생긴 규칙이 아니라, 원래 있던 것을
# 글로 적은 것이다.**
#
# ★★ 그동안 이 창은 코드에 없었고 **버그가 대신 하고 있었다**(2026-09-22 실측).
#   `fetch_papers_to_score` 가 조건 없는 select 로 papers 를 읽었고 PostgREST 가 그것을
#   1,000행에서 잘랐다. 정렬이 `published_date desc` 라 결과적으로 "가장 최근 1,000편"만
#   후보가 됐고, 그 경계가 마침 **약 21일**이었다(6,016편 중 1,000번째 = 21일 전).
#   잘림을 고치면 후보 풀이 2007년까지 열린다 — 그래서 같은 창을 **명시로** 둔다.
#
# ★ 이 창은 채점 대상에도 건다. 화면에 못 올라갈 논문을 채점하는 것은 그냥 돈이다.
BATCH_MAX_AGE_DAYS: int = _get_int("BATCH_MAX_AGE_DAYS", 21)


# ─────────────────────────────────────────────────────────────
# LLM 모델 ID  (CLAUDE.md 고정)
# ─────────────────────────────────────────────────────────────
# 기본은 품질 우선(sonnet/opus)이지만, 비용 절감을 위해 env 로 모델을 교체할 수 있다.
# 예: MODEL_SCORING=claude-haiku-4-5-20251001 로 채점 비용 1/5~1/10.
MODEL_SCORING: str = os.getenv("MODEL_SCORING", "gemini-2.5-flash")       # 5축 채점
MODEL_FACTSHEET: str = os.getenv("MODEL_FACTSHEET", "gemini-2.5-flash")    # Fact Sheet 추출
MODEL_SELFCHECK: str = os.getenv("MODEL_SELFCHECK", "gemini-2.5-flash")    # 자기검증
# ★ 기본을 flash 로 내렸다(2026-08-29). pro/opus 는 flash 의 25~30배이고, 어제 실측에서
#   대본 합성이 그날 텍스트 비용의 큰 몫을 먹었다(논문 16편 × 3안 = 48벌).
#   품질이 필요한 편은 MODEL_SCRIPT 를 **명시로** 올려 쓴다 — 비싼 것이 기본값이면
#   아무도 모르는 사이에 돈이 나간다.
MODEL_SCRIPT: str = os.getenv("MODEL_SCRIPT", "gemini-2.5-flash")            # 대본 합성
# 한국어 채점/추출 JSON(긴 rationale·red_flag 포함)이 잘리지 않도록 넉넉히.
# ★ 2048 은 한글 출력에 부족해 JSON 이 잘려 파싱 실패→전 축 0점이 되던 원인이었다.
LLM_MAX_TOKENS: int = 8192
# 대본 합성 전용 출력 상한. ★ 실측 사고(2026-08-03): 리포트 초안 3건이 연속으로
#   `Expecting ',' delimiter: line 693 column 8 (char 19194)` 로 죽었다. 모델이 이상한
#   JSON 을 낸 게 아니라 **출력이 6144 토큰에서 잘린** 것이었다(19K자 ≈ 6144토큰).
#   대본 1편은 씬 6~7개 × (제목·한/영 나레이션·이미지 프롬프트 한/영·영상 프롬프트 한/영
#   ·source_facts) + story_plan + video_flow 라 필드가 많다. 근거가 풍부한 리포트일수록
#   길어져서, 데이터가 좋은 편일수록 먼저 죽는 역설이 있었다.
#   Opus 는 훨씬 큰 출력을 지원하므로 여유를 둔다 — 상한은 사고를 막는 안전장치이지
#   비용 조절 수단이 아니다(출력 토큰은 실제 쓴 만큼만 과금된다).
LLM_SCRIPT_MAX_TOKENS: int = _get_int("LLM_SCRIPT_MAX_TOKENS", 16384)
# 논문 대본 전용 출력 상한. ★ `scriptgen.py:439` 에 **8192 로 박혀 있던 것**을 꺼낸다
#   (매직넘버 금지 — config 밖에 있으면 env 로 못 바꾸고 근거도 안 남는다).
#   ★ 값을 32768 로 올리는 근거(2026-09-22, 원장 실측):
#       gemini-2.5-flash 의 논문 대본 출력 최대 **5,955** = 옛 상한 8,192 의 **73%**
#     제미나이조차 4분의 3을 쓴다. 그리고 같은 일에 **DeepSeek 은 2.4배를 쓴다**
#     (지시서 실측: 제미나이 12,738 vs 딥시크 30,085). 5,955 × 2.4 ≈ 14,300 —
#     옛 상한으로는 **딥시크를 붙이는 순간 확실히 잘린다.**
#   ★★ 이 저장소는 그 사고를 이미 두 번 겪었고 두 번 다 "모델이 못한다"고 오판했다:
#     deepseek-flash 가 지시서에서 3/3 절단(32,768 정각), Fact Sheet 에서 8,192 정각.
#     천장이 공급자를 떨어뜨린 것을 그 공급자의 실력으로 읽으면 측정이 거짓말을 한다.
LLM_PAPER_SCRIPT_MAX_TOKENS: int = _get_int("LLM_PAPER_SCRIPT_MAX_TOKENS", 32768)
# 자기검증 전용 출력 상한. ★ `selfcheck.py:239` 에 **6144 로 박혀 있던 것**을 꺼낸다.
#   실측: gemini-2.5-flash 최대 3,016(상한의 49%). × 2.4 ≈ 7,240 — 옛 상한을 넘는다.
#   2026-09-10 에 `korean_natural`·`awkward_spans`·`fluency_issues` 축이 같은 호출에
#   얹히면서 출력이 더 두꺼워졌다(§대본 한국어 검수). 여유를 둔다.
LLM_SELFCHECK_MAX_TOKENS: int = _get_int("LLM_SELFCHECK_MAX_TOKENS", 16384)
# 지시서 생성 전용 출력 상한. ★ 코드에 8192 로 박혀 있던 것을 꺼낸다(매직넘버 금지).
#   실측(2026-08-29): 11컷 실사형에서 **Anthropic 경로만** 잘렸다. Gemini pro 는
#   `max(max_tokens, GEMINI_PRO_MAX_OUTPUT_TOKENS)` 로 자체 하한을 받아 살아남는데,
#   Anthropic 은 이 값을 그대로 쓴다 — 즉 같은 프롬프트가 백엔드에 따라 죽고 살았다.
#   컷이 늘고(골격) 재사용 컷에 state_change 가 필수가 되면서 출력이 더 커졌다.
#   상한은 사고를 막는 안전장치이지 비용 조절 수단이 아니다(출력은 쓴 만큼만 과금된다).
# ★ 16384 → 32768 (2026-09-02 실측): 원문 전문이 있는 실제 초안(Moon Impactor, 10 claims,
#   34,835자)으로 photo 지시서를 만들자 **Gemini flash 경로도** 16384 에서 잘렸다
#   (사고 토큰은 0 — 순수 출력이다). 컷마다 temporal_plan 비트·mechanism 구조·
#   stage_mutations·overlay_plan 이 붙고 [컷 수] 규칙이 12컷 이상을 요구하니 출력이
#   4만 자를 넘는다. Fact Sheet 때처럼 "개수를 묶는" 답은 여기엔 안 맞는다 — 컷 수는
#   이미 목표 길이에서 역산돼 묶여 있고, 잘린 것은 개수가 아니라 컷당 계약의 두께다.
#   flash 2.5 의 출력 상한은 65,536 이라 여유가 있다.
# ★★ 32768 → 49152 (2026-09-19 실측, DeepSeek 전환과 함께): 같은 프롬프트에서 출력량이
#   **백엔드마다 2배 넘게 다르다.** 지시서 3벌씩 실측한 값이다:
#       gemini-2.5-pro   12,616 / 13,063 / 13,104  (상한의 55%까지)
#       deepseek-v4-pro  28,403 / 29,403 / 30,928  (상한의 **94%**)
#       deepseek-flash   32,768 / 32,768 / 32,768  (**정확히 상한 — 3/3 절단 실패**)
#   deepseek-flash 가 상한을 정확히 채웠다는 것이 이 상한에 **닿을 수 있다는 증거**다.
#   v4-pro 는 94% 까지 갔다 — 한 번만 길게 쓰면 잘리고, 절단은 재시도가 소용없는
#   하드 에러라 파이프라인이 선다. 이건 위 2026-08-29 주석이 말한 바로 그 상황이다:
#   "같은 프롬프트가 백엔드에 따라 죽고 살았다 … 상한이 잘못 놓였다는 뜻이다."
#   상한은 사고를 막는 안전장치이지 비용 조절 수단이 아니다 — 출력은 쓴 만큼만 과금되므로
#   올려 둔다고 비싸지지 않는다. Gemini 쪽은 55% 밖에 안 쓰므로 영향이 없다.
LLM_DIRECTIVE_MAX_TOKENS: int = _get_int("LLM_DIRECTIVE_MAX_TOKENS", 49152)
# Fact Sheet 추출 전용 출력 상한. ★ 실측(2026-08-03, 운영): 대본이 아니라 **여기가** 먼저
#   잘리고 있었다 — 새 진단이 그것을 바로 말해 줬다:
#     `출력이 maxOutputTokens(8192)에서 잘렸다 — 상한을 올려야 한다 (model=gemini-2.5-flash)`
#   원인은 추출 프롬프트에 원문 전문이 들어가면서(§4-2) Fact Sheet 가 훨씬 두꺼워진 것이다.
#   number_facts 하나가 fact_id·value·unit·period·metric·scope·basis·attribution·
#   interpretation·source_page·comparator·source_refs(원문 인용 최대 300자)·display 라
#   수치가 20개만 돼도 1만 자를 넘는다. 기본값 8192 로는 근거가 풍부한 리포트일수록 먼저 죽었다.
LLM_FACTSHEET_MAX_TOKENS: int = _get_int("LLM_FACTSHEET_MAX_TOKENS", 16384)
# ★★ 상한만으로는 안 풀렸다(실측 2026-08-03). 8192 → 16384 로 올려도 같은 자리에서 잘렸다:
#     출력이 maxOutputTokens(16384)에서 잘렸다 — … (model=gemini-2.5-flash)   [64초 소요]
#   ★ 처음엔 "모델이 반복 생성한다"고 적었는데 **틀렸다.** 원문을 실제로 세어 보니
#     11,996자 안에 **숫자 토큰이 1,194개**였다(증권사 리포트라 표가 빽빽하다 —
#     목표주가·사업부별 적용배수·3개년 추정치·PER 밴드…). 모델은 반복한 게 아니라
#     **성실하게 다 뽑고 있었다.**
#   진짜 원인은 **숫자 하나당 스키마 비용**이다. fact 하나가 fact_id·value·unit·period·
#   metric·scope·basis·attribution·interpretation·source_page·comparator·
#   source_refs(원문 인용 최대 300자)·display 라 400~600자다. 100개만 뽑아도 4~6만 자 —
#   16384 토큰(약 39,000자)에서 잘린 지점과 정확히 맞는다.
#   즉 입력이 큰 게 아니라(11,996자는 작다) **출력이 입력의 3~5배로 불어나는 구조**였다.
#   그래서 상한을 또 올리지 않고 **계약을 묶는다**: 프롬프트가 개수를 명시하고, 코드가 자른다.
#   품질에도 맞다 — 25초 영상에 쓸 수 있는 수치는 어차피 몇 개뿐이고, 30개짜리 Fact Sheet 는
#   고르는 일을 하류로 떠넘긴 것에 불과하다.
FACTSHEET_MAX_NUMBER_FACTS: int = _get_int("FACTSHEET_MAX_NUMBER_FACTS", 20)
# 논문 Fact Sheet 의 claim 상한. ★ 같은 사고가 논문 라인에서 재현됐다(2026-08-29):
#   원문 전문(34,835자)을 추출 프롬프트에 넣자 **16384 토큰에서 잘렸다** — 리포트 라인이
#   2026-08-03 에 겪은 것과 같은 자리다. claim 하나가 20개 필드(population·sample_size·
#   study_design·effect_size·uncertainty·source_quote…)라 500~800자이고, 논문 한 편에서
#   뽑을 수 있는 주장은 수십 개다. 출력이 입력의 몇 배로 불어난다.
#   그때 배운 답을 그대로 쓴다: **상한을 또 올리지 않고 개수를 묶는다.**
#   품질에도 맞다 — 45초 영상이 지불할 수 있는 주장은 대여섯 개뿐이고, 30개짜리 원장은
#   고르는 일을 하류로 떠넘긴 것에 불과하다.
FACTSHEET_MAX_CLAIMS: int = _get_int("FACTSHEET_MAX_CLAIMS", 10)
# 인용 대조에서 요구하는 **연속 일치 비율**. 1.0 이면 완전 일치.
#   ★ 왜 1.0 이 아닌가(2026-08-29 실측): 표기 차이를 규칙으로 쫓으면 서로 충돌한다 —
#     각주 `$^{1}$` 는 빼야 맞고(본문에선 9번), 단위 지수 `km s$^{-1}$` 는 빼면 깨진다.
#     실측 사례는 130자 중 129자가 일치하고 각주 번호 하나만 달랐다. 그 하나 때문에
#     정상 주장을 "지어낸 인용"으로 차단하면 게이트가 통째로 불신된다.
#   ★ 낮추지 마라: 0.9 는 "원문을 거의 그대로 옮겼다"는 뜻이고, 그보다 낮추면 의역이
#     통과하기 시작한다 — 그 순간 이 검증은 아무것도 보증하지 않는다.
EVIDENCE_QUOTE_MATCH_RATIO: float = _get_float("EVIDENCE_QUOTE_MATCH_RATIO", 0.9)
LLM_JSON_RETRY: int = 1   # JSON 파싱 실패 시 재시도 횟수(명세 3-3)

# Gemini(재미나이) 대체 백엔드: 모델 id 가 "gemini" 로 시작하면 이 경로로 라우팅(REST).
# 무료 등급 비용 절감용. GEMINI_API_KEY 필요.
GEMINI_BASE: str = "https://generativelanguage.googleapis.com/v1beta/models"

# DeepSeek — OpenAI 호환 엔드포인트. 모델 ID 는 **라이브 /models 로 확인한 것만** 쓴다
# (2026-09-19 실측: deepseek-flash, deepseek-v4-pro. 널리 알려진 deepseek-chat /
#  deepseek-reasoner 는 이 계정에 존재하지 않는다 — 추측한 모델명을 넣으면 404 다).
DEEPSEEK_BASE: str = os.getenv("DEEPSEEK_BASE", "https://api.deepseek.com")
# 무료 등급 RPM 제한(예: flash 15 RPM) 대비 요청 간 최소 간격.
GEMINI_MIN_INTERVAL_SEC: float = 4.5
# ★ gemini-2.5* 는 추론 모델이라 사고(thinking) 토큰이 maxOutputTokens 를 잠식해 JSON 이 비거나
#   잘린다(채점 JSON 파싱 실패의 주원인). 채점/추출은 구조화 과제이므로 사고를 끈다(thinkingBudget=0).
#   단, flash 만 사고 끄기(budget 0)가 허용되고 pro 는 "This model only works in thinking mode"(400)로 거부한다.
GEMINI_THINKING_BUDGET: int = 0
# pro 등 사고 필수 2.5 모델: 사고를 못 끄므로 사고 토큰이 JSON 을 자르지 않도록 출력 예산을 키운다.
GEMINI_PRO_MAX_OUTPUT_TOKENS: int = 32768
# ★ Gemini 가 계속 5xx/429 를 내면(모델 과부하·쿼터 소진) Anthropic 으로 갈아탄다.
#   엣지 함수(generate-report-draft)는 진작부터 이렇게 하고 있었는데 **워커에만 없어서**,
#   같은 503 이 엣지에서는 폴백으로 넘어가고 워커에서는 요청이 error 로 죽었다(실측:
#   report_directive_requests 2건, "503 from gemini", 2026-08-04). 트윈을 맞춘다.
#   빈 문자열이면 폴백을 끈다. ANTHROPIC_API_KEY 가 없으면 자동으로 꺼진다.
# ★ 기본 꺼짐(2026-08-29 운영자 확정: "앤트로픽 폴백 연결은 없습니다").
#   그리고 그날 이 폴백이 실제로 사고를 냈다: Gemini 가 **크레딧 소진**으로 429 를 냈는데
#   폴백이 발동해 크레딧 없는 Anthropic 으로 30분간 재시도하다 타임아웃했고, 진짜 원인
#   ("Your prepayment credits are depleted")은 로그 어디에도 남지 않았다.
#   429 는 "공급자가 죽었다"가 아니라 "천천히 하라" 또는 "돈이 없다"다 — 폴백 대상이 아니다.
#   쓰려면 값을 명시로 넣어야 한다.
LLM_ANTHROPIC_FALLBACK_MODEL: str = os.getenv("LLM_ANTHROPIC_FALLBACK_MODEL", "")
# ★★ Anthropic 경로 하드 차단(2026-08-29 운영자 지시: "앤트로픽 경로 전부 코드에서 막아").
#
#   왜 기본값을 바꾸는 것만으로 부족한가: 오늘 실제로 그랬다. 세션 초반에 운영자가
#   "제미나이로 해야지"라고 했고 나는 **그 실행만** Gemini 로 바꿨다. 기본값(MODEL_DIRECTIVE·
#   MODEL_SCRIPT·폴백)은 Anthropic 그대로 뒀고, 그래서 오늘 지시서 생성이 Anthropic 으로
#   나갔고 Gemini 429 마다 자동으로 Anthropic 으로 넘어갔다. 잔액이 0이라 400 으로 거절돼
#   과금은 안 됐지만, **그건 운이 좋았던 것이지 내가 막은 것이 아니다.**
#
#   그래서 판정을 코드로 옮긴다: 이 값이 참이면 engine/llm.py 가 Anthropic 클라이언트를
#   아예 만들지 않고 즉시 에러를 낸다. 모델 ID 가 claude 로 시작해도, 폴백이 켜져 있어도,
#   환경변수에 키가 있어도 나가지 않는다. 쓰려면 명시로 꺼야 한다.
ANTHROPIC_DISABLED: bool = _get_bool("ANTHROPIC_DISABLED", True)
# ★ 폴백이 있을 때 gemini 를 몇 번까지 시도할까. HTTP_MAX_RETRIES(4)를 그대로 쓰면 과부하가
#   *지연*으로 나타날 때 4 × LLM_HTTP_TIMEOUT_SEC(180초) + 백오프 ≈ 12분을 쓴다 —
#   report-draft.yml 잡 상한이 15분이라 폴백에 닿기 전에 잡이 죽는다. 갈아탈 곳이 있으면
#   오래 기다릴 이유가 없다(2회 ≈ 6분). 폴백이 없으면 이 값을 쓰지 않고 끝까지 버틴다.
GEMINI_ATTEMPTS_WITH_FALLBACK: int = _get_int("GEMINI_ATTEMPTS_WITH_FALLBACK", 2)


# ─────────────────────────────────────────────────────────────
# 레이트리밋 / 재시도  (CLAUDE.md, 리뷰 4)
# ─────────────────────────────────────────────────────────────
ARXIV_REQUEST_INTERVAL_SEC: float = 3.0   # arXiv 요청 간 최소 간격(명세 2-1)
HTTP_TIMEOUT_SEC: float = 30.0
# ★ LLM 호출만 별도 타임아웃. 30초는 arXiv/OpenAlex 조회엔 맞지만 생성 호출엔 짧다.
#   gemini-2.5-pro 는 사고(thinking)를 못 끄고 출력 예산도 32768 로 키워 두기 때문에
#   지시서 한 건에 1분 이상 걸린다. 30초로 두면 tenacity 가 4회 재시도한 뒤
#   "The read operation timed out" 으로 죽는다(리포트 지시서 생성 실패 원인).
#   초안 대본도 같은 벽에 걸렸다 — 2026-07-29 실측 gemini-2.5-pro 대본 호출 60.5초
#   (Actions run 30455288327). 30초일 때는 4회 전부 read timeout 이었다(run 30454427379).
LLM_HTTP_TIMEOUT_SEC: float = float(os.getenv("LLM_HTTP_TIMEOUT_SEC", "180"))
HTTP_MAX_RETRIES: int = 4                 # API 5xx/타임아웃 지수 백오프
HTTP_BACKOFF_BASE_SEC: float = 2.0

# PostgREST 가 조건 없는 select 를 조용히 자르는 지점. 이 값으로 페이징한다
# (`db.select_all`). 1,000 은 서버 기본값이라 **올려도 소용없다** — 나눠 읽는 수밖에 없다.
DB_PAGE_ROWS: int = 1000


# ─────────────────────────────────────────────────────────────
# 데이터 소스 엔드포인트
# ─────────────────────────────────────────────────────────────
OPENALEX_BASE: str = "https://api.openalex.org/works"
OPENALEX_PER_PAGE: int = 200
# 수집 폭주 방지: 윈도우 내 works 를 무한 페이지네이션하지 않도록 상한.
# 최신순(publication_date desc)으로 받아 상한까지만. 1차 필터·컷오프가 뒤에서 더 줄인다.
OPENALEX_MAX_RESULTS: int = _get_int("OPENALEX_MAX_RESULTS", 1000)
# 동료 리뷰(peer-reviewed) 한정: type=article + 저널 소스만 수집(프리프린트·세미나·데이터셋 제외).
# 품질을 크게 올리는 핵심 토글. ko 논문 유지를 위해 언어는 1차 필터에서 따로 처리.
PEER_REVIEWED_ONLY: bool = _get_bool("PEER_REVIEWED_ONLY", True)
ARXIV_BASE: str = "http://export.arxiv.org/api/query"
ARXIV_CATEGORIES: tuple[str, ...] = ()  # 비면 전체. 예: ("cs.AI", "cs.LG")
HN_ALGOLIA_BASE: str = "https://hn.algolia.com/api/v1/search_by_date"
REDDIT_SUBREDDITS: tuple[str, ...] = ("science", "EverythingScience")
# buzz 수집 시 논문 링크로 인정할 도메인(HN/Reddit 글에서 추출).
PAPER_LINK_DOMAINS: tuple[str, ...] = ("arxiv.org", "doi.org", "biorxiv.org", "medrxiv.org")
# 응답 대역폭 절감: OpenAlex select 로 필요한 필드만 받는다(수집지시서 v2 §3-4).
OPENALEX_SELECT_FIELDS: str = (
    "id,doi,title,abstract_inverted_index,publication_date,created_date,updated_date,"
    "type,primary_location,authorships"
)


# ─────────────────────────────────────────────────────────────
# 수집 커버리지 v2 — 플래그십 저널 (docs/deviation-collection-coverage-v2.md)
# ─────────────────────────────────────────────────────────────
# 주 수집(좁은 게재일 창 + 1000컷)은 플래그십 본지를 놓친다(실측: Nature/Science/Cell/Lancet/NEJM
# 역대 0편). 그래서 "플래그십 source_id 로만 좁힌 넓은 게재일 롤링 창"을 따로 훑는다. 소스가 좁아
# 볼륨이 작으므로 컷 손실이 없고, 게재 당시 미색인이던 논문도 다음 실행(창이 넓음)에서 잡힌다.
# ★ created_date 워터마크(수집지시서 v2 §3-1)는 OpenAlex 유료 플랜 전용 필터라 무료 티어에선 불가 —
#   docs/deviation-collection-coverage-v2.md 에 사유 기록, 동등한 무료 방식(넓은 게재일 창)으로 대체.
# source_id·ISSN-L 로 엄격 구분(저널명 문자열 매칭 금지).
FLAGSHIP_SOURCES: tuple[dict[str, Any], ...] = (
    {"source_id": "S137773608", "issn_l": "0028-0836", "name": "Nature", "is_flagship": True, "enabled": True},
    {"source_id": "S3880285",   "issn_l": "0036-8075", "name": "Science", "is_flagship": True, "enabled": True},
    {"source_id": "S110447773", "issn_l": "0092-8674", "name": "Cell", "is_flagship": True, "enabled": True},
    {"source_id": "S62468778",  "issn_l": "0028-4793", "name": "New England Journal of Medicine", "is_flagship": True, "enabled": True},
    {"source_id": "S49861241",  "issn_l": "0099-5355", "name": "The Lancet", "is_flagship": True, "enabled": True},
    {"source_id": "S125754415", "issn_l": "0027-8424", "name": "Proceedings of the National Academy of Sciences", "is_flagship": True, "enabled": True},
)
# 플래그십 수집 대상 문서 유형(§4-2). article/review 만, paratext/retracted 제외.
FLAGSHIP_ALLOWED_TYPES: tuple[str, ...] = ("article", "review")
# 정규 수집 롤링 게재일 창(일). 지연 색인분을 다음 실행에서 잡을 만큼 넓게(월 단위). 30 = 약 한 달 소급.
FLAGSHIP_PUB_LOOKBACK_DAYS: int = _get_int("FLAGSHIP_PUB_LOOKBACK_DAYS", 30)
# 초기 백필: 배포 직후 과거 누락분을 이 기간만큼 1회 메운다(LHS 1140b 등 즉시 구제).
FLAGSHIP_BACKFILL_DAYS: int = _get_int("FLAGSHIP_BACKFILL_DAYS", 90)
# 플래그십 수집 상한(주 수집 1000 과 별도). 6개 저널 롤링창이라 넉넉히(백필 90일 ≈ 1900편 대비).
FLAGSHIP_MAX_RESULTS: int = _get_int("FLAGSHIP_MAX_RESULTS", 3000)

# ─ 과학 언론 RSS(P2, §6) — 발견 + 화제성 신호 전용(품질 근거 아님, 본문 복제 금지) ─
# 파서 실패 시 로그+무시(전체 중단 금지). content_type 으로 역할 구분.
PRESS_FEEDS: tuple[dict[str, str], ...] = (
    {"feed_id": "eurekalert_all", "url": "https://www.eurekalert.org/rss/technology_engineering.xml", "content_type": "press_release"},
    {"feed_id": "physorg", "url": "https://phys.org/rss-feed/", "content_type": "science_news"},
    {"feed_id": "nature_news", "url": "https://www.nature.com/nature.rss", "content_type": "flagship_news"},
    {"feed_id": "science_news", "url": "https://www.science.org/rss/news_current.xml", "content_type": "flagship_news"},
)
PRESS_ENABLED: bool = _get_bool("PRESS_ENABLED", True)
# 다단계 DOI 매칭 자동연결 임계(§6): 제목 유사도 + 연도·제1저자 일치 동반 필수.
PRESS_TITLE_SIMILARITY_MIN: float = float(os.getenv("PRESS_TITLE_SIMILARITY_MIN", "0.94"))
# 언론 언급 1건이 buzz total 에 더하는 가중(품질 아닌 화제성 신호 — 과대반영 방지로 작게).
PRESS_SIGNAL_WEIGHT: float = float(os.getenv("PRESS_SIGNAL_WEIGHT", "2.0"))


# ─────────────────────────────────────────────────────────────
# 영상화 파이프라인 (P-V0/P-V1)  (docs/deviation-render-pipeline.md, DV1~DV6)
# ─────────────────────────────────────────────────────────────
# 제공 버전: 만화식(comic)·웹툰 장면파생(webtoon)·이미지 나열식(image_sequence 레거시).
# 모두 핵심 컷 3~4개를 I2V 영상 클립(Veo)으로 포함한다.
# (구 animation/hybrid 는 제거 — 기존 저장 지시서는 저장된 값으로 렌더 계속 가능.)
# webtoon = 장면 파생형(docs/수정명세서_웹툰버전_v1.md): 새로 만드는 것은 **장면**이고 컷은 그 장면에서
#   크롭으로 파생한다. comic 과 같은 웹툰 화풍이되 카메라 이동을 생성이 아니라 크롭으로 만든다는 점이 다르다.
# ★ editorial(B타입 데이터 에디토리얼)은 2026-07-28 폐기했다 — docs/deviation-webtoon-b1-removal.md.
#   저장된 version_type='editorial' 행은 그대로 렌더되지만(free text 컬럼) 새로 발주할 수 없고,
#   그 행의 data_viz 컷은 코드차트가 아니라 스틸로 나간다.
# ★ explainer(설명판형 데이터 에디토리얼)는 **금융 리포트 라인 전용** 버전이다
#   (docs/개선명세서_설명판형_v3_3.md · docs/deviation-explainer-v3_3.md). 논문 라인 발주 화면
#   (web/lib/versions.ts VERSION_META)에는 노출하지 않는다 — enum 은 공유하지만 발주는 분리.
# ★ photo(실사형)는 2026-08-19 추가 — 만화식·설명판형과 나란히 발주해 비교한다(운영자 결정).
# ★ 폐기(새로 발주 불가, 저장된 옛 행은 계속 렌더된다 — editorial 전례):
#   webtoon·explainer 2026-08-28 운영자 결정. 근거: docs/deviation-drop-explainer-webtoon.md
VIDEO_VERSIONS: tuple[str, ...] = ("comic", "image_sequence", "photo")
DEFAULT_VERSION: str = "image_sequence"

# ★ 초안 요청이 `version_types` 를 실으면 워커가 초안을 저장한 뒤 **같은 실행에서** 그 버전들의
#   지시서를 이어서 만든다(2026-09-11 운영자 지시 "초안 생성에서 바로 스타일을 고르게" —
#   docs/설계안_초안지시서_통합발주_v2.md). 끄면 version_types 를 무시하고 옛 동선(⑤ 에서 따로
#   발주)으로 돌아간다. 지시서 실패는 초안을 실패로 만들지 않는다.
DRAFT_CHAINS_DIRECTIVE: bool = _get_bool("DRAFT_CHAINS_DIRECTIVE", True)
# 버전 → 컷 기본 visual_type. 영상 컷(motion_source=video)도 이 스타일의 스틸을 첫 프레임으로 애니메이션.
VERSION_VISUAL_TYPE: dict[str, str] = {
    "comic": "comic_panel",
    "image_sequence": "image",
    # 폐기된 버전의 옛 행이 렌더될 때 쓰인다(발주 목록에는 없다).
    "webtoon": "comic_panel",
    "explainer": "image",
    # 실사형은 생성 실사 사진 + 코드 오버레이. 만화 패널이 아니므로 image.
    "photo": "image",
}
# 지시서 생성 모델. 라우팅은 engine/llm._backend_for (gemini* / deepseek* / 그 외 Anthropic).
# ★ gemini-2.5-pro → deepseek-v4-pro (2026-09-19, 운영자 승인). 같은 논문·같은 프롬프트로
#   3벌씩 뽑아 **렌더 파이프라인의 게이트로** 채점한 결과다(scripts/model_ab.py):
#       문제합   gemini 14·10·13   vs   deepseek 8·9·6      — 3/3 DeepSeek 우세
#       계약위반 gemini  7· 3· 4   vs   deepseek 1·2·2      — 구간이 겹치지도 않는다
#       3회차는 **컷 수가 7 로 같은데** 문제가 6 대 13 이었다 — "컷이 적어 문제가 적다"가
#       설명이 안 되는 짝이다.
#       1벌 비용  $0.220 (3벌에 4번 호출 — JSON 파싱 재시도 1회) vs $0.149 (3/3 무재시도)
#   ★ 값은 레이턴시다: 126초 → 309초로 **2.4배 느리다**(편차는 오히려 작다, 297–315초).
#     지시서 생성은 사람이 기다리는 경로이므로 이건 실제 비용이고, 알고 바꿨다.
#   ★ deepseek-flash 는 후보가 아니다 — 같은 실측에서 3/3 절단 실패했다.
#   ★ flash 티어(MODEL_SCORING/FACTSHEET/SELFCHECK/SCRIPT)는 **바꾸지 않았다.** 같은
#     하네스로 재 보니 정반대였다(deepseek-flash 가 3회 중 1회 절단으로 죽었다).
#     티어가 다르면 따로 재야 한다.
#   ★ MODEL_REPORT_SCRIPT 도 pro 티어지만 **미측정이라 그대로 둔다.** 지시서 결과를
#     재지 않은 자리에 밀지 않는다.
MODEL_DIRECTIVE: str = os.getenv("MODEL_DIRECTIVE", "deepseek-v4-pro")

# 총길이 예산(DV6). 1분 기준이되 내용에 따라 유연(실제 길이는 나레이션 실측을 따른다).
TARGET_TOTAL_SEC: int = _get_int("TARGET_TOTAL_SEC", 60)
TOTAL_SEC_MIN: int = 45
TOTAL_SEC_MAX: int = 90
CUT_MIN_SEC: int = 3
CUT_MAX_SEC: int = 8
ASPECT_RATIO: str = os.getenv("ASPECT_RATIO", "9:16")

# 통제 어휘(명세 §4/§5). enum 밖 토큰은 정규화에서 드롭+로그(자유 텍스트 금지).
ALLOWED_EFFECTS: tuple[str, ...] = (
    "ken_burns_zoom_in", "ken_burns_zoom_out", "pan_left", "pan_right", "highlight",
)
# 파라미터형 토큰은 접두사로 허용(예: "text_overlay:72의 법칙", "particle:soft").
ALLOWED_EFFECT_PREFIXES: tuple[str, ...] = ("text_overlay:", "particle:")
# 스틸 컷 정지화면 방지용 켄번스/팬 모션(효과 미지정 시 인덱스로 순환 주입).
KEN_BURNS_EFFECTS: tuple[str, ...] = (
    "ken_burns_zoom_in", "pan_right", "ken_burns_zoom_out", "pan_left",
)
ALLOWED_TRANSITIONS: tuple[str, ...] = ("cut", "crossfade")
DEFAULT_TRANSITION: str = "cut"

# ─────────────────────────────────────────────────────────────
# 훅·리텐션 개정 (수정지시서 v2 — docs/deviation-hook-retention-v2.md)
# ─────────────────────────────────────────────────────────────
# 【P1】 훅 유형 — 예고형 삭제, "증거 선공개형"만. 첫 컷(0~1.5s)에 논문의 가장 강한 사실을 먼저 제시.
#   H1 충격수치형 / H2 상식반전형 / H3 인과미스터리 / H4 개인영향형
HOOK_TYPES: tuple[str, ...] = ("H1", "H2", "H3", "H4")
DEFAULT_HOOK_TYPE: str = "H1"
# 훅에서 절대 쓰면 안 되는 예고·서론형 문구(프롬프트에 명시 + 정규화 시 로그 경고).
HOOK_BANNED_PHRASES: tuple[str, ...] = (
    "이 영상 끝나면", "끝나면 알게", "오늘은", "알아보겠습니다",
    "한 논문에 따르면", "최근 연구에서", "지금부터",
)
# 【P2】 앵글 리프레이밍 — 논문마다 "가장 강한 1개"만. 사실 왜곡 아닌 '각도' 변경.
HOOK_ANGLES: tuple[str, ...] = (
    "personal_cost", "competition", "daily_life", "risk", "counterintuition",
    "mechanism", "future_impact", "human_scale", "scientific_wonder",
)
DEFAULT_HOOK_ANGLE: str = "counterintuition"
# 【P5】 마무리 CTA — 5택1(강제 아님). none 포함(매영상 구독 강제 폐기).
CTA_TYPES: tuple[str, ...] = (
    "none", "comment_question", "save_prompt", "subscribe_series", "next_episode_bridge",
)
DEFAULT_CTA_TYPE: str = "none"
# 【P3】 근거강도 게이트 — 대담·단정형 훅은 evidence_strength=high AND generalization_risk=low 일 때만.
CLAIM_TYPES: tuple[str, ...] = (
    "measured_result", "author_interpretation", "model_projection", "speculation",
)
DEFAULT_CLAIM_TYPE: str = "author_interpretation"
EVIDENCE_STRENGTHS: tuple[str, ...] = ("high", "medium", "low")
DEFAULT_EVIDENCE_STRENGTH: str = "medium"
GENERALIZATION_RISKS: tuple[str, ...] = ("low", "medium", "high")
DEFAULT_GENERALIZATION_RISK: str = "medium"

# ─────────────────────────────────────────────────────────────
# 근거밀도·가변길이 (수정명세 docs/수정명세서_근거밀도_가변길이_v1.md)
# ★ 논문 라인 전용. CUT_MAX_SEC·TARGET_TOTAL_SEC 는 engine/report_directive.py 와 공유하므로
#   여기서 건드리지 않는다(명세 §1 판정표 — 올리면 범위 밖인 리포트 프롬프트가 조용히 바뀐다).
# ─────────────────────────────────────────────────────────────
# 【§6】 콘텐츠 모드 — 논문 복잡도가 길이를 정한다(60초 수렴 폐기).
CONTENT_MODES: tuple[str, ...] = ("flash", "standard", "deep", "extended", "series_split")
DEFAULT_CONTENT_MODE: str = "standard"
# 모드별 목표 길이(초). series_split 은 길이가 없다(한 편으로 만들지 않는다).
CONTENT_MODE_DURATION: dict[str, tuple[int, int]] = {
    "flash": (25, 35),      # 단일 결과·명확한 비교·강한 수치
    "standard": (36, 50),   # 범위·방법·결과·한계가 모두 필요(기본)
    "deep": (51, 65),       # 조절효과·메커니즘이 결론에 중요
    "extended": (66, 80),   # 예외 모드 — 압축하면 사실 왜곡이 나는 경우만
}
CONTENT_MODE_HARD_MAX_SEC: int = 80   # 초과 → 승인 차단(시리즈 분할)
CONTENT_MODE_SOFT_MIN_SEC: int = 25   # 미만 → 경고만(RENDER_QA_MIN_SEC=20 은 그대로)
CONTENT_MODE_CUT_RANGE: dict[str, tuple[int, int]] = {
    "flash": (4, 5), "standard": (5, 7), "deep": (6, 8), "extended": (7, 9),
}
# 【§10-3】 모드별 고유(신규 생성) 시각 에셋 상한 — 길이가 아니라 이 값이 이미지비를 정한다.
CONTENT_MODE_MAX_UNIQUE_ASSETS: dict[str, int] = {
    "flash": 4, "standard": 6, "deep": 7, "extended": 8,
}
CONTENT_MODE_PREFERRED_CODE_VIZ: dict[str, int] = {
    "flash": 1, "standard": 2, "deep": 3, "extended": 4,
}
CONTENT_MODE_ASSET_REUSE_TARGET: dict[str, float] = {
    "flash": 0.0, "standard": 0.2, "deep": 0.3, "extended": 0.35,
}
# ★ 2026-08-29 실측 사고: 위 표는 **만화식(comic) 기준**이다. 만화식은 같은 인물을 컷마다
#   다시 그리면 얼굴이 바뀌므로 재사용이 품질 장치다. 그 표를 실사형이 그대로 물려받아
#   11컷짜리 지시서에 "새 이미지 최대 6장"이 걸렸고, 결과물은 컷1=10=11 · 2=8 · 5=6 · 7=9 —
#   그 중 5=6 은 **바이트까지 동일한 파일**이었다. 아낀 돈은 이미지 5장 × $0.039 = $0.195,
#   그 편 총비용 $1.963 의 10%. 20센트를 아끼려고 영상을 복붙으로 만든 것이다.
#   실사형은 "컷마다 다른 것을 보여주는 것"이 존재 이유라 상한을 컷 수에 붙인다.
#   ※ 재사용을 금지하지는 않는다(운영자 지시 2026-08-29): 같은 인물·부품이 **서사·단계가
#     진행돼서** 다시 나오는 것은 옳다. 막아야 하는 것은 **아무것도 안 변한 반복**이고,
#     그것은 상한이 아니라 state_delta 검증(REUSE_REQUIRES_VISIBLE_DELTA)이 잡는다.
# ★★ **1.0 이다**(2026-09-20 실측으로 올렸다). 0.8 은 실사형에서 재사용이 **아직 가능하던 때**
#   잡은 값이다. 2026-09-05 에 스틸 복사 재사용을 코드가 막으면서(바로 위 ※ 주석의 그 결정)
#   모든 실사형 컷이 new_asset 이 됐다 — 10컷 지시서의 고유 에셋은 **항상 10** 이고 상한 8은
#   넘길 수밖에 없다. photo 리포트 8편 전부가 `unique_assets_over_budget` 이었다(8/8).
#   지킬 수 없는 상한은 예산 장치가 아니라 잡음이다. 100% 뜨는 경고는 정보가 0이고,
#   운영자는 그것을 읽지 않게 된다 — 그러면 **진짜 초과를 놓친다.**
#   돈을 막는 자리는 따로 있다: `render_budget_cap`(잡 단위 총액)과 컷 수 게이트.
#   실사형에서 재사용을 되살리는 날 이 값을 다시 내린다.
PHOTO_UNIQUE_ASSET_RATIO: float = _get_float("PHOTO_UNIQUE_ASSET_RATIO", 1.0)
PHOTO_MIN_UNIQUE_ASSETS: int = _get_int("PHOTO_MIN_UNIQUE_ASSETS", 8)
# 【§6-4】 모드 자동선택 임계 — 필수 Evidence Unit 개수 기준.
MODE_UNITS_FLASH_MAX: int = 3
MODE_UNITS_STANDARD_MAX: int = 5
MODE_UNITS_DEEP_MAX: int = 6
MODE_FLASH_WARN_UNITS: int = 6        # flash 인데 이 이상이면 경고(모드는 유지)
SERIES_SPLIT_MAX_UNIQUE_ASSETS: int = 9

# 【§10-2】 컷 길이 — 한 메시지가 유지되면 8초를 넘겨도 쪼개지 않는다.
PAPER_CUT_MAX_SEC: int = 10           # 논문 컷 기본 상한(공유 CUT_MAX_SEC=8 을 대체하지 않고 추가)
DATA_VIZ_CUT_MAX_SEC: int = 12        # scene_kind=data_viz 만 — 한 시각화를 충분히 쓰라고
CUT_STATE_CHANGE_MIN_SEC: int = 9     # 이보다 긴 컷은 state_change 필수(정지 홀드 금지)
# ★ 영상(I2V) 컷만은 8초로 묶는다: 4초 Veo 클립을 12초 컷에 넣으면 clip_fit ratio 가 3.0 이 되어
#   CLIP_FIT_PINGPONG_RATIO_MAX(0.60)를 한참 넘어 홀드만 남는다(품질 저하).
VIDEO_CUT_MAX_SEC: int = CUT_MAX_SEC

# 【§4】 Claim Ledger — Fact Sheet 위에 얹는 구조화 주장 원장.
#   ★ CLAIM_TYPES(위 §P3, science_reliability 용)와 다른 축이다. 이름 혼동 주의.
CLAIM_KINDS: tuple[str, ...] = (
    "main_result", "method", "scope", "number", "mechanism",
    "moderator", "subgroup", "limitation", "author_interpretation", "background",
)
DEFAULT_CLAIM_KIND: str = "main_result"
CAUSAL_STRENGTHS: tuple[str, ...] = (
    "descriptive", "association_only", "quasi_causal", "causal", "projection", "speculation",
)
DEFAULT_CAUSAL_STRENGTH: str = "association_only"   # 보수측 — 상관을 인과로 올리지 않는다
EVIDENCE_GRADES: tuple[str, ...] = ("A", "B", "C", "D")
DEFAULT_EVIDENCE_GRADE: str = "C"
# A 는 원문 PDF/HTML 본문을 실제로 읽은 경우만(§4-6). 초록만 있으면 코드가 B 로 강등한다.
ABSTRACT_ONLY_MAX_GRADE: str = "B"
EFFECT_DIRECTIONS: tuple[str, ...] = (
    "increase", "decrease", "no_change", "mixed", "unspecified",
)
DEFAULT_EFFECT_DIRECTION: str = "unspecified"
CLAIM_ID_FORMAT: str = "C{:02d}"      # 결정론적 부여(C01, C02 …) — LLM 값 불신
# 원장 항목 중 "없으면 추정하지 말고 null" 인 필드들. missing_fields 재계산의 기준이다.
CLAIM_NULLABLE_FIELDS: tuple[str, ...] = (
    "population", "sample_size", "geography", "study_period", "study_design",
    "treatment_or_exposure", "comparison", "outcome", "outcome_definition",
    "effect_size", "effect_unit", "uncertainty", "statistical_significance",
    "source_page", "table_or_figure", "source_quote",
)

# 【§5】 필수 근거 단위 — 대본 작성 전에 "무엇을 반드시 말/보여줄지" 정한다.
EVIDENCE_UNITS: tuple[str, ...] = ("E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8")
EVIDENCE_UNITS_REQUIRED: tuple[str, ...] = ("E1", "E2", "E7")  # 핵심결과·범위·한계는 모든 영상
EVIDENCE_UNIT_LABELS: dict[str, str] = {
    "E1": "핵심 결과", "E2": "대상·지역·기간", "E3": "비교 방식·연구 설계", "E4": "효과 크기·대표 수치",
    "E5": "작동 원리", "E6": "조건·예외·하위집단", "E7": "한계·인과 범위", "E8": "논문이 지지하는 의미",
}
# 컷·씬이 맡는 근거 역할(현행 render_notes 대괄호 표기의 필드 승격).
EVIDENCE_ROLES: tuple[str, ...] = (
    "primary_result", "scope", "method", "magnitude", "mechanism",
    "moderator", "caveat", "implication", "connective", "cta",
)
DEFAULT_EVIDENCE_ROLE: str = "connective"
# 【§5-3】 말할 근거 / 보여줄 근거 — 전부 읽으면 집중도가 떨어진다.
EVIDENCE_DELIVERY: tuple[str, ...] = ("spoken", "visual", "both", "caption", "omit")
DEFAULT_EVIDENCE_DELIVERY: str = "spoken"

# 【§9-2·§7-1】 근거 밀도·리텐션 수치 규칙.
MAX_SPOKEN_NUMBERS: int = 2           # 영상 전체에서 소리 내 읽는 대표 숫자
MAX_SPOKEN_NUMBERS_PER_CUT: int = 1
RETENTION_MAX_NO_NOVELTY_SEC: int = 7       # 이 간격 안에 새 정보·새 시각 상태가 없으면 경고
RETENTION_FIRST_EVIDENCE_MAX_SEC: float = 1.5
RETENTION_SCOPE_REVEAL_MAX_SEC: float = 4.0
RETENTION_PAYOFF_START_RATIO: float = 0.72

# 【§10-4·§10-5】 컷 단위 비용 노브 — 움직임이 이해에 기여하는 곳에만 영상비를 쓴다.
MOTION_VALUES: tuple[str, ...] = ("high", "medium", "low")
DEFAULT_MOTION_VALUE: str = "low"     # 안전측 — 미지정 컷은 스틸
# ─────────────────────────────────────────────────────────────
# Visual Sequence (v3) — 작업계획서_시각엔진_v3.md Phase 1
#
# 무엇이 달라지는가: 영상의 기본 단위가 **독립 컷**에서 **하나의 세계가 단계적으로 변하는
# 시퀀스**로 바뀐다. Cut 은 나레이션·자막·타이밍 단위로 그대로 남고, 그 위에 Stage 가 얹힌다.
#
# ★ Phase 0 실측(docs/실측_continuity_v3.md)이 이 설계를 뒷받침한다:
#   이전 stage 화면을 참조로 주면 같은 인물·같은 세계에서 다음 상태가 만들어지고,
#   **이미지 단가는 그대로다**(장당 $0.134 = 현행 1.00배). 연속성은 이미지비를 올리지 않는다.
# ─────────────────────────────────────────────────────────────
SEQUENCE_ROLES: tuple[str, ...] = (
    "MECHANISM_SEQUENCE",   # 원리·구조·인과가 단계적으로 진행한다(2 stage 이상 필수)
    "REALITY_ANCHOR",       # 실제 현장·제품 — 진행이 아니라 앵커
    "RESULT_SEQUENCE",      # 결과가 갱신된다(예: 15% → 16.9%)
    "FRAMING",              # 훅·마무리
)
# 물체·기하 변화(작업지시서 Paper §5).
VISUAL_OPERATIONS: tuple[str, ...] = (
    "REVEAL", "CUTAWAY", "EXPLODE", "ASSEMBLE", "SPLIT", "MERGE",
    "TRANSFER", "FLOW", "ACCUMULATE", "TRANSFORM", "ISOLATE", "ZOOM_INTO",
)
CAMERA_OPERATIONS: tuple[str, ...] = (
    "ORBIT", "DOLLY_IN", "DOLLY_OUT", "TRACK", "TOP_DOWN", "SECTION_DIVE",
    "FOLLOW_OBJECT", "HOLD",
)
# 에셋 전략의 의미 확장(리뷰 §8). 기존 new_asset/reuse 는 "같은 파일인가"만 구분했는데,
# 그 둘로는 **같은 세계의 다음 상태**를 표현할 수 없었다 — v2 가 복붙으로 퇴행한 구조적 원인.
CONTINUITY_MODES: tuple[str, ...] = (
    "NEW_WORLD",                        # 새 세계를 만든다(참조 없음)
    "CONTINUE_WORLD",                   # 같은 세계·같은 카메라, 다음 상태
    "MUTATE_STATE",                     # 같은 프레임에서 개체 상태만 바뀐다
    "CAMERA_REVEAL",                    # 세계·상태 그대로, 카메라만 움직인다
    "RETURN_WORLD",                     # 앞서 떠난 세계로 되돌아온다(진행 이유 필요)
    "REFERENCE_CONDITIONED_NEW_STATE",  # 참조를 주되 새 배치를 만든다
)
DEFAULT_CONTINUITY_MODE: str = "NEW_WORLD"
# 참조 이미지를 실제로 태우는 모드 — 렌더가 이걸 보고 이전 stage 프레임을 첨부한다(Phase 3).
CONTINUITY_NEEDS_REFERENCE: tuple[str, ...] = (
    "CONTINUE_WORLD", "MUTATE_STATE", "CAMERA_REVEAL", "RETURN_WORLD",
    "REFERENCE_CONDITIONED_NEW_STATE",
)

# ★★ 카메라 규격을 **문장으로 모델에 보내지 않는다** (Phase 0 실측 §3-3).
#
#   실측 사고: 세계 프롬프트에 `35 degree isometric camera` 를 넣었더니 Veo 가 화면에
#   **"35°" 를 글자로 그렸다.** 같은 날 아침 이미지에서 잡은 `MECHANISM` 누출과 같은 계열 —
#   **기계에게 하는 말(규격·역할)이 화면에 그려진다.**
#
#   금지어를 늘려서 막을 수 없다: "35 degree isometric camera" 는 정당한 카메라 서술이다.
#   그래서 카메라는 **구조화 토큰**으로만 선언하게 하고, 프롬프트로 나갈 때는 여기 표의
#   산문으로 바꾼다. 숫자·기호(°, mm)가 프롬프트 본문에 들어가지 않는 것이 요점이다.
CAMERA_BASES: tuple[str, ...] = (
    "elevated_three_quarter", "eye_level_front", "top_down", "low_angle",
    "side_profile", "close_detail",
)
DEFAULT_CAMERA_BASE: str = "elevated_three_quarter"
CAMERA_BASE_PROSE: dict[str, str] = {
    "elevated_three_quarter": "elevated three-quarter view looking down at the scene",
    "eye_level_front": "eye-level view facing the scene straight on",
    "top_down": "directly overhead view looking straight down",
    "low_angle": "low viewpoint looking slightly upward",
    "side_profile": "side view from the left of the scene",
    "close_detail": "tight view filling the frame with the key object",
}
CAMERA_OPERATION_PROSE: dict[str, str] = {
    "ORBIT": "the camera slowly circles around the scene",
    "DOLLY_IN": "the camera moves steadily closer",
    "DOLLY_OUT": "the camera pulls steadily back",
    "TRACK": "the camera glides sideways alongside the scene",
    "TOP_DOWN": "the camera rises to look straight down",
    "SECTION_DIVE": "the camera moves through the opened cross-section",
    "FOLLOW_OBJECT": "the camera follows the moving object",
    "HOLD": "the camera stays still",
}
# 프롬프트 본문에 남으면 화면에 글자로 그려질 수 있는 규격 토큰(각도·렌즈·해상도 표기).
# ★ 어휘 목록이 아니라 **형태**로 잡는다 — "35 degree", "50mm", "4K" 는 서로 다른 단어지만
#   같은 사고를 낸다. visual_sequence.scrub_spec_tokens 가 이 패턴을 지운다.
# ─────────────────────────────────────────────────────────────
# Explanation Beat + Visual Router (v3 Phase 2)
#
# ★ 분업: LLM 은 컷에 **beat 라벨만** 단다. "그것을 어떻게 보여줄 것인가"는 코드가 정한다
#   (visual_router.route). 라우팅까지 LLM 에 맡기면 근거가 얇은 컷에도 3D 기전이 붙는다 —
#   v2 가 정확히 그랬다(초록만 있는 논문에 코→뇌 분자 이동을 그렸다).
# ─────────────────────────────────────────────────────────────
BEAT_KINDS: tuple[str, ...] = (
    "QUESTION", "SCOPE", "EXPERIMENT_SETUP", "INTERVENTION", "MEASUREMENT",
    "MECHANISM", "RESULT", "COMPARISON", "LIMITATION", "CONCLUSION",
)
DEFAULT_BEAT_KIND: str = "RESULT"
VISUAL_TREATMENTS: tuple[str, ...] = (
    "MECHANISM_SEQUENCE",  # 같은 세계가 단계적으로 변한다
    "CODE_VIZ",            # 코드가 그린 차트·도형(정확한 수치)
    "REALITY",             # 실제 현장·대상 앵커
    "OVERLAY",             # 화면 카드만(출처·범위·단서)
)
# beat → 기본 표현. 코드가 여기서 출발해 source_depth·수치 유무로 조정한다.
BEAT_DEFAULT_TREATMENT: dict[str, str] = {
    "QUESTION": "REALITY", "SCOPE": "OVERLAY",
    "EXPERIMENT_SETUP": "MECHANISM_SEQUENCE", "INTERVENTION": "MECHANISM_SEQUENCE",
    "MEASUREMENT": "MECHANISM_SEQUENCE", "MECHANISM": "MECHANISM_SEQUENCE",
    "RESULT": "CODE_VIZ", "COMPARISON": "CODE_VIZ",
    "LIMITATION": "OVERLAY", "CONCLUSION": "REALITY",
}
# ★★ 정밀 레이어 — **수치는 시퀀스를 끊지 않는다**(코덱스 리뷰 R1, 2026-08-30).
#
#   ✗ 종전: 컷이 수치를 말하면 treatment 가 통째로 CODE_VIZ 가 됐다. 그래서 시퀀스 중간의
#     한 컷이 "7분 주기가 8초 변했다"고 말하면 **그 컷만 차트로 빠져 세계가 끊겼다**
#     (골든B 15컷 중 4컷이 실제로 그렇게 튕겨 나갔다).
#   ✓ 지금: 세계(base)는 그대로 두고 **코드 렌더 정밀 레이어를 얹는다.**
#     같은 로켓이 계속 돌고, 그 위에 정확한 "약 7분 → 8초 이상" 이 코드로 그려진다.
#
#   Phase 0 이 실측한 것은 "생성모델은 정확한 개수를 못 지킨다"이지 "수치가 있는 장면은
#   3D 로 만들면 안 된다"가 아니다. 실측을 과대해석했던 것을 되돌린다.
PRECISION_LAYERS: tuple[str, ...] = ("", "CODE_OVERLAY")
# 세계가 없는(=화면 전체가 그래픽인) 표현. 여기에는 정밀 레이어를 따로 얹지 않는다.
PRECISION_LAYER_REDUNDANT_BASES: tuple[str, ...] = ("CODE_VIZ", "OVERLAY")

# ★★ 표현 수준(코덱스 리뷰 §11). claim_id 가 맞아도 **묘사가 틀릴 수 있다.**
#   골든B 분광이 사례다: 주장(C03)은 원문이 지지하지만 원문은 **지상 관측**인데 화면은
#   우주에서 로켓에 빛을 쏘는 그림이었다 — claim 은 맞고 관측 방식 묘사가 틀린 환각이다.
#   그래서 각 stage 가 **어느 수준의 표현인지**를 선언하고, literal 이면 실제 관측 방식이
#   원문에 의해 지지돼야 한다. metaphor 는 사실 관측처럼 보이지 않게 한다.
REPRESENTATION_MODES: tuple[str, ...] = (
    "LITERAL_OBSERVATION",   # 실제로 그렇게 관측·측정했다 — 원문이 방식까지 지불해야 한다
    "SCHEMATIC_PRINCIPLE",   # 원리를 도식으로 — 실제 장면이라고 주장하지 않는다
    "METAPHOR",              # 은유 — 사실 관측으로 오인되면 안 된다
)
DEFAULT_REPRESENTATION_MODE: str = "SCHEMATIC_PRINCIPLE"
# 원문이 **관측 방식까지 말하지 않는** 확보 수준. 여기서는 LITERAL_OBSERVATION 을 선언할
# 자격이 없다 — 초록은 "무엇을 알아냈다"를 말하지 "어떻게 봤는가"를 말하지 않는다.
DEPTH_LITERAL_FORBIDDEN: tuple[str, ...] = ("abstract_only", "parse_failed", "none")

# ★★ source_depth 는 **미디어 라우팅이 아니라 표현 제약**이다(코덱스 리뷰 R2, 2026-08-30).
#
#   ✗ 종전: abstract_only 면 기전 시퀀스를 REALITY 로 후퇴시켰다. 그런데 그 후퇴는
#     근거 없는 컷을 막지 못하면서(골든A 는 후퇴하고도 "사전 등록된 무작위 실험"을 그렸다)
#     정상 컷만 벌했다. `abstract_only ≠ 기전 시각화 금지` 다.
#   ✓ 지금: 기전 시각화는 허용하되 **초록이 지불하지 않는 구체성**을 금지한다.
#     그리고 그 판정은 어휘 목록이 아니라 **원문 대조**로 한다 — 아래 용어가 프롬프트에
#     있는데 원문에 없으면 차단이고, 원문에 있으면 통과다(옳게 한 것을 벌하지 않는다).
DETAIL_SPECIFICITY_TERMS: dict[str, tuple[str, ...]] = {
    # 실험 설계의 구체 절차
    "protocol": ("double-blind", "double blind", "single-blind", "placebo", "placebo-controlled",
                 "randomi", "pre-registered", "preregistered", "crossover", "washout",
                 "이중맹검", "위약", "무작위", "사전 등록", "사전등록"),
    # 장비·시료 취급
    "apparatus": ("vial", "syringe", "pipette", "centrifuge", "fmri", "mri scanner", "eeg cap",
                  "nasal spray", "intranasal", "spectrometer", "telescope dome",
                  "바이알", "주사기", "비강 분무", "원심분리"),
    # 생리·해부 경로
    "physiology": ("bloodstream", "blood-brain", "receptor", "neuron", "synap", "amygdala",
                   "hypothalamus", "cortex", "nasal cavity", "olfactory",
                   "혈류", "수용체", "뉴런", "시냅스", "편도체", "시상하부"),
}
# 확보 수준별로 **원문 대조를 요구하는** 구체성 범주. 전문이면 원문이 곧 근거라 제약이 없다.

# 관계·인과 어휘 — **원문에 없는 관계를 화면이 지어내는 것**을 잡는다(리뷰 §14).
#   ★ 왜 필요한가: 기존 문자열 게이트는 `glow`·`decorative` 같은 **스타일**만 봤다.
#     정작 위험한 것은 스타일이 아니라 **주장**이다 — 골든B 컷14 "다른 궤도들이 기준
#     궤도에 맞춰 정렬된다" 는 원문에 없는 관계인데 아무 사유 없이 통과했다.
#   ★ 왜 어휘 목록으로 되는가: 판정을 목록이 하지 않는다. 목록은 **어디를 볼지**만 정하고,
#     통과 여부는 DETAIL_SPECIFICITY_TERMS 와 똑같이 **원문·주장 대조**가 정한다.
#     그래서 "결합"·"bind" 처럼 논문이 실제로 말하는 관계는 그대로 통과한다.
RELATION_TERMS: tuple[str, ...] = (
    # 정렬·동기 — 여러 대상이 서로 맞춰진다는 주장
    "정렬", "동기화", "수렴", "일치시", "맞춰",
    "align", "synchron", "converge",
    # 인과·유발 — A 가 B 를 일으킨다는 주장
    "유발", "촉발", "야기", "이어진다", "때문에",
    "trigger", "cause", "lead to", "leads to", "result in", "results in",
    # 억제·차단 — A 가 B 를 막는다는 주장
    "억제", "차단", "저해", "상쇄",
    "inhibit", "suppress", "block", "counteract",
    # 결합·매개 — A 가 B 와 붙거나 사이를 잇는다는 주장
    "결합", "부착", "매개", "전달되어", "증폭",
    "bind", "attach", "mediate", "amplif",
)

# ─────────────────────────────────────────────────────────────
# 실사형 화풍 계약 어휘 (2026-09-07, 화풍 전환 실측 4회)
# ─────────────────────────────────────────────────────────────
# ★ 무엇이 문제였나: "화풍은 코드가 정한다. visual_prompt 에 화풍 형용사를 쓰지 마라" 는
#   지시가 `directive.py` 에 **이미 있었다.** 그런데 검사가 없어서 모델이 계속 어겼고,
#   네 번의 실측이 전부 같은 자리에서 졌다 — 장면 묘사의 긍정 어휘가 코드가 뒤에 붙이는
#   부정어를 이긴다(`docs/핸드오프_화풍전환_2026-09-07.md` §3-①).
#   지시만 있고 검사·되먹임이 없는 게이트는 함정이다(skill: gate-prompt-feedback-parity).
#
# ★★ 검사 대상이 **cuts 만이 아니다.** 화풍은 세 곳에서 정해진다(§3-④) — 셋째가
#   `visual_sequences[].world` 다. 지시서 프롬프트가 LLM 에게 world.style 을 "화풍·재질
#   한 구절"로 쓰라고 시켰고, 세포 세계에서 그 답이 "Microscopic, detailed 3D rendering
#   … Soft, internal glow … blurred cellular matrix" 였다. 실험실 세계(장소를 적었다)는
#   목표 화풍이 나왔고 세포 세계는 삽화가 나왔다 — 성공·실패가 이 선언과 정확히 갈렸다.

#: **화풍 선언 어휘** — 모델이 "어떤 그림체로 그릴지"를 정해 버린 말. **차단**이다.
#   ★ 이건 코드가 단어만 지워서 고칠 수 없다. 단어를 지워도 모델이 그 장면을 **삽화로
#     구상했다는 사실**은 남는다. 구상을 다시 하라고 돌려보내야 한다.
#   ⚠ 여기에 넣을 수 있는 것은 **실물을 가리킬 수 없는 말뿐**이다. "glowing"(진짜 표시등)
#     처럼 실제 사물일 수 있는 말은 아래 UNDRAWABLE 쪽(경고)으로 보낸다.
PHOTO_RENDER_STYLE_TERMS: tuple[str, ...] = (
    "stylized", "photorealistic", "photo-realistic", "photoreal",
    "3d render", "3d rendering", "cgi", "cinematic still", "cinematic render",
    "illustration", "illustrated", "painterly", "watercolor", "oil painting",
    "cel shading", "cel-shaded", "line art", "vector art", "flat design",
    "anime", "cartoon", "comic style", "claymation", "low poly", "low-poly",
    "render style", "art style", "rendered in",
)

#: **렌즈·광학 어휘 → 배치 표현**. 이건 코드가 **고친다**(차단하지 않는다).
#
# ★ 왜 프롬프트가 아니라 코드인가: 지시서 프롬프트에 금지와 대안을 둘 다 적고 실측했는데,
#   모델이 **부분만** 지켰다(2026-09-07 재생성 2회: world 3개 중 1개만 고쳐졌고 나머지는
#   "A blurred, neutral studio backdrop" 으로 남았다). 어휘 치환은 기계가 확실히 할 수
#   있는 일이다 — 모델에게 반복해 시키고 재시도 비용을 내는 것은 설계 실패다.
#   이 저장소는 이미 같은 자세를 쓴다(`photo_video_camera_repaired`·
#   `photo_visual_role_backfilled` — 코드가 고치고 경고를 남긴다).
#
# ★★ 이 표는 **수동 실측에서 실제로 통한 것**이다. 그림 2·3(목표 화풍)이 이 치환을 거친
#   프롬프트로 나왔다(`scripts/style_probe.py` 가 같은 표를 쓴다 — 정본은 여기 하나다).
#   "흐림"을 지우는 대신 **거리**로 바꾸는 것이 핵심이다: 배경이 뒤에 있다는 정보는
#   유지하면서 렌즈 지시만 뺀다.
PHOTO_OPTICS_REWRITES: tuple[tuple[str, str], ...] = (
    (r",?\s*with\s+(?:a\s+)?shallow depth of field", ""),
    (r",?\s*shallow depth of field", ""),
    (r",?\s*depth of field", ""),
    (r"Photoreal macro detail\.?", ""),
    (r",?\s*macro detail", ""),
    (r",?\s*macro shot", ""),
    (r",?\s*bokeh", ""),
    (r",?\s*lens flare", ""),
    (r",?\s*film grain", ""),
    (r",?\s*motion blur", ""),
    (r",?\s*tilt-shift", ""),
    (r",?\s*long exposure", ""),
    (r",?\s*shallow focus", ""),
    # 흐림 → 거리. 정보를 지우지 않고 옮긴다.
    (r"far out of focus", "further back"),
    (r"slightly out of focus", "further back"),
    (r"out of focus", "further back"),
    (r"\bblurred figures\b", "figures further back"),
    (r"\bblurred background\b", "background further back"),
    (r"\ba blurred,\s*", "a plain "),
    # ★ 형용사 자리의 `blurred` 는 **거리 형용사**로 바꾼다. 문장 첫머리를 따로 다루지
    #   않는다 — 이 표는 re.I 로 컴파일되므로 `Blurred` 전용 규칙을 두면 문장 **중간의**
    #   소문자 `blurred` 까지 잡아간다(실측: "a bench with blurred trays" 가
    #   "a bench with Further back, trays" 가 됐다). 대문자 복원은 strip_optics 가 한다.
    (r"\bblurred\s+", "more distant "),
    (r"\bblurred\b", "further back"),
)

#: **화풍 선언 어휘 중 코드가 지우는 것** — 지금은 `stylized` 하나다.
#
# ★ 위 PHOTO_RENDER_STYLE_TERMS 주석("단어만 지워서 고칠 수 없다")의 **예외**다.
#   2026-09-11 운영자 지시("stylized 도 코드가 치환하게 해줘"). 계기: 성격 유전 논문
#   지시서가 재생성 1회를 거치고도 컷 10·11 에 `stylized` 가 남아 승인이 막혔다.
#   `stylized` 는 형용사라 지워도 장면(무엇이 어디에 있나)이 그대로 남는다 — "3D render"·
#   "illustration" 처럼 장면 전체를 그림체로 바꾸는 명사와 다르다. 그래서 이것만 옮긴다.
#   화풍 자체는 코드 접미사(VISUAL_ROLE_STYLE)가 정하므로 지워도 잃는 정보가 없다.
# ★ 순서가 중요하다 — 복합어를 먼저 지운다. "stylized 3D render of a brain" 에서
#   stylized 만 지우면 "3D render of a brain" 이 남아 여전히 차단된다.
# ★ 게이트 목록(PHOTO_RENDER_STYLE_TERMS)에서는 빼지 않는다. 치환이 놓친 변형이 있으면
#   게이트가 계속 잡아야 한다.
#
# ★★ **`photorealistic` 계열도 넣는다**(2026-09-19). 같은 기준에 정확히 해당한다 — 형용사라
#   지워도 장면이 그대로 남는다. 그리고 `stylized` 와 달리 **삽화로 구상했다는 증거도
#   아니다**: 모델은 사실적으로 그려 달라고 말한 것이고, 그 결정은 어차피 코드가 한다
#   (무광 CG, VISUAL_ROLE_STYLE). 지워도 잃는 정보가 없다.
#   실측(저장된 photo 지시서 54편·572컷): 화풍어휘 차단 59자리 중
#     photorealistic 32 · photoreal 3 (**59%**) · 3d render 15 · stylized 13 · 그 외 6.
#   `3d render`·`illustration` 은 그대로 둔다 — 장면 전체를 그림체로 바꾸는 **명사**라
#   지운다고 구상이 바뀌지 않는다(위 주석).
PHOTO_STYLE_WORD_REWRITES: tuple[tuple[str, str], ...] = (
    # "A stylized 3D render of a brain" → "a brain"(관사까지 먹어야 "A a brain" 이 안 된다).
    (r"\b(?:an?\s+)?stylized\s+3d\s+render(?:ing)?\s+of\s+", ""),
    # 같은 이유로 복합어를 먼저 — "a photorealistic 3D rendering of X" 에서 형용사만 빼면
    # "3D rendering of X" 가 남아 **여전히 차단된다**(stylized 규칙이 이미 겪은 자리).
    (r"\b(?:an?\s+)?photo-?real(?:istic)?\s+3d\s+render(?:ing)?\s+of\s+", ""),
    (r",?\s*\bphoto-?realistic\b", ""),
    (r",?\s*\bphoto-?real\b", ""),
    (r",?\s*\bstylized\b", ""),
)

#: **발광 어휘 치환** — 화풍이 금지하는 빛남을 코드가 걷어낸다(2026-09-18 저녁).
#
# ★ 왜 경고가 아니라 치환인가: `VISUAL_ROLE_NEGATIVE` 가 "no glowing effects, no neon, no bloom,
#   no light emission" 이라고 이미 말하고 있는데 **그림에는 발광이 나왔다**(2026-09-18 실측,
#   지시서 79298b9f 컷3 — 산호색 뇌에 주황 발광 테두리). 이 저장소의 결론 그대로다:
#   **부정어로는 못 막는다. 막는 것은 긍정 어휘다**(화풍 전환 핸드오프, 실측 4회).
#   그러니 프롬프트에서 그 긍정 어휘를 빼야 한다 — `stylized` 를 지우는 것과 같은 자리·같은 이유.
#
# ★★ 히트율(저장된 photo 지시서 40건 437컷): 발광 어휘 **143회**가 컷 프롬프트에 있었다
#   (glowing 88 · glow/glows 51 · luminous 2 · aura 1 · emits 1). **셋 중 한 컷**이 화풍과
#   싸우는 문장을 들고 있었다는 뜻이다.
#
# ★★★ **뜻을 죽이지 않는다.** 모델이 발광을 쓰는 이유는 "여기를 봐라"이고, 그 일은 우리 화풍에
#   이미 있다 — `amber accent on the part being explained`. 그래서 지우는 것이 아니라
#   **앰버 강조로 옮긴다.** 형용사(`glowing lines`)만 그냥 지운다(지워도 장면이 남는다).
#   순서가 중요하다 — 긴 표현을 먼저 잡아야 짧은 규칙이 문장을 조각내지 않는다.
PHOTO_GLOW_REWRITES: tuple[tuple[str, str], ...] = (
    # ── ① 발광을 **동사로** 쓴 자리부터. 먼저 안 잡으면 아래 형용사 규칙이 문장을 조각낸다
    #      (실측: "The model is glowing softly, emphasizing…" → "The model is softly, emphasizing…").
    (r"\bemitting\s+(?:an?\s+)?(?:soft|warm|bright|subtle|faint)?\s*(?:glow|light)\b",
     "picked out in amber"),
    (r"\b(is|are|was|were)\s+glowing(?:\s+(?:softly|brightly|faintly|gently|intensely))?\b",
     r"\1 picked out in amber"),
    (r"\bglowing\s+(?:softly|brightly|faintly|gently|intensely)\b", "picked out in amber"),
    # "glows with a warm amber light" — 이미 앰버를 말하고 있다. 발광만 뗀다.
    (r"\bglows\s+with\s+(?:an?\s+)?(?:warm|soft|bright|subtle)?\s*amber\s+(?:light|glow)\b",
     "is picked out in amber"),
    (r"\bglow\s+with\s+(?:an?\s+)?(?:warm|soft|bright|subtle)?\s*amber\s+(?:light|glow)\b",
     "are picked out in amber"),
    # "824 specific markers glow more intensely" · "the cortex glows brightly" (실측)
    (r"\bglows\s+(?:more\s+)?(?:brightly|softly|intensely|faintly)\b", "is picked out in amber"),
    (r"\bglow\s+(?:more\s+)?(?:brightly|softly|intensely|faintly)\b", "are picked out in amber"),
    # ── ② 명사로 쓴 자리. "a soft glow emanating from the spectrometer" (실측)
    (r"\b(?:an?|the)\s+(?:soft|warm|bright|subtle|faint|inner|internal)?\s*glow\s+emanating\s+from\b",
     "an amber accent on"),
    # "The glow in the prefrontal cortex slowly fades" (실측)
    (r"\bthe\s+(?:bright|soft|warm|subtle|faint)?\s*glow\s+in\b", "the amber accent in"),
    (r"\b(?:an?|the)\s+(?:soft|warm|bright|subtle|faint|inner|internal)\s+glow\b", "an amber accent"),
    # "glows a bright, expanded coral color" (실측) — 뜻은 **그 색이 된다**이지 빛난다가 아니다.
    #   동사만 바꾸면 "is picked out in amber a bright … color" 로 문장이 깨진다.
    (r"\bglows\s+(an?|the)\s+", r"turns \1 "),
    (r"\bglow\s+(an?|the)\s+", r"turn \1 "),
    (r"\bglows\b", "is picked out in amber"),
    (r"\bglow\b", "amber accent"),
    # ── ③ 남은 형용사는 그냥 뗀다 — 지워도 장면이 남는다("glowing blue double-helix" → "blue …").
    (r",?\s*\bglowing\b", ""),
    (r",?\s*\bluminous\b", ""),
    (r",?\s*\bradiant\b", ""),
    (r"\baura\b", "accent"),
)

#: **그릴 수 없는 판정 어휘** — 차이를 *가치 판단*으로 적은 말.
#   ★ 실측(2026-09-07 그림 4): "the same stylized aged cell … initiating a more pronounced
#     transformation into a healthier, more active cell" → 두 세포가 **똑같이** 나왔다.
#     생성 모델은 "건강함"을 그릴 수 없다. 그릴 수 있는 것은 형태·색·자세·개수·거리다.
#   ⚠ **기본은 경고다.** 목록에 오탐이 있다 — "more active mice" 는 자세로 그릴 수 있는
#     정당한 묘사다. 히트율을 재기 전에 차단으로 올리지 않는다(이 저장소는 series_split 이
#     100% 를 막은 사고를 이미 겪었다). 재고 나서 PHOTO_UNDRAWABLE_BLOCKS 로 올린다.
#   ★★ **판정을 우회해 적는 말**도 같은 실패다(2026-09-10 추가). 실측 사고: 세포 세계를
#     여는 컷이 "showing visible **signs of** inflammation and cellular damage" 라고 적었다.
#     '염증의 징후'는 물체가 아니라 판정이라 아무 표지도 안 그려졌고, 뒤 컷들이 "붉은 조각을
#     줄여라"고 하는데 **첨부 그림에 그 조각이 없어서** 세 컷이 같은 화면이 됐다.
#   ※ 히트율 측정(2026-09-10, 저장된 photo 지시서 20건 237컷):
#       signs of 3 · sense of 8 · suggesting 10 · look of 1  → 히트 23컷(9.7%)·지시서 13/20.
#       잡힌 22건을 눈으로 전부 확인했다: 'suggesting a longer lifespan' ·
#       'conveying a sense of caution' · 'suggesting clarity and importance' —
#       전부 그림이 아니라 **의미 해설**이다(오탐 0).
#     `appearing to` 는 **뺐다** — 2건 다 정당했다('a hand appearing to highlight a section',
#     'the stage appearing to accelerate'). 둘 다 실제로 그릴 수 있는 동작이다.
#     `indications of`·`evidence of`·`appears to` 는 히트 0 이지만 같은 계열이라 함께 넣는다
#     (경고이므로 히트 0 인 항목이 생산을 막지 않는다).
PHOTO_UNDRAWABLE_QUALITY_TERMS: tuple[str, ...] = (
    "healthier", "healthy-looking", "more active", "more vibrant", "vibrant",
    "improved", "improvement", "better", "enhanced", "optimized",
    "more pronounced", "subtle improvement", "revitalized", "rejuvenated",
    "youthful", "more efficient", "more effective", "superior",
    "energized",
    # ★ glowing·glow·aura·radiant 는 2026-09-18 에 **여기서 뺐다.** 그것들은 "그릴 수 없는
    #   판정"이 아니라 반대로 **모델이 너무 잘 그리는 것**이고(그래서 화풍이 깨졌다),
    #   경고가 아니라 치환이 맞는 처방이다 — PHOTO_GLOW_REWRITES 로 옮겼다.
    # 판정을 우회해 적는 말 — "그렇게 보인다"는 물체가 아니다.
    "signs of", "indications of", "evidence of", "appears to",
    "sense of", "look of", "suggesting",
)

#: 판정 어휘를 **차단**으로 올릴지. 기본은 경고 — 위 주석의 오탐 때문이다.
PHOTO_UNDRAWABLE_BLOCKS: bool = _get_bool("PHOTO_UNDRAWABLE_BLOCKS", False)

# ─────────────────────────────────────────────────────────────
# 역할별 화면시간 (2026-09-09, 외부 리뷰 GO WITH CHANGES 반영)
# ─────────────────────────────────────────────────────────────
# ★ 차단 문턱을 두지 않는다. 규칙이 `evidence_role` 에 기대는데 그 값은 **모델이 스스로
#   붙이고 코드가 내용 정합을 검증하지 않는다**(normalize_directive 는 enum 검사만 한다).
#   차단을 걸면 모델이 내용을 그대로 두고 라벨만 바꿔 통과할 수 있다 — 지표 셋이 동시에
#   좋아지는데 영상은 안 좋아진다. 이 저장소 원칙("자기보고를 믿지 않는다")과 충돌한다.
#   그래서 지금은 **지표로만 기록**하고, 라벨 정합 검사(아래)를 먼저 세운다.

#: 참고 성격 역할. 화면시간 비중을 **재기만** 한다(문턱 없음).
#   ★ `method` 를 여기 넣은 것은 통계용이다. 차단 대상으로 삼으면 안 된다 —
#     무작위 대조인지 관찰연구인지, 어떤 비교를 했는지는 결과 해석에 필수일 수 있다.
REFERENCE_EVIDENCE_ROLES: tuple[str, ...] = ("scope", "method", "connective")

#: 첫 기전 컷이 이 지점을 넘겨 시작하면 경고. **calibration 값이다 — 검증된 품질 문턱이 아니다.**
#   근거: 기전이 있는 지시서 5편의 첫 기전 시점이 20·39·43·49·51%(전체 대비)였다.
#   사람 평가와 연결한 적이 없으므로 차단으로 올리지 않는다. Phase C 에서 판단한다.
#   ★ 우회 가능성 미검증: 2초짜리 기전 컷 하나를 앞에 끼우면 형식만 만족한다.
MECHANISM_START_SHARE_WARN: float = _get_float("MECHANISM_START_SHARE_WARN", 0.40)

#: **경고인데도 재생성을 한 번 띄우는** 사유들.
#
# ★ 왜 필요한가(2026-09-09 외부 리뷰): `photo_subject_dominates` 는 정확한 처방 문장까지
#   갖고 있는데 **모델에게 전달되지 않는다.** `feedback_prompt` 은 차단이 없으면 빈 문자열을
#   돌려주고 `generate()` 는 차단·등급미달이 없으면 재생성을 안 하기 때문이다.
#   이번 문제("연구 대상이 화면의 51%")를 이미 감지하고 고칠 말도 갖고 있었는데
#   말을 건네지 않고 있었다 — 경고가 장식으로 끝나는 구조였다.
# ★★ 승인 차단은 **아니다.** 계약은 "경고 → 재생성 1회 → 그래도 남으면 경고인 채로
#   사람에게 보여준다". 오탐이 생산을 막지 않는다는 기존 철학을 그대로 지킨다.
RETRYABLE_QUALITY_WARNINGS: tuple[str, ...] = (
    "photo_subject_dominates",
    "photo_narrative_no_mechanism",
    "photo_hook_visual_repeated",
    "photo_mechanism_starts_late",
    "photo_role_claim_mismatch",
    # ★ 2026-09-10 — 여는 컷이 배우를 무대에 세우지 않으면 뒤 컷이 통째로 정지 화면이 된다.
    #   되먹임 한 번으로 고쳐질 수 있는 종류다(여는 컷 프롬프트에 물체를 적으면 된다).
    "photo_lead_cut_missing_entity",
    # ★ 2026-09-12 — stage 가 APPEAR·HIGHLIGHT 만 선언하면 그 컷은 8초를 못 받고 화면도
    #   거의 안 움직인다. 코드는 없는 변형을 지어낼 수 없으니(beats_from_stage) 되물어야 한다.
    #   실측: 재생성 뒤에도 13컷 중 12컷이 이 이유 하나로 standard 였다.
    "photo_stage_no_transformation",
    # ★ 2026-09-18 — 기전 시퀀스에 범례·캡션이 없으면 두 집단을 그려도 어느 쪽이 무엇인지
    #   시청자가 모른다. overlay_plan 에 legend/label_pair 를 넣으면 되는 종류라 되묻는다.
    "photo_mechanism_unlabeled",
    # ★ 2026-09-18 — 카드·화살표는 되먹임 한 번으로 고쳐지는 종류다(문구를 줄이거나 구역 이름을 고친다).
    # ★ 2026-09-19 — 색의 뜻이 갈아엎히면 범례가 거짓말이 된다. 되먹임 한 번으로 고쳐질 종류다
    #   (한 개체 한 색으로 되돌리고, 부위는 amber·화살표로 가리키면 된다).
    "photo_color_code_reused",
    "photo_keyword_is_a_sentence",
    "photo_keyword_repeats_narration",
    "photo_pointer_zone_unknown",
    # ★★ 2026-09-21 — 리포트 모델이 `visual_sequences` 를 안 쓰면 코드 폴백이 돈다. 그 경로는
    #   컷이 무엇을 그리든 2번째 stage 부터 무조건 CONTINUE_WORLD 를 찍는다 — 운영자가 통째로
    #   폐기한 "네 칸 비교표"와 "파이프가 화면에 안 나온" 편이 거기서 나왔다.
    #   되물으면 되는 종류다: A/B 9벌에서 세 모델 **모두 3/3** 으로 썼다(어려운 요구가 아니다).
    #   그런데 운영 경로의 한 회차가 빠뜨렸고, 폴백은 조용해서 승인 화면에 아무것도 안 떴다.
    "report_sequences_from_code_fallback",
)

#: 역할 라벨이 **명백히 거짓인지**만 보는 필요조건표(의미 분류기가 아니다).
#
# ★ 목표는 역할을 코드가 맞히는 것이 아니라 **라벨 세탁을 통과시키지 않는 것**이다.
#   `scope` 컷을 `mechanism` 이라고 부르면 지표 셋이 동시에 좋아지는데, 연결된 claim 이
#   기전을 말하지 않으면 그 라벨은 거짓이다.
# ★★ 애매하면 **아무것도 내지 않는다.** 컷에 claim_ids 가 없거나 원장에서 못 찾으면
#   판정 불가로 두고 넘어간다 — 판정 불가와 위반을 섞지 않는다(이 저장소의 일관된 자세).
#   kinds/fields 중 **하나라도** 만족하면 통과다.
ROLE_CLAIM_REQUIREMENTS: dict[str, dict[str, tuple[str, ...]]] = {
    "mechanism": {"kinds": ("mechanism", "author_interpretation"), "fields": ()},
    "magnitude": {"kinds": ("number",), "fields": ("effect_size",)},
    "scope": {"kinds": ("scope",), "fields": ("population", "study_period", "geography")},
    "method": {"kinds": ("method",),
               "fields": ("study_design", "treatment_or_exposure", "comparison")},
}

#: 실사형의 **전 컷 일관성 앵커**. 코드가 정한다 — LLM 이 쓰지 않는다.
#
# ★ 왜 코드가 정하나(2026-09-08 운영자 지시 "저 화풍으로 고정해서 유지"):
#   `global_style` 은 이미지·영상 프롬프트의 **맨 앞**에 붙는다
#   (`providers/image._build_image_prompt`, `providers/video.build_motion_prompt`).
#   그런데 출력 스키마가 LLM 에게 "화풍/톤 앵커 한 줄"을 쓰라고 시켜서, 지시서마다
#   다른 화풍 선언이 맨 앞에 왔다 — 실측: "Scientific realism, clean laboratory aesthetic".
#   화풍이 정해지는 자리가 하나 더 있었던 셈이고, 그러면 편마다 화면이 달라진다.
#
# ★★ 이 문장은 **역할 화풍과 싸우지 않는다.** 재질·조명·색을 새로 선언하지 않고
#   "컷마다 같아야 한다"는 일관성만 말한다. 구체적인 화풍은 VISUAL_ROLE_STYLE 이 정한다 —
#   그것이 MECHANISM/REALITY 로 갈리기 때문에 여기서 겹쳐 말하면 충돌한다.
PHOTO_GLOBAL_STYLE: str = (
    "One consistent look across every cut: the same materials, the same even studio light, "
    "and the same restrained palette"
)

#: **따옴표 친 라벨 이름** — 이미지에 글자로 구워지는 가장 확실한 신호.
#
# ★ 실측(2026-09-07 시퀀스 렌더): 컷8 이 `The left model represents 'Calorie Restriction'
#   and the right model represents 'Semaglutide' … 'Exploratory Behavior', 'Spatial Memory',
#   'Glucose Control'` 이라고 적었고, 완성된 그림에 **그 다섯 개가 영어 글자로 박혔다.**
#   이미지는 한국어판·영어판이 공유하므로 글자가 구워지면 언어 공유가 통째로 깨진다.
#
# ★★ 기존 `_TEXT_REQUEST` 가 왜 놓쳤나: 그 정규식은 "text overlay"·"the word 'X'" 처럼
#   **글자를 그려 달라는 말**을 찾는다. 컷8 은 그런 말을 하지 않았다 — 그냥 대상에
#   이름을 붙였을 뿐이고, 모델이 그 이름을 라벨로 그렸다. 요구가 없어도 결과는 같다.
#
# ★★★ **차단인 근거는 실측이다.** 저장된 실사형 지시서 19건 224컷을 훑었다:
#   히트 10컷(4.5%) · 지시서 8건(42%). 그리고 잡힌 10건이 **전부 진짜 라벨**이었다
#   ('DIRECT IMPACT', 'Creative AI', 'Preregistered Study Protocol' …). 오탐 0.
#   낮은 히트율 + 높은 정밀도라 차단해도 정상 컷을 벌하지 않는다.
#   ※ **대소문자를 가리지 않는다**(2026-09-08 재측정). 처음에는 대문자로 시작하는 것만
#     봤는데, 새로 만든 지시서에서 `'weight loss'` 가 소문자라 그대로 빠져나갔다.
#     그래서 같은 224컷으로 다시 쟀다 — 대문자만 11컷(4.9%) → 소문자 포함 27컷(12.1%).
#     늘어난 17건을 눈으로 전부 확인했고 **하나도 빠짐없이 진짜 라벨**이었다:
#     'calorie restriction' · 'good match' · 'bad match' · 'ad quality' · 'conscientious' ·
#     'arXiv' · 'not just scores'. 오탐 0.
#     실사형 장면 묘사에 따옴표가 정당하게 쓰일 자리는 사실상 없다 — 물체는 **생김새로**
#     적는 것이지 이름을 붙이는 것이 아니다.
#     ※ **소유격·축약형은 뺀다**(2026-09-11 실측 사고). 여는 따옴표가 글자 **바로 뒤**면
#       그건 라벨이 아니라 `mouse's`·`don't` 의 아포스트로피다. 한 문장에 소유격이 둘이면
#       그 사이가 통째로 "라벨"로 읽힌다 — 실제로 이렇게 잡혔고, 차단이라 지시서를 막았다:
#         "A close-up of a researcher's gloved hand … The mouse's fur is visible"
#         → 잡힌 것: 's fur as the researcher'
#       고친 정규식으로 저장된 264컷을 다시 훑었다: 히트 29컷 → 28컷.
#       **줄어든 1건이 정확히 그 오탐**이고, 진짜 라벨 34종은 하나도 안 놓쳤다
#       ('Calorie Restriction' · 'arXiv' · 'good match' …).
PHOTO_QUOTED_LABEL_PATTERN: str = (
    r"(?<![A-Za-z])['‘’“”\"]([A-Za-z][A-Za-z0-9 +\-]{2,40})['‘’“”\"]"
)

#: 세계 선언(world.style·lighting·background)을 **그림 프롬프트에 싣는다.**
#
# ★ 여기가 오래 끊겨 있었다 — `visual_sequence.world_prose` 가 저장소 어디에서도 불리지
#   않았다(`camera_prose` 도 테스트에서만). 지시서가 세계를 선언해도 그림에는 안 닿았고,
#   그래서 세계는 장식이었다. `config.py` 의 옛 주석은 "코드가 시퀀스에서 만들어 뒤에
#   붙인다"고 적었는데 절반만 사실이었다(entity_prose 만 이어져 있었다).
# ★★ **선언을 청소한 다음에 배선했다.** 그 전에 이었으면 world 안의 "Soft, internal glow"·
#   "blurred cellular matrix" 가 프롬프트에 실려 더 나빠졌다. 지금은 게이트가 화풍 어휘를
#   막고 코드가 렌즈 어휘를 걷어낸다.
# ★★★ 참조 컷에는 붙지 않는다 — 첨부 그림이 이미 세계를 확정했고, 말로 다시 설명하면
#   "이것만 바꿔라"와 싸운다.
IMAGE_PROMPT_CARRIES_WORLD: bool = _get_bool("IMAGE_PROMPT_CARRIES_WORLD", True)

# ★★ 도해 구조(mechanism)를 이미지 프롬프트에 싣는다(2026-09-18, 연구 T1-a).
#   `mechanism` 은 게이트가 검사만 하고 **버렸다** — subject/components/transformation 이
#   그림에 한 번도 닿지 않았다(연구 §3-1). 그래서 구조는 완벽한데 화면은 배경 사진이었다.
#   이제 `visual_sequence.mechanism_prose` 가 영어 필드만 골라 한 문장으로 만들어 세계
#   선언 다음에 붙인다. 한글이 섞인 필드는 싣지 않는다(글자로 구워질 위험·번역 어긋남).
IMAGE_PROMPT_CARRIES_MECHANISM: bool = _get_bool("IMAGE_PROMPT_CARRIES_MECHANISM", True)

#: 세계 선언과 **그 세계를 여는 컷**이 겹치는 낱말이 하나도 없을 때 경고할지.
#
# ★ 실측: NEW_WORLD stage 34개 중 5개(14.7%)가 공통 낱말 0개였다.
#   그중 하나가 이번 사고다 — world 는 "cutaway teaching model of an animal cell" 인데
#   그 세계를 여는 컷8 이 벤 다이어그램을 그렸고, **세포 모형이 영상에서 사라졌다**
#   (뒤 stage 가 참조로 그것을 물려받는다).
# ★★ **경고인 근거도 실측이다.** 잡힌 5건에 오탐이 섞여 있다 — 근접 촬영("주사 펜 클로즈업"이
#   실험실 세계를 안 적는다)과 동의어("satellite imagery" vs "Moon's far side")가 걸린다.
#   낱말 겹침은 거친 대리 판정이다. 차단으로 올리면 옳게 한 컷을 벌하고, 그러면 운영자가
#   게이트를 무시하기 시작한다(photo_contract 설계원칙 1).
PHOTO_WORLD_LEAD_OVERLAP_WARNS: bool = _get_bool("PHOTO_WORLD_LEAD_OVERLAP_WARNS", True)

#: 위 검사에서 **내용어로 치지 않는** 말. 겹쳐도 세계를 그렸다는 근거가 못 된다.
PHOTO_WORLD_OVERLAP_STOPWORDS: frozenset[str] = frozenset("""
that this these those with without over under near beside around inside outside
their there where which while would could should
plain clean modern soft bright even natural warm cool dark light
small large tall short thin thick wide narrow
""".split())

#: **세계를 여는 컷이 뒤에 움직일 배우를 무대에 세웠는가**를 검사할지 (2026-09-10).
#
# ★ 왜 필요한가(실측 사고): NEW_WORLD stage 의 여는 컷이 그 세계의 **유일한 새 그림**이고,
#   뒤 stage 들은 그것을 첨부해 "이것만 바꿔라"로 만든다(`sequence_render.reference_decision`).
#   그래서 여는 그림에 없는 물체는 **뒤 컷이 줄이거나 키울 수 없다.**
#   실측: 여는 컷4 가 세포 모형만 그렸는데 뒤 stage 가 INFLAMMATION_MARKERS ·
#   SENESCENCE_MARKERS · NAD_MOLECULE 를 줄이고 등장시키라고 했다. 없는 것은 줄일 수 없어
#   컷 7·8·9 가 사실상 같은 화면이 됐다.
# ★★ 지금 있는 검사는 개체가 `entities` 에 **선언**됐는지만 본다
#   (`vseq_state_entity_undeclared`). 여는 **그림이 실제로 그리는지**는 아무도 안 봤다.
PHOTO_LEAD_STAGES_ENTITIES: bool = _get_bool("PHOTO_LEAD_STAGES_ENTITIES", True)

#: 위 검사에서 **개체를 특정하지 못하는** 말. 이것만 겹쳐서는 무대에 섰다는 근거가 못 된다.
#   ★ 왜 따로 두나: 개체 이름은 대부분 "무엇 + 총칭"이다(INFLAMMATION_MARKERS ·
#     NAD_MOLECULE · CELL_MODEL_A). 총칭까지 근거로 치면 여는 컷의 "a cell model" 한 마디가
#     세 개체를 전부 통과시킨다 — 실측에서 정확히 그렇게 샜다. 특정하는 낱말만 남긴다.
PHOTO_ENTITY_GENERIC_WORDS: frozenset[str] = frozenset("""
model models marker markers molecule molecules group groups object objects
structure structures piece pieces item items element elements unit units
figure figures sample samples specimen thing things part parts set setup
representing shown visible small large main primary secondary
and the for from with into onto its are was has have out off per
one two three next same other more less both each all any some
""".split())

#: 이름이 안 겹칠 때, `visual_identity` 의 특정 낱말이 **몇 개** 겹치면 무대에 섰다고 볼지.
#   ★ 1 로 두면 새 나간다(실측): SENESCENCE_MARKERS 의 생김새가 "…representing senescent
#     cells" 라 여는 컷의 "animal cells" 한 마디에 통과했다. 이름 대신 생김새로 적은
#     경우를 구제하되, 한 낱말 우연 일치는 근거로 치지 않는다.
PHOTO_ENTITY_LOOKS_MIN_OVERLAP: int = _get_int("PHOTO_ENTITY_LOOKS_MIN_OVERLAP", 2)

# EQ-V 계약 어휘 (작업지시서_시각엔진v3_equity §11). 리포트 문장을 읽는 검사용이라
# 이 셋에 기대는 사유는 전부 **경고**다 — 어휘 목록은 유한하고 오탐이 있다.
#: EQ-V2 — 애널리스트 추정·의견을 가리키는 말.
EQUITY_ESTIMATE_TERMS: tuple[str, ...] = (
    "추정", "전망", "예상", "목표주가", "컨센서스", "애널리스트", "의견",
    "estimate", "consensus", "analyst", "target price",
)
#: EQ-V3 — 아직 일어나지 않은 수치를 가리키는 말. 실적과 섞이면 안 된다.
EQUITY_FORECAST_TERMS: tuple[str, ...] = (
    "전망", "예상", "가이던스", "추정치", "E)", "F)",
    "guidance", "forecast", "outlook", "projected",
)
#: EQ-V7 — 은유. 사실 주장과 한 화면에 섞이면 시청자가 실제 사업구조로 읽는다.
EQUITY_METAPHOR_TERMS: tuple[str, ...] = (
    "스노우볼", "골드러시", "눈덩이", "금맥", "파도", "엔진처럼", "빙산",
    "snowball", "gold rush", "goldrush", "tidal wave", "iceberg",
)
DEPTH_DETAIL_RESTRICTIONS: dict[str, tuple[str, ...]] = {
    "full_body": (),
    "partial_body": ("protocol",),
    "abstract_only": ("protocol", "apparatus", "physiology"),
    "parse_failed": ("protocol", "apparatus", "physiology"),
    "none": ("protocol", "apparatus", "physiology"),
}

# 상태 변이 연산(State Ledger). LLM 은 **이 목록 안에서만** 변이를 제안하고, 상태 계산은
# 코드가 한다 — 자유 문장 두 벌(state_before/state_after)을 모델이 다 쓰면 진행 판정이
# 결국 자기보고가 된다(코덱스 리뷰 S1).
# ★★ **진짜 변형**으로 치는 변이 (2026-09-04). `APPEAR`·`HIGHLIGHT`·`DIM`·`DISAPPEAR` 는
#   "나타났다/강조됐다"라 화면이 **정지 상태로도 성립**한다 — 그것만으로는 기전을 설명하지 못한다.
#   근거 둘이 같은 말을 한다:
#     · 달 클립 실측(G2, 8/31): 좋았던 8초 팔의 비트는 DOLLY_OUT→TRACK→DOLLY_IN 에
#       마지막이 IMPACT 였다. 화면에 실제로 나타난 구간도 그 TRACK 이었다.
#     · Apify 벤치마크(8/19, 신비한 건축사전 제작법): "8초에 비트 2개, **횡이동 + 마지막
#       급속 푸시인**". 카메라가 움직이고 끝에서 사건이 터진다.
#   그런데 계약은 "mutation 필드가 있는가"만 봤고, 그래서 오늘 지시서가
#   `APPEAR+HOLD` 두 번으로 8초를 받았다(운영자: "역동적으로 움직이며 원리를 설명해야 한다").
TRANSFORMING_MUTATIONS: tuple[str, ...] = (
    "MOVE", "GROW", "SHRINK", "ROTATE", "TRANSFORM",
    "SPLIT_OFF", "MERGE_INTO", "REVERSE_TRACE", "IMPACT",
)
# 카메라가 실제로 움직이는 토큰(HOLD 제외). invest 는 최소 하나를 요구한다.
MOVING_CAMERAS: tuple[str, ...] = (
    "ORBIT", "DOLLY_IN", "DOLLY_OUT", "TRACK", "TOP_DOWN", "SECTION_DIVE", "FOLLOW_OBJECT",
)

MUTATION_OPERATIONS: tuple[str, ...] = (
    "APPEAR", "DISAPPEAR", "MOVE", "GROW", "SHRINK", "ROTATE", "TRANSFORM",
    "SPLIT_OFF", "MERGE_INTO", "HIGHLIGHT", "DIM", "REVERSE_TRACE", "IMPACT",
)

# 근거 원장 계약 버전. **저장된 판정은 검증 코드보다 오래 산다** — 골든B 가 그것을 증명했다:
# 커밋 c681613(연속 일치 비율) 이전 코드가 쓴 `quote_verified:false` 가 DB 에 남아,
# 지금 코드로는 통과하는 주장 4개를 지시서 단계가 계속 차단했다.
# 버전이 다른 판정은 **거짓이 아니라 판정 불가**로 다룬다(판정 불가와 실패를 섞지 않는다).
EVIDENCE_CONTRACT_VERSION: str = "2026-08-30.contiguous-ratio"

# ─────────────────────────────────────────────────────────────
# Phase 3 — 참조 조건 생성 (렌더 배선)
#
# ★ Phase 0 이 실측으로 검증한 방식 그대로 옮긴다(scripts/probe_continuity.py).
#   요청 바디의 `contents[0].parts` 에 **이미지 파트를 먼저**, 텍스트를 뒤에 싣는다.
#   실측 결과: 같은 인물·같은 세계가 3 stage 유지됐고 **단가는 그대로**였다($0.134 = 1.00배).
# ─────────────────────────────────────────────────────────────
SEQUENCE_REFERENCE_ENABLED: bool = _get_bool("SEQUENCE_REFERENCE_ENABLED", True)

# ★★ 참조가 필요한 컷은 **실시간으로 생성한다**(Batch 불가).
#
#   왜: Batch 는 렌더 시작 전에 요청을 한꺼번에 제출하는데, 참조로 쓸 앞 stage 의 그림은
#   그때 **아직 존재하지 않는다.** 즉 Batch 와 참조 조건은 원리적으로 함께 갈 수 없다.
#   기본 모드가 batch 라(IMAGE_GENERATION_MODE) 이 예외를 명시하지 않으면 시퀀스 컷이
#   조용히 텍스트 전용으로 그려지고 — 연속성이 사라진 것을 아무도 모른다.
#
#   Batch 는 반값이므로 이것은 **비용을 올리는 결정**이다. 대신 원장에 생성 모드가 남고
#   cost_plan 이 그 단가로 계산한다(싸게 보이게 하지 않는다).
SEQUENCE_REFERENCE_FORCES_REALTIME: bool = _get_bool(
    "SEQUENCE_REFERENCE_FORCES_REALTIME", True)

# 참조 프롬프트의 앞머리. **무엇을 유지하고 무엇만 바꾸는지**를 못박는다.
#   ★ Phase 0 에서 이 문구가 실제로 동작을 갈랐다. "참조를 붙였다"만으로는 모델이 장면을
#     다시 그린다 — "attached image as the exact starting frame … Do not redraw" 가 있어야
#     같은 세계의 다음 상태가 나온다.
#   ★ 세계·개체 서술은 코드가 시퀀스에서 만들어 뒤에 붙인다(visual_sequence.world_prose 등).
#     실측 프로브는 그 부분이 하드코딩이었다 — 그대로 옮기면 신뢰게임 세계에만 맞는다.
# ★ RETURN_WORLD 는 **다시 만들지 않는다.** 이미 그린 세계로 돌아가는 것이므로 크롭·톤
#   파생이 더 정확하고(같은 픽셀에서 나온다) 생성 호출이 0이다. 끄면 매번 새로 생성한다.
RETURN_WORLD_PREFERS_DERIVE: bool = _get_bool("RETURN_WORLD_PREFERS_DERIVE", True)

#: **색 불변식** — 참조 컷에서 물체의 색을 바꾸거나 서로 바꿔 달지 못하게 한다.
#
# ★ 왜(2026-09-19 실측, 지시서 fa58ed10·4851eb41): 비교색은 "이 물체가 어느 집단인가"를 말하는
#   **이름**인데, 참조 컷에서 모델이 그 색을 **물체 안의 부위 구분**으로 다시 썼다
#   ("청각장애인 뇌: 주변부 coral, 중심부 blue"). 그러면 화면의 범례가 거짓말이 된다.
# ★★ 여기서는 **개체 이름을 쓰지 않는다.** entity_id 를 프롬프트에 넣으면 그림에 글자로 구워질
#   위험이 있다(photo_quoted_label_in_prompt 가 막는 그것). 참조 그림이 이미 색을 확정했으므로
#   "붙어 있는 그림의 색 그대로"라고만 말하면 이름 없이도 불변식이 성립한다.
_COLOUR_INVARIANT: str = (
    "Every object keeps exactly the colour it has in the attached image: "
    "do not recolour any object and do not swap colours between objects. "
    "To point at one part inside an object, use the amber accent — "
    "never the two comparison colours. ")

SEQUENCE_REFERENCE_INSTRUCTION: str = (
    "Use the attached image as the exact starting frame. "
    "Keep the SAME subjects (same faces, same clothing, same placement), "
    "the SAME setting, the SAME camera angle, the SAME lighting and the SAME materials. "
    "Do not redraw the scene from scratch. " + _COLOUR_INVARIANT +
    "Change ONLY the following: ")
# 카메라가 움직이는 stage 용. 각도는 풀되 **피사체·세계·조명·재질은 그대로** 잠근다.
#   ★ 왜 나눴나(2026-08-30 채팅 실측): 하나만 쓰니 "SAME camera angle" 이라고 못박아 놓고
#     컷 프롬프트는 "extreme close-up" · "low-angle shot" 을 요구했다. 서로 반대말이다.
#     카메라는 camera_operation 으로 구조화돼 있으니 그 값을 보고 문구를 고른다.
SEQUENCE_REFERENCE_INSTRUCTION_MOVING: str = (
    "Use the attached image as the exact starting frame. "
    "Keep the SAME subjects (same objects, same design, same materials), "
    "the SAME setting and the SAME lighting. The camera may move as described. "
    "Do not redraw the scene from scratch and do not replace the subjects. " + _COLOUR_INVARIANT +
    "Change ONLY the following: ")
# ★★ 참조가 붙은 컷은 **장면 전체가 아니라 변화만** 말한다(2026-08-30 채팅 실측).
#
#   실측 사고: "Change ONLY the following:" 뒤에 컷의 visual_prompt 를 통째로 붙이고 있었다.
#   그런데 그 문장은 장면 전체 묘사다 — "medium shot of the Falcon 9 upper stage spinning
#   steadily, a digital timer overlay next to it…". 즉 **"이것만 바꿔라" 하고 전부 바꾸라고**
#   하는 꼴이었다. 6장에서 구도가 계속 헤맨 이유가 이것이다.
#   변화는 이미 구조로 있다(stage.mutations) — sequence_render.change_prose 가 그것을 문장으로
#   만든다. 만들어 놓고 배선하지 않았던 것을 잇는다. 변화 선언이 없으면 옛 경로로 후퇴한다.
SEQUENCE_REFERENCE_USES_DELTA: bool = _get_bool("SEQUENCE_REFERENCE_USES_DELTA", True)

# ★★ 참조 컷에서 **떼어내야 하는 화풍 문구**(2026-08-30 채팅 3차 실측).
#
#   MECHANISM 화풍에 `single amber accent color on the part being explained` 이 있다.
#   이것은 "설명 중인 부품을 호박색으로 칠하라"는 뜻이고, 컷마다 설명 대상이 바뀌므로
#   **정의상 물체 색이 매 컷 달라진다.** 그런데 같은 프롬프트가 "keep the SAME materials"
#   라고 말한다 — 두 지시가 정면으로 싸운다.
#   실측: 3차 생성에서 은색이던 엔진·노즐이 통째로 금색이 됐다.
#
#   첫 컷에서는 이 규칙이 옳다(설명 대상을 눈에 띄게 한다). 이어지는 컷에서는 **참조
#   이미지가 이미 재질을 확정**했으므로 다시 칠할 이유가 없다. 그래서 참조 컷에서만 뗀다.
# ★★ Veo I2V 연속 지시문(2026-08-30). 이미지 쪽과 같은 규율이다.
#   시작 프레임을 **애니메이트**하라고 말한다 — 다시 그리라고 하지 않는다.
#   Phase 0 관찰("Veo 가 다시 그린 쪽에 가깝다")이 Veo 한계인지 우리 지시 탓인지를
#   가르는 문장이다. 장면 묘사는 넣지 않는다 — 시작 프레임이 이미 장면이다.
# ★ [가설 기각 기록 — 2026-09-13] "the SAME framing 이 카메라를 막는다"고 보고 그 구절을 빼고
#   "카메라는 반드시 움직여라"를 넣어 **같은 시작 그림·같은 비트로 A/B** 를 했다.
#     옛 문구 motion_median 0.00113  vs  새 문구 0.00093 (벤치마크 0.0117, 문턱 0.0039)
#   새 문구가 더 낫지 않았다 — 근거가 없으므로 되돌린다. 같은 가설을 다시 세우지 말 것.
#   움직임이 낮은 원인은 다른 곳에 있다(모델 등급·측정 기준 자체를 다음에 본다).
VEO_CONTINUATION_INSTRUCTION: str = (
    "Animate the attached still image. It is the exact first frame. "
    "Keep the SAME subjects, the SAME design and materials, the SAME setting, "
    "the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, "
    "do not replace or restyle any object. Only the following motion happens: ")

STYLE_CLAUSES_DROPPED_WHEN_REFERENCED: tuple[str, ...] = (
    "amber accent on the part being explained",
)

# 참조 프레임을 못 만들었을 때 남기는 사유. **숨기지 않는다**(작업지시서 Paper §9).
DEGRADED_CONTINUITY_REASONS: tuple[str, ...] = (
    "degraded_no_reference_frame",   # 앞 stage 의 그림이 없다(생성 실패·순서 문제)
    "degraded_batch_mode",           # Batch 모드라 참조를 실을 수 없었다
    "degraded_reference_disabled",   # 스위치가 꺼져 있다
)

# 세계를 새로 만드는 비율이 이보다 높으면 경고 — "시퀀스"라고 부르지만 실은 컷 나열이다.
# ★ 차단이 아니라 경고인 이유: 짧은 영상은 세계가 여럿일 수 있고, 몇이 적정인지는 아직
#   실측이 없다. Phase 4 골든 비교 뒤에 숫자를 다시 잡는다.
VSEQ_WORLD_RESET_WARN: float = _get_float("VSEQ_WORLD_RESET_WARN", 0.6)

SPEC_TOKEN_PATTERN: str = (
    r"\b\d+\s*(?:°|deg\b|degrees?\b|mm\b|fps\b|k\b|K\b)"
    r"|\b(?:f/\d+(?:\.\d+)?|ISO\s*\d+|\d+\s*:\s*\d+)"
)

ASSET_STRATEGIES: tuple[str, ...] = (
    "new_asset", "reuse_crop", "reuse_zoom", "reuse_with_state_change",
    "reuse_background_new_overlay", "code_viz", "text_only_transition",
)
DEFAULT_ASSET_STRATEGY: str = "new_asset"
# 고유 에셋 수에 계상되지 않는(=생성 API 를 새로 부르지 않는) 전략들.
ASSET_STRATEGY_REUSE: tuple[str, ...] = (
    "reuse_crop", "reuse_zoom", "reuse_with_state_change", "reuse_background_new_overlay",
)
ASSET_STRATEGY_ZERO_COST: tuple[str, ...] = ("code_viz", "text_only_transition")
# ★ 재사용의 정의(2026-08-29 운영자 지시). "같은 인물·부품이 또 나오는 것"은 문제가 아니다 —
#   서사가 진행돼서 다시 나오는 것은 옳다. 문제는 **화면에서 아무것도 안 변한 반복**이다.
#   그래서 재사용 컷은 "무엇이 눈에 보이게 달라졌는가"(state_delta)를 선언해야 하고,
#   그 선언이 참인지는 **코드가 최종 프레임을 픽셀로 비교해** 판정한다(모델 자기보고 불신).
REUSE_REQUIRES_VISIBLE_DELTA: bool = os.getenv(
    "REUSE_REQUIRES_VISIBLE_DELTA", "true").lower() != "false"
REUSE_STATE_DELTA_MIN_CHARS: int = _get_int("REUSE_STATE_DELTA_MIN_CHARS", 12)
# 평균 픽셀 차이(0~255)가 이 값 미만이면 "같은 그림"으로 본다. 톤 그레이딩(알파 0.22)만 해도
# 이 선은 넉넉히 넘고, shutil.copyfile 수준의 복제는 0.0 이 나온다.
REUSE_MIN_PIXEL_DELTA: float = _get_float("REUSE_MIN_PIXEL_DELTA", 2.0)
# 한 기준 컷에서 파생이 이 개수 이상이면 경고 — 실측에서 컷1 하나가 3컷(1·10·11)을 차지했다.
REUSE_MAX_PER_BASE: int = _get_int("REUSE_MAX_PER_BASE", 3)
COST_PRIORITIES: tuple[str, ...] = ("evidence_over_motion", "motion_over_evidence")
DEFAULT_COST_PRIORITY: str = "evidence_over_motion"

# ─────────────────────────────────────────────────────────────
# 크롭 파생 · 톤 그레이딩 (docs/수정명세서_웹툰버전_v1.md §2)
#
# ★ 왜 필요한가: `reuse_crop`/`reuse_zoom` 전략은 예전부터 스키마에 있었지만 렌더가
#   `shutil.copyfile` 만 했다 — 즉 "확대"를 선언한 컷이 기준 컷과 픽셀 단위로 같은 그림이었다.
#   여기 상수들이 그 크롭을 실제 숫자로 만든다. 컷은 비율(0~1)만 싣고 픽셀은 렌더가 정한다
#   (원본 해상도가 바뀌어도 지시서가 낡지 않게).
# ─────────────────────────────────────────────────────────────
CROP_MIN_SCALE: float = 1.0
# 2.5배 상한 — 이걸 넘기면 업스케일 뭉개짐이 눈에 띈다(지시서 v2 §6). 실측 후 조정 가능.
CROP_MAX_SCALE: float = float(os.getenv("CROP_MAX_SCALE", "2.5") or "2.5")
CROP_MIN_BOX_PX: int = 8              # 이보다 작은 박스는 크롭이 아니라 사고다
CROP_DEFAULT_CENTER: float = 0.5

# 톤 그레이딩 — 감정·시간 변화만 필요한 컷에 새 이미지 대신 색을 입힌다(생성비 0).
# 값: (블렌드할 RGB, 알파). 알파가 클수록 원본이 덜 보인다.
TONE_GRADES: dict[str, tuple[tuple[int, int, int], float]] = {
    "warm": ((255, 176, 96), 0.22),
    "red": ((196, 48, 40), 0.28),
    "cool": ((80, 128, 208), 0.22),
    "desaturate": ((128, 128, 128), 0.45),
}
DEFAULT_TONE_GRADE: str = "none"      # "none" 은 TONE_GRADES 에 없다 — 무연산이라는 뜻

# 【§8-4】 근거가 감당하지 못하면 쓸 수 없는 단정·과장 표현. 단어 자체를 금지하는 게 아니라,
#   연결된 Claim 의 evidence_grade 가 C·D 면 훅 후보를 탈락시키는 판정 기준이다.
HOOK_STRONG_CLAIM_WORDS: tuple[str, ...] = (
    "증명했다", "완전히", "무조건", "전부", "인류", "지구를 망친다",
    "폭락", "폭증", "급감", "압도적", "충격적인 진실", "최종 답",
)

# 【§11】 근거 오버레이 — 말하지 않고 화면으로 증명하는 레이어.
#   ★ 별도 렌더 바이너리가 필요 없다: 자막과 같은 ASS 레이어에 이름 있는 스타일로 얹는다.
#     ASS 는 언어별로 생성되므로 언어 독립 에셋 불변식(I1)도 자동으로 지켜진다.
OVERLAY_TYPES: tuple[str, ...] = (
    "source_card", "evidence_card", "number_punch", "caveat_tag", "scope_tag",
    # ★ 2026-09-18 기전 교육력(연구_기전시퀀스_교육력 T3). 도해가 "무엇이 무엇인지"를 말할 길이
    #   없었다 — 이미지에 글자는 금지, overlay_plan 은 수치·출처 카드뿐. 그래서 두 뇌를 나란히
    #   그려도 어느 쪽이 정상인지 시청자가 모른다. 둘 다 ASS 텍스트라 언어별로 나간다.
    #     legend      색 견본 + 낱말 (■ 손상 뉴런 / ■ 정상 뉴런) — 기전 시퀀스당 1개
    #     label_pair  상·하 분할 화면의 위/아래 캡션 (전 / 후)
    "legend", "label_pair",
    # ★★ 2026-09-18 저녁, 운영자가 참고 영상(고기 핏물 편, 57초)을 주며 "키워드 카드랑 화살표까지".
    #   그 영상이 **모든 컷**에서 하는 두 가지다:
    #     keyword  화면 속 물체에 **낱말 하나**로 이름표를 단다(BLOOD? · MYOGLOBIN · 75% WATER).
    #              나레이션을 반복하는 문장 카드가 아니다 — 9/8 에 운영자가 뺀 것이 그 문장 카드였다.
    #     pointer  설명 대상에 **화살표**를 직접 얹는다. 색만으로 가리키는 것보다 세다.
    #   둘 다 생성 모델이 아니라 **코드가 그린다**(ASS 텍스트·도형) — 추가 비용 0, 언어별 렌더.
    "keyword", "pointer",
    # 아래 4종은 도형·차트가 필요해 M-E4(코드 시각화)에서 처리한다. 지금 지정되면 텍스트로 폴백.
    "before_after", "group_compare", "timeline", "mechanism_steps",
)
OVERLAY_TEXT_TYPES: tuple[str, ...] = (
    "source_card", "evidence_card", "number_punch", "caveat_tag", "scope_tag",
    "legend", "label_pair", "keyword", "pointer",
)
#: 문구 하나가 아니라 **구조(payload)** 를 갖는 오버레이. normalize 가 payload 를 보존한다.
OVERLAY_STRUCTURED_TYPES: tuple[str, ...] = ("legend", "label_pair", "pointer")
#: **주석 레이어** — 화면 가장자리·대상 위에 놓여 가운데 근거 카드와 자리를 다투지 않는다.
#  컷당 상한(OVERLAY_MAX_PER_CUT)을 따로 세고, 근거 카드가 꺼져 있어도 이것만 나간다.
OVERLAY_ANNOTATION_TYPES: tuple[str, ...] = ("legend", "label_pair", "keyword", "pointer")
OVERLAY_PRIORITIES: tuple[str, ...] = ("primary", "supporting")
DEFAULT_OVERLAY_PRIORITY: str = "supporting"
OVERLAY_MIN_SEC: float = 2.0          # §11-4 2초 미만으로 지나가는 복잡한 카드 금지
OVERLAY_MAX_PER_CUT: int = 2          # 한 화면에 핵심 1 + 보조 1
OVERLAY_FONT_SIZE: int = 48
# ★★ 72 → 110 (2026-09-04). 발행 벤치마크는 대표 수치를 **화면 폭의 절반 이상**으로 쓴다
#   (12.7km · 17.4mg · 254MW · 552GWh). 우리 72px 은 1080 폭에서 3자리 숫자가 13% 남짓이라
#   "카드"였지 "펀치"가 아니었다. docs/벤치마크_시화호_구조분석_2026-09-04.md 5절 ③.
# ★ 110 을 고른 근거는 실측이다 — 저장소의 number_punch 48건을 ASS 폭으로 계산하니
#   110px 에서 **35/48(73%)이 한 줄**에 들어간다. 140px 은 54%가 두 줄 이상으로 넘어간다.
# ★ 정직하게: 벤치의 정확한 픽셀을 재지 못했다(원본 영상이 임시폴더 정리로 사라졌다).
#   110 은 "확실히 지금보다 크고 대부분 한 줄에 든다"는 값이지 벤치 재현값이 아니다.
OVERLAY_NUMBER_FONT_SIZE: int = _get_int("OVERLAY_NUMBER_FONT_SIZE", 110)
# number_punch 텍스트가 이보다 넓으면 경고 — "펀치"가 아니라 문장이라는 뜻이다.
# ★ 실측이 드러낸 것: number_punch 최대 28자('AI 데이터센터 ESS 수요 2030년까지 20배↑').
#   그건 숫자가 아니라 요약문이고, 크게 키우면 화면을 3~4줄로 덮는다. 설명은
#   evidence_card 로 가고 number_punch 에는 **수치와 단위만** 남아야 한다.
OVERLAY_NUMBER_MAX_LINES: int = _get_int("OVERLAY_NUMBER_MAX_LINES", 2)
# 오버레이 좌우 마진(px). subtitles.py 의 ASS 스타일과 **같은 값**이어야 폭 계산이 맞는다.
# ★ 종전에는 subtitles.py 에 60 이 하드코딩돼 있었고 계산하는 쪽이 없었다.
OVERLAY_SIDE_MARGIN_PX: int = _get_int("OVERLAY_SIDE_MARGIN_PX", 60)
# 【근거 오버레이 켜기/끄기】 2026-09-08 운영자 지시로 **끈다**.
#
# ★ 지시 원문: "근거카드는 색깔이 문제가아니라 그냥 들어간다는게 문제입니다. 빼세요."
#   실물 조립에서 화면 중앙에 "+92일" · "캘리포니아 대학교 버클리 연구팀" 카드가 떴는데,
#   숫자와 출처는 **나레이션과 자막이 이미 말하고 있다** — 같은 정보를 두 번 얹으면
#   화면만 복잡해진다.
# ★★ 끄면 `photo_number_without_overlay` 차단도 함께 죽여야 한다. 그렇지 않으면
#   "숫자를 말했으니 카드를 넣어라"고 막으면서 그 카드를 **렌더가 그리지 않는** 상태가
#   된다 — 통과할 수 없는 함정이다. evaluate 가 이 스위치를 본다.
EVIDENCE_OVERLAY_ENABLED: bool = _get_bool("EVIDENCE_OVERLAY_ENABLED", False)
# 【범례·캡션만 켜기】 2026-09-18 운영자 지시 "오버레이 스위치 켜줘".
# ★ 위 스위치를 통째로 켜면 9/8 에 빼라고 한 수치·출처 카드가 같이 돌아온다. 사장님이 켜 달라고
#   한 것은 기전 시퀀스의 **범례(legend)·전후 캡션(label_pair)** 이다 — 이 둘은 나레이션이 말하지
#   않는 정보("어느 색이 무엇인지·위아래가 무엇인지")라 9/8 의 "같은 정보를 두 번" 지적에 해당하지
#   않는다. 그래서 스위치를 나눈다: 이 값이 True 면 EVIDENCE_OVERLAY_ENABLED 가 꺼져 있어도
#   구조형 오버레이(OVERLAY_STRUCTURED_TYPES)만 그린다. 수치·출처 카드까지 원하면 위 값을 켠다.
#   `photo_mechanism_unlabeled` 검사는 이 스위치를 본다(렌더가 그리는 것만 요구한다).
MECHANISM_LABEL_OVERLAYS_ENABLED: bool = _get_bool("MECHANISM_LABEL_OVERLAYS_ENABLED", True)

# ★★ ASS 색은 `&HAABBGGRR` — **RGB 가 아니라 BGR** 이다(2026-09-08 실물 렌더에서 잡았다).
#   옛 값 `&H00FFE000` 은 노랑을 적으려다 자릿수를 RGB 순으로 쓴 것이라 실제로는
#   R=0 G=224 B=255, 즉 **하늘색**으로 나갔다. 운영자 지적("가운데 파란색 자막은 뭐야")이
#   그것이다. 같은 파일의 헤더 훅은 `&H00E0FF&` 로 올바르게 적혀 있어 노랑으로 나왔다 —
#   한 화면에 두 색이 섞여 있던 이유다.
OVERLAY_COLOR_ASS: str = "&H0000E0FF"  # 강조 노랑 R255 G224 B0 (자막 흰색과 구분)
OVERLAY_CAVEAT_COLOR_ASS: str = "&H00B0B0B0"  # 한계·단서는 회색(주장보다 약하게)
# 오버레이 세로 위치: 자막(하단)·헤더(상단)와 겹치지 않는 중상단.
OVERLAY_MARGIN_V: int = 520

# ★ 기전 컷의 **색 규약**(2026-09-18, 운영자 승인 "T5 색까지 승인"). 화풍은 2026-09-08 에
#   고정됐지만 그 화풍의 "앰버 강조 1색"으로는 두 집단·전후를 구별할 수 없었다(연구 §3-4).
#   세 색을 **뜻과 함께** 고정한다 — 프롬프트(VISUAL_ROLE_STYLE)·범례(legend)·지시서 안내가
#   전부 이 표를 읽는다. 한 곳에서 이름을 바꾸면 세 곳이 같이 바뀐다.
MECHANISM_COLOR_CODE: dict[str, str] = {
    "amber": "the part being explained",
    "blue": "the first compared group, or the before state",
    "coral": "the second compared group, or the after state",
}
#: 위 세 색의 ASS 표기(&HAABBGGRR — BGR 순서). 범례의 ■ 견본에 쓴다.
LEGEND_COLORS_ASS: dict[str, str] = {
    "amber": "&H0000B0FF",   # R255 G176 B0
    "blue": "&H00E0A050",    # R80 G160 B224 (탁한 파랑)
    "coral": "&H006078E8",   # R232 G120 B96 (탁한 산호)
    "white": "&H00FFFFFF",
    "gray": "&H00B0B0B0",
}
OVERLAY_LEGEND_FONT_SIZE: int = 40
OVERLAY_LEGEND_MARGIN_V: int = 700     # 좌하단 기준(Alignment=1) — 근거 카드(520)보다 위, 자막 위
OVERLAY_LABEL_FONT_SIZE: int = 44
# ── 키워드 카드(2026-09-18) — 낱말 하나. 참고 영상은 시안색 불투명 박스를 좌상단에 쓴다 ──
OVERLAY_KEYWORD_FONT_SIZE: int = 72
#: ★ 주석 레이어는 **한 색**이다 — 카드 박스와 화살표가 같은 색이어야 "이건 우리가 얹은 설명"
#  이라고 한눈에 읽힌다(참고 영상이 시안 하나로 카드·화살표·조준선을 다 칠한다).
#  ASS 는 &HAABBGGRR(BGR!) — 아래 값은 RGB(32,192,224).
OVERLAY_ANNOTATION_COLOR_ASS: str = "&H00E0C020"
OVERLAY_KEYWORD_COLOR_ASS: str = "&H00FFFFFF"    # 카드 글자는 흰색
OVERLAY_KEYWORD_BOX_ASS: str = OVERLAY_ANNOTATION_COLOR_ASS
#: 낱말이 아니라 문장이면 카드가 아니다. 이 이상이면 게이트가 경고한다.
#: 카드 세로 자리 — 콘텐츠 밴드 맨 위(훅 아래). LAYOUT 절에서 레터박스 기하로 다시 잡는다.
OVERLAY_KEYWORD_MARGIN_V: int = 0
OVERLAY_KEYWORD_MAX_WORDS: int = 3
OVERLAY_KEYWORD_MAX_CHARS: int = 18
# ── 지시 화살표(2026-09-18) — 대상 구역을 코드가 가리킨다 ──
#: ★★ **기본 꺼짐**(2026-09-19 운영자 지시). 원문: "화살표에 왜 목숨거냐. 화살표는 그냥 없어도
#  되는거야. 아주가끔 필요하면 쓰는 도구이지 그걸 무슨 목숨걸고 처 넣으려고 낑낑거리고 있냐."
#  그 말이 맞았다 — 붙인 것은 모델이 아니라 **내가 쓴 프롬프트**다: 논문 쪽은
#  "원리를 설명하는 컷에는 되도록 붙여라", 리포트 쪽은 "설명 대상은 화살표로 찍어라"였다.
#  그래서 최근 지시서에서 논문 11/113 컷·리포트 8/48 컷이 화살표를 달았다.
#  화살표는 **그림이 이미 말하고 있는 것을 못 믿을 때** 쓰는 땜질이다. 그림이 말하게 하는 것이
#  먼저고, 그것이 안 되면 화살표가 아니라 그림을 고쳐야 한다. 켜는 것은 운영자 판단이다.
OVERLAY_POINTER_ENABLED: bool = _get_bool("OVERLAY_POINTER_ENABLED", False)
#: 화살표를 놓을 구역. **좌표를 모델에게 묻지 않는다** — 모델은 자기가 만든 그림을 본 적이 없다.
#  자기 장면 구성("왼쪽이 청각인")은 알고 있으므로 구역 이름은 신뢰할 수 있다.
OVERLAY_POINTER_ZONES: tuple[str, ...] = (
    "left", "right", "center", "top", "bottom",
    "top_left", "top_right", "bottom_left", "bottom_right",
)
OVERLAY_POINTER_MAX_PER_CUT: int = 3
OVERLAY_POINTER_COLOR_ASS: str = OVERLAY_ANNOTATION_COLOR_ASS
OVERLAY_POINTER_LENGTH_PX: int = 150
OVERLAY_POINTER_HALF_HEIGHT_PX: int = 30
#: 윤곽 에너지 문턱 — 이 위를 "물체가 있다"로 센다(0~255). 낮추면 배경 얼룩까지 잡는다.
OVERLAY_POINTER_EDGE_THRESHOLD: int = 24
#: 화살촉을 물체 한가운데에서 들어오는 쪽으로 물리는 거리(촉이 대상을 덮지 않게).
OVERLAY_POINTER_TIP_BACKOFF_PX: int = 110
#: 화살표가 화면 가장자리에서 떨어져 있어야 할 거리(꼬리까지 포함해 안으로 민다).
OVERLAY_POINTER_EDGE_MARGIN_PX: int = 24
#: 상·하 분할 캡션 자리는 **레터박스 기하에서 유도한다** — 아래 LAYOUT 절 참조.
#  (여기서 숫자로 박아 두면 LAYOUT_MODE·밴드 높이를 바꿀 때 캡션만 조용히 딴 곳에 남는다.)

# 【§14】 자기검증 3값 판정(해당 없음을 실패로 세지 않기 위해).
SELFCHECK_TRISTATE: tuple[str, ...] = ("pass", "fail", "not_applicable")

# ─────────────────────────────────────────────────────────────
# 대본 한국어 검수 (운영자 지시 2026-09-10:
#   "한국어 구조가 어색한게 없는지 한번더 대본리뷰한 후 생성하는 절차를 넣어야할듯합니다")
# ─────────────────────────────────────────────────────────────
# ★ 왜 없었나: `selfcheck.py` 는 **사실 검증관**이다 — 각 문장이 Fact Sheet 로 뒷받침되는지,
#   범위를 넘지 않는지, 인과를 과장하지 않는지를 본다. **한국어가 자연스러운지는 아무도
#   안 봤다.** 이 대본은 소리 내어 읽히므로 눈으로 말이 되는 것으로는 부족하다.
# ★★ **같은 호출에 얹는다** — 대본 단계 LLM 호출이 이미 여러 번이라 축 하나를 더 얹는 쪽이
#   별도 패스보다 싸다(추가 호출 0).

#: 어색함의 종류. 되먹임이 무엇을 고칠지 알려면 종류가 닫혀 있어야 한다.
SELFCHECK_FLUENCY_KINDS: tuple[str, ...] = (
    "translationese",   # 번역투(~에 대한 / ~를 통해 / 피동 남용)
    "particle",         # 조사가 어색하다
    "register_mix",     # 문어체·구어체 혼용
    "long_modifier",    # 수식 중첩 — 한 호흡에 못 읽는다
    "reading",          # 소리 내 읽을 때 걸린다(숫자·단위·영어 약어)
)

#: 어색하다고 판정된 씬을 **한 번 다시 쓰게** 할지.
#   ★ 경고이지 차단이 아니다 — LLM 판정이라 오탐이 있고, 이 저장소는 LLM 판정을 차단으로
#     쓰지 않는다(`selfcheck._WARNING_SCENE_FLAGS` 주석의 그 결정 그대로).
SCRIPT_POLISH_ENABLED: bool = _get_bool("SCRIPT_POLISH_ENABLED", True)

#: 다듬기가 문장을 얼마나 늘리거나 줄여도 되는가(글자 수 비). 벗어나면 **버린다.**
#   ★ 왜 필요한가: 나레이션 길이는 곧 화면 시간이다. 다듬는다며 문장을 반으로 줄이면
#     컷 길이 계산과 자막 배치가 통째로 어긋난다. 표현 교정은 길이를 크게 바꾸지 않는다.
#   ★ **늘어나는 쪽과 줄어드는 쪽이 다르다.** 다듬기의 주 업무가 번역투 제거이고,
#     번역투 제거는 **정의상 문장을 줄인다** — 대칭으로 재면 우리가 원하던 교정을 계속 막는다.
#     실측(2026-09-10, 살아 있는 모델로 표본 5): 정당한 교정이 −26·−27·−28·−44·−2% 였다.
#     반대로 **늘어나는 것**은 없던 설명을 덧붙였다는 뜻이라 위험하다 — 거기는 조인다.
#   ★★ 줄어드는 쪽을 풀 수 있는 이유는 **줄기 보존율**이 따로 지키기 때문이다(아래).
#     길이만 풀면 문장 하나를 통째로 빼는 교정이 통과한다.
SCRIPT_POLISH_LEN_TOLERANCE: float = _get_float("SCRIPT_POLISH_LEN_TOLERANCE", 0.25)
SCRIPT_POLISH_SHRINK_TOLERANCE: float = _get_float("SCRIPT_POLISH_SHRINK_TOLERANCE", 0.50)

#: 다만 **짧은 문장**은 비율로 재면 안 된다. 번역투를 걷어내면 원래 짧아지기 때문이다
#   (실측: "이 연구에 대한 결과를 통해 확인되었습니다"(23자) → "이 연구 결과로 확인되었습니다"(17자)
#   가 −26%). 글자 수 차이가 이 값 안이면 통과.
SCRIPT_POLISH_LEN_FLOOR_CHARS: int = _get_int("SCRIPT_POLISH_LEN_FLOOR_CHARS", 12)

#: **줄기 보존율** 하한 — 다듬은 문장이 원문의 낱말 줄기를 이만큼은 그대로 갖고 있어야 한다.
#
# ★ 무엇을 막는가: 숫자도 그대로고 뜻의 갈래도 그대로인데 **문장 하나가 통째로 빠지는** 교정.
#   "쥐 20마리에서 수명이 30% 늘었고, 인지 기능과 운동 능력도 함께 개선됐습니다"
#   → "쥐 20마리에서 수명이 30% 늘었습니다" 는 숫자·방향이 같아 앞의 두 검사를 다 통과한다.
#   발견 하나가 조용히 사라진다.
# ★★ 문턱은 **실측 분포에서 갈랐다**(2026-09-10, 표본 7):
#     정당한 교정 5건 = 53 · 60 · 63 · 70 · 82%
#     내용 삭제  2건 = 29 · 33%
#   둘 사이가 비어 있어 0.45 로 가른다. **표본이 7건뿐이다** — 경계가 촘촘해지면 다시 잰다.
SCRIPT_POLISH_MIN_STEM_RETENTION: float = _get_float(
    "SCRIPT_POLISH_MIN_STEM_RETENTION", 0.45)

# ★ 근거·숫자·방법·한계 공통 규칙 — SCRIPT_SYSTEM 과 DIRECTIVE_SYSTEM_BASE 가 **같은 상수**를 참조한다.
#   두 프롬프트에 near-duplicate 로 흩어져 있던 규칙(영상제작_프롬프트_통합명세.md §4-3)이 TS 사본까지
#   4벌로 번지는 걸 막는 유일한 장치다. 문구를 고칠 땐 여기만 고친다.
EVIDENCE_RULES_SHARED: str = """- 모든 사실 나레이션은 근거 Claim(claim_ids)을 가져야 한다. 연결어·질문·CTA 만 예외다.
- 소리 내 읽는 대표 숫자는 영상 전체 최대 2개, 한 컷에 1개. 나머지 수치는 화면(자막·오버레이)이 담당한다.
- 표본·기간·지역·세부 통계는 나레이션으로 나열하지 말고 화면으로 보여준다.
- 방법 설명은 기본 1문장. 통계 모델명은 그 방법 자체가 신뢰성 이해에 필요할 때만 말한다.
- 효과 크기가 없으면 '폭락·폭증·급감·압도적' 같은 강도 부사를 쓰지 마라. 유의성만 있으면 "차이가 나타났다" 수준으로.
- 한계는 "하지만 한계가 있습니다" 같은 면책 문구가 아니라, 훅이 넓혔던 범위를 정확히 회수하는 반전으로 쓴다.
- 같은 결과를 표현만 바꿔 두 번 말하지 마라. 5~7초마다 새 Claim·새 비교·새 시각 상태 중 하나가 등장해야 한다.
- 마지막 문장은 핵심 Claim 에 대한 정확한 답이다. 논문에 없는 교훈·도덕적 메시지·사회적 주장을 덧붙이지 마라."""

# 렌더 품질(영상 전문가 보강). 9:16 자막 세이프에어리어(화면 비율)·라우드니스.
SUBTITLE_SAFE_TOP: float = 0.12     # 상단 12% 자막 배치 회피
SUBTITLE_SAFE_BOTTOM: float = 0.15  # 하단 15% 회피(플랫폼 UI)
LOUDNESS_LUFS: float = -14.0        # 유튜브 기준 정규화 타깃
# ─ 렌더 QA 게이트 (수정지시서 v2 §7) — 발행 전 실제 mp4 를 ffprobe 로 실검(프레임 실측) ─
# "98.8%=버그" 단정 삭제 대신, 자동 판정 가능한 값만 하드 게이트로: 끝 검은프레임·>250ms 무음·오디오
# 클리핑·길이. 자막 존재는 우리 파이프라인이 ASS 를 결정적으로 번인하므로 프레임 디코드 여부로 확인
# (프레임 OCR 은 과투자 — 승인 UI 썸네일로 육안 확인 보조).
RENDER_QA_ENABLED: bool = _get_bool("RENDER_QA_ENABLED", True)
RENDER_QA_MAX_SILENCE_MS: int = _get_int("RENDER_QA_MAX_SILENCE_MS", 250)  # 이보다 긴 무음 = 경고
RENDER_QA_END_BLACK_MAX_SEC: float = float(os.getenv("RENDER_QA_END_BLACK_MAX_SEC", "0.3"))  # 끝 검은프레임 허용
RENDER_QA_PEAK_CEILING_DB: float = float(os.getenv("RENDER_QA_PEAK_CEILING_DB", "-0.5"))  # 이보다 크면 클리핑 위험
RENDER_QA_MIN_SEC: int = 20          # 이보다 짧으면 렌더 이상(길이 게이트)
RENDER_QA_MAX_SEC: int = 100         # 이보다 길면 렌더 이상
# ── Q1 정지 화면(지시서 v3 §9 "3초 동일 프레임 검사" · §14-1 "3초 연속 빈 콘텐츠 0") ──
# ★ 최종 mp4 에는 이 검사가 없었다(2026-09-03). 컷 후보에는 freezedetect 가 있는데
#   (CANDIDATE_FREEZE_*) 조립된 영상에는 없어서, 화면이 멈춘 채로 나가도 QA 가 통과시켰다.
#   코스피 빈 화면 사고와 같은 계열이다 — 오디오가 있고 길이가 맞으면 다 통과였다.
RENDER_QA_FREEZE_NOISE: str = os.getenv("RENDER_QA_FREEZE_NOISE", "-55dB")
RENDER_QA_MAX_FREEZE_SEC: float = float(os.getenv("RENDER_QA_MAX_FREEZE_SEC", "3.0"))
# ★★ 지금은 **경고**다. 차단으로 올리지 않은 이유가 있다: 이 문턱을 실제 렌더 분포에
#   대고 재 본 적이 **한 번도 없다**(렌더 0회). 근거 없는 문턱을 차단으로 걸면
#   core_underfilled 가 8건 중 5건을 죽였던 일이 반복된다. Phase 4 검증 렌더가
#   분포를 주면 그때 올린다 — 그 판단에 쓰라고 max_freeze_sec 를 원장에 남긴다.
RENDER_QA_FREEZE_BLOCKS: bool = _get_bool("RENDER_QA_FREEZE_BLOCKS", False)
# 자막 번인(libass). 한글 폰트 필요(러너: fonts-nanum). force_style 로 세이프에어리어 위 배치.
SUBTITLE_FONT_NAME: str = os.getenv("SUBTITLE_FONT_NAME", "NanumGothic")
SUBTITLE_FONT_SIZE: int = 66        # 본문 자막(크고 굵게 — 눈에 잘 띄게, 트렌디)
SUBTITLE_MAX_CHARS: int = 22        # 단어 타임스탬프→자막 줄 묶음 시 한 줄 최대 글자수
# 영상 상단 고정 헤더: 시리즈 제목 + 논문 후킹(부제). 전 구간 표시.
SERIES_TITLE: str = os.getenv("SERIES_TITLE", "하루 논문 한 편")
# ⑤ 언어별 시리즈 제목(EN 버전은 영어 제목). 상단 헤더에 언어에 맞춰 표시.
SERIES_TITLE_BY_LANG: dict[str, str] = {
    "ko": SERIES_TITLE,
    "en": os.getenv("SERIES_TITLE_EN", "A Paper A Day"),
}
HEADER_TITLE_SIZE: int = 74         # 상단 시리즈 제목(크고 굵게 — 특징있게)
HEADER_HOOK_SIZE: int = 46          # 상단 후킹(부제) 폰트
# 헤드 부제(후킹) 강조색 — 노랑(#FFE000). ASS 인라인 색 &HBBGGRR&. 제목(흰색)과 대비로 특징↑.
HEADER_HOOK_COLOR_ASS: str = "&H00E0FF&"
# BGM(무드 라이브러리 트랙 or 플레이스홀더 톤) + 나레이션 구간 자동 더킹(sidechain).
BGM_ENABLED: bool = _get_bool("BGM_ENABLED", True)
BGM_VOLUME: float = 0.18            # 기본 BGM 볼륨(나레이션 대비 낮게)
BGM_DUCK_THRESHOLD: float = 0.05    # sidechaincompress threshold
BGM_DUCK_RATIO: int = 8             # 나레이션 구간 감쇠 비율

# 제공자 선택(DV3). placeholder 는 키 불필요(조립 검증). 무료 실배선: edge(TTS).
IMAGE_PROVIDER: str = os.getenv("IMAGE_PROVIDER", "placeholder")
#: IMAGE_PROVIDER=reuse 일 때 그림을 꺼내 올 폴더(생성 호출 0·비용 0).
#  돈 드는 것은 그림 생성 하나뿐이라, 지난 렌더의 진짜 그림을 재사용하면 나머지 전부
#  (자막·범례·화살표·전후 분할·조립)를 사실대로 검증할 수 있다. 근거: providers/image._reuse_image.
IMAGE_REUSE_DIR: str = os.getenv("IMAGE_REUSE_DIR", "")
TTS_PROVIDER: str = os.getenv("TTS_PROVIDER", "placeholder")
VIDEO_PROVIDER: str = os.getenv("VIDEO_PROVIDER", "placeholder")

#: **한 푼도 나가지 않는** 제공자들. 캐시·원장·연속성 QA 가 전부 이 하나를 읽는다.
#  ★ `reuse` 가 여기 들어가야 하는 이유(2026-09-19): 이 판정은 예전에 `("placeholder", "")`
#    를 각자 적은 여섯 자리에 흩어져 있었고, 그래서 나중에 들어온 `reuse` 가 **유료로
#    취급**됐다 — 지난 렌더의 그림을 복사만 하는데 비용 원장에 정가가 쌓이고, 캐시를 켜면
#    빌려 온 그림이 진짜 에셋 자리에 저장될 수 있었다. 무료 경로가 돈 기록을 만드는 것은
#    이 저장소가 가장 경계하는 종류의 거짓말이다.
FREE_PROVIDERS: tuple[str, ...] = ("placeholder", "reuse", "")


def image_is_paid() -> bool:
    """이번 실행의 그림 생성이 **실제로 과금되는가**."""
    return IMAGE_PROVIDER not in FREE_PROVIDERS


def video_is_paid() -> bool:
    """이번 실행의 영상 생성이 **실제로 과금되는가**."""
    return VIDEO_PROVIDER not in FREE_PROVIDERS
# Edge TTS 음성(무료, 키 불필요). 한국어 여성 SunHi 기본.
# ★ 기본 음성을 Hyunsu 로 바꿨다(2026-09-09 운영자 청취 판정: "hyunsu 버전이 제일 나은데?").
#   후보는 한국어 Edge 음성 3종 전부 + 기존 일래븐랩스 영어 음성(George)이었다.
#   ★★ 일래븐랩스 한국어는 **못 쓴다** — 계정이 무료 등급이라 라이브러리 음성이 막혀 있고
#     (`paid_plan_required`), 남는 21개가 전부 영어라 한국어를 시키면 억양이 튄다.
#     쓰려면 유료 전환이 필요하다.
#   ⚠ 한국어 Edge 음성 3종은 **단어 타임스탬프를 주지 않는다**(실측). 그래서 자막은 항상
#     글자 수 비례 추정으로 배치된다 — `render._render_cut_clips` 의 그 폴백 경로를 볼 것.
EDGE_TTS_VOICE: str = os.getenv("EDGE_TTS_VOICE", "ko-KR-HyunsuMultilingualNeural")
# 나레이션 속도(Edge TTS rate). "+20%" ≈ 1.2배 빠름 → 컷 길이·전체 영상이 그만큼 짧아짐(자막 싱크 자동).
# ★ +20% → +5% (2026-09-03 첫 실사형 렌더 실측 — 운영자: "음성이 식상하고 급하다").
#   20% 빠르기는 20음절 문장을 4.4초에 밀어넣었고, 그 위에 숨 쉴 틈 0초가 겹쳐 '뚝뚝 끊김'이 됐다.
#   음성 자체(SunHi)는 취향이라 운영자가 고른다 — 후보: ko-KR-InJoonNeural(남), ko-KR-HyunsuMultilingualNeural(남).
# ★ +20% 로 되돌린다(운영자 지시 2026-09-05: "속도 보통보다 20% 가속"). 9/3 에 +5% 로 내린 건
#   "뚝뚝 끊긴다"는 지적 때문이었는데, 그 원인은 속도가 아니라 **컷 골격이 문장 중간을 자른 것**
#   (cut_skeleton, 9/4 수정)과 꼬리 여백 0초였다. 원인을 고쳤으니 속도는 운영자 취향으로 돌린다.
# ★ +20% → +10% (2026-09-12 운영자 지시 "나레이션을 좀 자연스럽게"). 9/5 의 +20% 는 운영자가
#   직접 정한 값이라 임의로 내리지 않았는데, 이번에 자연스러움을 요청해 한 단계만 낮춘다.
#   같은 문장을 네 가지(현수 +20%/+10%, 인준 +10%, 선히 +10%)로 들려 드렸고, 고른 값이 있으면
#   이 줄(또는 EDGE_TTS_RATE·EDGE_TTS_VOICE 환경변수)만 바꾸면 된다.
EDGE_TTS_RATE: str = os.getenv("EDGE_TTS_RATE", "+10%")

# ─────────────────────────────────────────────────────────────
# TTS 제공자 3종 (운영자 지시 2026-09-05: "구글이랑 일래븐랩스 둘 다 써보자")
# ─────────────────────────────────────────────────────────────
# TTS_PROVIDER = edge | google | elevenlabs | placeholder
#
# ★ 셋의 성질이 다르다. 고를 때 이 표를 본다:
#     edge        무료·무제한 · **단어 타임스탬프 있음**(WordBoundary) → 자막 싱크 정밀
#     google      무료 100만자/월(카드 등록) · 타임스탬프 없음 → 어절 청킹으로 자막
#     elevenlabs  무료 1만자/월(편당 ~500자면 월 20편) · 타임스탬프 없음 · 톤이 가장 자연스럽다
#
# ★★ 타임스탬프가 없는 제공자는 자막이 **어절 청킹**으로 떨어진다(subtitles.chunk_text_by_rate).
#   edge 만큼 정밀하지 않다 — 품질을 올리는 대신 싱크를 조금 잃는 교환이다.
#   이 사실을 여기 적어 두는 이유: 나중에 "자막이 밀린다"는 신고가 오면 원인이 여기다.

# Google Cloud TTS — Chirp3/Neural2 한국어. 키는 API 키 하나로 충분하다(REST).
GOOGLE_TTS_API_KEY: str = os.getenv("GOOGLE_TTS_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
GOOGLE_TTS_VOICE_BY_LANG: dict[str, str] = {
    "ko": os.getenv("GOOGLE_TTS_VOICE", "ko-KR-Chirp3-HD-Charon"),
    "en": os.getenv("GOOGLE_TTS_VOICE_EN", "en-US-Chirp3-HD-Charon"),
}
GOOGLE_TTS_LANG_CODE: dict[str, str] = {"ko": "ko-KR", "en": "en-US"}
# 속도. Edge 의 "+20%" 와 같은 뜻이 되도록 1.2 로 맞춘다.
# ★ 1.2 → 1.1 (2026-09-12): 제공자 셋은 **같은 속도**를 겨눈다. Edge 만 내리면 제공자를 바꿀 때
#   말 속도가 달라진다(tests/test_tts_providers.py::test_all_three_target_the_same_speed).
GOOGLE_TTS_SPEAKING_RATE: float = _get_float("GOOGLE_TTS_SPEAKING_RATE", 1.1)

# ElevenLabs — 무료 1만자/월. 다국어 v2 모델이 한국어를 읽는다.
# ★ **라이브러리 보이스를 기본값으로 두지 마라**(2026-09-05 실측). 처음 넣었던 Rachel
#   (21m00Tcm4TlvDq8ikWAM)은 공유 보이스 라이브러리 소속이라 무료 계정에서 402 가 난다:
#   "Free users cannot use library voices via the API." `GET /v1/voices` 가 돌려주는
#   21개는 전부 `category=premade` 이고 무료로 쓸 수 있다 — 그 안에서 고른다.
#   George(따뜻한 이야기꾼)로 한국어 합성 성공을 확인했다. 취향은 운영자가 고른다:
#   Eric(cjVigY5qzO86Huf0OWal, 부드럽고 신뢰감) · Alice(Xb7hH8MSUJpSbSDYk0k2, 또렷한 설명)
ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")  # George
ELEVENLABS_MODEL: str = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
# ★ ElevenLabs 는 rate 파라미터가 없다. 속도는 렌더가 atempo 로 맞춘다.
ELEVENLABS_SPEED: float = _get_float("ELEVENLABS_SPEED", 1.1)  # 위와 같은 이유(셋이 같은 속도)
# 무료 티어 월 상한. 넘으면 API 가 401 을 준다 — 미리 알고 폴백하려고 적어 둔다.
ELEVENLABS_FREE_CHARS_PER_MONTH: int = 10_000
# 나레이션 발음 교정(TTS 입력 치환). Edge TTS 가 영문 약어를 이상하게 읽는 것 방지.
# 자막도 이 치환된 텍스트(=실제 발음)를 따라간다. 대소문자 무시 치환.
TTS_PRONUNCIATION: dict[str, str] = {
    "arXiv": "아카이브",
    "arxiv": "아카이브",
}
#: 소리로 읽을 때 **영문 병기 괄호**를 뺀다(자막은 그대로). 2026-09-11 운영자 지적:
#:   "네이처(Nature)" → 한국어 TTS 가 "네이처 네이처" 로 두 번 읽어 상당히 부자연스럽다.
#:   한글 괄호("1,260개(전체의 13%)")는 정보이므로 남긴다 — engine/speech_text.py.
TTS_DROP_LATIN_GLOSS: bool = _get_bool("TTS_DROP_LATIN_GLOSS", True)
# TTS 합성/조립 하드 타임아웃(초). Edge TTS wss 가 멈춰도 렌더 전체가 무한정 안 멈추게 한다.
TTS_TIMEOUT_SEC: float = float(os.getenv("TTS_TIMEOUT_SEC", "45"))
# 조립 전 컷 파일 최소 크기(바이트). 이보다 작으면 **빈 mp4** 로 보고 조립을 멈춘다.
#
# ★ 근거는 실측이다(2026-09-08 첫 실물 렌더): 구간 자르기 인자 결함으로 컷 4개가
#   **261바이트** 짜리 빈 컨테이너로 나왔다. concat 은 말없이 건너뛰었고 렌더는 성공으로
#   끝났다 — 42초여야 할 영상이 13.5초로 나갔다. 정상 컷은 가장 작은 것도 180KB 였다.
#   그래서 문턱을 그 사이에 둔다. 빈 컨테이너(수백 바이트)와 실제 컷(수십만 바이트)은
#   자릿수가 달라 경계가 민감하지 않다.
MIN_CUT_FILE_BYTES: int = int(os.getenv("MIN_CUT_FILE_BYTES", "4096"))

# 【전체 재생속도】 완성된 영상 전체를 빠르게 한다. 1.0 이면 손대지 않는다(출력 불변).
#
# ★ 운영자 지시(2026-09-09): "내래이션과 전체 재생속도를 10% 정도는 증가시켜야할듯합니다."
# ★★ **한 곳에서 한 번만** 건다. 나레이션 속도(EDGE_TTS_RATE)와 영상 속도를 따로 올리면
#   둘이 곱해져 체감이 20% 넘게 빨라지고, 자막·더킹 타이밍이 어긋난다.
#   여기서는 조립이 끝난 파일에 영상(setpts)과 소리(atempo)를 **같은 비율로** 걸어
#   싱크를 유지한 채 전체를 줄인다. 자막은 이미 구워져 있어 함께 빨라진다.
# ★ 1.10 → 1.20 (2026-09-10 운영자 지시). 1.10 실물을 보고 더 올리기로 했다.
RENDER_PLAYBACK_SPEED: float = _get_float("RENDER_PLAYBACK_SPEED", 1.20)

FFMPEG_TIMEOUT_SEC: float = float(os.getenv("FFMPEG_TIMEOUT_SEC", "300"))
# 진행중(assets/tts/assembling) 상태로 이 시간 넘게 방치된 렌더 잡은 워커가 죽은 것으로 보고 재큐.
RENDER_STALE_MINUTES: int = _get_int("RENDER_STALE_MINUTES", 20)

# ─────────────────────────────────────────────────────────────
# 렌더 잡 상태 어휘 (v3 §8-3). **여기가 정본이다.**
#
# ★ 왜 상수로 묶는가: 이 목록이 코드 곳곳에 문자열 배열로 흩어져 있었다 — 워치독 재큐 2곳,
#   중복 잡 방지 가드 3곳(웹), 클레임 CAS 2곳. 새 상태를 추가할 때 **한 곳이라도 빠뜨리면**
#   조용히 망가진다:
#     · 재큐 목록에 사람 대기 상태를 넣으면 → 워치독이 승인 대기 잡을 queued 로 되돌려
#       **승인을 지운다**
#     · 활성 목록에서 빠뜨리면 → 승인 대기 중인 지시서에 **두 번째 렌더 잡**이 생긴다
#   웹(TS) 쪽 쌍둥이는 web/lib/renderStatus.ts 다. 둘이 갈리면 테스트가 잡는다.
RENDER_STATUS_IN_PROGRESS: tuple[str, ...] = ("assets", "tts", "assembling")
# 사람이 봐야 끝나는 상태. **워치독이 절대 건드리면 안 된다** — 기계가 아니라 사람을 기다린다.
RENDER_STATUS_AWAITING_HUMAN: tuple[str, ...] = ("qa_pending", "degraded")
# "이 지시서에 이미 살아 있는 잡이 있는가" — 중복 발주 방지용. 사람 대기도 살아 있는 잡이다.
RENDER_STATUS_ACTIVE: tuple[str, ...] = (
    ("queued",) + RENDER_STATUS_IN_PROGRESS + RENDER_STATUS_AWAITING_HUMAN)
RENDER_STATUS_TERMINAL: tuple[str, ...] = ("done", "failed")
# Gemini 이미지(nano banana) — IMAGE_PROVIDER=gemini 일 때. GEMINI_BASE/키 재사용.
IMAGE_MODEL: str = os.getenv("IMAGE_MODEL", "gemini-2.5-flash-image")
#: 컷 화면 역할별 이미지 모델 상향(2026-08-28, 운영자 지시: "3D 영상 퀄리티를 올려달라").
#:
#: ★ 왜 역할별인가 — 실사형이 약한 지점은 **실사(REALITY)가 아니라 3D 도해(MECHANISM)** 다.
#:   단면·분해·조립 순서처럼 "화면이 설명을 하는" 그림은 구조를 정확히 그려야 하는데,
#:   `gemini-2.5-flash-image` 는 공식 문서가 legacy 로 분류한 빠른 모델이라 층·경계가 뭉갠다.
#:   `gemini-3-pro-image` 는 문서가 "복잡한 시각 작업을 위한 프리미엄"으로 지목한 모델이다.
#: ★ 실사 컷까지 올리지 않는 이유: 현장 사진풍은 지금도 충분히 나오고, 편당 비용만 3배가 된다.
#:   돈을 설명력이 갈리는 곳에만 쓴다.
# 역할 상향 모델이 실패하면 **기본 모델로 한 번 더** 시도한다(2026-08-29 실측).
# ★ 왜: gemini-3-pro-image 가 503(high demand)로 죽자 3D 도해 컷이 전부 회색 placeholder 로
#   나갔다 — 같은 순간 flash 는 정상이었다. 유료 렌더에서 "덜 좋은 그림"과 "그림 없음"은
#   비교 대상이 아니다. 폴백 그림은 **폴백 모델의 캐시 키**에 저장되므로, 프리미엄이 살아나면
#   다음 렌더가 다시 프리미엄으로 만든다(상향이 영구히 묻히지 않는다).
IMAGE_MODEL_FALLBACK: bool = _get_bool("IMAGE_MODEL_FALLBACK", True)
IMAGE_MODEL_BY_ROLE: dict[str, str] = {
    "MECHANISM": os.getenv("IMAGE_MODEL_MECHANISM", "gemini-3-pro-image"),
}


# 이미지 요청에 실을 출력 해상도. ★ "provider_default" 는 **우리가 지정하지 않는다**는 사실을
# 명시적으로 적어 둔 값이다 — 예전에는 그냥 안 보냈고, 단가표는 "기본값이 1K/2K" 라는 **가정**
# 위에 서 있었다(PRICING 주석). 값이 캐시 키·원장에 들어가므로, 나중에 실제 해상도를 지정하게
# 되면 그 순간 캐시가 갈리고 원장에도 무엇으로 만들었는지가 남는다.
IMAGE_OUTPUT_RESOLUTION: str = os.getenv("IMAGE_OUTPUT_RESOLUTION", "provider_default")
# 프롬프트·화풍 계약 버전. ★ 화풍 문구나 역할별 계약을 고치면 **그림이 달라진다** — 그때
# 이 값을 올리면 캐시가 통째로 갈린다(옛 그림이 새 계약의 컷에 재사용되지 않는다).
PROMPT_CONTRACT_VERSION: str = os.getenv("PROMPT_CONTRACT_VERSION", "2026-08-29")

# ─ 실사형 화면 계약의 결정론적 검사 임계값 (engine/photo_contract.py) ─
# ★ 상수로 뺀 이유: 임계값이 코드에 박히면 오탐이 났을 때 코드를 고쳐야 하고, 그러면 게이트를
#   끄는 쪽이 빨라진다. 여기서 조인다.
PHOTO_CUT_SEC_MIN: int = _get_int("PHOTO_CUT_SEC_MIN", 3)   # 한 컷 = 한 문장(2~4초) 계약의 하한
PHOTO_CUT_SEC_MAX: int = _get_int("PHOTO_CUT_SEC_MAX", 5)   # 컷 수 역산에 쓰는 상한
PHOTO_CUT_SEC_WARN: int = _get_int("PHOTO_CUT_SEC_WARN", 8)  # 이보다 길면 경고(차단은 아님)
PHOTO_MIN_CUTS: int = _get_int("PHOTO_MIN_CUTS", 8)          # 아무리 짧아도 이보다 적으면 슬라이드쇼다
PHOTO_MECHANISM_RATIO_MIN: float = _get_float("PHOTO_MECHANISM_RATIO_MIN", 0.3)
PHOTO_MECHANISM_RATIO_MAX: float = _get_float("PHOTO_MECHANISM_RATIO_MAX", 0.7)
PHOTO_VIDEO_CUTS_MIN: int = _get_int("PHOTO_VIDEO_CUTS_MIN", 3)
PHOTO_VIDEO_CUTS_MAX: int = _get_int("PHOTO_VIDEO_CUTS_MAX", 8)
# 계약 위반 시 1회 재생성(리뷰 §7). ★ 1회로 묶는 이유: 두 번 실패하면 프롬프트로 고칠 수 있는
# 문제가 아닐 가능성이 높고, 매번 유료 호출이 한 번 더 나간다. 두 번째도 실패하면 사람에게 간다.
DIRECTIVE_CONTRACT_RETRY: bool = _get_bool("DIRECTIVE_CONTRACT_RETRY", True)

# ─ 결정론적 컷 골격(리뷰 §6, engine/cut_skeleton.py) ─
# ★ 컷 수를 대본 scenes 개수에 종속시키지 않는다. 문장 경계와 목표 길이로 코드가 먼저 칸을
#   만들고 LLM 은 칸을 채운다 — 실측에서 LLM 이 계약(10~14컷)을 무시하고 8컷으로 줄였다.
CUT_SKELETON_ENABLED: bool = _get_bool("CUT_SKELETON_ENABLED", True)
CUT_SKELETON_MIN_CHARS: int = _get_int("CUT_SKELETON_MIN_CHARS", 6)   # 이보다 짧으면 문장이 아니다
# 한국어 나레이션 말속도(글자/초). TTS 실측 기준 대략값 — 골격의 칸 나누기에만 쓴다
# (실제 컷 길이는 렌더가 TTS 를 재서 다시 맞춘다).
SPEECH_CHARS_PER_SEC: float = _get_float("SPEECH_CHARS_PER_SEC", 5.5)
# 골격 대비 허용 축소 비율. 1.0 이면 한 칸도 못 합친다 — 문장 분해가 완벽하지 않아 자연스럽게
# 합쳐지는 경우가 있어 여유를 둔다. 0.8 = 11칸이면 9컷까지 허용.
CUT_SKELETON_TOLERANCE: float = _get_float("CUT_SKELETON_TOLERANCE", 0.8)

# ─ 생성 요청 큐의 임대(0043, 리뷰 §8) ─
# ★ 임대 길이는 "정상 생성이 끝나는 시간"보다 넉넉해야 한다. 짧으면 살아 있는 워커의 일을
#   다른 워커가 뺏어가 같은 지시서를 두 번 만든다(유료 호출 2배).
REQUEST_LEASE_SEC: int = _get_int("REQUEST_LEASE_SEC", 900)      # 15분
REQUEST_MAX_ATTEMPTS: int = _get_int("REQUEST_MAX_ATTEMPTS", 3)

# ─ 초안 요청 큐(draft_requests·report_draft_requests)의 정체 회수 ─
# ★ 왜 임대가 아니라 시간인가: 이 두 테이블에는 0043 의 임대 컬럼이 **없다**. 그런데 0043 이
#   고치려던 바로 그 사고(Edge Function isolate 가 47초에 죽어 요청이 영구 processing)는
#   **초안 경로에서** 났다 — 지시서 큐에만 장치가 붙고 초안 큐는 빠졌다(2026-09-17 실측).
#   두 테이블 다 updated_at 이 이미 있으므로 렌더 잡 워치독(_reclaim_stale_render_jobs)과
#   같은 방식으로 막는다. 마이그레이션이 필요 없다.
# ★★ 문턱을 워커의 **잡 타임아웃보다 크게** 잡는다. 살아 있는 워커의 일을 뺏으면 같은 초안을
#   두 번 만들어 유료 호출이 두 배가 된다. 지금 타임아웃은 draft.yml 30분 · queues.yml 45분이라
#   60분이면 살아 있는 워커와 절대 겹치지 않는다.
# ★ 45분 밑으로 줄이지 말 것 — 워커에는 **처리 중 하트비트가 없다.** 집을 때 한 번, 끝날 때
#   한 번 찍을 뿐이라(engine/draft.py::poll_once) 뒤쪽 요청은 앞쪽이 끝날 때까지 옛 시각을
#   달고 있다. 지금 안전한 이유는 잡 자체가 타임아웃으로 먼저 죽기 때문이다.
REQUEST_STALE_MINUTES: int = _get_int("REQUEST_STALE_MINUTES", 60)

# 누가 잡았는지 — 로그·디버깅용. Actions 러너면 워크플로가 넣어 준다.
WORKER_ID: str = os.getenv("WORKER_ID", os.getenv("GITHUB_RUN_ID", "local"))


def image_model_for(visual_role: str = "") -> str:
    """이 컷을 그릴 이미지 모델. 역할 지정이 없으면 전역 IMAGE_MODEL."""
    return IMAGE_MODEL_BY_ROLE.get(str(visual_role or "").strip(), IMAGE_MODEL)


def image_cost_for(visual_role: str = "") -> float:
    """그 모델의 장당 단가. 단가표에 없으면 기존 근사값으로 떨어진다(원장이 비지 않게)."""
    model = image_model_for(visual_role)
    return float(PRICING.get(model, {}).get("image_standard", GEMINI_IMAGE_COST_USD))
GEMINI_IMAGE_COST_USD: float = 0.039           # 이미지 1장 근사 단가(예산 가드용)
GEMINI_IMAGE_MIN_INTERVAL_SEC: float = 6.0     # 무료등급 이미지 RPM 대비 요청 간격

# ─────────────────────────────────────────────────────────────
# 작업 A: 이미지 Batch (명세 §7). 대량 패널은 Batch(표준가의 50%), 검수 단건은 Realtime.
# ★ 사용자 승인으로 기본 on(2026-07-16). Batch API 계약(엔드포인트/키 필드)은 공식 문서로 구조를
# 확인했으나, 이미지 모델(gemini-2.5-flash-image)의 Batch 지원 여부는 문서에 명시되지 않았고 라이브
# 키로 실제 검증되지 않았다(§12.6 "Preview 모델 문제 시 기존 경로로 롤백" — 문제 생기면 env 로
# realtime 복귀). render.py 의 Realtime 경로는 무수정이라 Batch 실패해도 그 컷은 Realtime 폴백.
# ─────────────────────────────────────────────────────────────
IMAGE_GENERATION_MODE: str = os.getenv("IMAGE_GENERATION_MODE", "batch")  # realtime | batch
GEMINI_BATCH_MIN_INTERVAL_SEC: float = 2.0     # 폴링 요청 간격(레이트리밋 대비)
BATCH_POLL_MAX_CHECKS_PER_RUN: int = _get_int("BATCH_POLL_MAX_CHECKS_PER_RUN", 20)

# ⑤ Burn-in 금지(명세 §5.3). 공유 에셋에 언어 텍스트·수치·라벨이 구워지면 언어 독립 공유가 깨진다
# (KO 이미지에 한글이 박히면 EN 이 재사용 불가 → 이중 생성). 이미지·영상 프롬프트 공통 negative 제약.
# ★ 두 숏츠 라인(논문/신규 주제) 공통 지침 — 어느 라인이든 공유 시각 에셋은 화면 텍스트가 없어야 한다.
# 텍스트(자막·제목·차트 라벨)는 언어별 MoviePy/ASS 레이어로 합성한다.
BURN_IN_NEGATIVE_PROMPT: str = (
    "no text, no captions, no subtitles, no labels, no letters, "
    "no numbers, no speech bubbles, no watermarks"
)

# ─────────────────────────────────────────────────────────────
# 화풍 앵커 · 종횡비 (docs/수정명세서_웹툰버전_v1.md §3)
#
# ★ 1차 샘플에서 컷마다 화풍이 튄(실사/페인팅/CG 혼재) 직접 원인은 **부정어가 없었던 것**이다.
#   프롬프트 지시만으로는 모델이 실사로 되돌아가므로, 프로바이더가 구조적으로도 덧붙인다.
#   문구는 지시서 v2 §3 원문 그대로 — 바꾸면 그 검증 결과와 연결이 끊긴다.
# ─────────────────────────────────────────────────────────────
WEBTOON_NEGATIVE_PROMPT: str = (
    "NOT photorealistic, no 3D render, no lens flare, no depth of field, "
    "no cinematic photography, no realistic texture"
)
# 버전별 품질 접미사. 기존 "high detail" 은 실사를 유도한다 — webtoon 에서만 교체한다
# (comic 문자열을 건드리면 A/B 비교의 단일 변수 원칙이 깨진다).
IMAGE_QUALITY_SUFFIX_BY_VERSION: dict[str, str] = {
    "webtoon": "clean flat colors",
    # 실사형: 벤치마크 채널(건축·구조 해설 쇼츠)의 톤 — 시네마틱 실사 풍, 다큐 색감, 부감·매크로.
    #   "high detail" 만으로는 일러스트가 섞여 나온다.
    "photo": ("photorealistic cinematic still, natural daylight, muted documentary color grade, "
              "subtle film grain, aerial or macro perspective"),
}
DEFAULT_IMAGE_QUALITY_SUFFIX: str = "high detail"

# ─────────────────────────────────────────────────────────────
# 컷 화면 역할 (2026-08-20) — 실사형은 "3D 도해 + 실사"를 섞는다
#
# ★ 왜 생겼나: 첫 실사형 시험작을 보고 운영자가 정확히 지적했다 — "만화를 실사로 바꾼 것뿐,
#   벤치마킹한 내용이 없다". 맞는 지적이었다. 벤치 채널(신비한 건축사전·이런거지)의 화면은
#   **실사가 아니라 3D 렌더**이고, 그래서 지반 단면·아치가 쌓이는 과정·다리가 흔들리는 순간을
#   보여줄 수 있다. 사진으로는 못 찍는 것들이다.
#   우리 첫 시험작은 "ESS 시설 전경·공장 내부·서버랙" 같은 **배경 사진**이었다 —
#   화면이 설명을 하지 않고 주제를 장식만 했다. 원인은 계약에 "실재하는 장면을 적어라"라고
#   쓴 것이다(설명판형에서 가져온 규칙 — 거기선 보드가 설명을 맡아 사진은 배경이 맞았다).
#
# 이제 컷마다 화면의 **역할**을 선언한다:
#   MECHANISM — 3D 도해. 단면·절개·조립·흐름·전후 비교. **화면이 설명을 한다.**
#   REALITY   — 실사. 실제 현장·제품·규모. "이건 진짜 있는 일이다"를 앵커한다.
VISUAL_ROLES: tuple[str, ...] = ("MECHANISM", "REALITY")
# 실사형에서 모델이 역할을 비워 둔 컷에 채울 값. **연결·CTA 컷**이 반복해서 비었고,
# 그런 문장은 정의상 도해가 아니므로 실사가 옳은 답이다(2026-09-04 실측).
# ★ 이 기본값은 photo 경로에서만 쓴다 — sanitize_visual_role 은 여전히 빈값을 돌려준다.
PHOTO_DEFAULT_VISUAL_ROLE: str = "REALITY"

# 실사형에서 **연구 대상**(동물·시료·장비)이 화면을 차지할 수 있는 최대 비율.
# ★ 실측(세마글루타이드 렌더 2026-09-05): 쥐가 86초 중 42초 = 49%. 운영자:
#   "생쥐 이미지를 사람들이 그렇게 오래 보고 싶어 할 것 같냐." 대상은 훅·규모 실감에서만
#   짧게 보이고 나머지는 원리·맥락·의미로 가야 한다. 경고 문턱이다.
PHOTO_SUBJECT_SHARE_WARN: float = _get_float("PHOTO_SUBJECT_SHARE_WARN", 0.35)
# 연구 대상 어휘(visual_prompt 에서 찾는다). 동물 실험 라인이 지금 주력이라 동물이 앞에 온다.
PHOTO_SUBJECT_TERMS: tuple[str, ...] = (
    "mouse", "mice", "rat", "rats", "rodent", "zebrafish", "fly", "flies", "worm",
    "cage", "cages", "syringe", "petri", "pipette", "vial", "specimen", "sample tube",
)

# 지시서 완성 뒤 **최종 나레이션**을 기초 자료에 대고 다시 본다(운영자 지시 2026-09-05).
# ★ 왜 지시서 단계에도 필요한가: selfcheck 는 초안에서만 돌았는데, 지시서 LLM 이 나레이션을
#   다시 쓰고(실측 14개 중 3개, 전부 훅·도입부) 운영자가 화면에서 손으로도 고친다.
#   그 뒤로는 아무도 안 본다 — 가장 과장되기 쉬운 자리가 무검증이었다.
# ★ 두 층위를 **함께** 쓴다:
#     DIRECTIVE_AUDIT      기계 판정(숫자·주장 id·단서·인과). LLM 없음, 비용 0. 기본 on.
#     DIRECTIVE_SELFCHECK  의미 판정(범위 확대·논리 비약). LLM 1회(~$0.02). 기본 on.
#   전자는 확신할 수 있는 것만, 후자는 판단이 필요한 것을. 둘 다 **경고**다.
# ★ 차단으로 올리지 않는 이유: 올바르게 짝지은 실측에서도 빨강이 0~3건 나온다. 그중
#   상당수가 "우리가 계산한 값"이고, 차단하면 정상 지시서가 막힌다.
DIRECTIVE_AUDIT_ENABLED: bool = _get_bool("DIRECTIVE_AUDIT_ENABLED", True)
DIRECTIVE_SELFCHECK_ENABLED: bool = _get_bool("DIRECTIVE_SELFCHECK_ENABLED", True)
DEFAULT_VISUAL_ROLE: str = "REALITY"

# 역할별 화풍 접미사. 컷 역할이 있으면 버전 접미사(IMAGE_QUALITY_SUFFIX_BY_VERSION)를 이긴다.
VISUAL_ROLE_STYLE: dict[str, str] = {
    # ★ 2026-08-28 재작성(운영자 지시: "3D 영상 퀄리티를 올려달라. 화질 비율은 좀 낮아도 된다").
    #   앞 버전의 "matte clay materials" 는 **일부러 부드럽고 디테일 없는 룩**이었다. 그래서
    #   단면을 그려도 층 경계가 뭉개져 "무엇이 어떻게 되는지"가 안 보였다 — 3D 도해의 값어치가
    #   정확히 거기 있는데. 재질·경계·조명을 정밀 렌더 어휘로 바꾼다.
    #   유지하는 것(의도된 설계): 앰버 강조 1색 · 중립 배경 — 설명할 부분에만 눈이 가게 한다.
    #   해상도 어휘를 넣지 않는 이유: 운영자가 "화질 비율은 낮아도 된다"고 정했다. 올리는 것은
    #   **구조 묘사력**이지 픽셀이 아니다.
    # ★★ 2026-09-07 재작성. 앞 버전의 `physically based materials with fine surface detail` 는
    #   **사실성을 올리는** 어휘였다(PBR 의 목표가 사진처럼 보이는 것이다) — 방향이 반대였다.
    #   그리고 `engineering-diagram clarity` 가 "도해 = 선으로 그린 그림" 쪽으로 밀어
    #   세포 컷이 아웃라인 선화로 나왔다(실측 시도 2·3).
    #   ★ REALITY 와 **한 줄만 다르다**(isometric cutaway). 재질·조명·색은 같다.
    # ★★★ 2026-09-18 색 규약(운영자 승인 "T5 색까지 승인"). 앞 문장의 "앰버 1색"은 설명할
    #   **한 부분**을 가리키는 데는 옳았지만, 기전 컷의 절반은 **두 집단·전후를 나란히** 놓는
    #   컷이라 색이 하나면 둘을 구별할 수 없었다(연구_기전시퀀스_교육력 §3-4 — 두 뇌가 같은
    #   색이라 어느 쪽이 손상인지 화면이 말하지 못했다). 앰버는 그대로 두고 비교용 두 색을
    #   **뜻과 함께** 더한다(MECHANISM_COLOR_CODE). 재질·조명·배경은 여전히 REALITY 와 같다.
    #   tests/test_photo_style_is_locked.py 를 같이 갱신했다(의도한 변경).
    "MECHANISM": (
        "stylized 3D render, simplified geometric forms with clean silhouettes, "
        "matte surfaces with minimal micro-texture, "
        "isometric cutaway with crisp layer separation, "
        "even studio lighting, "
        "amber accent on the part being explained, "
        "muted blue and muted coral as the only two comparison colors, "
        "no other saturated color, neutral background"
    ),
    # ★★ 2026-09-07 재작성(운영자 지시: "실사가 너무 실사 같아서 못 보겠다. 특히 쥐.
    #   벤치마킹하던 건축 도해처럼 반실사 CG 로 가자").
    #   앞 버전은 `photorealistic cinematic still … subtle film grain` 이었다 — 사진을
    #   목표로 하는 어휘다. 실측에서 진짜 쥐 사진이 나왔고 그게 운영자가 못 보겠다고 한 그것이다.
    #   ★ 이 문자열은 **수동 실측 시도 2에서 검증된 것**이다(핸드오프 §2). 그림 2(사육장)·
    #     3(연구원 손)이 이 어휘로 목표 화풍이 나왔다 — 아웃라인 없이 무광 CG.
    #   ★★ MECHANISM 과 **재질·조명·색을 공유한다.** 다른 것은 시점(단면)뿐이다.
    #     그래야 한 영상 안에서 실험실 장면과 세포 도해가 같은 작품으로 보인다 —
    #     "컷7(실사 쥐) → 컷8(3D 세포)에서 화면이 튄다"가 이 작업의 출발점이었다.
    "REALITY": (
        "stylized 3D render, simplified geometric forms with clean silhouettes, "
        "matte surfaces with minimal micro-texture, even studio lighting, "
        "limited desaturated palette with a single amber accent, neutral background"
    ),
}
# 역할별 부정어. 3D 도해는 사진처럼 되면 단면이 안 보이고, 실사는 일러스트가 섞이면 신뢰를 잃는다.
# ★★ 2026-09-07 재작성. 두 역할이 **같은 것을 금지한다** — 화풍을 하나로 통일했으므로
#   부정어도 하나여야 한다. 앞 버전은 정반대를 금지하고 있었다(MECHANISM 은 사진을,
#   REALITY 는 3D 렌더를) — 그래서 참조 사슬이 "사진으로 만든 그림을 첨부하고 사진이면
#   안 된다"고 말하는 자기모순에 빠졌다(providers/image.py 주석의 그 사고).
#   ★ 부정어는 **보조일 뿐 긍정 어휘를 이기지 못한다**(실측 4회). 아웃라인을 실제로 막는 것은
#     위 STYLE 의 긍정 어휘와 장면 묘사이지 여기가 아니다. 여기는 마지막 안전망이다.
VISUAL_ROLE_NEGATIVE: dict[str, str] = {
    "MECHANISM": (
        "not a photograph, no photorealistic detail, "
        "no cartoon outlines, no line art, no ink contours, no cel shading, "
        "no flat vector art, no anime, "
        "no glowing effects, no neon, no bloom, no light emission, "
        "no lens blur, no bokeh, no film grain"
    ),
    "REALITY": (
        "not a photograph, no photorealistic detail, no fur or skin micro-texture, no pores, "
        "no cartoon outlines, no line art, no ink contours, no cel shading, "
        "no flat vector art, no anime, "
        "no lens blur, no bokeh, no film grain"
    ),
}
# 12컷 기준 권장 배분. 벤치 채널은 대부분이 도해이고 실사는 앵커로 몇 컷 끼는 구조다.
VISUAL_ROLE_MIX: dict[str, tuple[int, int]] = {"MECHANISM": (5, 7), "REALITY": (3, 5)}

# 실사형 부정어 — 그림체로 되돌아가는 것을 막는다(webtoon 부정어의 정확한 반대).
PHOTO_NEGATIVE_PROMPT: str = (
    "not an illustration, no cartoon, no anime, no webtoon, no drawing, "
    "no 3D render, no painting, no flat vector art"
)

# ★ 버전 → 화풍 부정어. 예전에는 "IMAGE_QUALITY_SUFFIX_BY_VERSION 에 키가 있으면 webtoon
#   부정어를 붙인다"는 대리 판정이었다. 실사형을 추가하는 순간 그 규칙은 실사형에
#   "NOT photorealistic" 을 붙여 정반대로 동작한다 — 그래서 표를 따로 둔다.
#   comic·image_sequence 는 여기 없으므로 출력 문자열이 예전과 바이트 단위로 같다.
IMAGE_STYLE_NEGATIVE_BY_VERSION: dict[str, str] = {
    "webtoon": WEBTOON_NEGATIVE_PROMPT,
    "photo": PHOTO_NEGATIVE_PROMPT,
}

# ★ 종횡비를 프롬프트 텍스트가 아니라 **요청 파라미터**로 보낸다. 1차에서 8장 전부 1024×1024 로
#   나온 직접 원인이 이것이다(프롬프트의 "vertical 9:16" 은 무시된다).
#   ⚠ 필드 경로가 확정적이지 않다: 공식 문서에 generationConfig.imageConfig.aspectRatio 와
#   generationConfig.responseFormat.image.aspectRatio 가 **둘 다** 나오고, generate-content 레퍼런스의
#   GenerationConfig 필드 목록에는 어느 쪽도 없다. 그래서 경로를 상수로 빼고 400(INVALID_ARGUMENT)이
#   나면 env 한 줄로 되돌린다(IMAGE_ASPECT_RATIO_PARAM=false). Batch API 계약 주석과 같은 취급이다.
IMAGE_ASPECT_RATIO_PARAM: bool = _get_bool("IMAGE_ASPECT_RATIO_PARAM", True)
IMAGE_ASPECT_CONFIG_SHAPE: str = os.getenv("IMAGE_ASPECT_CONFIG_SHAPE", "image_config")
IMAGE_ASPECT_CONFIG_SHAPES: tuple[str, ...] = ("image_config", "response_format")
# 생성 결과가 9:16 인지 실측할 때의 허용 오차(모델이 1088×1920 처럼 살짝 어긋나게 줄 수 있다).
IMAGE_ASPECT_TOLERANCE: float = 0.02

# hybrid 버전: 핵심 컷만 I2V 영상(Veo). Google Veo API(직접 키) — VIDEO_PROVIDER=veo 일 때.
# 스틸(nano banana)을 첫 프레임으로 → Veo 가 모션 부여(I2V). 나머지 컷은 스틸+Ken Burns.
# 기본은 Lite(가장 저렴, $0.05/s — Fast 의 절반). env(VEO_MODEL)로 Fast(veo-3.1-fast-generate-preview,
# $0.10/s) 나 Standard 로 교체 가능. Fast 와 같은 predictLongRunning 계약(파라미터/응답 동일 계열).
VEO_MODEL: str = os.getenv("VEO_MODEL", "veo-3.1-lite-generate-preview")
VEO_CLIP_SEC: int = _get_int("VEO_CLIP_SEC", 4)                    # 클립 길이(Veo 3.1: 4·6·8초)
VEO_MAX_CLIPS_PER_DRAFT: int = _get_int("VEO_MAX_CLIPS_PER_DRAFT", 4)  # 편당 영상 컷 상한(3~4개, 비용 가드)
# ★ I2V 연쇄 — 영상 컷의 시작 화면을 **앞 영상 컷의 마지막 프레임**으로 잇는다.
#   왜: 벤치마크 채널의 "이어지는 느낌"은 화풍 일관성이 아니라 **같은 장면이 계속되는 것**에서
#   나온다(docs/benchmark-realistic-shorts-2026-08-19.md). 지금은 영상 컷마다 새 스틸을 그려
#   시작 화면으로 넣어서, 컷마다 다른 장소가 된다.
#   부수 효과로 생성비도 준다 — 이어 붙인 컷은 새 이미지를 사지 않는다($0.039/컷 절약).
I2V_CHAIN_VERSIONS: tuple[str, ...] = tuple(
    v for v in os.getenv("I2V_CHAIN_VERSIONS", "photo").split(",") if v.strip())

# 시퀀스(stage) 단위 렌더 — 컷마다 클립 1개가 아니라 stage 하나를 연속 영상으로 채운다.
# ★ 왜: 컷 단위는 컷 경계마다 화면이 끊기고, 나레이션이 클립보다 길면 마지막 프레임이
#   **얼어붙는다**(clip_fit hold). 실측(세마글루타이드 렌더): hold 5컷, 컷8 은 12.7초
#   나레이션에 8초 클립 → 4.7초 정지. 근거·설계는 docs/설계안_시퀀스단위_렌더_v1.md.
# ★ 끄면 즉시 옛 컷 경로로 돌아간다 — 새 경로가 실패했을 때 되돌리는 스위치다.
STAGE_RENDER_ENABLED: bool = _get_bool("STAGE_RENDER_ENABLED", True)

# ★★ 전·후 분할 스틸(2026-09-18, 연구 T2). 상태가 **바뀌는** stage(TRANSFORM·GROW·SHRINK 등)를
#   I2V 에 맡기면 카메라만 돌고 대상은 안 바뀐다 — 영상 모델은 의미 변화를 못 만든다(연구 §3-2,
#   실측: 뇌가 "재배선"되는 8초 동안 조명만 흔들렸다). 그런 stage 는 앞 stage 의 그림(전)과
#   이 stage 의 그림(후)을 **위·아래로 붙인 한 장**으로 만들고 켄번스로 잡는다. 영상비 0.
#   MOVE·ROTATE·IMPACT 같은 **운동**은 I2V 가 할 수 있는 일이라 그대로 둔다.
MECHANISM_SPLIT_BEFORE_AFTER: bool = _get_bool("MECHANISM_SPLIT_BEFORE_AFTER", True)
MECHANISM_SPLIT_OPERATIONS: tuple[str, ...] = (
    "TRANSFORM", "GROW", "SHRINK", "SPLIT_OFF", "MERGE_INTO", "DISAPPEAR",
)
MECHANISM_SPLIT_DIVIDER_PX: int = 8
MECHANISM_SPLIT_DIVIDER_RGB: tuple[int, int, int] = (58, 58, 58)
# ★★ 분할 스틸에는 **효과를 넣지 않는다**(2026-09-18 재리뷰, 실측 근거 둘).
#   ① 합성본을 이미 콘텐츠 밴드 크기로 만들기 때문에 켄번스를 걸면 그만큼 **가장자리를 잘라낸다** —
#      비교하라고 만든 두 화면의 바깥쪽이 사라진다.
#   ② 비교는 원래 멈춰서 보는 화면이다(참고 영상도 구도를 고정하고 주석 레이어만 움직인다).
#   대가: 최종 mp4 freezedetect 경고가 뜬다(차단 아님). 그 경고는 **사실이므로 숨기지 않는다**.
MECHANISM_SPLIT_EFFECT: str = ""
#: 분할 화면에 **캡션이 없으면 코드가 채운다**(2026-09-19 첫 실전 분할에서 잡았다).
#  모델이 label_pair 를 빼먹으면 위·아래가 무엇인지 알 길이 없어 분할 자체가 무의미해진다.
#  경고만 하고 넘기면 그 화면이 그대로 나간다 — 기계가 확실히 아는 것은 기계가 적는다.
#: 분할 캡션은 **컷이 끝날 때까지** 떠 있어야 한다(2026-09-19 실측으로 잡았다).
#  기본값 OVERLAY_MIN_SEC(2초)로 뒀더니 6초짜리 컷의 중간부터 이름표가 사라졌다 —
#  비교 화면은 끝까지 비교하는 화면이라, 후반을 보는 사람은 어느 쪽이 전인지 알 수 없다.
#  큰 값을 주고 컷 경계에서 자르게 둔다(build_overlay_cues 가 이미 컷 끝에서 자른다).
MECHANISM_SPLIT_LABEL_SEC: float = 600.0
#: **주석 레이어는 그 컷 내내 떠 있는다**(2026-09-19 실측으로 정했다).
#  키워드 카드는 화면 속 물체의 **이름표**이고 화살표는 그 물체를 가리킨다 — 물체가 화면에
#  있는 동안 이름표가 사라지면 그 컷의 후반은 이름 없는 화면이 된다. 범례도 같다(색이 화면에
#  있는 내내 뜻이 필요하다). 실측(리포트 da1a6b96): 8초 컷에 카드 3초·화살표 2초라 중간부터
#  둘 다 사라졌다. 참고 영상은 카드를 컷 내내 붙여 둔다.
#  수치·출처 카드(number_punch·source_card)는 **말하는 순간**에 뜨는 것이라 여기 해당하지 않는다.
#  큰 값을 주고 컷 경계에서 자르게 둔다(build_overlay_cues 가 이미 컷 끝에서 자른다).
OVERLAY_ANNOTATION_HOLD_SEC: float = 600.0
MECHANISM_SPLIT_DEFAULT_LABELS: dict[str, tuple[str, str]] = {
    "ko": ("변화 전", "변화 후"),
    "en": ("Before", "After"),
}

# ★ 도해 컷의 visual_prompt 가 구조와 **떨어져 있는가**(2026-09-18, 연구 T1-b).
#   components 중 프롬프트에 한 번도 안 나오는 컷 — 실측 117컷 중 4컷(3.4%), 오탐 0
#   (넷 다 entity_id 나 데이터셋 이름을 구성요소라고 적은 것). 그래서 처음부터 차단이다.
#   한글 구성요소는 셀 수 없으므로 **영어 구성요소가 2개 미만이면 역시 떨어진 것**으로 본다 —
#   그림은 영어로 그리고, 한글 구조는 그림에 닿지 못한다.
PHOTO_MECHANISM_PROMPT_MIN_HITS: int = 1
# ★ [혼자 서는 컷] 2026-09-14 운영자 실측 — stage_render.group_cuts 주석이 근거다.
#   결론 컷이 앞 stage 영상의 한 구간으로 잘려 **자기 그림이 한 번도 안 그려졌다**
#   (최근 16편 중 13편). 끄면 종전처럼 앞 묶음에 붙인다.
STAGE_FINAL_CUT_OWN_CLIP: bool = _get_bool("STAGE_FINAL_CUT_OWN_CLIP", True)
# ★ stage 영상 캐시(2026-09-14 실측) — 시퀀스 렌더 경로에 캐시가 없어 영어판이 Veo 클립을 다시 샀다.
#   render.stage_video_hash 는 언어·나레이션 길이를 넣지 않아 KO 영상을 EN 이 쓴다. 끄면 매번 만든다.
STAGE_VIDEO_CACHE_ENABLED: bool = _get_bool("STAGE_VIDEO_CACHE_ENABLED", True)
STAGE_CONNECTIVE_OWN_CLIP: bool = _get_bool("STAGE_CONNECTIVE_OWN_CLIP", True)
# stage 영상이 계획보다 이만큼 넘게 짧으면 "짧다"고 본다(그 아래는 인코딩 오차).
# ★ 실측 근거 없는 문턱이 아니다: 컷 경계 판정에 쓰는 값들과 같은 자리수(0.05초 = 1.5프레임
#   @30fps)다. 이보다 촘촘히 재면 ffmpeg 의 프레임 경계 반올림이 매번 "짧다"로 잡힌다.
STAGE_SHORTFALL_TOLERANCE_SEC: float = _get_float("STAGE_SHORTFALL_TOLERANCE_SEC", 0.05)
VEO_COST_PER_SEC_USD: float = float(os.getenv("VEO_COST_PER_SEC_USD", "0.05") or "0.05")  # Lite 720p 근사
VEO_RESOLUTION: str = os.getenv("VEO_RESOLUTION", "720p")
# 일부 Veo 프리뷰 모델의 predictLongRunning 은 resolution 파라미터를 거부(400)할 수 있어 기본 미전송.
VEO_SEND_RESOLUTION: bool = _get_bool("VEO_SEND_RESOLUTION", False)
VEO_GENERATE_AUDIO: bool = _get_bool("VEO_GENERATE_AUDIO", False)  # 나레이션은 파이프라인이 얹음 → 무음(현재 미사용)
VEO_POLL_INTERVAL_SEC: float = float(os.getenv("VEO_POLL_INTERVAL_SEC", "10") or "10")
VEO_POLL_TIMEOUT_SEC: float = float(os.getenv("VEO_POLL_TIMEOUT_SEC", "300") or "300")
# Veo 3.1 이 실제로 내주는 고정 길이 티어. 임의 길이는 지원하지 않는다(수정명세 v1 §3-2 / 열린질문 3).
# providers/video.py 가 이 목록을 CLIP_SEC_TIERS 로 노출하고 pick_clip_tier 로 선택한다.
VEO_CLIP_SEC_TIERS: tuple[int, ...] = (4, 6, 8)
# 티어 선택 상한(초). 나레이션이 길어도 이 값을 넘는 티어는 요청하지 않는다.
# ★ 기본값을 VEO_CLIP_SEC(=4)로 두는 이유: 티어를 올리면 초당 과금이라 클립당 비용이 1.5~2배가 된다
#   (4s $0.20 → 8s $0.40, 편당 4클립이면 +$0.80). 이 저장소의 비용 규율(Lite 모델·이중 캡)과 충돌하므로
#   기본은 비용 불변으로 두고, 잔여 갭은 무료 보정(hold/pingpong, clip_fit)이 흡수한다.
#   네이티브 길이 클립을 원하면 VEO_CLIP_MAX_TIER_SEC=8 로 올린다(비용 상승 감수).
VEO_CLIP_MAX_TIER_SEC: int = _get_int("VEO_CLIP_MAX_TIER_SEC", VEO_CLIP_SEC)

# ─────────────────────────────────────────────────────────────
# 단가표 (작업 C 원장, 명세 §2.3). 단가는 코드에 박지 않고 여기서 읽어 원장 행에 스냅샷한다
# (pricing_versions 테이블 불요 — 경량 경로). 과거 비용 재현은 원장 행의 unit_price_usd 로.
# ★ 가격은 2026-07 기준. 착수 시 공식 문서(Gemini Pricing/Batch, Veo 3.1) 재확인해 다르면 공식값 우선.
#   특히 Veo Fast 는 소스 간 $0.10 vs $0.15 충돌 → 공식 확정 전까지 $0.10(config 라 무영향).
# ─────────────────────────────────────────────────────────────
# 텍스트 LLM 단가(토큰당 USD, 공개 단가 스냅샷 2026-08).
#   ★ 왜 추가하는가(2026-08-29 사고): PRICING 에 **텍스트 모델이 한 줄도 없었다.**
#     이미지·영상만 기록되고 Fact Sheet·대본·지시서·채점 호출은 원장에 남지 않았다.
#     그래서 운영자가 "어제 1.7만원을 뭐에 썼냐"고 물었을 때 코드가 답하지 못하고
#     내가 추정으로만 말했다. 비용 원장의 존재 이유가 바로 그 질문에 답하는 것인데.
#   ★ 스냅샷이다 — 공급자가 단가를 바꾸면 여기를 고친다. 원장에는 기록 시점 단가가 남는다.
TEXT_PRICING: dict[str, dict[str, float]] = {
    "gemini-2.5-pro":   {"text_input_per_token": 1.25 / 1e6, "text_output_per_token": 10.00 / 1e6},
    "gemini-2.5-flash": {"text_input_per_token": 0.30 / 1e6, "text_output_per_token": 2.50 / 1e6},
    "gemini-3-pro":     {"text_input_per_token": 1.25 / 1e6, "text_output_per_token": 10.00 / 1e6},
    # ★★ Gemini 3.x (2026-09-20 ai.google.dev/gemini-api/docs/pricing 확인).
    #   ★ **정가를 적는다.** 3.8-flash 는 2026-12-31 까지 $0.75/$3.75 프로모가인데, 그 값을
    #     넣으면 내년 1월 1일부터 원장이 실제 지출의 절반을 적는다. DeepSeek 항목과 같은
    #     규율이다 — 지출을 작게 보이게 하는 것이 이 표에서 가장 위험한 실수다.
    #   ★ 3.8-flash 는 이름이 flash 지만 단가가 pro 급이다. 출력 $7.50 으로 **2.5-pro($10)보다
    #     싸다** — 지시서는 출력이 비용의 80% 라(실측: 입력 28,433 · 출력 14,160) 이 한 칸이
    #     편당 비용을 정한다.
    #   ★ 3.1-pro 는 `-preview` 뿐이다. 매일 도는 파이프라인의 기본값으로 쓰지 않는다 —
    #     예고 없이 바뀌거나 사라지는 자리다. 재보기용으로만 표에 둔다.
    "gemini-3.8-flash":      {"text_input_per_token": 1.50 / 1e6, "text_output_per_token": 7.50 / 1e6},
    "gemini-3.5-flash":      {"text_input_per_token": 1.50 / 1e6, "text_output_per_token": 9.00 / 1e6},
    "gemini-3.1-pro-preview": {"text_input_per_token": 2.00 / 1e6, "text_output_per_token": 12.00 / 1e6},
    # ★ Jev(TypeSafe System One) — 판단 전용. **출력은 과금되지 않는다**(문장을 안 만든다).
    #   0 을 적는 것은 "모르는 값"이 아니라 **확인한 값**이다 — 단가표에 아예 없으면
    #   원장이 호출을 0원으로 적고, 그건 "안 불렀다"와 구별되지 않는다.
    "jev-latest":       {"text_input_per_token": 0.042 / 1e6, "text_output_per_token": 0.0},
    "jev-1.13.0":       {"text_input_per_token": 0.042 / 1e6, "text_output_per_token": 0.0},
    "claude-opus-4-8":  {"text_input_per_token": 15.00 / 1e6, "text_output_per_token": 75.00 / 1e6},
    "claude-sonnet-4-6": {"text_input_per_token": 3.00 / 1e6, "text_output_per_token": 15.00 / 1e6},
    # ★ DeepSeek 은 **시간대별로 단가가 다르다**(UTC 01–04·06–10 평일이 peak, off-peak 는 절반).
    #   원장에는 **비싼 쪽(peak)**을 적는다 — 지출을 실제보다 작게 보이게 하는 것이 이 표에서
    #   가장 위험한 실수다(2026-08-29 사고의 본질이 "원장이 작게 보였다"였다).
    #   cache hit 단가는 훨씬 싸지만($0.006/$0.044) 지금은 miss 기준으로 보수적으로 잡는다.
    #   출처: api-docs.deepseek.com/quick_start/pricing (2026-09-19 확인).
    "deepseek-flash":   {"text_input_per_token": 0.30 / 1e6, "text_output_per_token": 1.20 / 1e6},
    "deepseek-v4-pro":  {"text_input_per_token": 1.32 / 1e6, "text_output_per_token": 3.96 / 1e6},
}

PRICING: dict[str, dict[str, float]] = {
    "gemini-2.5-flash-image":        {"image_standard": 0.039, "image_batch": 0.0195},
    # ★ 2026-08-28 공식 확인(ai.google.dev/gemini-api/docs/pricing). 2.5-flash-image 는 공식
    #   문서가 "legacy pioneer" 로 표기하고 전환을 권고한다. 3D 도해처럼 정밀한 그림에서 차이가 크다.
    #   ★ 단가는 **해상도별**이다. 우리는 1K/2K 를 전제한다(운영자 결정: "화질 비율은 낮아도 된다").
    #     ⚠ 다만 **요청이 해상도를 명시하지 않는다** — `_image_request_body` 는 aspectRatio 만
    #       싣고 크기는 API 기본값에 맡긴다. 그래서 아래 단가는 "기본값이 1K/2K" 라는 가정 위에
    #       서 있다. 라이브 키로 첫 렌더를 돌린 뒤 `generation_attempts` 의 실제 과금과 대조해
    #       다르면 이 표를 고친다(4K 로 나오면 pro 가 $0.134 → $0.24 라 캡을 넘길 수 있다).
    #     4K 를 쓰면 pro 가 $0.134 → $0.24 로 뛴다. 해상도를 올릴 땐 이 표도 함께 고쳐야 한다.
    #     gemini-3.1-flash-image: 0.5K $0.045 / 1K $0.067 / 2K $0.101 / 4K $0.151
    #     gemini-3-pro-image:     1K·2K $0.134 / 4K $0.24
    #   image_batch 는 Batch API 50% 할인 가정(현재 렌더 경로는 실시간이라 미사용).
    "gemini-3.1-flash-image":        {"image_standard": 0.067, "image_batch": 0.0335},
    "gemini-3-pro-image":            {"image_standard": 0.134, "image_batch": 0.067},
    "veo-3.1-lite-generate-preview": {"video_720p_per_sec": 0.05},
    "veo-3.1-fast-generate-preview": {"video_720p_per_sec": 0.10},   # ⚠️ 착수 시 공식 확정
    "veo-3.1-generate-preview":      {"video_720p_per_sec": 0.40},
    "edge-tts":                      {"tts_per_char": 0.0},          # 무료 등급
}

# 비용 가드(명세 §7-3). 편당(언어 1개 잡) 에셋 생성 비용 상한(USD), 컷별 재시도.
# ★ 작업 B 이중 캡(아래) 도입 후 영상 최대비가 $0.80→$0.40 로 줄어 이 캡은 이제 좀처럼 안 걸리는
# 백스톱이다(스틸 10장 $0.39 + 영상 캡 $0.40 ≈ $0.79 < $1.2). 값 자체는 유지(다른 실패 모드 대비).
RENDER_BUDGET_CAP_USD: float = float(os.getenv("RENDER_BUDGET_CAP_USD", "1.2") or "1.2")
# 실사형 전용 캡 — 컷 수·클립 비중이 달라 기본 캡으로는 렌더가 도중에 죽는다(render_budget_cap 주석).
# ★ 3.0 → 4.0 (2026-08-28). MECHANISM 컷을 gemini-3-pro-image(1K/2K $0.134/장)로 올렸다.
#   산식: 영상 48초 × $0.05 = $2.40 + 새 스틸 ~6장(도해 4장 $0.54 · 실사 2장 $0.08) ≈ $3.02.
#   캡은 **하드 스톱**이라 빠듯하게 잡으면 렌더 도중에 죽고 이미 쓴 돈은 못 돌려받는다.
#   반대로 너무 헐겁게 잡으면 가드 구실을 못 한다 — 예상비의 약 1.3배로 둔다.
#
# ★★ 4.0 → 8.0 (2026-08-31, 시퀀스 등급제 v2 / 코덱스 리뷰 P0-4).
#   등급제의 품질 우선 구성은 캡을 그대로 두면 **정상 편이 렌더 도중 죽는다**:
#     invest 4컷 × 8초 × 후보 2 = 64초 · standard/economy 8컷 × 4초 = 32초
#     → 영상 96초 × $0.05 = $4.80 + 스틸 ~12장 ≈ $0.5~1.2  ⇒ 편당 ~$5.3–6.0
#   `render_budget_cap` 은 **하드 스톱**이라(render.py 가 RuntimeError 를 던진다) 넘는
#   순간 이미 쓴 돈은 못 돌려받고 영상도 없다 — 리뷰가 "조용한 강등보다 나쁜 실패"라고
#   지적한 그것이다. 예상비의 약 1.3배 관례를 유지해 8.0 으로 올린다.
#   ★ 이 캡은 최후 안전선이고, **정상 차단은 발주 전**에 일어난다:
#     cost_plan 이 등급 기준으로 총액을 계산 → `video_budget_exceeded` → ⑤ 승인에서 멈춤.
PHOTO_COST_CAP_USD: float = float(os.getenv("PHOTO_COST_CAP_USD", "8.0") or "8.0")
# 버전별 I2V 클립 개수 상한. 기본(모드별 표)은 최대 4개인데, 실사형은 "움직이는 화면"이
# 문법이라 그 상한이 곧 버전의 정체성을 깎는다. 벤치마크 채널은 사실상 전 컷이 영상이다.
VIDEO_CLIPS_MAX_BY_VERSION: dict[str, int] = {"photo": 8}
# ★ 버전별 클립 **길이** 상한(2026-08-20). 기본 4초는 나레이션보다 짧아 남는 시간을 마지막
#   프레임으로 얼려 때운다 — 실측 시험작에서 5.76초 컷에 4초 클립이라 1.76초가 정지였고,
#   운영자가 바로 그 구간을 지적했다("영상이 3초만 나오고 2초는 가만히 있다").
#   길이 보정 모듈(engine/clip_fit.py)이 아직 미구현이라 핑퐁 루프도 못 쓴다 — 그래서
#   **클립을 나레이션 길이에 맞춰 사는 것**이 지금 할 수 있는 정직한 해법이다.
VIDEO_CLIP_TIER_MAX_BY_VERSION: dict[str, int] = {"photo": 8}
# 그만큼 총 영상 초수도 늘려야 티어가 실제로 올라간다(preflight 이 다시 자르지 않게).
#
# ★★ 48 → 110 (2026-08-31, 시퀀스 등급제 v2). **내가 만든 게이트가 스스로를 막고 있었다.**
#
#   실측: 지금 엔진으로 지시서를 재생성했더니 등급제가 영상 **70초**를 만들었는데
#   예산은 48초 그대로라 `video_budget_exceeded`·`video_cost_exceeded` 로 **승인이
#   차단됐다.** 하드캡(PHOTO_COST_CAP_USD)은 4→8 로 올렸으면서 **승인 예산은 안 올린**
#   것이다 — 품질 구성을 켜 놓고 그 구성을 통과 못 하게 만든 셈이다.
#
#   ★ 모든 것을 막는 게이트는 **없는 게이트와 같다.** 운영자가 매번 강제 승인을
#     누르기 시작하면 그 뒤로는 진짜 초과도 안 보인다(이 저장소가 반복해서 경계하는
#     실패 — "옳게 한 것을 벌하는 게이트는 무시당한다").
#
#   새 값의 근거(품질 우선 구성, 12컷 기준 — 기획서 §8 과 같은 셈):
#     invest 4컷 × 8초 × 후보 2 = 64초
#     standard/economy 8컷 × 4초 = 32초
#     ────────────────────────────── 96초  + 여유 → **110초** ($5.50)
#   렌더 하드캡 $8.0 안에 스틸 몫(~$1.2)이 남는다. 즉 세 숫자가 한 구성에서 나온다:
#     승인 예산 $5.50  <  예상 총액 ~$6.0  <  하드캡 $8.0
VIDEO_SEC_MAX_BY_VERSION: dict[str, int] = {"photo": _get_int("PHOTO_VIDEO_SEC_MAX", 110)}


def clip_tier_max(version_type: str = "") -> int:
    """이 버전의 클립 길이 상한(초). 지정이 없으면 기존 전역 상한.

    ★ 등급제(`SEQUENCE_TIER_VERSIONS`) 버전에서는 이것이 **상한**이고, 실제 길이는
      컷의 등급이 정한다(`tier_profile`). 등급제 밖 버전은 종전 그대로다.
    """
    return VIDEO_CLIP_TIER_MAX_BY_VERSION.get(version_type, VEO_CLIP_MAX_TIER_SEC)


# ─────────────────────────────────────────────────────────────
# 시퀀스 등급제 v2 (기획서 `docs/기획서_시퀀스등급제_v2.md`)
#
# ★★ 왜 "등급 = 길이"가 아닌가 (코덱스 리뷰 §7):
#   같은 8초라도 [고정 카메라·피사체 1개·미세 움직임]과 [wide reveal → lateral follow
#   → rapid push-in]은 완전히 다른 영상이다. 길이는 **품질을 만들 수 있는 시간 예산**일
#   뿐이고, 품질은 그 시간을 어떻게 쓰느냐에서 나온다.
#   그래서 등급은 clip_sec 하나가 아니라 **Quality Profile** 이다 —
#   시간축 비트 수·카메라 플랜·상태 변화·후보 개수까지가 등급의 내용이다.
#
# ★ 벤치마크 실측 근거: docs/benchmark-realistic-shorts-2026-08-19.md
#   "8초를 뽑아 좋은 3초만 쓴다. 한 컷에 2~3샷을 넣는 멀티샷. 8초에 비트 2개,
#    횡이동 + 마지막 급속 푸시인."
# ─────────────────────────────────────────────────────────────
SEQUENCE_TIERS: tuple[str, ...] = ("invest", "standard", "economy")
DEFAULT_SEQUENCE_TIER: str = "economy"

TIER_PROFILE: dict[str, dict[str, Any]] = {
    # 기전을 실제로 설명하는 컷 — 시간과 연출을 함께 준다.
    "invest": {
        "clip_sec": 8,
        "min_beats": 2, "max_beats": 3,
        "camera_plan": "required",
        "state_change": "required",
        # ★ 2 → 1 (2026-09-13 운영자 지시 "후보 1발로 내려"). 2발은 그 컷의 영상비가 두 배인데,
        #   지금까지 렌더가 전부 standard 라 **2발이 한 번도 실행된 적이 없다** — 더 낫다는
        #   증거가 없는 기능에 두 배를 내지 않는다(이 저장소의 "재기 전엔 올리지 않는다" 규율).
        #   실측 비교(같은 컷 1발 vs 2발)를 한 뒤 INVEST_CANDIDATES=2 로 되돌릴 수 있다.
        "candidates": _get_int("INVEST_CANDIDATES", 1),
    },
    # 결과·현장 앵커 — 움직이되 연출 계약까지 요구하지 않는다.
    "standard": {
        "clip_sec": 4,
        "min_beats": 1, "max_beats": 2,
        "camera_plan": "optional",
        "state_change": "optional",
        "candidates": 1,
    },
    # 훅·브릿지·CTA — 단순 모션.
    "economy": {
        "clip_sec": 4,
        "min_beats": 0, "max_beats": 1,
        "camera_plan": "none",
        "state_change": "none",
        "candidates": 1,
    },
}
# ★ v2 는 전 등급 Lite 다. Fast($0.10/s)는 PRICING 주석이 "착수 시 공식 확정"으로
#   남겨 둔 미확정 단가이고, 길이·연출·후보의 효과를 먼저 재야 한다(Phase G2·G4).
#   확정되면 이 표의 invest 값만 교체하면 켜진다 — 다른 코드는 손대지 않는다.
TIER_VIDEO_MODEL: dict[str, str] = {t: VEO_MODEL for t in SEQUENCE_TIERS}

# 등급제를 적용하는 버전. 나머지(만화식·설명판형)는 **종전 경로 그대로**다(하위호환).
SEQUENCE_TIER_VERSIONS: tuple[str, ...] = tuple(
    x.strip() for x in os.getenv("SEQUENCE_TIER_VERSIONS", "photo").split(",") if x.strip())
# video-first: 정적으로 느껴지는 컷을 없앤다("전부 video 플래그"가 아니다 — 리뷰 §10).
#   Phase F 에서 채운다. Phase E(연쇄 경계) 없이 켜면 테스트가 막는다.
VIDEO_FIRST_VERSIONS: tuple[str, ...] = tuple(
    x.strip() for x in os.getenv("VIDEO_FIRST_VERSIONS", "").split(",") if x.strip())
# I2V 연쇄에서 **생성물을 다시 anchor 로 쓰는** 깊이 상한. 초과하면 원본으로 rebase 한다.
#   ★ 8초 클립이 길어질수록 identity·geometry 드리프트가 누적된다(리뷰 §11 문제 2).
MAX_CHAIN_DEPTH: int = _get_int("MAX_CHAIN_DEPTH", 2)


def tier_profile(tier: str) -> dict[str, Any]:
    """등급 → Quality Profile. 모르는 등급은 기본(economy)."""
    return TIER_PROFILE.get(str(tier or ""), TIER_PROFILE[DEFAULT_SEQUENCE_TIER])


def video_model_for_tier(tier: str) -> str:
    """등급 → 영상 모델. 표에 없으면 전역 기본."""
    return TIER_VIDEO_MODEL.get(str(tier or ""), VEO_MODEL)


# 연출 계약(Phase E2) — 비트 상한과 **닫힌 어휘의 산문화**.
#   ★ 산문은 여기 표에서만 나온다. provider 가 즉석에서 문장을 지어내면 규격 토큰이
#     화면에 글자로 박히는 사고(Phase 0 §3-3 "35°")가 되돌아온다.
TEMPORAL_MAX_BEATS: int = _get_int("TEMPORAL_MAX_BEATS", 3)
CAMERA_PROSE: dict[str, str] = {
    "ORBIT": "the camera orbits around the subject",
    "DOLLY_IN": "the camera pushes in rapidly",
    "DOLLY_OUT": "the camera pulls back to reveal the whole structure",
    "TRACK": "the camera moves laterally alongside",
    "TOP_DOWN": "the camera looks straight down",
    "SECTION_DIVE": "the camera dives through the cutaway",
    "FOLLOW_OBJECT": "the camera follows the moving part",
    "HOLD": "the camera holds steady",
}
MUTATION_PROSE: dict[str, str] = {
    "APPEAR": "comes into view", "DISAPPEAR": "leaves the frame",
    "MOVE": "travels across", "GROW": "grows larger", "SHRINK": "shrinks",
    "ROTATE": "rotates", "TRANSFORM": "changes form",
    "SPLIT_OFF": "splits apart", "MERGE_INTO": "merges together",
    "HIGHLIGHT": "stands out from the rest", "DIM": "fades back",
    "REVERSE_TRACE": "traces backwards", "IMPACT": "strikes the surface",
}

# ★ [행동이 앞, 카메라는 한 벌] 2026-09-14 조사(핸드오프 §3-4): 발주 문장에서
#   ① 코드 비트와 모델 motion_prompt 가 카메라를 두 번, 서로 반대로 지시했고(251컷 중 방향 반대 17·
#   빠르게 vs 천천히 106) ② 비트는 entity_id + 일반 동사("the person working changes form")라
#   stage 의 result_state(실제 행동)가 실리지 않았다. 켜면 비트마다 **행동 문장을 먼저** 싣고
#   motion_prompt 에서는 카메라 구절을 뺀다.
#   ★ 2026-09-14 운영자 결정으로 **기본 on**. A/B 1쌍($0.40)에서 행동이 장면 안에서 보였고, 그때 나온
#   아이콘 배지 원인(뜻풀이 구절)은 저장 지시서 251컷 오프라인 스윕으로 부류째 막았다.
#   클립 캐시 키에는 최종 발주 문장이 없어(assemble.clip_content_hash) 이미 만든 클립은 그대로 재사용된다.
#   되돌리기: 환경변수 VEO_BEAT_ACTION_PROSE=0.
VEO_BEAT_ACTION_PROSE: bool = _get_bool("VEO_BEAT_ACTION_PROSE", True)
# motion_prompt 에서 카메라 구절로 보고 빼는 어휘.
MOTION_CAMERA_CLAUSE_PATTERN: str = (
    r"\b(?:camera|dolly|pans?|panning|zoom(?:s|ing)?|orbit(?:s|ing)?|tracks?|tracking|"
    r"push(?:es)?[- ]in|pull(?:s)?\s+back|close-up|wide\s+shot|tilt(?:s)?|crane)\b")


# 후보 선택(Phase E3) — 신호 추출 파라미터와 점수 가중치.
#   ★ 매직넘버 금지 규약대로 전부 여기 둔다. 튜닝은 Phase G4 실측 뒤에 한다.
CANDIDATE_FREEZE_NOISE: str = os.getenv("CANDIDATE_FREEZE_NOISE", "-55dB")
CANDIDATE_FREEZE_MIN_SEC: float = float(os.getenv("CANDIDATE_FREEZE_MIN_SEC", "0.5") or "0.5")
CANDIDATE_SCENE_THRESHOLD: float = float(os.getenv("CANDIDATE_SCENE_THRESHOLD", "8") or "8")
#
# ★★★ 2026-08-31 **실측 4클립으로 재교정**(docs/실측_품질/교정_2026-08-31.md).
#   종전 가중치(정지 0.7 · 전환 0.3)는 **가정 위에 서 있었고 실측이 그 가정을 깼다.**
#
#   실측표(Veo I2V · 10초 · 프레임 239개):
#     클립            정지    전환   평균움직임  중앙움직임
#     G2 계약없음     0.00     0     0.0058    0.0011
#     G2 연출계약     0.00     1     0.0100    0.0017
#     G4 take1       0.00     2     0.0081    0.0037
#     G4 take2       0.00     1     0.0081    0.0019
#
#   드러난 것 셋:
#   ① **정지 비율이 4개 전부 0.00 이다.** 점수의 70% 를 차지하던 항이 **한 번도
#      갈리지 않았다.** 실제로 점수를 가른 것은 전환 수(30% 항) 하나뿐이었다 —
#      G4 에서 "옳은 답을 우연히 맞혔다"의 정체가 이것이다.
#      → 정지는 **가드로 남기되 지배 항에서 내린다.** Manim·홀드 경로에서는 여전히
#        실재하는 실패라 0 으로 만들지는 않는다.
#   ② **전환 수를 상으로 주면 안 된다.** 하드컷(>0.4)은 4개 전부 0 이었고, 세어진
#      "전환"은 8% 이상 소프트 변화다. 그런데 **좋은 invest 클립은 컷이 아니라
#      카메라가 움직이는 한 테이크**다 — 컷에 점수를 주면 우리가 실제로 관측한
#      **세계 이탈**(다이어그램으로 튕겨 나감)에 상을 주게 된다.
#      → 전환은 **보고만 하고 점수에서 뺀다.**
#   ③ **중앙 움직임이 실제로 갈랐다.** G4 는 평균이 둘 다 0.0081 로 같은데 중앙값이
#      0.0037 vs 0.0019 다 — take2 는 대부분 정지하다 몇 번 크게 튀고, take1 은
#      **계속 움직인다.** 눈으로 본 판정(take1 이 낫다)과 일치한다.
#      평균은 스파이크에 속고 중앙값은 안 속는다.
#      → **중앙 움직임을 주 지표로 삼는다.**
#
#   목표값은 관측 최고치를 1.0 으로 둔다. 표본이 작아 정밀한 값이 아니라
#   **관측 범위를 재현하는 값**이다 — 더 좋은 클립이 나오면 올린다.
#
# ★★ **올렸다: 0.0037 → 0.0117** (2026-09-04). 위 문장이 예고한 그 상황이다 —
#   운영자가 실제로 발행된 벤치마크 영상을 줬고(신비한 건축사전 시화호 편, 105초),
#   같은 자로 재니 우리 관측 최고치의 3배였다:
#       벤치 샘플1 0.0078 · 샘플2 0.0134 · 샘플3 0.0150 → 중앙값 0.0117
#       우리 첫 실사형 렌더 13컷: 0.0005~0.0028, 중앙값 0.0012 (**1/9.5**)
#   종전 0.0037 은 우리 클립 중 가장 잘 움직인 것을 만점으로 놓은 값이라,
#   "발행된 영상만큼 움직이는가"를 물을 수 없었다.
#
# ★ 올리는 방향은 **랭킹을 뒤집지 않는다** — 이 값은 나눗셈 정규화라 단조 변환이고,
#   순위가 바뀌는 경우는 오직 min(1.0, ...) 에서 잘릴 때뿐이다. 즉 올리면
#   **포화가 풀려 변별이 살아날 뿐** 잘못 고를 위험은 없다.
# ★ 정직하게 — 벤치는 화면녹화라 자막·숫자 오버레이 애니메이션이 화면 중앙 크롭(72%)에
#   일부 섞인다. 참값은 0.0117 **이하**일 수 있다. 그래도 위 이유로 상향은 안전하고,
#   원본 영상을 다시 받으면 오버레이를 뺀 값으로 다시 잰다.
#   근거: docs/벤치마크_시화호_구조분석_2026-09-04.md 4절
CANDIDATE_MOTION_MEDIAN_TARGET: float = float(
    os.getenv("CANDIDATE_MOTION_MEDIAN_TARGET", "0.0117") or "0.0117")

# 렌더 뒤 "이 영상은 거의 정지해 있다"를 잡는 문턱. 벤치 중앙값의 **1/3**이다.
# ★ 왜 이제야 생겼나: 문턱을 정하려면 "좋은 영상은 얼마인가"의 표본이 있어야 하는데
#   2026-09-04 전에는 우리가 만든 클립밖에 없었다(전부 나쁜 표본). 벤치가 그 기준선이다.
# ★ 왜 1/3 인가: 벤치와 같기를 요구하면 생성 클립이 거의 전부 걸려 경고가 소음이 된다.
#   1/3(0.0039)은 종전 만점 기준(0.0037)과 거의 같다 — 즉 "예전 기준으로 만점이던
#   수준에도 못 미치면 경고"다. 우리 첫 렌더 13컷은 전부 여기 걸린다(최고 0.0028).
# ★ 차단이 아니라 경고다(RENDER_QA_* 규율): 움직임은 취향이 섞이고, 정지가 옳은 컷도
#   있다(마지막 여운). 차단하면 운영자가 게이트 전체를 불신한다.
# ★★ 0.0039 → 0.0003 (2026-09-14 운영자 판정으로 재교정).
#   위 0.0039 는 **실사 화면녹화 벤치**의 1/3 이었다. 그런데 우리 화풍(무광 CG, 평평한 질감)은
#   같은 카메라 움직임에도 프레임 간 변화가 훨씬 적게 잡힌다 — 그래서 모든 렌더가 "거의 정지"
#   경고를 달았고, 경고가 소음이 됐다(실측: 비트를 채우든 문구를 바꾸든 0.0008~0.0011).
#   운영자가 같은 그림·같은 비트의 A/B 클립 둘(0.00113·0.00093)을 보고 "둘 다 괜찮다,
#   카메라 움직임은 같다"고 판정했다 → **이 화풍의 좋은 표본**이 생겼다.
#   같은 논리(좋은 영상의 1/3)를 우리 표본에 적용한다: 0.001 / 3 ≈ 0.0003.
#   진짜 멈춘 화면은 여전히 잡힌다 — 스틸을 8초 늘린 영상이 0.00001 로 이 문턱의 1/30 이다.
#   ★ CANDIDATE_MOTION_MEDIAN_TARGET(0.0117)은 **건드리지 않는다** — 그건 후보 순위를 매기는
#     정규화 기준이라 값을 바꿔도 순위가 안 뒤집히고, 벤치와의 거리를 보는 눈금으로 남겨 둔다.
CLIP_MOTION_MEDIAN_FLOOR: float = _get_float("CLIP_MOTION_MEDIAN_FLOOR", 0.0003)
# 이 비율 넘게 바닥 미달이면 영상 전체 문제로 본다(컷 하나면 연출 선택일 수 있다).
CLIP_MOTION_LOW_SHARE_WARN: float = _get_float("CLIP_MOTION_LOW_SHARE_WARN", 0.5)

# 실사형 대본이 **원리를 설명하는 컷**을 몇 개 가져야 하는가(evidence_role='mechanism').
#
# ★★ **고정값이 아니라 길이에서 파생한다**(운영자 지시 2026-09-04: "영상 길이나 원래
#   소스 내용에 따라서 길이조절이 들어갈 거니까 기전은 유동적으로 조절되도록").
#   맞는 지적이다 — 40초 영상과 100초 영상에 같은 수를 요구하면, 짧은 쪽은 기전으로
#   꽉 차 훅·결과가 밀리고 긴 쪽은 결과 나열로 되돌아간다.
#
# ★ 간격의 근거는 실측이다: 발행 벤치마크(시화호 편)가 **105초에 기전 3회**였다 —
#   원인(방조제가 물길을 끊었다) · 재정의(오염이 아니라 호수 자체) · 해법(구멍+터빈).
#   105 / 3 = 35초당 1회. 그 간격을 그대로 쓴다.
#       40초 → 1개   60초 → 2개   80초 → 2개   105초 → 3개(벤치와 일치)
# ★ 하한 1: 어떤 길이든 원리가 0개면 그건 설명 영상이 아니라 소식이다.
# ★ 상한 4: 더 요구하면 기전이 얇은 소스에서 **지어내게 된다**. 원문에 없는 인과를
#   만드는 것은 이 저장소의 제1 불변식(환각 방지) 위반이다.
# 어떤 종류의 주장이 "왜 그런지"를 지불하는가. 이것이 없는 논문에는 기전 컷을 요구하지 않는다.
# ★ author_interpretation 을 넣는 이유: 논문이 기전을 증명하지 않아도 "연구진은 …로 봅니다"로
#   화면에 정직하게 나갈 수 있다. 그것도 없으면 원리 설명형으로 만들 수 없는 소재다.
MECHANISM_CLAIM_KINDS: tuple[str, ...] = ("mechanism", "author_interpretation")

PHOTO_MECHANISM_SEC_PER_CUT: int = _get_int("PHOTO_MECHANISM_SEC_PER_CUT", 35)
PHOTO_MIN_MECHANISM_CUTS_FLOOR: int = _get_int("PHOTO_MIN_MECHANISM_CUTS_FLOOR", 1)
PHOTO_MIN_MECHANISM_CUTS_CAP: int = _get_int("PHOTO_MIN_MECHANISM_CUTS_CAP", 4)

# 실사형에서 **1분당 새 세계 몇 개**까지 허용하는가.
#
# ★ 이름을 world_reset_rate 로 하지 않는다 — visual_sequence_contract 에 **같은 이름의 다른
#   지표**가 이미 있다(new_worlds / stage 수). 두 곳이 같은 이름으로 다른 숫자를 말하면
#   이 저장소가 반복해 겪은 이중 정의 사고가 된다. 여기는 **분당 고유 세계 수**다.
#
# ★★ 이 문턱은 **알려진 좋은 것과 나쁜 것을 실제로 가른다**(2026-09-04 실측 18건):
#     발행 벤치마크(시화호)        1세계 / 105초 = 0.57/분
#     달 충돌 지시서 4종(좋았던 것) 1세계 / 48~70초 = 0.86~1.25/분   ← 전부 통과
#     성격조합 v2~v6(화면이 나빴던 것) 4~6세계 / 49~71초 = 3.38~6.12/분 ← 전부 걸림
#   문턱 2.0 에서 히트율 50%(9/18) — 소음이 아니라 신호다.
#   다른 문턱들과 달리 이건 100% 가 아니어서, 처음부터 판별력이 있다.
# ★ 그래도 경고다: 물리적 장소가 없는 주제(순수 상관 연구)는 세계가 여럿일 수 있다.
PHOTO_MAX_WORLDS_PER_MIN: float = _get_float("PHOTO_MAX_WORLDS_PER_MIN", 2.0)

# 축척 사다리 — 시퀀스가 둘 이상이면 그중 최소 하나는 근접 시점이어야 한다.
# ★ 근거: 벤치는 광역에서 손바닥까지 **3초 만에** 내려온다(22.5s 손이 물을 뜬다 →
#   24.0s 유리병 → 25.5s 계기판). 크기 대비가 "이게 진짜 있는 일"을 만든다.
# ★ 실측 히트율 94%(17/18 지시서에 close_detail 이 하나도 없다) — 그래서 경고다.
#   시퀀스가 하나뿐인 영상은 검사하지 않는다(세계가 하나면 camera_base 도 하나다).
PHOTO_SCALE_LADDER_MIN_SEQUENCES: int = _get_int("PHOTO_SCALE_LADDER_MIN_SEQUENCES", 2)
PHOTO_CLOSE_CAMERA_BASE: str = "close_detail"
CANDIDATE_W_MOTION: float = 0.8      # 중앙 움직임(지속적으로 움직이는가)
CANDIDATE_W_FREEZE: float = 0.2      # 정지 가드(실측에선 안 갈렸지만 다른 경로에선 실재)
# 이보다 작은 점수차는 **차이 없음**으로 읽는다. 표본이 작을 때 미세한 차이를 효과로
#   부르면 인상평과 다를 바 없다(리뷰 §16 이 경계한 것).
#
# ★★ **0.05 → 0.0158 로 재교정했다**(2026-09-04). 이 값 자체의 판단이 바뀐 게 아니라
#   **점수의 단위가 바뀌었다**. CANDIDATE_MOTION_MEDIAN_TARGET 을 0.0037 → 0.0117 로
#   올리자 motion 항이 0.316배로 압축돼, 같은 클립 쌍의 격차가 같이 줄었다:
#       G2 쌍(눈으로 확인된 차이)  0.1297 → 0.0410   ← 0.05 문턱 **아래로 떨어졌다**
#       G4 쌍(눈으로 확인된 차이)  0.3892 → 0.1231
#   즉 문턱을 그대로 두면 **전에는 "차이 있음"이던 쌍이 갑자기 "차이 없음"**이 된다.
#   그건 새로 알게 된 사실이 아니라 자를 바꿔 놓고 눈금을 안 옮긴 것이다.
# ★ 그래서 같은 배수(0.316)로 옮겨 **종전 판정을 그대로 보존한다** — 0.05 × 0.316 = 0.0158.
#   이 변경으로 어떤 쌍의 판정도 달라지지 않는다(그것이 목적이다).
# ★ 남는 사실 하나: 이 두 상수는 **서로 묶여 있다.** 한쪽만 고치면 판정이 조용히 바뀐다.
#   tests/test_clip_candidates.py 의 실측 격차 검사가 그 커플링을 지킨다.
CANDIDATE_MEANINGFUL_GAP: float = _get_float("CANDIDATE_MEANINGFUL_GAP", 0.0158)

# 텍스트 번인(화면에 박힌 글자) 프록시 — **기록 전용, 문턱 없음**.
#   왜: 2026-08-31 G4 실측에서 take2 를 망친 가장 큰 요인이 지어낸 글자 범벅
#   (AGENT ZERO·LOYAL DEPLOY)이었는데 **지표에 없었다**. 중앙 움직임이 우연히 같은
#   방향을 가리켜 옳은 후보를 골랐을 뿐이다(교정_2026-08-31.md).
#   방법: 시간 평균(tmix)으로 움직이는 화면을 뭉갠 뒤 남는 **정지 고주파**를 잰다 —
#   카메라가 움직이면 배경은 흐려지고 고정 오버레이(글자·도표선)만 선명하게 남는다.
#   ★ 정규화 상수를 두지 않는다. 원시 값(0~255)을 그대로 남기고 문턱은 표본으로
#     정한다 — 지금 문턱을 지어내면 그것이 곧 "실측 없는 매직넘버"다.
CANDIDATE_TEXT_TMIX_FPS: int = int(os.getenv("CANDIDATE_TEXT_TMIX_FPS", "4") or "4")
# 8초 invest 클립에서 2초 창(4fps × 8프레임)이면 카메라 이동은 뭉개지고 고정물은 남는다.
CANDIDATE_TEXT_TMIX_FRAMES: int = int(
    os.getenv("CANDIDATE_TEXT_TMIX_FRAMES", "8") or "8")

# 저장소 용량 경고 — 2026-08-24 사고 재발 방지.
#   그날 Supabase Storage 가 무료 한도 1GB 를 넘겨(1.53GB) **조직 전체가 402 로 정지**했고
#   같은 조직의 다른 프로젝트까지 멈췄다(engine/storage_gc.py 첫 주석).
#   storage_gc 가 "쌓이면 지운다"를 맡았지만, **한도에 다가가는 것을 알려 주는 장치**는
#   아직 없었다(작업계획서_시각엔진_v3 Phase S 가 지정한 잔여 작업).
#   ★ 두 값 다 지어낸 숫자가 아니다: 1GB 는 실제로 걸렸던 한도이고, 80% 는 Phase S 가
#     명시한 값이다. 유료 요금제로 올리면 STORAGE_LIMIT_BYTES 를 환경에서 덮어쓴다.
STORAGE_LIMIT_BYTES: int = int(
    os.getenv("STORAGE_LIMIT_BYTES", str(1024 ** 3)) or str(1024 ** 3))
STORAGE_WARN_RATIO: float = float(os.getenv("STORAGE_WARN_RATIO", "0.8") or "0.8")


# ── 판단 전용 모델 Jev (TypeSafe AI System One) — 2026-09-22 ────────────
#
# 무엇에 쓰나: **생성이 아니라 게이트의 애매한 판정**이다. 이 저장소의 게이트는 대부분
#   정규식인데, 정규식으로는 못 가르는 자리가 실측으로 두 번 드러났다:
#     ① "따옴표가 라벨 요구인가, 겁따옴표인가" — 159건에 대고 규칙을 세워 봤지만
#        `bars for 'NASDAQ'`(라벨)과 `the 'cost' of`(겁따옴표)가 같은 형태라 못 갈랐다.
#     ② "이 컷이 연결 컷인가" — 라우터 판정과 어긋나 기각했다.
#   둘 다 "이 문장이 X인가?" 라는 예·아니오 질문이고, LLM 한 번 부르기엔 과한 자리다.
#
# 실측(2026-09-22, 저장된 photo 지시서 31건):
#   · 같은 문장 3회 반복 시 흔들림(표준편차) 0.005~0.031 — 무작위가 아니다.
#   · 정규식이 차단한 31건 중 **17건이 오탐**이었고 Jev 가 갈라냈다(54% 감소).
#   · 입력 8,862 토큰 = **$0.00037**. 출력은 과금되지 않는다.
#
# ★★ **Jev 는 게이트를 풀기만 한다 — 새로 막지 않는다.** 이유는 실측이다:
#     `represents 'Calorie Restriction'` → 0.42 (라벨 아님으로 판정)
#   그 문장은 2026-09-07 에 **다섯 개가 그대로 그림에 글자로 박힌** 바로 그 문장이다.
#   Jev 에게 최종 판정을 맡기면 그 사고가 돌아온다. 그래서 명백한 라벨 동사
#   (labeled/titled/represents…)는 정규식이 **먼저 무조건 막고**, 동사가 없는 애매한
#   구간만 Jev 에게 묻는다. Jev 가 틀려도 게이트가 약해지지 않는 구조다.
#
# ★ 꺼져 있거나 키가 없으면 **네트워크 호출이 0** 이고 판정은 종전(정규식) 그대로다.
#   테스트는 기본 꺼짐으로 돈다 — 게이트 순수성을 지킨다.
JEV_ENABLED: bool = _get_bool("JEV_ENABLED", False)
JEV_BASE: str = os.getenv("JEV_BASE", "https://api.typesafe.ai/v1/systemone")
JEV_MODEL: str = os.getenv("JEV_MODEL", "jev-latest")
JEV_TIMEOUT_SEC: int = _get_int("JEV_TIMEOUT_SEC", 20)
#: 이 확률 **미만**이면 "라벨이 아니다"로 보고 차단을 푼다.
#  ★ 0.35 의 근거(위 실측 31건): 겁따옴표들이 0.04~0.15 에 몰려 있고, 사람이 봐도
#    라벨인 것들은 0.62~0.93 이다. 그 사이가 비어 있어 문턱을 어디 두든 같은 답이 나온다.
#    애매한 0.35~0.6 구간(`Kepler`·`Laser Downlink`·`Experience`)은 **차단을 유지**한다 —
#    확신이 없으면 막는 쪽이 이 저장소의 기본 자세다.
JEV_LABEL_RELEASE_BELOW: float = _get_float("JEV_LABEL_RELEASE_BELOW", 0.35)
#: 판정에 보낼 문장 길이 상한. Jev 의 컨텍스트는 32,000 토큰이라 여유가 크지만,
#  입력 토큰이 곧 비용이고 판정에 필요한 것은 따옴표 주변 문맥이다. 프롬프트 한 컷이
#  실측 400~1,500자라 넉넉하다.
JEV_STATE_MAX_CHARS: int = _get_int("JEV_STATE_MAX_CHARS", 4000)

# 연속성 멀티모달 QA (계획서 Phase 3 D2) — stage 전후 그림이 같은 세계인가.
#   ★ 기본 켜짐. 끄고 싶으면 환경에서 0 을 준다. 다만 유료 이미지 경로에서만 실제로
#     돌므로(continuity_qa.enabled) placeholder 데모 렌더는 이 값과 무관하게 호출이 없다.
#   ★ 비용: 참조 조건 stage 당 flash 1회(실측 텍스트 호출 기준 건당 ~$0.001).
#     실패 시 재생성 1회 + 재판정이라 최악의 경우 stage 당 2회다.
CONTINUITY_QA_ENABLED: bool = os.getenv("CONTINUITY_QA_ENABLED", "1") not in ("0", "false", "")
CONTINUITY_QA_MODEL: str = os.getenv("CONTINUITY_QA_MODEL", "gemini-2.5-flash")
# 판정은 한 문장 사유만 받는다 — 길게 받을 이유가 없고, 길면 잘려서 JSON 이 깨진다.
CONTINUITY_QA_MAX_TOKENS: int = int(os.getenv("CONTINUITY_QA_MAX_TOKENS", "200") or "200")
# 세계이탈 신호를 운영자에게 알리는 문턱. **점수·게이트가 아니다** — 표본이 쌓이기 전에
#   벌점으로 만들면 "충돌 → 분화구"처럼 정상적으로 크게 변하는 컷을 벌한다.
WORLD_DRIFT_NOTICE: float = 0.30


def tiering_enabled(version_type: str = "") -> bool:
    """이 버전에 등급제를 적용하는가. 아니면 종전 경로 그대로."""
    return str(version_type or "") in SEQUENCE_TIER_VERSIONS


def video_budget_for(version_type: str, mode_budget: dict) -> tuple[int, float]:
    """이 버전의 (총 영상 초수, 총 영상 금액) 예산.

    ★ 상한이 **세 겹**이다. 개수만 풀면 여기서 다시 잘린다 — 실제로 그랬다:
      개수 상한을 8개로 올렸는데도 지시서가 계속 영상 2개로 나왔고, 원인이 이 초수 예산
      (standard 모드 8초 ÷ 4초 티어 = 2개)이었다. 세 번 생성해 세 번 다 2개였다.
      ① enforce_mode_video_budget(개수) ② enforce_video_clip_cap(개수) ③ 여기(초수·금액)
    """
    sec = VIDEO_SEC_MAX_BY_VERSION.get(version_type)
    if sec is None:
        clips = VIDEO_CLIPS_MAX_BY_VERSION.get(version_type)
        if clips is None:
            return (int(mode_budget["max_video_generated_sec"]),
                    float(mode_budget["max_video_cost_usd"]))
        sec = clips * VEO_CLIP_MAX_TIER_SEC
    return int(sec), round(sec * VEO_COST_PER_SEC_USD, 4)
# ─────────────────────────────────────────────────────────────
# 저장소 자동 정리 (2026-08-24 신설 — engine/storage_gc.py)
#
# ★ 왜 생겼나: 렌더 산출물을 지우는 장치가 **아예 없었다**. ⑥ 의 "버리기"는 deleted_at 만
#   찍고 파일은 남겼고, 유튜브로 나간 편의 컷 캐시도 영원히 남았다. 편당 15~30MB 씩
#   2026-07-08 부터 쌓여 Supabase 무료 한도(1GB)를 넘겼고, **조직 전체가 정지**됐다
#   (대시보드·REST·Storage·S3 전부 402). 다른 프로젝트까지 함께 멈췄다.
#   근거·실측: docs/deviation-storage-quota-lockout.md
STORAGE_GC_ON_UPLOAD: bool = _get_bool("STORAGE_GC_ON_UPLOAD", True)
# 정기 청소(워커에서 1회 훑기). 끄면 업로드 직후 정리만 돈다.
STORAGE_GC_SWEEP: bool = _get_bool("STORAGE_GC_SWEEP", True)

#: 저장소 보관 기한 3종 (engine/storage_gc.py). 전부 "지우기 전에 얼마나 기다리나"다.
#:  · TRASH        ⑥ [버리기] 후 [복원]할 수 있어야 하는 기간
#:  · CACHE        컷 스틸/클립은 재생성 캐시다. 2주면 캐시로서 값을 잃는다.
#:  · UNPUBLISHED  한 달이 지나도록 유튜브에 안 올린 편은 접은 것으로 본다.
#:                 ★ 이 기한이 없던 탓에 7월 실험 렌더 532MB 가 6주간 남아 무료 한도의
#:                   절반을 먹었다(2026-08-28 실측). 0 으로 두면 그 시절로 되돌아간다.
STORAGE_TRASH_RETENTION_DAYS: float = _get_float("STORAGE_TRASH_RETENTION_DAYS", 7.0)
STORAGE_CACHE_RETENTION_DAYS: float = _get_float("STORAGE_CACHE_RETENTION_DAYS", 14.0)
STORAGE_UNPUBLISHED_RETENTION_DAYS: float = _get_float("STORAGE_UNPUBLISHED_RETENTION_DAYS", 30.0)

ASSET_RETRY: int = 1  # 컷별 생성 실패 시 재시도 → 실패면 플레이스홀더(전체 중단 금지)
# ★ 역할 상향 모델(3D 도해용 프리미엄)은 더 끈질기게 매달린다(2026-08-29 실측).
#   실측: gemini-3-pro-image 가 30초 안에 503 을 두 번 내자 곧바로 flash 로 폴백했고,
#   **flash 는 도해에 깨진 글자 라벨을 그렸다**("Oliporjihum", "Amigadla" — 같은 프롬프트
#   재현 확인). 같은 모델이 몇 시간 뒤에는 정상이었으므로 503 은 일시적이다.
#   폴백 자체는 남긴다(회색 placeholder 가 더 나쁘다) — 다만 그 전에 더 시도한다.
ASSET_RETRY_ROLE_MODEL: int = _get_int("ASSET_RETRY_ROLE_MODEL", 4)

# ─────────────────────────────────────────────────────────────
# 클립 길이 ↔ 나레이션 길이 보정 (수정명세 v1 §3-3). 나레이션이 타임라인의 주인이고,
# 클립은 고정 티어(4/6/8초)라 원리적으로 딱 맞지 않는다 → ratio 구간별 결정론적 전략.
#   ratio = (narration_sec - clip_sec) / narration_sec
#   ratio ≤ 0            → trim   (뒤에서 잘라내고 끝 페이드아웃)
#   0 < ratio ≤ HOLD_MAX → hold   (마지막 프레임 홀드 + 켄번스)
#   … ≤ PINGPONG_MAX     → pingpong (정방향→역방향, loop_safe=true 컷만)
#   > PINGPONG_MAX        → flagged (보정 금지 · QA 빨간 플래그 · 컷 분할 권고)
# 판정 자체는 engine/clip_fit.py(순수 함수), 타입 계약은 engine/clip_fit_types.py.
# ─────────────────────────────────────────────────────────────
CLIP_FIT_HOLD_RATIO_MAX: float = float(os.getenv("CLIP_FIT_HOLD_RATIO_MAX", "0.15") or "0.15")
CLIP_FIT_PINGPONG_RATIO_MAX: float = float(
    os.getenv("CLIP_FIT_PINGPONG_RATIO_MAX", "0.60") or "0.60")
CLIP_FIT_TRIM_FADE_SEC: float = float(os.getenv("CLIP_FIT_TRIM_FADE_SEC", "0.2") or "0.2")
# ★ 문장 끝 **숨 쉴 틈**(2026-09-03 첫 실사형 렌더 실측 — 운영자: "나레이션이 끝나자마자
#   화면이 넘어가서 뚝뚝 끊긴다"). 컷 화면 길이가 나레이션 실측과 **정확히 같아서**
#   (13컷 전부 trim, 컷1 4.368s → 4.4s) 마지막 음절이 끝나는 프레임에서 다음 컷으로 넘어갔다.
#   여기 적힌 만큼을 나레이션 뒤에 붙인다. 오디오는 assemble 이 같은 길이로 apad 한다 —
#   `-shortest` 가 짧은 쪽에서 멈추므로 영상만 늘리면 그대로 잘려 나간다(둘을 같이 늘려야 한다).
#   0 이면 종전과 바이트 단위로 같다.
CLIP_FIT_TAIL_PAD_SEC: float = float(os.getenv("CLIP_FIT_TAIL_PAD_SEC", "0.35") or "0.35")
# hold 구간이 "정지 사진"으로 보이지 않게 얹는 미세 줌 상한(1.00 → 이 값). §3-3 표의 "켄번스".
CLIP_FIT_HOLD_ZOOM_MAX: float = float(os.getenv("CLIP_FIT_HOLD_ZOOM_MAX", "1.04") or "1.04")
# pingpong 컷 비중이 이 값을 넘으면 노란 경고(지시서 컷 설계 재검토 신호, §3-6).
CLIP_FIT_PINGPONG_WARN_SHARE: float = float(
    os.getenv("CLIP_FIT_PINGPONG_WARN_SHARE", "0.5") or "0.5")
# loop_safe 미지정 컷의 기본값. 안전측(false) — 역재생이 어색한 모션을 핑퐁으로 망치지 않는다.
CLIP_FIT_LOOP_SAFE_DEFAULT: bool = _get_bool("CLIP_FIT_LOOP_SAFE_DEFAULT", False)

# ─────────────────────────────────────────────────────────────
# 작업 B: 영상 정책·이중 캡 (명세 §8). 초수만 캡하면 티어를 Fast/Standard 로 올릴 때 비용 통제가
# 안 된다 → 초수 캡 + 금액 캡을 병행한다. 이 캡은 "주제(directive)당" 이며, 지시서 생성 시점(렌더
# 이전, Preflight)에 적용해 캡을 넘는 영상 컷은 애초에 유료 API 를 호출하지 않고 스틸로 강등한다.
# ─────────────────────────────────────────────────────────────
VIDEO_MAX_GENERATED_SEC_PER_TOPIC: int = _get_int("VIDEO_MAX_GENERATED_SEC_PER_TOPIC", 8)
VIDEO_MAX_COST_USD_PER_TOPIC: float = float(
    os.getenv("VIDEO_MAX_COST_USD_PER_TOPIC", "0.40") or "0.40")
VIDEO_DEFAULT_TIER: str = os.getenv("VIDEO_DEFAULT_TIER", "lite")
# image_only(영상 금지) | image_preferred(기본, 예산 내 영상) | video_allowed(예산 내 영상 허용,
# preferred 와 동일 강제) | video_required(캡 초과라도 최우선 1개는 유지 — 사람 개입 큐가 없는
# 경량 경로라 "렌더 중단" 대신 강제 유지+경고 로그로 대체, §8.2).
MEDIA_POLICIES: tuple[str, ...] = ("image_only", "image_preferred", "video_allowed", "video_required")
DEFAULT_MEDIA_POLICY: str = os.getenv("DEFAULT_MEDIA_POLICY", "image_preferred")

# ── 모드별 영상 예산 (결정 D-E1, 수정명세서_근거밀도_가변길이_v1.md §3) ──────────────
# 위 주제당 캡은 모드를 모르는 전역값이라 짧은 영상에도 8초를 허용하고 복잡한 영상은 2클립에서 끊겼다.
# 모드가 정해지면 이 표가 그 캡을 **대체**한다(모드 없는 레거시 지시서는 위 전역값으로 폴백).
# ★ 금액은 초수에서 파생한다 — 두 값을 따로 적으면 단가가 바뀔 때 조용히 어긋난다.
CONTENT_MODE_MAX_VIDEO_SEC: dict[str, int] = {
    "flash": 4, "standard": 8, "deep": 12, "extended": 16,
}
# 클립 수도 파생: 요청 티어 상한(기본 VEO_CLIP_SEC=4초)으로 나눈다.
CONTENT_MODE_MAX_VIDEO_CLIPS: dict[str, int] = {
    mode: max(1, sec // VEO_CLIP_MAX_TIER_SEC)
    for mode, sec in CONTENT_MODE_MAX_VIDEO_SEC.items()
}
CONTENT_MODE_MAX_VIDEO_COST_USD: dict[str, float] = {
    mode: round(sec * VEO_COST_PER_SEC_USD, 4)
    for mode, sec in CONTENT_MODE_MAX_VIDEO_SEC.items()
}
# 편당 총예산 점검(명세 §3): extended 최악 = 고유 에셋 8장 × $0.039 + 영상 $0.80 = $1.112
# < RENDER_BUDGET_CAP_USD($1.2). 캡 상향 불필요. 이미지 Batch 기본값이면 $0.956 로 더 여유.

# 렌더 캔버스(9:16 숏폼). 조립 엔진 기준 해상도·프레임레이트.
RENDER_WIDTH: int = 1080
RENDER_HEIGHT: int = 1920
RENDER_FPS: int = 30

# 버전3 애니(DV5). 자유 Manim 코드 금지 → 파라미터 씬 템플릿. 무료·결정론적·LaTeX 불요(Text/pango).
ANIMATION_ENGINE: str = os.getenv("ANIMATION_ENGINE", "manim")
MANIM_BG_COLOR: str = "#20242e"
MANIM_FONT: str = os.getenv("MANIM_FONT", "NanumGothic")  # 한글 렌더(러너: fonts-nanum)


# ─────────────────────────────────────────────────────────────
# 숏폼 규격 v2  (docs/규격서_숏폼_v2.md, DV7~DV11)
# 값은 실측 A/B 보정 대상(고정 표준 아님) — 매직넘버 흩뿌리지 말고 전부 여기서.
# ─────────────────────────────────────────────────────────────
# ⑤ 이중언어(DV11). 언어 무관 에셋 1회 + 언어별 (b)TTS·(c)자막·(d)조립 2회.
LANGUAGES: tuple[str, ...] = ("ko", "en")
DEFAULT_LANG: str = "ko"
# 언어별 Edge TTS 보이스(무료·키 불필요). 기존 EDGE_TTS_VOICE(ko)를 계승.
EDGE_TTS_VOICE_BY_LANG: dict[str, str] = {
    "ko": EDGE_TTS_VOICE,
    "en": os.getenv("EDGE_TTS_VOICE_EN", "en-US-AriaNeural"),
}
# 언어별 자막 폰트(번인). 러너 설치 폰트 우선(ko: fonts-nanum). Pretendard/Montserrat 는 설치 시 교체.
CAPTION_FONT: dict[str, str] = {
    "ko": SUBTITLE_FONT_NAME,
    "en": os.getenv("SUBTITLE_FONT_NAME_EN", "Montserrat"),
}

# ① 레이트 기반 자막 청킹 + Fallback(DV7). R = 청크_글자수 / target_CPS.
# CJK 는 문자당 정보량이 커 낮게 시작. 워드바이워드는 시선을 끌어 약간 높여도 됨.
CAPTION_TARGET_CPS: dict[str, float] = {"ko": 11.0, "en": 20.0}
CAPTION_TARGET_CPS_RANGE: dict[str, tuple[float, float]] = {
    "ko": (9.0, 13.0), "en": (18.0, 22.0),
}
CAPTION_MIN_DISPLAY_FLOOR_SEC: float = 0.7   # 하드 플로어(이보다 짧으면 인접 청크 병합)
CAPTION_TAIL_HOLD_MAX_SEC: float = 0.5       # 침묵 구간까지만 표시창 연장(오디오는 안 밈)
# 한 청크 최대 토큰 수(언어별). 빠른 발화면 fast 로 줄여 가독 부하↓.
CAPTION_CHUNK_MAX: dict[str, int] = {"ko": 6, "en": 7}
CAPTION_CHUNK_FAST: dict[str, int] = {"ko": 4, "en": 5}
# 한 줄 최대 글자수(오토핏 근사). EN 은 폭 초과 방지 위해 넉넉히.
CAPTION_MAX_CHARS: dict[str, int] = {"ko": SUBTITLE_MAX_CHARS, "en": 34}
CAPTION_AUTOFIT_MAX_WIDTH_PX: int = 900
CAPTION_AUTOFIT_MIN_FONT_PX: int = 56
CAPTION_AUTOFIT_MAX_LINES: int = 2
CAPTION_HIGHLIGHT_COLOR: str = "#FFE000"     # 핵심어 1개 하이라이트(노랑)

# ② 플랫폼별 자막 앵커(DV8). 앵커%(화면 상단 기준 높이) → 하단 MarginV = height*(1-anchor).
# 마스터는 가장 빡빡한 TikTok. 비주얼·오디오 1개, 자막 레이어만 플랫폼별 y-오프셋 재합성.
DEFAULT_PLATFORM: str = os.getenv("DEFAULT_PLATFORM", "tiktok")
PLATFORM_CAPTION_ANCHOR_PCT: dict[str, float] = {
    "tiktok": 0.62, "reels": 0.68, "shorts": 0.70, "fb_reels": 0.68,
}
PLATFORM_SAFE_BOTTOM_PX: dict[str, int] = {
    "tiktok": 480, "reels": 380, "shorts": 340, "fb_reels": 380,
}

# ③ 시각 다양성 래더(DV9). scene_kind 는 컷마다 지정, 다양성 제약을 정규화·렌더러가 강제.
SCENE_KINDS: tuple[str, ...] = (
    "comic_panel", "motion_graphic", "kinetic_typography", "data_viz", "broll_stock",
)
# 고효율(코드 기반) 씬 — 캐릭터 일관성 문제 없음·저비용. Manim 클립으로 렌더.
SCENE_HIGH_EFFORT_KINDS: tuple[str, ...] = ("motion_graphic", "kinetic_typography", "data_viz")
SCENE_MAX_CONSECUTIVE_SAME: int = 2          # 같은 kind 3연속 금지(최대 2연속)
SCENE_HIGH_EFFORT_MIN_PER_SEC: int = 10      # 10초당 최소 1회 고효율 씬
SCENE_SEMANTIC_LINK_REQUIRED: tuple[str, ...] = ("broll_stock", "comic_panel")
# 버전 → 컷 기본 scene_kind(모델이 생략 시 폴백). visual_type 과 병행(레거시 호환).
VERSION_DEFAULT_SCENE_KIND: dict[str, str] = {
    "comic": "comic_panel",
    "webtoon": "comic_panel",
    "image_sequence": "broll_stock",
    # 설명판형의 기본 화면은 실사 b-roll 이 아니라 데이터 판(motion_graphic 계열)이다.
    "explainer": "motion_graphic",
    # 실사형은 현장·제품 맥락 컷이 기본이다.
    "photo": "broll_stock",
}

# ④ 엔벨로프 더킹(DV10). 실시간 사이드체인 대신 VO 스팬 사전계산 볼륨 엔벨로프(결정론·재현성).
DUCK_METHOD: str = os.getenv("DUCK_METHOD", "precomputed_envelope")  # precomputed_envelope | sidechain
DUCK_DB: float = -20.0            # 감쇠 깊이(-18~-22 범위)
DUCK_ATTACK_MS: int = 8
DUCK_RELEASE_MS: int = 300
DUCK_MERGE_GAP_MS: int = 800      # 인접 VO 간극 < 이 값이면 병합(펌핑 방지)

# 페이싱(참고 상수 — 프롬프트·검증용).
PACING_VISUAL_CHANGE_SEC: tuple[float, float] = (2.0, 4.0)
PACING_DEAD_AIR_MAX_MS: int = 250
PACING_NO_DISSOLVE_FIRST_SEC: int = 5
KEN_BURNS_ROLE: str = "micro_motion_only"

# 화면 레이아웃(2026 숏폼 트렌드): 이미지를 꽉 채우지 않고 중앙 밴드 + 상하 바(레터박스).
# 근거: Reels/Shorts 에서 콘텐츠를 중앙(≈4:5~1:1) 밴드에 넣고 상하를 검정/블러 바로 채우는 편집이
#       표준화(상단 바=훅, 하단 바=여백/자막 안전지대, 플랫폼 UI 겹침 회피). 리서치 반영.
# full_bleed = 기존(이미지 화면 꽉 채움) / center_band = 중앙 밴드 + 상하 바.
LAYOUT_MODE: str = os.getenv("LAYOUT_MODE", "center_band")
LETTERBOX_TOP_PX: int = _get_int("LETTERBOX_TOP_PX", 200)        # 상단 바 높이
LETTERBOX_CONTENT_HEIGHT: int = _get_int("LETTERBOX_CONTENT_HEIGHT", 1300)  # 중앙 콘텐츠 밴드 높이(px, 크게)
LETTERBOX_BAR_COLOR: str = os.getenv("LETTERBOX_BAR_COLOR", "black")  # 상하 바 색(ffmpeg color)

# ★ 전·후 분할 스틸의 **분할선이 최종 화면에서 놓이는 y**. 콘텐츠 밴드 한가운데다.
#   캡션 두 줄은 이 선을 위·아래로 끼고 붙는다 — 그래야 어느 캡션이 어느 화면 것인지 명확하고,
#   상단 헤더(제목·훅)와도 겹치지 않는다. 숫자를 박지 않고 **유도**한다(2026-09-18 재리뷰).
_SPLIT_DIVIDER_Y: int = (LETTERBOX_TOP_PX + LETTERBOX_CONTENT_HEIGHT // 2
                         if LAYOUT_MODE == "center_band" else RENDER_HEIGHT // 2)
_SPLIT_CAPTION_GAP_PX: int = 24
# ★★ 두 캡션은 **각자 자기 화면의 머리**에 붙는다 — 둘 다 상단 기준(ASS Alignment=8).
#   실제 그림으로 세 번 만들어 보고 정했다(2026-09-18):
#     ① 분할선을 위·아래로 끼게 두니 두 줄이 60px 간격으로 몰려 **어느 게 어느 화면 것인지
#        안 보였다** — 그냥 두 줄짜리 자막처럼 읽힌다.
#     ② 각자 화면 **아래**에 두니 아래 캡션이 나레이션 자막과 **12px** 까지 붙었다(실측).
#        콘텐츠 밴드 바닥이 자막 영역과 겹치므로, "아래 화면의 아래"는 구조적으로 자리가 없다.
#     ③ 각자 화면 **위**: 위 캡션은 훅 아래, 아래 캡션은 분할선 아래. 650px 떨어져 주인이 분명하고
#        자막과도 안 겹친다. 참고 영상들도 라벨을 화면 위쪽에 얹는다.
_SPLIT_BAND_BOTTOM_Y: int = (LETTERBOX_TOP_PX + LETTERBOX_CONTENT_HEIGHT
                             if LAYOUT_MODE == "center_band" else RENDER_HEIGHT)
#: 아래 화면의 캡션 — 분할선 바로 아래.
OVERLAY_LABEL_BOTTOM_MARGIN_V: int = _SPLIT_DIVIDER_Y + _SPLIT_CAPTION_GAP_PX
# center_band 에서 제목/자막을 바 안에 배치하되 "콘텐츠에 가깝게". 콘텐츠[200~1500]·하단 바[1500~1920].
# ★ 자막은 바닥 채널 UI 와 겹치지 않게 더 위로(=바닥 여백 키움), 제목/부제목은 상단 끝에서 더 내려오게(=위 여백 키움).
LETTERBOX_CAPTION_MARGIN_V: int = _get_int("LETTERBOX_CAPTION_MARGIN_V", 380)  # 하단 자막(바닥에서 px) ↑
LETTERBOX_HEADER_MARGIN_V: int = _get_int("LETTERBOX_HEADER_MARGIN_V", 120)   # 상단 제목(위에서 px) ↓

# ★ 주석 레이어는 **헤더(시리즈 제목 + 훅) 아래에서 시작한다.** 밴드 맨 위로 잡았더니
#   키워드 카드(불투명 박스)가 훅을 덮었다(2026-09-18 실측). 헤더 높이에서 유도한다.
_HEADER_BLOCK_BOTTOM_Y: int = ((LETTERBOX_HEADER_MARGIN_V if LAYOUT_MODE == "center_band"
                                else int(RENDER_HEIGHT * SUBTITLE_SAFE_TOP))
                               + HEADER_TITLE_SIZE + HEADER_HOOK_SIZE)
#: 키워드 카드 — 헤더 바로 아래, 좌상단.
OVERLAY_KEYWORD_MARGIN_V = _HEADER_BLOCK_BOTTOM_Y + _SPLIT_CAPTION_GAP_PX
#: 위 화면의 캡션 — 키워드 카드 **아래** 줄(둘이 같은 줄이면 좌측 카드와 가운데 캡션이 붙는다).
OVERLAY_LABEL_TOP_MARGIN_V: int = (OVERLAY_KEYWORD_MARGIN_V + OVERLAY_KEYWORD_FONT_SIZE
                                   + _SPLIT_CAPTION_GAP_PX)


# ─────────────────────────────────────────────────────────────
# 유튜브 자동 업로드 (P-V2 승인 이탈)  (docs/deviation-youtube-upload.md)
# ─────────────────────────────────────────────────────────────
# 렌더 완료 mp4 를 대시보드 버튼으로 큐잉 → engine.publish 워커가 YouTube Data API v3 videos.insert.
# 인증: 채널 업로드는 서비스계정이 불가(채널을 소유할 수 없음) → OAuth 리프레시 토큰 흐름.
# 클라이언트 ID/시크릿은 채널 공통(같은 GCP 프로젝트), 리프레시 토큰은 채널(언어)마다 다르다.
YOUTUBE_UPLOAD_ENABLED: bool = _get_bool("YOUTUBE_UPLOAD_ENABLED", True)
YOUTUBE_TOKEN_URI: str = "https://oauth2.googleapis.com/token"
YOUTUBE_UPLOAD_SCOPE: str = "https://www.googleapis.com/auth/youtube.upload"
# 기본 공개 상태(사용자 결정: private). 올린 뒤 사람이 스튜디오에서 공개로 전환.
YOUTUBE_DEFAULT_PRIVACY: str = os.getenv("YOUTUBE_DEFAULT_PRIVACY", "private")
YOUTUBE_ALLOWED_PRIVACY: tuple[str, ...] = ("private", "unlisted", "public")
# 카테고리: 27=Education(교육). YouTube Data API categoryId(지역 무관 표준값).
YOUTUBE_CATEGORY_ID: str = os.getenv("YOUTUBE_CATEGORY_ID", "27")
YOUTUBE_MADE_FOR_KIDS: bool = _get_bool("YOUTUBE_MADE_FOR_KIDS", False)
# YouTube 하드 제한: 제목 100자, 설명 5000자. 초과 시 안전하게 절단.
YOUTUBE_TITLE_MAX: int = 100
YOUTUBE_DESC_MAX: int = 5000
# 언어별 채널(리프레시 토큰) 매핑. secrets 속성명을 가리킨다(값이 아니라 이름).
YOUTUBE_REFRESH_TOKEN_SECRET_BY_LANG: dict[str, str] = {
    "ko": "youtube_refresh_token_ko",
    "en": "youtube_refresh_token_en",
}
# ★ 리포트 전용 채널 맵은 제거됐다 (2026-07-30 채널 통합,
#   docs/specs/20260730-report-merge-into-paper-ko.md). 리포트도 하루한편 KO 채널로 발행하며,
#   채널→토큰 매핑은 engine/youtube_channels.CHANNEL_REGISTRY 한 곳으로 통일했다.
#   되돌리기는 그 레지스트리의 report_ko 3개 값만 바꾸면 된다(명세서 §4).

# 하루한편 KO 채널 공통 태그 — 채널 통합으로 논문·리포트가 한 채널을 쓰므로 공통 태그를 붙인다.
# 영상별 태그와 합친 뒤 YouTube 태그 합계 500자 제한을 지켜 절단한다(명세서 §3-3).
CHANNEL_CORE_TAGS_KO: tuple[str, ...] = tuple(
    t.strip() for t in os.getenv(
        "CHANNEL_CORE_TAGS_KO", "하루지식하나,지식쇼츠,shorts"
    ).split(",") if t.strip()
)
# 태그 합계 상한(쉼표 포함 계산). YouTube 하드 제한.
YOUTUBE_TAGS_TOTAL_MAX: int = 500


# ─────────────────────────────────────────────────────────────
# 유튜브 쇼츠 성과 수집 (P-V3 승인 이탈)  (docs/deviation-youtube-analytics.md)
# ─────────────────────────────────────────────────────────────
# 채널에 최근 N일 올린 쇼츠의 성과(조회수·시청지속·노출 CTR·좋아요·구독전환)를 YouTube
# Data API(영상 목록·길이) + YouTube Analytics API(reports.query, 지표)로 끌어와 Supabase
# youtube_analytics 에 스냅샷 저장한다. 대시보드 /analytics 가 읽는다. 업로드(쓰기)와 분리된
# 읽기 전용 흐름 — 스코프도 토큰도 별개다(업로드 토큰엔 조회 권한이 없다).
YOUTUBE_ANALYTICS_ENABLED: bool = _get_bool("YOUTUBE_ANALYTICS_ENABLED", True)
# 읽기 스코프 2종: 영상 메타(목록/길이)는 youtube.readonly, 지표는 yt-analytics.readonly.
YOUTUBE_READONLY_SCOPE: str = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_ANALYTICS_SCOPE: str = "https://www.googleapis.com/auth/yt-analytics.readonly"
YOUTUBE_ANALYTICS_SCOPES: tuple[str, ...] = (YOUTUBE_READONLY_SCOPE, YOUTUBE_ANALYTICS_SCOPE)
# 성과 수집 윈도우(며칠 치 쇼츠를 볼지). 사용자 요청 "지난 일주일" = 7.
YOUTUBE_ANALYTICS_WINDOW_DAYS: int = _get_int("YOUTUBE_ANALYTICS_WINDOW_DAYS", 7)
# 쇼츠 판정: 영상 길이 ≤ 이 값(초)이면 쇼츠로 본다. 유튜브 정책상 상한이 60→180s 로 바뀌었다.
YOUTUBE_SHORTS_MAX_SEC: int = _get_int("YOUTUBE_SHORTS_MAX_SEC", 180)
# Analytics reports.query 로 뽑을 지표(순서 = 응답 컬럼 순서). CTR(노출 클릭률)은 별도 계산.
YOUTUBE_ANALYTICS_METRICS: tuple[str, ...] = (
    "views", "estimatedMinutesWatched", "averageViewDuration",
    "averageViewPercentage", "likes", "comments", "shares", "subscribersGained",
)
# 한 번에 Analytics 필터에 넣을 video id 최대 개수(reports.query filters=video== 제한 대비 보수적).
YOUTUBE_ANALYTICS_ID_CHUNK: int = _get_int("YOUTUBE_ANALYTICS_ID_CHUNK", 200)
# 언어별 성과 조회 토큰. 비어 있으면 업로드 토큰으로 폴백(사용자가 업로드 토큰을 조회 스코프
# 포함해 재발급한 경우). 폴백 토큰에 조회 스코프가 없으면 API 가 403 → 명확한 에러로 안내.
YOUTUBE_ANALYTICS_TOKEN_SECRET_BY_LANG: dict[str, str] = {
    "ko": "youtube_analytics_refresh_token_ko",
    "en": "youtube_analytics_refresh_token_en",
}

# ─ 성과 리포트(일간/주간/월간 + 하이브리드 분석)  (docs/deviation-youtube-analytics.md) ─
# 채널 단위 날짜별 시계열(dimensions=day)을 이 기간만큼 끌어와 youtube_analytics_daily 에 저장.
# 주/월 집계에 충분하도록 넉넉히(기본 90일). 대시보드 /analytics/report 가 이걸 읽어 집계·차트.
YOUTUBE_ANALYTICS_DAILY_LOOKBACK_DAYS: int = _get_int("YOUTUBE_ANALYTICS_DAILY_LOOKBACK_DAYS", 90)
# 날짜별 채널 지표(순서 = 응답 컬럼 순서). per-video 와 달리 averageViewDuration 은 뺀다(채널 일별 무의미).
YOUTUBE_ANALYTICS_DAILY_METRICS: tuple[str, ...] = (
    "views", "estimatedMinutesWatched", "averageViewPercentage",
    "likes", "comments", "shares", "subscribersGained",
)
# 성과 리포트 문장화(하이브리드의 LLM 단계) 모델 — 비용·품질 균형(리포트 팩토리와 동일 기본).
MODEL_PERF_REPORT: str = os.getenv("MODEL_PERF_REPORT", "gemini-2.5-flash")
# 규칙 단계 임계값(facts 계산용). 시청지속률 이 값 미만이면 '개선 필요' 후보.
PERF_LOW_RETENTION_PCT: float = float(os.getenv("PERF_LOW_RETENTION_PCT", "40"))
# 리포트 상/하위 영상 개수(best/worst).
PERF_TOP_N: int = _get_int("PERF_TOP_N", 3)


# ─────────────────────────────────────────────────────────────
# 리포트 팩토리 (PF0~)  — 두 번째 "공장"  (docs/deviation-report-factory.md)
# ─────────────────────────────────────────────────────────────
# ARIA 신호 → 4축 경량 채점 → 리포트 대시보드. 수집 블록(OpenAlex/arXiv/HN/Reddit)이
# ARIA MCP 호출 몇 개로 압축된다(명세 §2). 논문 공장과 테이블/화면 모두 완전 분리(report_*, /finance).
#
# ★ PFD3(ARIA 연동): 로컬/크론 엔진은 이 세션의 MCP 를 못 쓴다. 사용자의 ARIA 는 REST 가 아니라
#   MCP 서버(streamable HTTP/JSON-RPC)다. 전송방식 선택 우선순위(engine/aria/client.py get_client):
#     1) ARIA_MCP_URL — MCP 서버 직접 호출(프로덕션 경로). URL 경로에 인증 토큰이 포함돼 별도 키 불필요.
#     2) ARIA_BASE — 순수 REST API(레거시/대안). ARIA_API_KEY 헤더.
#     3) 둘 다 비면 fixture(engine/aria/fixtures) — 로컬·테스트·오프라인.
ARIA_MCP_URL: str = os.getenv("ARIA_MCP_URL", "")         # ARIA MCP 엔드포인트(토큰 포함 URL) — 프로덕션
ARIA_BASE: str = os.getenv("ARIA_BASE", "")               # 순수 REST(대안). 둘 다 비면 fixture 모드
ARIA_SIGNAL_LIMIT: int = _get_int("ARIA_SIGNAL_LIMIT", 40)  # list_signals 상위 N = 후보 풀(중복 제거 전)
ARIA_PASS_ONLY: bool = _get_bool("ARIA_PASS_ONLY", True)   # 기준 통과(HIGH/MID)만
ARIA_TODAY_ONLY: bool = _get_bool("ARIA_TODAY_ONLY", False)  # True 면 오늘(KST) 매칭분만

# 같은 원문이 여러 테마에 매칭돼 신호가 복제되는 것을 문서 단위로 접는 키 길이(요약 앞부분).
REPORT_DEDUP_PREFIX_CHARS: int = _get_int("REPORT_DEDUP_PREFIX_CHARS", 120)
# 메시지 헤더에서 증권사(출처)를 추정할 때 쓰는 알려진 증권사명 — get_signal 상세(channel) 실패 시 폴백.
REPORT_KNOWN_BROKERS: tuple[str, ...] = (
    "신한투자증권", "하나증권", "유안타증권", "키움증권", "현대차증권", "미래에셋증권",
    "삼성증권", "KB증권", "NH투자증권", "한국투자증권", "대신증권", "메리츠증권",
    "한화투자증권", "교보증권", "유진투자증권", "신영증권", "SK증권", "IBK투자증권",
)
# 저작권 안전장치(명세 §2): 원문 전문은 저장하지 않는다 — 요약만 이 길이로 잘라 보관.
REPORT_SUMMARY_MAX_CHARS: int = _get_int("REPORT_SUMMARY_MAX_CHARS", 1200)

# ─ Source Contract (작업지시서 영상엔진품질 v3 §4 · Phase 0 결정 §8-1 (가)+런타임 주입) ─
# ★ 왜: 지금까지 Fact Sheet 입력은 list_signals 의 **미리보기**(평균 366자)뿐이었다. ARIA 는 같은
#   리포트의 전문(get_research.content_raw / get_signal.raw_content)을 이미 갖고 있었는데 엔진이
#   그 도구를 부르지 않았다(docs/phase0-영상엔진품질_v3.md §1-3).
# ★ 저장하지 않는다 — 추출 직전에 불러 프롬프트에만 넣는다. 0018 주석의 저작권 자세를 유지한다.
#   저장으로 바꾸려면 이 상수가 아니라 §8-1 서브 결정을 다시 해야 한다.
SOURCE_INJECT_FULLTEXT: bool = _get_bool("SOURCE_INJECT_FULLTEXT", True)
# 원문 보관(0033 report_sources). ★ 수집 시점에 보관해야 대시보드 [초안 생성] 경로가 살아난다 —
#   그 버튼은 Edge Function 을 부르고 Edge 에는 ARIA 접속이 없다. DB 에 있으면 워커든 Edge 든
#   같은 전문을 읽는다. 끄면 예전처럼 추출 때마다 ARIA 를 부른다(대시보드 경로는 요약만 봄).
SOURCE_PERSIST_FULLTEXT: bool = _get_bool("SOURCE_PERSIST_FULLTEXT", True)
# 전문 주입 상한(문자). 지시서 §4-2 의 "30k 토큰 가드"를 문자로 해소한 값 — 한국어는 대략
# 1토큰≈1.2~1.6자라 40,000자면 30k 토큰 언저리다. 넘으면 앞에서부터 자르고 잘린 사실을 남긴다.
SOURCE_FULLTEXT_MAX_CHARS: int = _get_int("SOURCE_FULLTEXT_MAX_CHARS", 40000)
# 청크 분할 길이(지시서 §4-1). PDF 파싱을 하지 않으므로 페이지가 아니라 문자 길이로 나눈다 —
# page_start/page_end 를 지어내지 않기 위해서다(없는 페이지 번호는 화면에 못 나간다).
SOURCE_CHUNK_CHARS: int = _get_int("SOURCE_CHUNK_CHARS", 1200)
# 원문 확보 수준(지시서 §4-1 source_depth). 코드가 데이터로 판정한다 — 모델 자기보고 불신.
SOURCE_DEPTHS: tuple[str, ...] = ("full_text", "partial_text", "summary_only", "parse_failed")
# partial_text ↔ full_text 경계(문자). 증권사 정식 리포트 전문은 보통 이보다 길고, 텔레그램
# 메시지는 짧다. 실측(2026-08-02): 하나증권 LG전자 전문 ≈ 4,700자 / 대신 시황 메시지 ≈ 1,800자.
SOURCE_FULLTEXT_MIN_CHARS: int = _get_int("SOURCE_FULLTEXT_MIN_CHARS", 2500)
# 프롬프트에 박는 전문 구간 마커. ★ tests/test_fulltext_injection.py 가 이 마커의 존재를
#   검사한다(지시서 §11-1) — 프롬프트를 나중에 누가 다듬어도 전문 주입이 조용히 빠질 수 없다.
SOURCE_FULLTEXT_MARKER: str = "<<FULL_SOURCE>>"
SOURCE_FULLTEXT_END_MARKER: str = "<</FULL_SOURCE>>"

# ★ 지시서 §4-2 의 **초안 단계** 주입. 여기까지가 사장님 원지시였다 —
#   "초록·요약만으로 대본 금지, **초안·세부지시는 전체를 읽고** 구체 근거"(§1-1).
#   추출(Fact Sheet)에는 전문이 들어갔는데 대본에는 안 들어가고 있었다: report_scriptgen 의
#   프롬프트가 Fact Sheet JSON 한 덩어리뿐이었다. 그래서 대본 작가는 "48.6배"라는 결론만 보고
#   **왜 그 숫자가 나왔는지**는 못 봤다. 각색에 필요한 맥락이 바로 그 '왜'다.
# ★ 상한은 따로 두지 않는다 — packet["text"] 가 build_packet 에서 이미
#   SOURCE_FULLTEXT_MAX_CHARS(40,000자 ≈ 30k 토큰)로 잘려 있다. 두 번 자르면 상한이 두 곳에
#   생겨 어느 쪽이 실제로 작동하는지 알 수 없게 된다.
DRAFT_INCLUDE_FULLTEXT: bool = _get_bool("DRAFT_INCLUDE_FULLTEXT", True)
# 초안 프롬프트의 근거 묶음 마커. ★ 전문 마커와 **둘 다** 검사해야 §11-1 ② 가 성립한다 —
#   전문만 보고 Fact Sheet 를 무시하는 프롬프트도, 그 반대도 이 지시가 깨진 것이다.
DRAFT_EVIDENCE_MARKER: str = "<<EVIDENCE_PACKET>>"
DRAFT_EVIDENCE_END_MARKER: str = "<</EVIDENCE_PACKET>>"

# ─ 포털 리포트 수집(§8-1 (가)) ─
# ★ 왜 필요한가: 전문 주입 배선만으로는 소용이 없다. 지금까지 수집한 162건은 전부 텔레그램
#   계열(aria_signal)이라 전문이라 해도 메시지 본문이 전부다. 인용·근거 추적이 가능한 것은
#   ARIA search_research 가 주는 **포털 계열 정식 리포트**(report_title·PDF source_url 보유)다.
# ─────────────────────────────────────────────────────────────
# 논문 원문 확보 (작업명세서_설명엔진_v2 §3 Phase 1)
# ★ 리포트 라인의 SOURCE_* 와 이름을 나눈다 — D1(도메인 엔진 분리). 리포트는 ARIA 한 곳에서
#   받지만 논문은 확보처가 4곳(arXiv·OpenAlex OA·PMC·Unpaywall)이고 실패율이 훨씬 높다.
#   상수를 공유하면 한쪽을 조일 때 다른 쪽이 조용히 딸려 움직인다.
# ─────────────────────────────────────────────────────────────
PAPER_SOURCE_ENABLED: bool = _get_bool("PAPER_SOURCE_ENABLED", True)
# 확보 체인 순서. 앞에서 본문이 잡히면 뒤는 부르지 않는다(호출 절약 + 라이선스가 분명한 순서).
PAPER_SOURCE_CHAIN: tuple[str, ...] = ("arxiv", "openalex", "pmc", "unpaywall")
# 원문 주입 상한(문자). 리포트(40,000)보다 크게 잡는다 — 논문 본문은 평균이 훨씬 길다.
PAPER_SOURCE_MAX_CHARS: int = _get_int("PAPER_SOURCE_MAX_CHARS", 60000)
PAPER_SOURCE_CHUNK_CHARS: int = _get_int("PAPER_SOURCE_CHUNK_CHARS", 1200)
# 확보 수준(§3-1). ★ 코드가 글자 수로 판정한다 — report_source.classify_depth 와 같은 자세.
PAPER_SOURCE_DEPTHS: tuple[str, ...] = ("full_body", "partial_body", "abstract_only", "parse_failed")
# partial_body ↔ full_body 경계(문자). 논문 본문은 보통 2만자 이상이고, 초록은 1~2천자다.
# 그 사이(예: 확장 초록·레터·파서가 앞부분만 건진 경우)를 partial_body 로 본다.
PAPER_SOURCE_FULLBODY_MIN_CHARS: int = _get_int("PAPER_SOURCE_FULLBODY_MIN_CHARS", 8000)
# 초록 수준으로 볼 하한. 이보다 짧으면 본문을 못 건진 것으로 본다.
PAPER_SOURCE_MIN_BODY_CHARS: int = _get_int("PAPER_SOURCE_MIN_BODY_CHARS", 2000)
# 참고문헌 이후는 버린다. 인용 검증의 대조 대상이 아니고, 상한만 잡아먹는다.
PAPER_SOURCE_DROP_REFERENCES: bool = _get_bool("PAPER_SOURCE_DROP_REFERENCES", True)
# 확보처 엔드포인트.
ARXIV_HTML_BASE: str = "https://arxiv.org/html"
ARXIV_PDF_BASE: str = "https://arxiv.org/pdf"
AR5IV_HTML_BASE: str = "https://ar5iv.labs.arxiv.org/html"
EUROPEPMC_REST_BASE: str = "https://www.ebi.ac.uk/europepmc/webservices/rest"
UNPAYWALL_BASE: str = "https://api.unpaywall.org/v2"
# 원문 다운로드 타임아웃(초). PDF 는 수 MB 라 일반 HTTP_TIMEOUT_SEC(30)보다 길게 준다.
PAPER_SOURCE_TIMEOUT_SEC: float = _get_float("PAPER_SOURCE_TIMEOUT_SEC", 60.0)
# 내려받을 원문 최대 바이트. 이보다 크면 받다가 끊는다(수백 MB PDF 방어).
PAPER_SOURCE_MAX_BYTES: int = _get_int("PAPER_SOURCE_MAX_BYTES", 30 * 1024 * 1024)
# OpenAlex locations[] 를 몇 곳까지 두드릴지. 한 논문에 위치가 10곳 넘게 달리는 경우가 있어
# 상한이 없으면 실패 논문 하나가 수십 초를 먹는다.
PAPER_SOURCE_MAX_LOCATIONS: int = _get_int("PAPER_SOURCE_MAX_LOCATIONS", 5)
# 프롬프트에 박는 전문 구간 마커(논문 라인). 리포트와 같은 문자열을 쓰면 test_prompt_sync 의
# 앵커가 두 라인에서 뒤섞인다.
PAPER_SOURCE_MARKER: str = "<<PAPER_FULL_SOURCE>>"
PAPER_SOURCE_END_MARKER: str = "<</PAPER_FULL_SOURCE>>"

# ─ Evidence Contract (v3 §5) — 전 상수 여기에서. 소비처: engine/report_evidence.py ─
# 인용 대조: 너무 짧은 인용은 우연히 원문에 있을 수 있어 대조 의미가 없다.
EVIDENCE_QUOTE_MIN_CHARS: int = _get_int("EVIDENCE_QUOTE_MIN_CHARS", 8)
EVIDENCE_QUOTE_MAX_CHARS: int = _get_int("EVIDENCE_QUOTE_MAX_CHARS", 300)
EVIDENCE_MAX_SOURCE_REFS: int = _get_int("EVIDENCE_MAX_SOURCE_REFS", 3)
# 숫자 대조 허용 오차(상대). 리포트 본문 반올림 표기("1조 5,791억" vs 1.5791조)를 흡수한다.
EVIDENCE_NUMBER_TOLERANCE: float = _get_float("EVIDENCE_NUMBER_TOLERANCE", 0.01)
# 자릿수 환산 배수 — 한국어 단위계(만·억·조)에 해당하는 것만. ★ 임의의 10 거듭제곱을 허용하면
#   오차 허용과 겹쳐 "1" 이 9,999 와 일치로 판정된다(실측). 여기 없는 배수(예: 10배)는
#   단위 환산이 아니라 **자릿수 오류**이므로 통과시키지 않는다.
#   ★ 천(1e3)·백만(1e6)·십억(1e9)도 넣는다. 없던 시절 "500(백만원) vs 5억원" 과
#     "3000(억) vs 3천억원" 이 미검증으로 떨어졌는데, 백만원은 한국 재무제표의 기본 단위이고
#     달러 표기는 백만/십억이 표준이다(500만 달러 / 3억 달러).
EVIDENCE_SCALE_FACTORS: tuple[float, ...] = (
    1.0,
    1e3, 1e-3,      # 천
    1e4, 1e-4,      # 만
    1e6, 1e-6,      # 백만 (재무제표 단위 / million)
    1e8, 1e-8,      # 억
    1e9, 1e-9,      # 십억 (billion)
    1e12, 1e-12,    # 조
)
# ★ 하드 차단 스위치. 기본 **off** — 지금 재고(요약 기반 162건)에 켜면 전부 막힌다.
#   포털 리포트 재고가 쌓이고 인용률이 올라간 뒤 운영자가 켠다(§9 source_depth 정책과 함께).
EVIDENCE_HARD_BLOCK_ENABLED: bool = _get_bool("EVIDENCE_HARD_BLOCK_ENABLED", False)

# §5-3 content_profile 별 최소 기준. v1 의 "≥8/≥3" 일괄 기준이 시황·이벤트에 과도하다는
# 지적(§0-1 #3)을 받아 유형별로 나눴다. 필수 범주는 키워드로 판정한다 — 분류기를 만들지 않는다.
EVIDENCE_PROFILES: tuple[str, ...] = (
    "company_update", "earnings_review", "industry_report",
    "market_wrap", "event_flash", "paper_explainer",
)
EVIDENCE_PROFILE_DEFAULT: str = "company_update"
EVIDENCE_PROFILE_MINIMUMS: dict[str, dict[str, Any]] = {
    "company_update": {"min_evidence": 6, "min_comparator": 2, "required_categories": {
        "실적_수주_가이던스": ("매출", "영업이익", "수주", "가이던스", "실적"),
        "밸류_목표가": ("목표주가", "목표가", "PER", "PBR", "밸류"),
    }},
    # ★ 리스크는 키워드가 아니라 risks 배열 존재로 판정한다(requires_risks) — factsheet 가
    #   "리포트가 말한 것만"으로 바뀌어 본문 키워드 검색이 상시 오탐을 냈다.
    # ★ "F)" 를 전망 키워드에서 뺐다 — 단순 부분문자열이라 "(2026F)" 같은 무관한 조각에 걸린다.
    "earnings_review": {"min_evidence": 7, "min_comparator": 3, "requires_risks": True,
                        "required_categories": {
                            "매출": ("매출",), "이익": ("영업이익", "순이익", "이익"),
                            "전망": ("전망", "가이던스", "예상", "추정"),
                        }},
    "industry_report": {"min_evidence": 6, "min_comparator": 2, "required_categories": {
        "시장규모_성장": ("시장", "성장", "수요", "출하"),
        "기업영향": ("수혜", "영향", "점유율", "공급"),
    }},
    "market_wrap": {"min_evidence": 5, "min_comparator": 2, "required_categories": {
        "지수": ("지수", "KOSPI", "코스피", "KOSDAQ", "코스닥"),
        "수급": ("순매수", "순매도", "외국인", "기관", "수급"),
        "원인": ("배경", "이유", "때문", "인식", "영향"),
    }},
    "event_flash": {"min_evidence": 4, "min_comparator": 1, "required_categories": {
        "사건": ("발표", "체결", "공시", "인증", "계약", "출시"),
        "영향": ("영향", "수혜", "기대", "전망"),
    }},
    "paper_explainer": {"min_evidence": 5, "min_comparator": 1, "required_categories": {
        "결과": ("결과", "성능", "개선", "정확도"),
        "한계": ("한계", "제약", "가정", "리스크"),
    }},
}

REPORT_COLLECT_RESEARCH: bool = _get_bool("REPORT_COLLECT_RESEARCH", True)
ARIA_RESEARCH_LIMIT: int = _get_int("ARIA_RESEARCH_LIMIT", 40)   # search_research 상위 N
ARIA_RESEARCH_STATUS: str = os.getenv("ARIA_RESEARCH_STATUS", "selected")  # 선별 통과분만
# 포털 계열만 받는다 — report_title 이 있는 것. 제목이 null 인 항목은 텔레그램 계열이고
# 이미 aria_signal 로 들어오므로 중복이다.
REPORT_RESEARCH_REQUIRE_TITLE: bool = _get_bool("REPORT_RESEARCH_REQUIRE_TITLE", True)
# 종목 쿨다운: 최근 N일 발행/등장 종목 재등장 감점·제외(같은 종목 반복 = 펌핑 오해 방지, 명세 §4).
REPORT_TICKER_COOLDOWN_DAYS: int = _get_int("REPORT_TICKER_COOLDOWN_DAYS", 5)

# 4축(시의성/이해가능성/스토리성/안전도) → 정렬 지수 가중치. 채택률로 조정하는 변수(고정 아님, 명세 §3).
# 관심 지수 = 시의성·이해·스토리 가중합 / 스토리 지수 = 스토리 중심 / 안전 지수 = 안전도 원점수.
REPORT_INTEREST_WEIGHTS: dict[str, float] = {
    "timeliness": 0.50,
    "explainability": 0.30,
    "story": 0.20,
}
REPORT_STORY_WEIGHTS: dict[str, float] = {
    "story": 0.70,
    "timeliness": 0.30,
}
# 정렬 모드: 관심순 / 스토리순 / 안전순(명세 3-2). daily_batch 는 세 모드 상위를 라운드로빈.
REPORT_SORT_MODES: tuple[str, ...] = ("interest", "story", "safety")
REPORT_DAILY_BATCH_SIZE: int = _get_int("REPORT_DAILY_BATCH_SIZE", 15)
REPORT_BATCH_EXCLUDE_PRIOR: bool = _get_bool("REPORT_BATCH_EXCLUDE_PRIOR", True)
# ARIA 신호 강도(total_score)는 LLM 채점과 분리해 정렬 동점 보정에만 쓴다(명세 3-1).
# 리포트 채점 모델(기본 sonnet — 비용·품질 균형). env 로 교체 가능.
MODEL_REPORT_SCORING: str = os.getenv("MODEL_REPORT_SCORING", "gemini-2.5-flash")

# ─ PF1 초안 파이프라인 모델 (논문 MODEL_FACTSHEET/SCRIPT/SELFCHECK 대응) ─
MODEL_REPORT_FACTSHEET: str = os.getenv("MODEL_REPORT_FACTSHEET", "gemini-2.5-flash")
MODEL_REPORT_SCRIPT: str = os.getenv("MODEL_REPORT_SCRIPT", "gemini-2.5-pro")     # 대본 합성
# ★★ 리포트 지시서 모델 — **재지 않은 자리에 밀지 않는다**(2026-09-19).
#   종전에 `report_directive._generate_once` 는 `MODEL_DIRECTIVE` 를 그대로 썼다. 그래서
#   논문 지시서를 DeepSeek 으로 바꾸면 **리포트 지시서까지 같이 딸려 간다** — 내가 재지
#   않은 경로다. 그냥 두면 안 되는 이유가 하나 더 있다: 이 경로의 출력 상한은
#   `LLM_SCRIPT_MAX_TOKENS`(16,384)이고, deepseek-v4-pro 는 논문 지시서에서 28,403~30,928
#   토큰을 썼다. 상한의 거의 2배다 — 거의 확실히 절단되고, 절단은 재시도가 소용없는
#   하드 에러라 리포트 라인이 선다.
#   그래서 이 자리를 **명시 상수로 분리하고 현행값(gemini-2.5-pro)을 지킨다.** 바꾸려면
#   `scripts/model_ab.py` 로 이 경로를 먼저 재라. MODEL_REPORT_* 가족에 이 멤버만
#   없었던 것은 설계 의도가 아니라 빠진 자리로 보인다.
#   ★★★ **2026-09-20: gemini-3.8-flash 로 옮긴다.** 같은 하네스로 3벌씩 쟀다
#     (`scripts/model_ab.py --job report_directive`, 이 자리를 재라고 위에 적어 둔 그것이다):
#         문제합   2.5-pro 8·17·18(평균 14.3) · deepseek 14·8·14(12.0) · 3.8-flash 17·9·8(11.3)
#         시간     78~118초          · 312~325초            · **26~31초**
#         1벌 비용 $0.144~0.202      · $0.159~0.164          · **$0.114~0.121**
#     ★ **품질로는 못 가른다** — 셋 다 8~18 을 오가고 구간이 겹친다. 세 벌로는 운과 실력이
#       안 갈린다. 그러니 "3.8-flash 가 더 낫다"고 적지 않는다.
#     ★ 바꾸는 근거는 **겹치지 않는 두 축**이다: 3.5배 빠르고 25% 싸다(정가 기준. 출력이
#       편당 비용의 80% 인데 출력 단가가 $10.00 → $7.50 이다). 품질이 같다면 빠르고 싼 쪽이다.
#     ⚠ 지켜볼 것: 1회차에 `근거red` 2건이 나왔다(2.5-pro 는 3회 다 0건). 증권 라인에서 근거는
#       가장 민감한 축이다 — 초반 몇 편은 승인 화면의 근거 경고를 눈으로 본다.
#     ★ **논문 지시서(MODEL_DIRECTIVE)는 건드리지 않는다.** 3.8-flash 를 그 자리에서 잰 적이
#       없다. 재지 않은 자리에 측정 결과를 미는 것이 바로 이 상수가 생긴 이유다.
MODEL_REPORT_DIRECTIVE: str = os.getenv("MODEL_REPORT_DIRECTIVE", "gemini-3.8-flash")
MODEL_REPORT_SELFCHECK: str = os.getenv("MODEL_REPORT_SELFCHECK", "gemini-2.5-flash")
MODEL_REPORT_COMPLIANCE: str = os.getenv("MODEL_REPORT_COMPLIANCE", "gemini-2.5-flash")

# ─ Financial Reasoning Model (작업명세서_설명엔진_v2 §7 Phase 5) ─
# ★ 왜 논문 스키마와 합치지 않는가(D1): 논문은 "왜 그렇게 되는가"(MECHANISM/STRUCTURE…)를
#   설명하고, 리포트는 "왜 그렇게 전망하는가"(driver→실적→밸류)를 논증한다. 단위 이름을 공유하면
#   한쪽 규칙을 고칠 때 다른 쪽이 조용히 딸려 움직인다.
# ★ 왜 story_plan.claim_chain 을 대체하지 않는가: claim_chain 은 **대본의 논증 순서**이고
#   reasoning unit 은 **그 논증이 딛는 인과 단계**다. 대체하면 이미 돌고 있는 근거 게이트
#   (report_evidence.validate_story_plan)가 참조를 잃는다. 위에 얹고 서로 id 로 잇는다.
REPORT_REASONING_ENABLED: bool = _get_bool("REPORT_REASONING_ENABLED", True)
# 기본값이 gemini 인 이유: 리포트 워커는 CI 에서 Gemini 로 돈다(.github/workflows/
# report-draft.yml 의 MODEL_REPORT_* 가 전부 gemini-2.5-*). 여기만 Anthropic 으로 두면
# 같은 파이프라인 안에서 이 단계만 조용히 다른 공급자를 쓰고, ANTHROPIC_API_KEY 가 없는
# 잡에서는 그냥 실패한다. 형제 상수(MODEL_REPORT_FACTSHEET)와 같은 값을 기본으로 둔다.
MODEL_REPORT_REASONING: str = os.getenv("MODEL_REPORT_REASONING", "gemini-2.5-flash")
REASONING_UNIT_TYPES: tuple[str, ...] = (
    "DRIVER_CHAIN",      # 수요·가격·점유율 같은 동인이 실적으로 이어지는 사슬
    "EARNINGS_BRIDGE",   # 전기→당기 실적 변화를 항목별로 잇는 다리
    "VALUATION_LOGIC",   # 멀티플·목표가가 어떤 전제에서 나오는가
    "CATALYST_PATH",     # 촉매가 언제·어떤 경로로 주가에 반영되는가
    "RISK_PATH",         # 리스크가 실현되면 어디를 거쳐 무엇을 깎는가
    "SCENARIO",          # 전제가 달라지면 결과가 어떻게 갈리는가
    "COMPARISON",        # 경쟁사·과거·컨센서스 대비 위치
)
DEFAULT_REASONING_UNIT_TYPE: str = "DRIVER_CHAIN"
# 단위·단계 상한. ★ 상한을 두는 이유는 0-B/0-C 실측에서 배운 것이다 — 원문을 주면 모델이
#   원장·단위를 끝없이 늘려 출력 상한에서 잘린다(그 편은 통째로 날아간다).
#   출력 상한을 올릴 게 아니라 개수를 제한한다(docs/실측_0ABC_설명엔진.md).
REASONING_MAX_UNITS: int = _get_int("REASONING_MAX_UNITS", 5)
REASONING_MAX_STEPS: int = _get_int("REASONING_MAX_STEPS", 5)
REASONING_ID_FORMAT: str = "R{:02d}"
# 저장 스키마 버전(D7 — 신규 테이블 없이 report_drafts JSONB 에 versioned 로 넣는다).
REASONING_SCHEMA_VERSION: int = 1
# 대본·지시서 프롬프트에 박는 논증 구간 마커. ★ 리포트 전문 마커(<<FULL_SOURCE>>)·논문 마커와
#   문자열을 나눈다 — 같으면 tests/test_prompt_sync.py 의 앵커가 서로를 오탐한다.
REASONING_MARKER: str = "<<REASONING_UNITS>>"
REASONING_END_MARKER: str = "<</REASONING_UNITS>>"  # 컴플라이언스 심사관

# ─────────────────────────────────────────────────────────────
# Equity Semantic Operation (v3 Phase 5 — 작업지시서 equity §5)
# ─────────────────────────────────────────────────────────────
# 무엇을 푸는가: 리포트의 논증 단계는 "수주가 늘고 → 잔고가 차고 → 매출로 인식된다" 처럼
# **사업 의미**로 쓰여 있다. 화면 연산(TRANSFER·ACCUMULATE…)은 그것과 다른 층위다.
# 둘을 섞으면 "수주"라는 말이 곧 화면 동작이 돼서, 리포트가 말하지 않은 공정이 그려진다.
# 그래서 **사업 의미 → 화면 연산**을 표로 못박는다(§5 "혼동하지 않는다").
#
# ★ 판정은 코드가 한다. LLM 에게 다시 물어보지 않는다 — `report_reasoning.steps` 를
#   **다시 추출하는 것은 금지**(§4)고, 다시 물으면 같은 입력에서 다른 답이 나온다.
EQUITY_SEMANTIC_OPERATIONS: tuple[str, ...] = (
    "DEMAND_INCREASE", "ORDER", "BACKLOG", "PRODUCE", "SHIP", "RECOGNIZE_REVENUE",
    "EXPAND_CAPACITY", "PRICE_CHANGE", "COST_INCREASE", "PASS_THROUGH_COST",
    "MIX_SHIFT", "ACCUMULATE_PROFIT", "REVALUE", "RISK_BREAK",
)
# 단계 문장 → 사업 의미. **먼저 맞는 것이 이긴다**(아래 순서가 곧 우선순위다).
# 순서가 중요한 이유: "수주잔고가 쌓인다"는 ORDER 와 BACKLOG 어휘를 둘 다 갖는데
# 화면에서 벌어지는 일은 **누적**이다. 더 구체적인 쪽을 앞에 둔다.
EQUITY_SEMANTIC_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("BACKLOG", ("수주잔고", "수주 잔고", "잔고", "backlog", "order book", "수주 residual")),
    ("RECOGNIZE_REVENUE", ("매출로 인식", "매출 인식", "매출인식", "revenue recognition",
                           "recognize revenue", "매출에 반영", "실적에 반영")),
    ("EXPAND_CAPACITY", ("증설", "capa", "케파", "생산능력", "capacity expansion",
                         "설비 투자", "설비투자", "공장 신설", "라인 증설")),
    ("PASS_THROUGH_COST", ("원가 전가", "원가전가", "가격 전가", "판가 전가",
                           "pass-through", "pass through")),
    ("MIX_SHIFT", ("믹스", "mix shift", "제품 구성", "고마진 제품 비중", "비중 상승",
                   "product mix")),
    ("ORDER", ("수주", "신규 수주", "발주", "주문", "order intake", "new order", "계약 체결")),
    ("PRODUCE", ("생산", "제조", "가동", "production", "manufactur", "라인 가동")),
    ("SHIP", ("납품", "출하", "인도", "shipment", "deliver", "선적")),
    ("PRICE_CHANGE", ("판가", "가격 인상", "가격 인하", "단가", "price increase", "asp")),
    ("COST_INCREASE", ("원가 상승", "원가상승", "비용 증가", "cost increase", "원자재 가격")),
    ("ACCUMULATE_PROFIT", ("영업이익", "이익률", "이익 개선", "마진", "operating profit",
                           "margin", "수익성")),
    ("REVALUE", ("목표주가", "목표가", "밸류에이션", "멀티플", "per", "pbr", "ev/ebitda",
                 "target price", "valuation", "multiple", "재평가")),
    ("RISK_BREAK", ("리스크", "위험", "둔화", "지연", "취소", "risk", "delay", "cancel",
                    "하향", "부진")),
    ("DEMAND_INCREASE", ("수요", "투자 확대", "전력망 투자", "발주 확대", "demand",
                         "데이터센터 증가", "전력 수요")),
)
# 사업 의미 → (화면 연산, 상태 변이 연산, 지속 개체, 카메라).
#   ★ 화면 연산은 `VISUAL_OPERATIONS`, 변이는 `MUTATION_OPERATIONS`, 카메라는
#     `CAMERA_OPERATIONS` 안에서만 고른다 — 금융용으로 enum 을 복제하지 않는다(§3).
#   ★ 지속 개체는 §10 목록이다. "돈"을 모든 장면에 쓰지 않는다 — 수주는 주문서 블록,
#     전력은 흐름, 생산은 제품 단위가 더 자연스럽다.
EQUITY_OP_TRANSLATION: dict[str, dict[str, str]] = {
    "DEMAND_INCREASE":   {"operation": "FLOW",       "mutation": "GROW",
                          "entity": "DEMAND_FLOW",         "camera": "TRACK"},
    "ORDER":             {"operation": "TRANSFER",   "mutation": "APPEAR",
                          "entity": "ORDER_BLOCK",         "camera": "FOLLOW_OBJECT"},
    "BACKLOG":           {"operation": "ACCUMULATE", "mutation": "GROW",
                          "entity": "BACKLOG_QUEUE",       "camera": "DOLLY_OUT"},
    "PRODUCE":           {"operation": "ASSEMBLE",   "mutation": "TRANSFORM",
                          "entity": "FACTORY_LINE",        "camera": "TRACK"},
    "SHIP":              {"operation": "TRANSFER",   "mutation": "MOVE",
                          "entity": "PRODUCT_UNIT",        "camera": "FOLLOW_OBJECT"},
    "RECOGNIZE_REVENUE": {"operation": "TRANSFORM",  "mutation": "TRANSFORM",
                          "entity": "REVENUE_CONTAINER",   "camera": "DOLLY_IN"},
    "EXPAND_CAPACITY":   {"operation": "ASSEMBLE",   "mutation": "GROW",
                          "entity": "FACTORY_LINE",        "camera": "DOLLY_OUT"},
    "PRICE_CHANGE":      {"operation": "TRANSFORM",  "mutation": "TRANSFORM",
                          "entity": "PRODUCT_UNIT",        "camera": "HOLD"},
    "COST_INCREASE":     {"operation": "ACCUMULATE", "mutation": "GROW",
                          "entity": "COST_FLOW",           "camera": "HOLD"},
    "PASS_THROUGH_COST": {"operation": "SPLIT",      "mutation": "SPLIT_OFF",
                          "entity": "COST_FLOW",           "camera": "TRACK"},
    "MIX_SHIFT":         {"operation": "SPLIT",      "mutation": "TRANSFORM",
                          "entity": "PRODUCT_UNIT",        "camera": "TOP_DOWN"},
    "ACCUMULATE_PROFIT": {"operation": "ACCUMULATE", "mutation": "GROW",
                          "entity": "REVENUE_CONTAINER",   "camera": "DOLLY_OUT"},
    "REVALUE":           {"operation": "ISOLATE",    "mutation": "HIGHLIGHT",
                          "entity": "REVENUE_CONTAINER",   "camera": "HOLD"},
    "RISK_BREAK":        {"operation": "SPLIT",      "mutation": "DIM",
                          "entity": "BACKLOG_QUEUE",       "camera": "DOLLY_OUT"},
}
DEFAULT_EQUITY_SEMANTIC_OP: str = "DEMAND_INCREASE"
# 사업 의미 → **화면에서 무엇이 보이게 달라지는가**(en=프롬프트용, ko=사람용).
#
# ★★ 왜 리포트 문장을 그대로 쓰지 않는가(2026-08-30 실제 리포트로 잡음):
#   리포트 문장에는 정확한 수치가 들어 있다("지분 49.99%를 인수", "MACR 55% 이상").
#   그것을 화면 계약에 그대로 실으면 **생성 이미지에게 정확한 수치를 그리라고 요구**하는
#   것이고, VSEQ-7 이 그 자리에서 차단한다(실측: `vseq_quantitative_visual` 2건).
#   Phase 0 이 잰 것이 정확히 그것이다 — 생성모델은 개수를 의도대로 읽지 지키지 않는다.
#
#   수치는 **정밀 레이어(코드 렌더)와 claim_ids** 가 정확히 담당한다(코덱스 리뷰 R1).
#   화면 계약은 **방향과 동작**만 말한다. 리포트 문장은 버리지 않고 `reasoning_text` 로
#   남겨 운영자·게이트가 그대로 읽는다 — 지어내는 것이 아니라 **층을 나누는 것**이다.
EQUITY_CHANGE_PROSE: dict[str, dict[str, str]] = {
    "DEMAND_INCREASE":   {"en": "the incoming flow grows stronger and brighter",
                          "ko": "들어오는 흐름이 굵고 밝아진다"},
    "ORDER":             {"en": "a new order block arrives and lands in the bay",
                          "ko": "새 주문서 블록이 도착해 자리에 놓인다"},
    "BACKLOG":           {"en": "order blocks stack up higher in the holding bay",
                          "ko": "주문서 블록이 대기 구역에 더 높이 쌓인다"},
    "PRODUCE":           {"en": "the production line runs and assembles the unit",
                          "ko": "생산 라인이 돌며 제품이 조립된다"},
    "SHIP":              {"en": "finished units travel out along the outbound path",
                          "ko": "완성된 제품이 출하 경로를 따라 나간다"},
    "RECOGNIZE_REVENUE": {"en": "a unit dissolves into the reservoir, raising its level",
                          "ko": "제품이 저장조로 녹아들며 수위가 올라간다"},
    "EXPAND_CAPACITY":   {"en": "a new line section assembles alongside the existing one",
                          "ko": "기존 라인 옆에 새 라인이 조립되어 붙는다"},
    "PRICE_CHANGE":      {"en": "the unit's surface shifts to a richer finish",
                          "ko": "제품 표면이 더 고급스러운 마감으로 바뀐다"},
    "COST_INCREASE":     {"en": "the counter-stream thickens and darkens",
                          "ko": "역방향 흐름이 굵고 어두워진다"},
    "PASS_THROUGH_COST": {"en": "the counter-stream splits and is diverted downstream",
                          "ko": "역방향 흐름이 갈라져 하류로 넘어간다"},
    "MIX_SHIFT":         {"en": "the batch separates and the premium portion grows",
                          "ko": "묶음이 갈라지며 고급 제품 몫이 커진다"},
    "ACCUMULATE_PROFIT": {"en": "the reservoir fills further from below",
                          "ko": "저장조가 아래에서부터 더 차오른다"},
    "REVALUE":           {"en": "the reservoir is isolated and lit for inspection",
                          "ko": "저장조만 남고 조명이 집중된다"},
    "RISK_BREAK":        {"en": "the queue thins out and dims",
                          "ko": "대기 줄이 성기어지고 어두워진다"},
}
# 지속 개체의 외형 서술(§10). 프롬프트에 실리는 문장이라 **규격 토큰·숫자를 넣지 않는다.**
EQUITY_ENTITY_IDENTITY: dict[str, str] = {
    "DEMAND_FLOW":       "a stream of glowing energy moving through cabling",
    "ORDER_BLOCK":       "a slab-like contract block with a clean matte surface",
    "BACKLOG_QUEUE":     "a stack of contract blocks queued in a holding bay",
    "FACTORY_LINE":      "an industrial production line with conveyors and robotic arms",
    "PRODUCT_UNIT":      "a boxy grey industrial transformer unit",
    "REVENUE_CONTAINER": "a transparent reservoir that fills from below",
    "COST_FLOW":         "a darker counter-stream running against the main flow",
}
# **사업 기전으로 화면을 만드는** 논증 단위. 나머지(밸류에이션·비교)는 정확한 수치가
# 본체라 code viz 가 맞다(§6.2 "+130% 를 13개의 물체로 보여주지 않는다").
EQUITY_MECHANISM_UNIT_TYPES: tuple[str, ...] = (
    "DRIVER_CHAIN", "EARNINGS_BRIDGE", "CATALYST_PATH", "RISK_PATH", "SCENARIO",
)
# 시퀀스로 만들 최소 단계 수. 1단계짜리는 진행이 아니라 한 장면이다
# (공통 `sequence_is_progression` 도 stage 2개 미만을 진행으로 보지 않는다).
EQUITY_MIN_STAGES: int = _get_int("EQUITY_MIN_STAGES", 2)
EQUITY_SEQUENCE_ENABLED: bool = _get_bool("EQUITY_SEQUENCE_ENABLED", True)

# ─ 컴플라이언스 게이트 (명세 §5, PF1 심장) ─
# 층1 규칙기반 스캔용 정규식. block = 발행 차단, warn = 경고(승인 가능하되 표시).
# ★ 초안 목록이며 실 오탐/미탐 데이터로 계속 보강한다(명세 부록 C). 자본시장법 대응이라 보수적으로.
# 이중관리 지점: supabase/functions/generate-report-draft 와 동기화.
COMPLIANCE_BLOCK_PATTERNS: dict[str, tuple[str, ...]] = {
    "투자권유": (
        r"지금\s*사(라|세요|자)", r"매수\s*(하세요|추천|의견)", r"담(아라|으세요|자)",
        r"비중\s*확대", r"풀\s*매수", r"가즈아", r"줍줍", r"불타기", r"영끌",
    ),
    "미실현수익률": (
        r"상승\s*여력", r"[+\-]?\d+\s*%\s*(상승|수익|먹|오)", r"목표\s*수익률",
        r"\d+\s*배\s*(간다|갑니다|먹)", r"떡상",
    ),
    "단정예측": (
        r"무조건", r"반드시\s*오른", r"확실히\s*(오|상승)", r"100\s*%\s*(오|수익|상승)",
        r"보장", r"찐", r"틀림없",
    ),
}
COMPLIANCE_WARN_PATTERNS: dict[str, tuple[str, ...]] = {
    "과열소재": (r"테마주", r"급등주", r"품절주", r"세력"),
}
# 엔딩 면책 문구 — 산출물 필수(명세 5-2). 이 문자열(핵심 어구)이 대본에 없으면 '면책누락' 플래그.
REPORT_DISCLAIMER_TEXT: str = (
    "본 영상은 정보 제공 목적이며 투자 권유가 아닙니다. 투자 판단과 책임은 본인에게 있습니다."
)
# 하단 고정 자막의 출처 접두어. ★ 언어별로 갈라야 한다 — 면책 문구는 en 으로 바뀌는데
#   "출처"만 한글로 남아 영어 영상 하단에 `출처 하나증권 · For information only…` 가 나갔다.
#   그 한 단어 때문에 영어권 시청자에게는 오작동으로 보인다.
REPORT_SOURCE_LABEL_BY_LANG: dict[str, str] = {"ko": "출처", "en": "Source"}
# 면책/출처 존재 판정용 핵심 어구(부분일치).
COMPLIANCE_DISCLAIMER_MARKERS: tuple[str, ...] = ("투자 권유가 아", "판단과 책임", "정보 제공 목적")

# ─ PF2 영상화 (지시서→렌더) — 논문 VIDEO_* 대응. 렌더 엔진은 그대로 재사용 ─
REPORT_DEFAULT_VERSION: str = os.getenv("REPORT_DEFAULT_VERSION", "comic")  # config.VIDEO_VERSIONS 중
# 영상 상단 시리즈 제목(논문 SERIES_TITLE 대응). 언어별.
# 운영자 결정(2026-07-30): "하루 한 리포트" → "오늘의 리포트".
# 논문 시리즈("하루 한 편")를 그대로 변주한 이름이라 어색했다. 채널 통합 후 같은 채널에
# 두 시리즈가 나란히 놓이므로 이름이 서로 헷갈리지 않는 편이 낫다.
# 명세서 docs/specs/20260730-report-merge-into-paper-ko.md §6-1 의 열린 질문 해소.
REPORT_SERIES_TITLE: str = os.getenv("REPORT_SERIES_TITLE", "오늘의 리포트")
REPORT_SERIES_TITLE_BY_LANG: dict[str, str] = {
    "ko": REPORT_SERIES_TITLE,
    "en": os.getenv("REPORT_SERIES_TITLE_EN", "One Report A Day"),
}
# 하단 고정 면책 자막(build_ass footer). 사용자 요구: 면책은 씬이 아니라 하단 자막으로.
FOOTER_FONT_SIZE: int = 30            # 본문 자막보다 작게(눈에 띄되 방해 안 되게)
FOOTER_COLOR_ASS: str = "&H00D0D0D0&"  # 옅은 회색(&HAABBGGRR&)
FOOTER_MARGIN_V: int = 24             # 화면 맨 아래 근접(캡션 밴드 아래)

# ─ 금융 리포트 영상 시각·서사 강화 (C안 v1.1 · docs/강화지시서_금융리포트시각화_C안_v1.1.md) ─
# fin_charts 코드 도표 5종 + Arc A 서사 + Veo≤1 오프닝. 전 상수는 여기서(매직넘버 금지, CLAUDE.md 규칙).
# ★ 정합(deviation-fin-visual-v1): 지시서 §8 의 fin_* 신규 파일 대신 기존 report_* 를 확장한다.
#   fin_charts/ (도표 서브시스템, Codex 경계) 만 신규. 이 상수는 그 계약(fin_charts/types.py)이 참조.

# 서사(§3-2·§5). v1 구현은 Arc A + report_type=TARGET_REVISION 만(필드는 열어두되 라우팅 로직 없음).
FIN_SCENE_ROLES: tuple[str, ...] = (
    "HOOK", "REVEAL", "REASON", "EVIDENCE", "SNOWBALL", "BROKER_VIEW", "COLD_TRUTH", "MEANING",
)
FIN_REPORT_TYPES: tuple[str, ...] = (
    "TARGET_REVISION", "EARNINGS_REVIEW", "EARNINGS_PREVIEW", "INDUSTRY",
    "INITIATION", "EVENT", "VALUATION", "RISK",
)
FIN_REPORT_TYPE_DEFAULT: str = "TARGET_REVISION"    # v1 은 전부 이 유형으로 처리(분기 없음)
FIN_REVEAL_POLICIES: tuple[str, ...] = ("IMMEDIATE", "DELAYED", "PARTIAL")
FIN_REVEAL_POLICY_DEFAULT: str = "DELAYED"          # 기본 후보 전략(근거 필수), IMMEDIATE 시 회사명 숨김 금지
FIN_REVEAL_DELAY_SEC: float = 6.0                   # DELAYED 시 회사명 이 시각 이전 미노출(§9 QA)
FIN_NARRATIVE_ARCS: tuple[str, ...] = ("A", "B", "C", "D", "E")  # enum. v1 구현은 A(미스터리형)만
FIN_NARRATIVE_ARC_DEFAULT: str = "A"

# 에셋 소스(§3-2 cuts). code_chart·editorial_composite = 코드 합성($0), image = 유료(product_visual 포함).
FIN_ASSET_SOURCES: tuple[str, ...] = (
    "veo", "image", "code_chart", "editorial_composite", "product_visual",
)
FIN_ZERO_COST_ASSET_SOURCES: tuple[str, ...] = ("code_chart", "editorial_composite")  # 생성 API 스킵→$0

# 코드 도표 5종(§4, LS v2 역산). Codex 소유 templates/ 가 구현.
FIN_CHART_TEMPLATES: tuple[str, ...] = (
    "step_climb", "dual_marker", "gauge_fill", "number_count", "race_bar",
)

# Veo 정책(§3-2·§3-6). 훅/리빌 최대 1컷. 실패 시 폴백(§12-2 확정: EDITORIAL_MOTION).
FIN_VEO_POLICY_DEFAULT: str = "OPTIONAL"            # OPTIONAL(0 허용) | REQUIRED
FIN_VEO_MAX_CLIPS: int = 1
FIN_VEO_FALLBACKS: tuple[str, ...] = ("EDITORIAL_MOTION", "STILL_MOTION", "MANUAL_REVIEW")
FIN_VEO_FALLBACK_DEFAULT: str = "EDITORIAL_MOTION"  # 코드 오프닝 자동 폴백(§12-2)
# Veo 프롬프트 필수 접미(화면 글자 억제). motion_prompt 뒤에 항상 합류(§5).
FIN_VEO_NEGATIVE_SUFFIX: str = "no text, no captions, no labels, no numbers, no watermarks"

# 비용(§3-6). 편당(KO+EN) 목표 ≤$0.30, 하드캡 $0.40. normalize 가 컷 구성으로 재계산(자기보고 불신).
FIN_RENDER_COST_TARGET_USD: float = 0.30
FIN_RENDER_COST_CAP_USD: float = 0.40
FIN_IMAGE_MAX_CUTS: int = 2                         # image(product_visual 포함) ≤ 2

# 면책·오버레이(§7). 면책 카드 ≥2.0초 + BGM 덕킹. 재질 배분 가이드(§5): 코드수치 50~65% / 의미 20~30% / 출처·리스크 10~20%.
FIN_DISCLAIMER_MIN_SEC: float = 2.0
FIN_DISCLAIMER_TEXT: str = (
    "본 영상은 {broker} 리포트({date})를 재구성한 정보 제공 콘텐츠이며 투자 권유가 아닙니다. "
    "투자 판단과 책임은 본인에게 있습니다."
)

# 디자인 토큰(§3-4 DesignTokens 기본값). fin_charts/types.py DesignTokens 가 이 값을 기본으로 읽는다.
# 색: 배경/앰버(위험·반전·핵심 수치 전용)/포인트 블루(§4 공통).
# ★ 값을 여기 적지 않는다 — visual_contract.TOKENS 에서 파생시킨다(§7-4 토큰 통일).
#   예전엔 같은 색이 이 파일과 visual_contract 와 board_render 세 곳에 각각 적혀 있었고,
#   실제로 board_render 의 fg·muted 만 갈라져 있었다. 파생시키면 갈라질 수가 없다.
FIN_TOKEN_BG: str = visual_contract.token_hex("bg")
FIN_TOKEN_ACCENT: str = visual_contract.token_hex("accent")    # 앰버 — 위험·반전·핵심 수치에만
FIN_TOKEN_POINT: str = visual_contract.token_hex("point")      # 포인트 블루
# 숫자 폰트(§12-1). ★ 기본은 러너 설치·라이선스 확인된 NanumGothic(=MANIM_FONT). 에스코어드림 9 Black·
#   Anton 은 임베딩 라이선스 확인 후 env 로 opt-in(Anton=Google Fonts OFL 안전, 에스코어드림만 확인 대기).
FIN_NUM_FONT_KO: str = os.getenv("FIN_NUM_FONT_KO", MANIM_FONT)
FIN_NUM_FONT_EN: str = os.getenv("FIN_NUM_FONT_EN", MANIM_FONT)

# ─ 설명판형 explainer (개선명세서 v3.3 · docs/deviation-explainer-v3_3.md) ─
# "누가 · 무엇을 근거로 · 어떤 숫자를 · 왜 중요하게" 를 화면에서 명시하는 리포트 해석 영상.
# ★ 전 상수 여기에서(매직넘버 금지). 소비처: engine/explainer.py · engine/report_directive.py · web.

# §4-1 프로필. 소재 유형에 따라 필수 보드가 달라진다.
EXPLAINER_PROFILES: tuple[str, ...] = ("NUMERIC", "MECHANISM", "EVENT")
EXPLAINER_PROFILE_DEFAULT: str = "NUMERIC"

# 원문 확보 수준(v3.2 source_mode). ★ 이 저장소는 리포트 **원문 전문을 수집하지 않는다**
#   (reports.summary = 핵심요약, 본문은 report_url 에 둔다 — supabase/migrations/0018 주석).
#   그래서 FULL_REPORT 는 PDF 수집이 생기기 전까지 **도달할 수 없는 값**이고, 코드가 데이터로
#   판정한다(모델 자기보고 불신). 근거·한계는 deviation-explainer-v3_3.md §2.
EXPLAINER_SOURCE_MODES: tuple[str, ...] = ("FULL_REPORT", "PARTIAL_REPORT", "NEWS_ONLY")
EXPLAINER_SOURCE_MODE_DEFAULT: str = "NEWS_ONLY"

# §5 보드 시스템. 컷마다 `board` 를 하나 지정한다(자유 텍스트 금지).
EXPLAINER_BOARDS: tuple[str, ...] = (
    "HOOK_BOARD", "CLAIM_BOARD", "NUMBER_BOARD", "CHART_BOARD", "EVIDENCE_BOARD",
    "REPORT_REASON_BOARD", "MECHANISM_BOARD", "VALUATION_BOARD", "COMPARISON_BOARD",
    "WATCHPOINT_BOARD", "CONTEXT_BOARD",
)
EXPLAINER_BOARD_DEFAULT: str = "CONTEXT_BOARD"
# 보드 → 컷 scene_kind. 렌더는 scene_kind 로 화면을 고르므로 보드가 실제 화면에 반영된다.
EXPLAINER_BOARD_SCENE_KIND: dict[str, str] = {
    "HOOK_BOARD": "motion_graphic",
    "CLAIM_BOARD": "kinetic_typography",
    "NUMBER_BOARD": "kinetic_typography",
    "CHART_BOARD": "data_viz",
    "EVIDENCE_BOARD": "data_viz",
    "REPORT_REASON_BOARD": "kinetic_typography",
    "MECHANISM_BOARD": "motion_graphic",
    "VALUATION_BOARD": "data_viz",
    "COMPARISON_BOARD": "data_viz",
    "WATCHPOINT_BOARD": "kinetic_typography",
    "CONTEXT_BOARD": "broll_stock",
}
# §4-1 프로필별 필수 보드(하나라도 없으면 깊이 경고). EVIDENCE_BOARD 는 전 프로필 공통 의무(§P2).
EXPLAINER_PROFILE_REQUIRED_BOARDS: dict[str, tuple[str, ...]] = {
    "NUMERIC": ("NUMBER_BOARD", "EVIDENCE_BOARD"),
    "MECHANISM": ("MECHANISM_BOARD", "EVIDENCE_BOARD"),
    "EVENT": ("HOOK_BOARD", "EVIDENCE_BOARD"),
}
# §P2·§8-1 근거 보드 최소 개수(차단) / 권장 개수(경고).
EXPLAINER_MIN_EVIDENCE_BOARDS: int = 1
EXPLAINER_RECOMMENDED_EVIDENCE_BOARDS: int = 2

# §7 길이 정책 — 초 단위 하드 규칙 대신 **비트 수**. 컷마다 beat_role 을 지정한다.
EXPLAINER_BEAT_ROLES: tuple[str, ...] = (
    "HOOK", "QUESTION", "CLAIM", "EVIDENCE", "MECHANISM", "RISK", "WATCHPOINT",
)
EXPLAINER_BEAT_ROLE_DEFAULT: str = "EVIDENCE"

# ─ 초안 **씬** 역할 (v3 §5-4·§6) ─
# ★ 왜 별도 상수인가: 역할 어휘가 이미 3벌이다 — EVIDENCE_ROLES(논문 컷 10종),
#   EXPLAINER_BEAT_ROLES(설명판 컷 7종), story_plan 의 주장 역할. 셋을 합치면 어느 계층의
#   이름인지 알 수 없게 된다. 진짜 구멍은 **초안 씬**에 역할이 아예 없다는 것이었고(그래서
#   §5-4 면제를 걸 키가 없었다), 그 구멍만 메운다.
# ★ EXPLAINER_BEAT_ROLES 자체에 값을 더하지 않는다 — 그 enum 은 explainer.depth_gate 의
#   비트 수 판정에 쓰이고, 값을 늘리면 지시서 LLM 이 새 값을 써서 판정이 흔들린다.
SCENE_ROLES: tuple[str, ...] = EXPLAINER_BEAT_ROLES + ("CTA", "BRIDGE")
SCENE_ROLE_DEFAULT: str = "EVIDENCE"
# §5-4 자기검증 면제 — 훅·질문·마무리·연결부는 사실 주장이 아니다. 실측: 최근 초안 6/6 이
# 첫 씬과 마지막 씬에서 "근거 불충분" 오탐을 받아 빨간 깃발이 신호로서 죽어 있었다
# (docs/phase0-영상엔진품질_v3.md §4).
SCENE_ROLES_EVIDENCE_EXEMPT: tuple[str, ...] = ("HOOK", "QUESTION", "CTA", "BRIDGE")
# ★ 면제 남용 상한. 모델이 전 씬에 HOOK 을 붙이면 자기검증이 통째로 무력해진다(적대적 리뷰
#   재현: 진짜 환각 7건에도 all_grounded=True). 역할 이름표만 믿지 않는다.
SELFCHECK_EXEMPT_MAX_RATIO: float = _get_float("SELFCHECK_EXEMPT_MAX_RATIO", 0.4)

# §6 story_plan 의 주장 역할. 씬 역할과 **축이 다르다** — 씬 역할은 "이 씬이 화면에서 하는 일",
# 이쪽은 "이 주장이 논증에서 하는 일"이다. 주장 수(3~6)와 씬 수(6~7)가 달라 합칠 수 없다.
STORY_CLAIM_ROLES: tuple[str, ...] = (
    "hook", "reveal", "proof", "mechanism", "valuation", "risk", "closing",
)
STORY_CLAIM_MIN: int = _get_int("STORY_CLAIM_MIN", 3)
STORY_CLAIM_MAX: int = _get_int("STORY_CLAIM_MAX", 6)
# §6 텍스트 밀도 — 읽기 속도(글자/초). 화면 텍스트가 컷 길이 안에 읽히는지 볼 때 쓴다.
STORY_READ_CHARS_PER_SEC: float = _get_float("STORY_READ_CHARS_PER_SEC", 9.0)
# ★ 발화 속도(글자/초). **렌더된 영상 68컷을 실측한 중앙값 7.64**(범위 5.9~8.7, KO/edge-tts).
#   왜 필요한가: 컷 길이는 초안이 적어 둔 duration_sec 가 아니라 **나레이션 실측 길이**로
#   나간다(engine/assemble.py:119 "duration 은 나레이션 실측"). 그래서 나레이션을
#   duration_sec 와 비교하면 렌더에 존재하지 않는 조건을 검사하게 된다 — 실제로 최근 초안
#   12편 중 12편에서 씬 대부분이 "다 읽을 수 없다" 경고를 받았고(평균 6.6개 중 5.75개),
#   같은 편의 완성 영상은 계획 25~30초가 아니라 43~59초로 정상 재생됐다.
#   근거·되돌리기: docs/deviation-density-warning.md
STORY_SPEAK_CHARS_PER_SEC: float = _get_float("STORY_SPEAK_CHARS_PER_SEC", 7.6)
# 계획 길이와 발화 기준 예상 길이가 이 비율 넘게 어긋나면 경고 1건(씬마다가 아니라 편마다).
STORY_DURATION_TOLERANCE: float = _get_float("STORY_DURATION_TOLERANCE", 0.25)
STORY_MAX_NUMBERS_PER_SCENE: int = _get_int("STORY_MAX_NUMBERS_PER_SCENE", 2)
EXPLAINER_BEATS_MIN: int = 6           # §7-2 기본 골격 6~8비트(참고 범위 — 경고만)
EXPLAINER_BEATS_MAX: int = 8
EXPLAINER_MIN_EVIDENCE_BEATS: int = 2  # §P5 근거 비트 2~3개
# §4-4 메커니즘 비트 의무화 — 이 역할이 하나도 없으면 "숫자 나열형"으로 남는다(경고).
EXPLAINER_MECHANISM_BEAT_ROLE: str = "MECHANISM"

# §6 숫자 규칙. 대형 숫자 보드의 주인공이 되려면 아래 자격 필드가 2개 이상 있어야 한다(§6-2).
EXPLAINER_NUMBER_COMPARISON_BASES: tuple[str, ...] = (
    "연간 목표", "전년 동기", "과거 평균", "컨센서스", "경쟁사", "직전 분기", "가이던스",
)
EXPLAINER_NUMBER_QUALIFIER_FIELDS: tuple[str, ...] = (
    "comparison_basis", "comparison_value", "why_significant", "fact_refs", "page_refs",
)
EXPLAINER_NUMBER_MIN_QUALIFIERS: int = 2
EXPLAINER_MAX_NUMBER_CLAIMS: int = 6   # 한 편에 숫자를 6개 넘게 담으면 아무것도 안 남는다

# §8-2 승인 전 필수 — 인사이트 조각 최소 개수.
EXPLAINER_MIN_INSIGHT_NUGGETS: int = 2

# §9-3 시각 게이트. CLAIM_BOARD 가 텍스트 덩어리가 되면 읽히지 않는다.
EXPLAINER_CLAIM_BOARD_MAX_CHARS: int = 60
EXPLAINER_STATEMENT_MAX_CHARS: int = 120   # report_claim_summary.statement 한 문장 상한

# 승인 차단을 운영자가 넘길 수 있는 탈출구를 남긴다(신규 경로 락아웃 방지).
# ★ 넘긴 사실은 승인 라우트가 로그로 남긴다 — 조용한 우회가 아니다.
EXPLAINER_GATE_FORCE_ALLOWED: bool = _get_bool("EXPLAINER_GATE_FORCE_ALLOWED", True)


# ─ 설명판형 코드 렌더 보드 (최종명세 v3.3 §20-3 밴드 그리드 · §21 킬 스위치) ─
# ★ 왜 코드로 그리는가: 이미지 생성 모델에 "데이터 보드"를 시키면 **가짜 대시보드에 가짜 숫자**를
#   그린다(실측: 243.5%·45.4%·27.5% 가 근거 없이 화면에 박혔다). 시청자는 그걸 리포트 수치로
#   읽는다 — 품질 문제가 아니라 컴플라이언스 사고다(§21 K1). 화면의 숫자·차트·축·범례는
#   전부 코드가 그린다. 생성 이미지는 CONTEXT_BOARD 배경으로만.

# §20-3 세로 밴드 그리드. ★ 좌표의 원본은 여기가 아니라 engine/visual_contract.py 다
# (v3.4 §22-1: 그 모듈이 규범이고, 산문 명세나 다른 코드와 충돌하면 모듈이 이긴다). 여기서는
# 렌더 해상도에 맞춰 **픽셀로 해소만** 한다 — 절대좌표를 두 곳에 적으면 반드시 어긋난다(F2).
EXPLAINER_BANDS: dict[str, tuple[int, int]] = {
    b.name: (visual_contract.y_of(b.name, 0.0, RENDER_HEIGHT),
             visual_contract.y_of(b.name, 1.0, RENDER_HEIGHT))
    for b in visual_contract.BANDS
}
EXPLAINER_SAFE_X: tuple[int, int] = visual_contract.x_bounds(RENDER_WIDTH)
EXPLAINER_CORE_ANCHOR_Y: int = int(visual_contract.CORE_ANCHOR_R * RENDER_HEIGHT)
EXPLAINER_CORE_MIN_FILL: float = visual_contract.CORE_MIN_AREA_FILL
# ★ 레이아웃 실패 중 "잡을 죽이지 않고 사람에게 넘길 것"(2026-08-19).
#   배경: 충전율 판정을 warn→fail 로 올린 뒤(v3 §9) 설명판형 렌더 8건 중 5건이 전부
#   core_underfilled 하나로 죽었고, 그 상태로 2주간 이 버전이 멈췄다. 판정 자체는 옳다 —
#   빈 보드가 그대로 발행되는 것을 막았다. 틀린 것은 **처리 방식**이다: 이미 이미지·TTS·조립
#   비용을 다 쓴 뒤 산출물을 버리고, 운영자에게는 실패 로그 한 줄만 남았다.
#   이제 이 목록의 사유는 mp4 를 만들어 올린 뒤 잡을 degraded(사람 승인 대기)로 둔다 —
#   ⑥ 화면 "조치 필요" 탭에서 영상을 **보고** 판단할 수 있다. 화면 규격 위반(밴드 침범·
#   안전선 초과·중복 텍스트)은 그대로 즉시 실패다.
LAYOUT_FAIL_REVIEWABLE: tuple[str, ...] = ("core_underfilled",)

# ── Q3 애니메이션 계약 검사(지시서 v3 §9 · engine/animation_qa.py) ────────────
# ★ 왜 생겼나: component_registry 가 컴포넌트마다 min_change_ratio 를 선언해 놨는데
#   **그 값을 읽는 코드가 없었다**(2026-09-03). 계약만 있고 검사가 없으면 카운트업이
#   정지된 숫자로 나가도 아무도 모른다. §14-1 하드 게이트가 Phase 4 조건으로 걸어 놨다.
ANIM_QA_ENABLED: bool = _get_bool("ANIM_QA_ENABLED", True)
# 픽셀이 "달라졌다"고 볼 최소 차이(0~255). JPEG/PNG 양자화 잡음보다 크게 잡는다.
ANIM_QA_PIXEL_TOL: int = _get_int("ANIM_QA_PIXEL_TOL", 12)
# 중간 프레임이 끝 프레임보다 이만큼 넘게 더 변했으면 "갔다가 되돌아왔다"로 본다(경고).
ANIM_QA_MONOTONIC_SLACK: float = _get_float("ANIM_QA_MONOTONIC_SLACK", 0.15)
# 사유 코드 접두사. animation_qa 와 render_manifest 가 **같은 문자열**을 봐야 한다.
ANIM_QA_REASON_PREFIX: str = "animation_contract:"
# 표본 축소 크기. 판정은 "잉크 중 얼마가 달라졌나"라 해상도가 필요 없다 —
# 원본(1080×681)으로 세 프레임을 훑으면 컷마다 220만 픽셀 × 3 이 렌더 시간에 얹힌다.
ANIM_QA_SAMPLE_W: int = _get_int("ANIM_QA_SAMPLE_W", 216)
ANIM_QA_SAMPLE_H: int = _get_int("ANIM_QA_SAMPLE_H", 136)

# 코드 렌더 전용 보드(§21 K2 — 생성 자산 절대 금지). 이 목록 밖은 생성 이미지 배경 허용.
EXPLAINER_CODE_RENDER_BOARDS: tuple[str, ...] = (
    "HOOK_BOARD", "CLAIM_BOARD", "NUMBER_BOARD", "CHART_BOARD", "EVIDENCE_BOARD",
    "REPORT_REASON_BOARD", "MECHANISM_BOARD", "VALUATION_BOARD", "COMPARISON_BOARD",
    "WATCHPOINT_BOARD",
)

# 보드 폰트 — v3.4 §22 K8. ★ **폴백 후보 목록을 없앴다.** 이전에는 나눔→유니폰트→데자뷰 순으로
#   존재하는 것을 조용히 골랐는데, 그 결과 러너·로컬·샌드박스가 서로 다른 폰트로 렌더했고
#   최악의 경우 한글 없는 폰트가 걸려 미학이 무너졌다(실측 결함 F1). 이제 저장소가 폰트를
#   들고 다니고(assets/fonts/, OFL), 없으면 visual_contract.load_font 가 예외로 죽는다.
#   역할별 파일 지정은 visual_contract.FONT_FILES 가 유일한 원본이다.
EXPLAINER_FONT_SIZES: dict[str, int] = {
    "meta": 34, "title": 62, "big_number": 170, "number_unit": 56,
    "label": 42, "sowhat": 44, "source": 30, "body": 40,
}
# CORE 문장 보드(HOOK·CLAIM·MECHANISM·REPORT_REASON·WATCHPOINT)에서 글자를 키울 상한.
# ★ §20-3 "CORE 가 비면 요소를 키운다" — 짧은 문장을 기준 크기(62)로 큰 패널에 넣으면
#   아래 절반이 빈 검은 상자로 남는다(실측). 담기는 한도까지 키우되, 대형 숫자(170)와
#   위계가 뒤집히지 않게 그 아래에서 멈춘다.
EXPLAINER_CORE_TEXT_MAX_SIZE: int = 104
# ★ 폴백으로 숫자 카드가 CORE 를 혼자 쓸 때만 쓰는 상한. 원래 자리(NUMBER_BOARD)에서는
#   다른 요소와 자리를 나누므로 big_number(170) 그대로다. 혼자 쓸 때 그 크기로 두면 넓은
#   CORE 가 휑하게 남아 충전율 게이트(0.25)에 걸린다 — 실측 0.217 로 잡이 죽었다.
EXPLAINER_FALLBACK_NUMBER_MAX_SIZE: int = 260
# 크기 → 폰트 역할(visual_contract.FONT_FILES 의 키). 렌더러는 역할로만 폰트를 요청한다.
EXPLAINER_FONT_ROLES: dict[str, str] = {
    "meta": "small", "title": "head", "big_number": "num_ko", "number_unit": "head",
    "label": "body", "sowhat": "body", "source": "small", "body": "body",
}

# 단계 등장(§9) — 보드는 한 번에 다 뜨지 않고 나레이션에 맞춰 정보가 밝혀진다.
EXPLAINER_STAGE_MIN_SEC: float = 0.6      # 한 단계 최소 노출
EXPLAINER_STAGE_MAX: int = 4              # 보드당 최대 단계 수

# §9 모션 — ★ 보드는 PNG 슬라이드쇼가 아니라 프레임 시퀀스다. v3.3 구현이 정지 화면을 툭툭
#   바꾸는 방식이라 §5-2 "정적 텍스트가 주인공인 화면 금지"를 정면으로 어겼다(운영자 검수에서
#   드러남). 막대는 자라고 숫자는 올라가야 스와이프 판단 시점에 볼 것이 있다.
EXPLAINER_MOTION_FPS: int = 30
EXPLAINER_MOTION_LEAD_IN: float = 0.15    # 첫 요소가 뜨기까지(§10 "첫 음성 0.2~0.4초 내")
EXPLAINER_MOTION_STEP_SEC: float = 0.75   # 한 단계가 자라는 데 걸리는 시간
EXPLAINER_MOTION_TAIL: float = 0.5        # 마지막 요소 도착 후 읽을 여유
# ★ EXPLAINER_CORE_TARGET_FILL(=0.70) 를 제거했다. 읽는 코드가 0곳인 죽은 상수였고,
#   실측에서 **21컷 전부 미달**이라 도달 불가능한 값이다(docs/measure-core-fill-2026-08-03.md).
#   남겨 두면 "명세가 0.70 이라던데"라는 오해가 계속 생긴다. 실제 기준은 위
#   EXPLAINER_CORE_MIN_FILL 하나뿐이다.
# §20-2 "맨 배경 금지" — 차트 씬은 그리드 배경(가독성 우선), 텍스트 씬은 딤 처리 실사 배경.
EXPLAINER_GRID_SPACING: int = 60
EXPLAINER_BG_DIM_BRIGHTNESS: float = 0.45   # 밝기 0.40~0.50
EXPLAINER_BG_NAVY_ALPHA: int = 175          # 네이비 오버레이 α 165~185
EXPLAINER_TEXT_STROKE_PX: int = 3           # 배경 위 텍스트 스트로크 2~4px

# §20-3 full_bleed 전환 시 자막·출처 바를 밴드 안으로 올리는 마진(화면 바닥 기준 px).
EXPLAINER_CAPTION_MARGIN_V: int = 1920 - EXPLAINER_BANDS["CAPTION"][1]   # 519
EXPLAINER_SOURCE_MARGIN_V: int = 1920 - EXPLAINER_BANDS["SOURCE"][1]     # 419

# §21 K5 편당 생성비 하드캡. FIN_RENDER_COST_CAP_USD(C안 라인, $0.40)와 별개다 —
# 두 명세가 다른 숫자를 요구한다. 설명판형은 코드 렌더가 주역이라 더 낮게 잡는다.
# ★ 2026-08-03 배선: 이 상수는 정의만 돼 있고 **읽는 곳이 한 군데도 없었다**(grep 0건).
#   실제로 작동하던 캡은 RENDER_BUDGET_CAP_USD($1.2) 하나뿐 — 명세값의 5배였다.
# ★ 실측(2026-08-03, 운영 DB report_render_jobs 조회): 설명판형 1편 = **$0.039**.
#   캡 $0.25 는 실측의 6배라 여유가 크다 — "코드 렌더가 주역이라 더 싸다"는 명세의 전제가
#   맞았다. 대조군으로 같은 DB 의 comic 3편은 $0.595·$0.634·$0.673 였다(그래서 comic 은
#   계속 $1.2 를 쓴다). env 로 올릴 수 있게는 남겨 둔다 — 설명판형에 생성 이미지가 늘면
#   이 실측이 낡는다. 그때는 코드가 아니라 EXPLAINER_COST_CAP_USD 를 올리고 여기를 갱신한다.
EXPLAINER_COST_CAP_USD: float = _get_float("EXPLAINER_COST_CAP_USD", 0.25)
# 캡에 닿기 전에 미리 경고하는 지점(캡 대비 비율). 캡은 잡을 죽이므로, 죽기 전에 "얼마까지
# 왔는지"가 로그에 남아야 실측 없이 캡을 정한 것을 사후에 교정할 수 있다.
RENDER_COST_WARN_RATIO: float = _get_float("RENDER_COST_WARN_RATIO", 0.7)


def video_clips_max(version_type: str = "", mode_limit: int | None = None) -> int:
    """이 버전의 I2V 클립 개수 상한. 버전 지정이 있으면 그것이 이긴다.

    ★ 상한이 두 겹인 이유(둘 다 남긴다): 모드별 표(D-E1)는 "이 길이의 콘텐츠에 영상이 몇 개
      필요한가"를, 전역 캡은 "어떤 경우에도 이보다 많이 사지 않는다"를 지킨다. 실사형은 둘 다
      풀어야 벤치마크 문법(움직이는 화면)이 나온다 — 한쪽만 풀면 다른 쪽이 다시 4개로 자른다.
    """
    override = VIDEO_CLIPS_MAX_BY_VERSION.get(version_type)
    if override is not None:
        return override
    return VEO_MAX_CLIPS_PER_DRAFT if mode_limit is None else mode_limit


def unique_assets_max(version_type: str = "", mode_limit: int | None = None,
                      cut_count: int = 0) -> int:
    """이 버전의 **신규 생성 이미지** 상한. 실사형은 컷 수에 붙는다.

    ★ 왜 버전을 보는가(2026-08-29): 모드별 표는 만화식 전제로 잡힌 고정값(standard=6)이라,
      컷이 11개인 실사형에 그대로 걸면 5컷이 강제로 복제된다 — 실제로 그렇게 나왔다.
      실사형은 컷 수의 PHOTO_UNIQUE_ASSET_RATIO 만큼까지 새로 만들 수 있게 한다.
      나머지 여유분은 "재사용해도 되는 자리"지 "재사용해야 하는 자리"가 아니다.
    """
    base = SERIES_SPLIT_MAX_UNIQUE_ASSETS if mode_limit is None else mode_limit
    if version_type != "photo" or cut_count <= 0:
        return base
    return max(base, PHOTO_MIN_UNIQUE_ASSETS,
               int(round(cut_count * PHOTO_UNIQUE_ASSET_RATIO)))


def render_budget_cap(version_type: str = "") -> float:
    """이 버전 타입의 편당 생성비 하드캡(§21 K5).

    ★ 실사형만 더 높다. 실사형은 컷이 10~14개로 만화식(6~8)의 두 배고, 벤치마크 문법상
      영상 클립 비중도 높다 — 기존 $1.2 는 "컷 7~8개 + 클립 4개" 전제로 잡힌 값이라
      실사형에서는 렌더 도중에 터진다(실측 계산: 12컷·4클립 = $1.27).
      캡은 하드 스톱이라(report_render.py) 터지면 이미 쓴 돈은 못 돌려받는다.
    """
    if version_type == "explainer":
        return EXPLAINER_COST_CAP_USD
    if version_type == "photo":
        return PHOTO_COST_CAP_USD
    return RENDER_BUDGET_CAP_USD

# §21 K1 — explainer 생성 이미지 전용 네거티브. ★ BURN_IN_NEGATIVE_PROMPT 는 건드리지 않는다
#   (comic 출력 바이트 불변 계약 — providers/image.py 주석 + tests/test_image_prompt.py).
EXPLAINER_IMAGE_NEGATIVE_PROMPT: str = (
    "no charts, no graphs, no dashboards, no data visualization, no UI panels, "
    "no infographic, no percentages, no axes, no legends, no diagrams"
)


# ─────────────────────────────────────────────────────────────
# 시크릿 / 접속 정보  (서버·엔진 전용 — 클라이언트 노출 금지)
# ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Secrets:
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    deepseek_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    jev_api_key: str = field(default_factory=lambda: os.getenv("JEV_API_KEY", ""))
    elevenlabs_api_key: str = field(default_factory=lambda: os.getenv("ELEVENLABS_API_KEY", ""))
    higgsfield_api_key: str = field(default_factory=lambda: os.getenv("HIGGSFIELD_API_KEY", ""))
    supabase_url: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    supabase_service_key: str = field(default_factory=lambda: os.getenv("SUPABASE_SERVICE_KEY", ""))
    openalex_mailto: str = field(default_factory=lambda: os.getenv("OPENALEX_MAILTO", ""))
    # 리포트 팩토리 — ARIA HTTP API 키(설정 시 HTTP 클라이언트, 없으면 fixture 모드).
    aria_api_key: str = field(default_factory=lambda: os.getenv("ARIA_API_KEY", ""))
    arxiv_contact: str = field(default_factory=lambda: os.getenv("ARXIV_CONTACT", ""))
    reddit_client_id: str = field(default_factory=lambda: os.getenv("REDDIT_CLIENT_ID", ""))
    reddit_client_secret: str = field(default_factory=lambda: os.getenv("REDDIT_CLIENT_SECRET", ""))
    reddit_user_agent: str = field(default_factory=lambda: os.getenv("REDDIT_USER_AGENT", "video-article/0.1"))
    # 유튜브 업로드 OAuth(채널 공통 클라이언트 + 언어별 리프레시 토큰).
    youtube_client_id: str = field(default_factory=lambda: os.getenv("YOUTUBE_CLIENT_ID", ""))
    youtube_client_secret: str = field(default_factory=lambda: os.getenv("YOUTUBE_CLIENT_SECRET", ""))
    youtube_refresh_token_ko: str = field(default_factory=lambda: os.getenv("YOUTUBE_REFRESH_TOKEN_KO", ""))
    youtube_refresh_token_en: str = field(default_factory=lambda: os.getenv("YOUTUBE_REFRESH_TOKEN_EN", ""))
    # (리포트 전용 토큰 필드는 채널 통합으로 제거 — 명세서 20260730-report-merge-into-paper-ko §4.
    #  되돌릴 때 youtube_refresh_token_report_ko 필드와 레지스트리 값을 함께 복원한다.)
    # 유튜브 쇼츠 성과 조회 OAuth(읽기 전용 스코프). 비면 업로드 토큰으로 폴백(providers/youtube.py).
    youtube_analytics_refresh_token_ko: str = field(default_factory=lambda: os.getenv("YOUTUBE_ANALYTICS_REFRESH_TOKEN_KO", ""))
    youtube_analytics_refresh_token_en: str = field(default_factory=lambda: os.getenv("YOUTUBE_ANALYTICS_REFRESH_TOKEN_EN", ""))
    # 성과 조회 전용 OAuth 클라이언트(선택). 비면 업로드 클라이언트(youtube_client_id/secret)로 폴백 —
    # 업로드 GCP 프로젝트를 못 찾거나 건드리고 싶지 않을 때, 완전히 별도 프로젝트/클라이언트로 조회만
    # 분리해 쓸 수 있게(운영 자동업로드에 영향 없음).
    youtube_analytics_client_id: str = field(default_factory=lambda: os.getenv("YOUTUBE_ANALYTICS_CLIENT_ID", ""))
    youtube_analytics_client_secret: str = field(default_factory=lambda: os.getenv("YOUTUBE_ANALYTICS_CLIENT_SECRET", ""))

    def require(self, *names: str) -> None:
        """필요한 시크릿이 비어 있으면 명확한 에러."""
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            raise RuntimeError(
                f"필수 환경변수 누락: {', '.join(missing)}. .env(.env.example 참조)를 채우세요."
            )


SECRETS = Secrets()
