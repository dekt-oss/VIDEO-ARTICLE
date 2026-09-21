"""Python↔TS 프롬프트 동기화 가드 (명세 B1 §4-3, 통합명세 §4-8, 근거밀도 §5-5).

대본·지시서 프롬프트는 **양쪽에 존재**한다(이중관리):
- 초안: `engine/{factsheet,scriptgen,selfcheck}.py` ↔ `supabase/functions/generate-draft/index.ts`
- 지시서: `engine/directive.py` ↔ `supabase/functions/generate-directive/index.ts`

대시보드는 **엣지 함수**로 실행하므로, 파이썬만 고치면 테스트는 초록인데 프로덕션은 그대로다.
바이트 동일은 비현실적이다(f-string ↔ template literal, config 치환). 그래서 세 층으로 감시한다:
1. **앵커 존재** — 핵심 문구가 양쪽에 다 있는가
2. **부재 앵커** — 제거하기로 한 문구가 양쪽에서 진짜 사라졌는가
3. **수치 파리티** — 비용·예산 숫자가 같은가(문자열 앵커로는 못 잡는다)
"""

import re
from pathlib import Path

import pytest

from engine import config
from engine import directive as dv

ROOT = Path(__file__).resolve().parents[1]
ENGINE_SRC = (ROOT / "engine" / "directive.py").read_text(encoding="utf-8")
TS_SRC = (ROOT / "supabase" / "functions" / "generate-directive" / "index.ts").read_text(encoding="utf-8")
# 초안 파이프라인은 파이썬 3모듈이 TS 1파일에 대응한다.
ENGINE_DRAFT_SRC = "\n".join(
    (ROOT / "engine" / f"{name}.py").read_text(encoding="utf-8")
    for name in ("factsheet", "scriptgen", "selfcheck", "content_mode", "script_polish")
)
TS_DRAFT_SRC = (ROOT / "supabase" / "functions" / "generate-draft" / "index.ts").read_text(encoding="utf-8")

# ★ 2026-08-29: 지시서 프롬프트의 **이중관리가 끝났다**(리뷰 §8).
#   엣지 generate-directive 는 이제 요청 검증 + 큐 적재만 하고, 생성·정규화·계약검사는
#   Python 워커(engine/directive.py)가 독점한다. 그래서 "양쪽에 같은 앵커가 있는가"를
#   감시하던 테스트들은 **감시 대상 자체가 사라져** 걷어냈다.
#   대신 아래 test_edge_is_queue_only_* 가 복제가 되살아나는 것을 막는다.
#   ※ 초안(generate-draft)은 여전히 폴백 생성 경로라 앵커 감시가 남아 있다.

# 초안 파이프라인 앵커(Claim Ledger·계획·훅 후보·자기검증 축).
DRAFT_ANCHORS = [
    "claims",
    "causal_strength",
    "evidence_grade",
    "association_only",
    "초록만 주어졌으면 A 를 쓰지 마라",
    "추정하지 말고 null",
    "content_plan",
    "essential_evidence_units",
    "hook_candidates",
    "selected_hook_id",
    "scope_preserved",
    "causal_calibrated",
    "series_split",
    "scope_match",
    "causal_calibration",
    "numeric_match",
    "qualifier_preserved",
    "editorial_inference",
    "matched_claim_ids",
    "spoken_number_count",
    "bold_claim_on_weak_evidence",
    # 대본 한국어 검수(2026-09-10). 한쪽에만 있으면 같은 대본이 경로에 따라 다른 검수를 받는다.
    "korean_natural",
    "awkward_spans",
    "fluency_issues",
    "translationese",
    "register_mix",
]


def test_edge_is_queue_only_no_generation():
    """엣지가 다시 생성을 하기 시작하면 그 자리에서 막는다(리뷰 §8).

    ★ 왜 이 검사가 필요한가: 202 를 돌려준 뒤 백그라운드에서 생성하면 런타임이 끊길 때
      catch 가 돌지 않아 요청이 **영구 processing** 으로 남는다(2026-08-28 실측).
      "빠르니까 여기서 한 번만" 이 다시 들어오는 것을 코드로 막는다.
    """
    for forbidden in ("EdgeRuntime.waitUntil", "VERSION_GUIDANCE", "generateContent",
                      "anthropic", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        assert forbidden not in TS_SRC, f"엣지에 생성 경로가 되살아났다: {forbidden}"


def test_edge_still_refuses_unknown_versions():
    """배포본이 낡았을 때 조용히 다른 버전으로 갈아치우지 않는다(2026-08-20 사고)."""
    assert "미지원 버전" in TS_SRC
    assert "이 엣지 함수 배포본이 낡았을 수 있습니다" in TS_SRC


def test_edge_enqueues_without_duplicating():
    """같은 (논문, 버전) 요청이 이미 대기·처리 중이면 새로 쌓지 않는다 — 중복 발주 = 유료 2배."""
    assert 'in("status", ["queued", "processing"])' in TS_SRC
    assert "directive_requests" in TS_SRC


@pytest.mark.parametrize("anchor", DRAFT_ANCHORS)
def test_draft_anchor_present_in_both_sources(anchor):
    assert anchor in ENGINE_DRAFT_SRC, f"engine 초안 모듈에 앵커 누락: {anchor!r}"
    assert anchor in TS_DRAFT_SRC, f"generate-draft/index.ts 에 앵커 누락: {anchor!r}"


def test_draft_prompts_no_longer_bake_a_style():
    """초안은 화풍을 정하지 않는다(2026-09-11 운영자 지시 — 설계안_초안지시서_통합발주_v2 §2).

    ★ 실측 사고: 초안 프롬프트가 "modern Korean webtoon/comic style…" 을 씬마다 박아 넣었다.
      화풍이 정해지는 자리는 넷으로 못박아 뒀는데 **다섯째 자리**가 남아 있었고, ④ 화면이
      "이미 웹툰으로 정해졌다"로 읽혔다. 화풍은 지시서/렌더 단계에서 버전별로 코드가 붙인다.
      **양쪽에서** 사라져야 한다 — 한쪽만 지우면 대시보드 버튼이 만든 초안에 계속 나온다.
    """
    for src, where in ((ENGINE_DRAFT_SRC, "engine"), (TS_DRAFT_SRC, "generate-draft/index.ts")):
        assert "modern Korean webtoon/comic style" not in src, f"{where}: 웹툰 화풍 앵커가 남아 있다"
        assert "화풍·매체 어휘를" in src, f"{where}: 화풍 금지 고지가 없다"


def _ts_number_map(src: str, const_name: str) -> dict[str, int]:
    """TS 의 `const NAME: Record<...> = { a: 1, b: 2 };` 리터럴을 파싱한다."""
    m = re.search(rf"const {const_name}[^=]*=\s*\{{(.*?)\}};", src, re.S)
    assert m, f"{const_name} 리터럴을 찾지 못했다"
    return {k: int(v) for k, v in re.findall(r"(\w+):\s*(\d+)", m.group(1))}


def test_claim_ledger_enums_match_python_config():
    """원장 enum 이 어긋나면 한쪽에서만 등급 강등·인과 보정이 걸린다."""
    for name, expected in (
        ("CLAIM_KINDS", config.CLAIM_KINDS),
        ("CAUSAL_STRENGTHS", config.CAUSAL_STRENGTHS),
        ("EVIDENCE_GRADES", config.EVIDENCE_GRADES),
        ("EFFECT_DIRECTIONS", config.EFFECT_DIRECTIONS),
        ("EVIDENCE_UNITS_REQUIRED", config.EVIDENCE_UNITS_REQUIRED),
    ):
        m = re.search(rf"const {name} = \[(.*?)\];", TS_DRAFT_SRC, re.S)
        assert m, f"generate-draft/index.ts 에 {name} 없음"
        got = tuple(re.findall(r'"([^"]+)"', m.group(1)))
        assert got == tuple(expected), f"{name} 불일치: TS={got} Python={tuple(expected)}"


def test_editorial_version_is_gone_from_both_sources():
    """editorial(B타입) 폐기가 **양쪽에서** 됐는가 — 한쪽만 지우면 대시보드에서 되살아난다.

    ★ 이 테스트는 오탐에 예민하다. 'editorial' 이라는 문자열 자체는 살아 있는 다른 것들에도
      쓰인다(자기검증 축 editorial_inference, OpenAlex work_type, 금융 editorial_composite,
      image_sequence 가이드의 'clean editorial illustration'). 그래서 **버전 enum 멤버십**으로만 본다.
    """
    assert "editorial" not in config.VIDEO_VERSIONS
    assert "editorial" not in config.VERSION_VISUAL_TYPE
    assert "editorial" not in config.VERSION_DEFAULT_SCENE_KIND
    m = re.search(r"const VIDEO_VERSIONS = \[(.*?)\]", TS_SRC, re.S)
    assert m, "TS 에 VIDEO_VERSIONS 없음"
    ts_versions = tuple(re.findall(r'"([^"]+)"', m.group(1)))
    assert "editorial" not in ts_versions
    assert ts_versions == config.VIDEO_VERSIONS, "버전 enum 이 Python↔TS 에서 갈렸다"


def test_editorial_false_positives_are_left_alone():
    """폐기 작업이 같은 글자를 쓰는 **다른 것들**을 쓸어가지 않았는가.

    이 넷은 editorial 버전과 무관하다 — 잘못 지우면 자기검증 축·수집 필터·금융 라인이 깨진다.
    """
    selfcheck_src = (ROOT / "engine" / "selfcheck.py").read_text(encoding="utf-8")
    models_src = (ROOT / "engine" / "models.py").read_text(encoding="utf-8")
    config_src = (ROOT / "engine" / "config.py").read_text(encoding="utf-8")
    assert "editorial_inference" in selfcheck_src        # 주장충실도 자기검증 축
    assert "editorial_inference" in TS_DRAFT_SRC
    assert "editorial" in models_src                     # OpenAlex work_type 필터
    assert "editorial_composite" in config_src           # 금융 라인 에셋 소스
    assert "clean editorial illustration" in ENGINE_SRC  # image_sequence 톤 앵커(레거시 폴백)


def test_dropped_versions_cannot_be_ordered_on_either_side():
    """폐기 버전이 **양쪽 발주 enum에서** 빠졌는가 — 한쪽만 지우면 대시보드에서 되살아난다.

    ★ 2026-08-28 운영자 결정으로 webtoon(웹툰 장면파생)·explainer(설명판형)를 뺐다
      (docs/deviation-drop-explainer-webtoon.md). editorial 은 2026-07-28.
    ★ 렌더 쪽 매핑(VERSION_VISUAL_TYPE 등)에는 남겨 둔다 — 이미 만든 옛 지시서가 계속
      렌더돼야 하기 때문이다. 여기서 보는 것은 "새로 발주할 수 있는가" 하나뿐이다.
    """
    ts_versions = re.search(r"const VIDEO_VERSIONS = \[([^\]]+)\]", TS_SRC).group(1)
    for v in ("editorial", "webtoon", "explainer"):
        assert v not in config.VIDEO_VERSIONS, f"엔진 발주 목록에 남았다: {v}"
        assert f'"{v}"' not in ts_versions, f"엣지 발주 목록에 남았다: {v}"
        assert v not in dv.VERSION_GUIDANCE, f"엔진 가이던스에 남았다: {v}"
        # ※ 엣지에는 가이던스가 더 이상 없다(생성이 워커로 넘어갔다) — 발주 enum 만 본다.


def test_dropped_versions_still_render_legacy_rows():
    """폐기했다고 옛 행까지 깨뜨리지 않는다 — 이미 만든 영상의 지시서는 계속 열려야 한다."""
    for v in ("webtoon", "explainer"):
        assert v in config.VERSION_VISUAL_TYPE


# ── 승인 게이트 미러 (web/lib/approvalGate.ts ↔ engine/directive.directive_block_reasons) ──
GATE_TS = (ROOT / "web" / "lib" / "approvalGate.ts").read_text(encoding="utf-8")


def test_approval_gate_mirrors_python_block_reasons():
    """웹 게이트가 파이썬과 같은 사유 코드를 쓰는가.

    ★ 웹에는 테스트 러너가 없어(package.json 에 test 스크립트 없음) TS 쪽 단위 테스트가 돌지
      않는다. 최소한 사유 코드가 갈라지는 건 여기서 잡는다 — 코드가 어긋나면 승인 화면이
      번역하지 못하는 사유가 뜨거나, 파이썬이 막는 걸 웹이 통과시킨다.
    """
    # 사유 코드는 두 모듈에 나뉘어 있다 — 길이·시리즈 축은 content_mode.block_reasons(),
    # 예산·커버리지 축은 directive.directive_block_reasons(). 웹 미러는 둘을 합친 집합이다.
    engine_src = "\n".join(
        (ROOT / "engine" / name).read_text(encoding="utf-8")
        for name in ("directive.py", "content_mode.py")
    )
    # ★ series_split_required 는 2026-09-03 에 **차단에서 내렸다**(명세가 권고라고 정했고
    #   화면에 푸는 길이 없는데 초안 100% 가 걸렸다 — content_mode.block_reasons 주석 참조).
    #   양쪽 다 더는 내보내지 않으므로 동기화 대상에서도 뺀다.
    for reason in ("over_max_duration",
                   "video_budget_exceeded", "missing_required_claims",
                   "primary_claim_not_covered"):
        assert reason in engine_src, f"engine 에 사유 코드 없음: {reason}"
        assert reason in GATE_TS, f"approvalGate.ts 에 사유 코드 없음: {reason}"


def test_approval_gate_numbers_match_python_config():
    """80초 하드 상한·클립 티어가 어긋나면 웹이 파이썬과 다른 선을 긋는다."""
    for name, expected in (("CONTENT_MODE_HARD_MAX_SEC", config.CONTENT_MODE_HARD_MAX_SEC),
                           ("VEO_CLIP_MAX_TIER_SEC", config.VEO_CLIP_MAX_TIER_SEC)):
        m = re.search(rf"const {name} = (\d+);", GATE_TS)
        assert m, f"approvalGate.ts 에 {name} 없음"
        assert int(m.group(1)) == expected, f"{name} 불일치: TS={m.group(1)} Python={expected}"


def test_draft_token_budgets_match_python():
    """출력 예산 드리프트 가드 (2026-07-29 장애 재발 방지).

    Fact Sheet 만 TS 에서 2048 이었다. claims 원장이 붙어 출력이 길어지자 잘린 JSON 이
    파싱에서 터졌는데, 파이썬은 8192(config.LLM_MAX_TOKENS)라 로컬 워커만 멀쩡했다.
    프롬프트가 길어질 때 잘리는 쪽은 **예산이 작은 쪽**이므로 숫자를 직접 대조한다.
    """
    factsheet_src = (ROOT / "engine" / "factsheet.py").read_text(encoding="utf-8")
    # ★ 2026-08-29 ~ 2026-09-22 의 이력. 한동안 factsheet.py 가 상한을 **조건부로** 지정했다 —
    #   원문이 있을 때만 LLM_FACTSHEET_MAX_TOKENS, 없으면 None → LLM_MAX_TOKENS(8,192).
    #   그 조건을 뗐다. 출력 크기를 정하는 것은 **입력에 원문이 있느냐**가 아니라 **모델이
    #   얼마나 길게 쓰느냐**이고, 실측에서 deepseek-flash 가 초록만 있는 경로에서 8,192 정각에
    #   잘렸다(그걸 보고 "그 모델이 claim_id 를 빠뜨린다"고 오판했다).
    assert "max_tokens=config.LLM_FACTSHEET_MAX_TOKENS," in factsheet_src, (
        "factsheet.py 가 config 상한을 안 쓴다 — 엣지 예산 대조 기준이 무너진다")
    assert config.LLM_FACTSHEET_MAX_TOKENS >= config.LLM_MAX_TOKENS, (
        "원문 경로의 상한이 기본보다 작다 — 원문을 줄수록 먼저 잘린다")
    expected = {
        "MAX_TOKENS_FACTSHEET": config.LLM_FACTSHEET_MAX_TOKENS,
        "MAX_TOKENS_SCRIPT": _python_max_tokens("scriptgen.py"),
        "MAX_TOKENS_SELFCHECK": _python_max_tokens("selfcheck.py"),
    }
    for name, want in expected.items():
        m = re.search(rf"const {name} = (\d+);", TS_DRAFT_SRC)
        assert m, f"generate-draft/index.ts 에 {name} 없음"
        assert int(m.group(1)) == want, f"{name} 불일치: TS={m.group(1)} Python={want}"
    # 상수를 정의만 하고 호출부가 리터럴을 쓰면 가드가 무력해진다.
    for name in expected:
        assert TS_DRAFT_SRC.count(name) >= 2, f"{name} 이 호출부에서 쓰이지 않는다"


def _python_max_tokens(module: str) -> int:
    """그 모듈이 실제로 쓰는 출력 상한. **config 상수를 통해** 읽는다.

    ★ 2026-09-22: 예전에는 `max_tokens=<숫자>` 리터럴을 읽었다. 상한을 config 로 빼면서
      (매직넘버 금지) 그 정규식이 0건이 되어 **드리프트 가드가 조용히 죽을 뻔했다** —
      드리프트를 막는 장치가, 드리프트를 막으려는 리팩터링에 걸려 넘어지는 꼴이다.
      이제 `max_tokens=config.X` 를 찾아 config 에서 값을 꺼낸다. 리터럴이 남아 있으면
      그것도 못 읽으므로 `tests/test_ceilings_are_not_hardcoded.py` 가 함께 막는다.
    """
    src = (ROOT / "engine" / module).read_text(encoding="utf-8")
    names = set(re.findall(r"max_tokens=config\.([A-Z_]+)", src))
    assert len(names) == 1, f"{module}: config 출력 상한이 유일하지 않다({names})"
    return int(getattr(config, names.pop()))


def test_draft_call_timeout_matches_python():
    """엣지 타임아웃이 파이썬보다 짧으면 엣지에서만 사고형 모델이 잘려 나간다."""
    m = re.search(r"const CALL_TIMEOUT_MS = ([\d_]+);", TS_DRAFT_SRC)
    assert m, "generate-draft/index.ts 에 CALL_TIMEOUT_MS 없음"
    assert int(m.group(1).replace("_", "")) == int(config.LLM_HTTP_TIMEOUT_SEC * 1000)


def test_draft_truncation_is_reported_not_silently_parsed():
    """잘린 응답을 SyntaxError 로 흘리면 원인을 못 찾는다 — finishReason 을 직접 본다."""
    assert 'finishReason === "MAX_TOKENS"' in TS_DRAFT_SRC
    assert 'stop_reason === "max_tokens"' in TS_DRAFT_SRC


def test_approval_gate_never_blocks_on_llm_judgment():
    """결정 D-E4: LLM 판단 축은 승인을 막지 않는다. 웹 게이트에 그 코드가 있으면 회귀."""
    for llm_axis in ("scope_expanded", "causal_overreach", "numeric_mismatch",
                     "qualifier_dropped", "editorial_inference"):
        assert llm_axis not in GATE_TS, f"LLM 판단 축이 웹 차단 게이트에 섞였다: {llm_axis}"


# ─────────────────────────────────────────────────────────────
# 리포트 라인 트윈 (v3 §11-2) — 대시보드 [초안 생성] 버튼이 도는 경로
#
# ★ 왜 이 절이 생겼나: 리포트 초안은 워커(engine/report_*.py)와 엣지
#   (generate-report-draft/index.ts) 두 경로로 만들어지는데, 지금까지 이 짝은 감시 대상이
#   아니었다. 그 사이 엣지의 Fact Sheet 스키마가 레거시 문자열에 멈춰 있었고, 전문 주입도
#   엣지에는 없었다 — 같은 리포트가 경로에 따라 다른 근거로 영상이 됐다.
# ─────────────────────────────────────────────────────────────
ENGINE_REPORT_SRC = "\n".join(
    (ROOT / "engine" / f"{name}.py").read_text(encoding="utf-8")
    for name in ("report_factsheet", "report_scriptgen", "report_selfcheck", "report_draft")
)
TS_REPORT_SRC = (
    ROOT / "supabase" / "functions" / "generate-report-draft" / "index.ts"
).read_text(encoding="utf-8")

REPORT_ANCHORS = [
    # §4 전문 주입 — 마커와 지시문이 양쪽에 다 있어야 한다.
    "<<FULL_SOURCE>>",
    "요약만 보고 답하지 마라",
    # §4-2 **초안 단계** 주입(§11-1 ②). 추출에만 있고 대본에는 없던 것을 메운 자리다.
    "<<EVIDENCE_PACKET>>",
    "새 수치를 끌어오지 마라",
    # §5 evidence unit — 인용과 비교 기준.
    "number_facts",
    "source_refs",
    "comparator",
    "원문에 있는 문장 그대로",
    # §5-4 씬 역할 면제.
    "scene_role",
    "HOOK|QUESTION|CLAIM|EVIDENCE|MECHANISM|RISK|WATCHPOINT|CTA|BRIDGE",
]


# ★ 워커 전용 필드 — 엣지에 **일부러 이식하지 않은** 것들(설명엔진 v2 §4·§7).
#   엣지 generate-report-draft 는 폴백 경로다. 논증 단위는 LLM 호출을 한 번 더 쓰고 원문
#   인용 대조를 요구하는데, 엣지는 60초 타임아웃이 있어 그 체인을 감당하지 못한다
#   (실사형 엣지 시간초과 실측, 커밋 a7395dc). 여기 적어 두는 이유는 다음 사람이 "왜 한쪽에만
#   있지?"를 결함으로 오해하고 앵커에 추가하는 것을 막기 위해서다.
WORKER_ONLY_REPORT_FIELDS = [
    "financial_reasoning",      # 0042 — 논증 단위 저장 필드
    "<<REASONING_UNITS>>",      # 논증 구간 마커(engine/report_scriptgen)
    "reasoning_id",             # 씬·컷이 어느 논증을 옮기는가
    "reasoning_step",           # 그 논증의 몇 번째 단계인가(v3 Phase 5 — 컷↔stage 연결)
]


@pytest.mark.parametrize("field", WORKER_ONLY_REPORT_FIELDS)
def test_worker_only_fields_are_absent_from_edge(field):
    """워커 전용이라고 적어 놓고 엣지에 흘러 들어가면, 엣지가 감당 못 하는 계약을 받는다."""
    assert field in ENGINE_REPORT_SRC or field in (
        ROOT / "engine" / "report_directive.py").read_text(encoding="utf-8"), (
        f"워커에 없는 것을 워커 전용이라 적었다: {field}")
    assert field not in TS_REPORT_SRC, f"워커 전용 필드가 엣지로 새어 들어갔다: {field}"


@pytest.mark.parametrize("anchor", REPORT_ANCHORS)
def test_report_draft_anchor_exists_on_both_sides(anchor):
    assert anchor in ENGINE_REPORT_SRC, f"엔진 리포트 초안에 앵커 없음: {anchor}"
    assert anchor in TS_REPORT_SRC, f"엣지 리포트 초안에 앵커 없음: {anchor}"


# 제거하기로 한 문구 — 한쪽에만 남으면 그 경로만 환각을 계속 만든다.
REPORT_ABSENT_ANCHORS = [
    # 리스크가 없으면 지어내라는 지시(v3 §5 에서 제거).
    "일반적 리스크(밸류 부담·시장 변동성 등) 1개를 반드시 생성",
]


@pytest.mark.parametrize("anchor", REPORT_ABSENT_ANCHORS)
def test_report_draft_removed_anchor_is_gone_on_both_sides(anchor):
    assert anchor not in ENGINE_REPORT_SRC, f"엔진에 제거 대상 문구가 남았다: {anchor}"
    assert anchor not in TS_REPORT_SRC, f"엣지에 제거 대상 문구가 남았다: {anchor}"


def test_report_scene_roles_match_between_python_and_ts():
    """역할 목록이 어긋나면 같은 대본이 한쪽에서만 면제된다."""
    m = re.search(r"const SCENE_ROLES = \[([^\]]+)\]", TS_REPORT_SRC, re.S)
    assert m, "엣지에 SCENE_ROLES 없음"
    ts_roles = tuple(x.strip().strip('"') for x in m.group(1).split(",") if x.strip())
    assert ts_roles == config.SCENE_ROLES

    m2 = re.search(r"const SCENE_ROLES_EVIDENCE_EXEMPT = \[([^\]]+)\]", TS_REPORT_SRC, re.S)
    assert m2, "엣지에 SCENE_ROLES_EVIDENCE_EXEMPT 없음"
    ts_exempt = tuple(x.strip().strip('"') for x in m2.group(1).split(",") if x.strip())
    assert ts_exempt == config.SCENE_ROLES_EVIDENCE_EXEMPT


def test_report_selfcheck_recomputes_all_grounded_on_both_sides():
    """LLM 자기보고를 그대로 쓰면 면제가 반영되지 않는다."""
    assert "all(s[\"grounded\"] for s in scenes)" in ENGINE_REPORT_SRC
    assert "scenes.every((s) => s.grounded)" in TS_REPORT_SRC


def test_gate_labels_match_between_engine_and_web():
    """게이트 라벨이 어긋나면 승인 화면이 게이트 결과를 잘못 설명한다.

    ★ web/lib/gateLabels.ts 는 engine/report_evidence.GATE_LABELS 의 트윈이다. 토큰이 한쪽에만
      있으면 운영자에게 `number_without_period:num_3` 같은 원문 토큰이 그대로 나간다.
    """
    from pathlib import Path

    from engine import report_evidence

    src = (Path(__file__).resolve().parents[1] / "web/lib/gateLabels.ts").read_text(encoding="utf-8")
    body = re.search(r"export const GATE_LABELS[^{]*\{(.*?)\n\};", src, re.S)
    assert body, "web 에 GATE_LABELS 없음"
    ts_keys = set(re.findall(r"^\s*([a-z_]+):", body.group(1), re.M))
    py_keys = set(report_evidence.GATE_LABELS)
    assert ts_keys == py_keys, (
        f"엔진에만: {sorted(py_keys - ts_keys)} / web 에만: {sorted(ts_keys - py_keys)}")


# ─────────────────────────────────────────────────────────────
# 실사형 3D 품질 상향 (2026-08-28, 운영자 지시)
# ─────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────
# 실사형 화면 계약 — 사유 코드는 Python 이 정본, 웹은 미러 (2026-08-29 리뷰 §4)
# ★ 코드 문자열이 갈리면 승인 화면이 사유를 "photo_hook_missing" 원문 그대로 보여주거나
#   (라벨 누락), 웹이 막은 것을 엔진이 안 막는(또는 그 반대) 상태가 된다.
# ─────────────────────────────────────────────────────────────
PHOTO_GATE_TS = (ROOT / "web" / "lib" / "approvalGate.ts").read_text(encoding="utf-8")
PHOTO_LABELS_TS = (ROOT / "web" / "lib" / "blockLabels.ts").read_text(encoding="utf-8")


def test_photo_block_reason_codes_have_web_labels():
    from engine import photo_contract

    for code in photo_contract.BLOCK_REASONS:
        assert f"{code}:" in PHOTO_LABELS_TS, f"웹 라벨에 사유 코드가 없다: {code}"


def test_photo_warning_codes_have_web_labels():
    """★ 경고도 라벨이 있어야 한다(2026-09-04).

    종전에는 mode_warnings 가 화면에 **코드 이름 그대로** 나갔다
    (`photo_world_churn:3.38/분`). 감지는 하는데 운영자가 읽을 수 없으면 그 신호는
    없는 것과 같다 — 이 저장소가 차단 쪽에서 이미 겪은 실패의 반복이다.
    """
    from engine import photo_contract

    for code in photo_contract.WARNING_REASONS:
        assert f"{code}:" in PHOTO_LABELS_TS, f"웹 라벨에 경고 코드가 없다: {code}"


def test_the_label_helper_does_not_call_a_value_a_cut_number():
    """`photo_world_churn:3.38/분` 이 '(컷 3.38/분)' 으로 나가면 안 된다."""
    assert "CUT_LIST" in PHOTO_LABELS_TS
    assert "export function warningLabel" in PHOTO_LABELS_TS


def test_the_screens_actually_call_the_label_helpers():
    """★ 라벨을 만들어 놓고 화면이 안 부르면 아무것도 안 바뀐다(이 저장소의 단골 실패)."""
    for name in ("DirectiveClient.tsx", "ReviewClient.tsx"):
        src = (ROOT / "web" / "components" / name).read_text(encoding="utf-8")
        assert "warningLabel(" in src, f"{name} 가 경고 라벨을 쓰지 않는다"
    dc = (ROOT / "web" / "components" / "DirectiveClient.tsx").read_text(encoding="utf-8")
    assert "BLOCK_LABEL[" not in dc, "차단 사유를 맵에서 직접 찾으면 접미사 붙은 코드를 놓친다"


def test_web_recomputes_the_edit_sensitive_photo_reasons():
    """운영자가 ⑤ 에서 컷을 고치면 저장된 판정은 낡는다 — 편집으로 깨질 수 있는 항목은
    웹도 다시 세야 한다(approvalGate.ts 가 존재하는 이유 그대로)."""
    for code in ("photo_hook_missing", "photo_visual_role_missing",
                 "photo_forbidden_screen_request", "photo_number_without_overlay",
                 "photo_cut_count_low", "photo_mechanism_missing"):
        assert code in PHOTO_GATE_TS, f"웹 승인 게이트가 재계산하지 않는다: {code}"


def test_web_does_not_reimplement_the_judgement_heavy_checks():
    """도해가 장식적인가 같은 판단은 웹에서 재계산하지 않는다(오탐이 두 배가 된다).
    엔진이 생성 시점에 판정해 저장한 값을 쓴다."""
    assert "photo_mechanism_decorative" not in PHOTO_GATE_TS
