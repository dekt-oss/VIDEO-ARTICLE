"""PF2 영상화 순수 로직 테스트 — 하단 면책 자막(build_ass footer)·프롬프트. ffmpeg/LLM 불요."""

from engine import config, subtitles


CUES = [(0.0, 2.0, "첫 자막"), (2.0, 4.0, "둘째 자막")]


def test_build_ass_footer_adds_style_and_dialogue():
    ass = subtitles.build_ass(CUES, header_title="하루 한 리포트", total_sec=4.0,
                              footer_text="출처 신한투자증권 · 투자 권유 아님")
    assert "Style: Footer," in ass
    # 하단 자막이 전 구간([0, total]) 1줄로 나가는지.
    assert ",Footer,," in ass
    assert "출처 신한투자증권" in ass


def test_build_ass_no_footer_is_paper_identical():
    # ★ 회귀: footer_text 미전달 시(논문 경로) Footer 스타일·다이얼로그가 전혀 없어야 한다.
    ass = subtitles.build_ass(CUES, header_title="하루 논문 한 편", total_sec=4.0)
    assert "Footer" not in ass
    # footer_text="" 도 동일(빈 문자열 → 미출력).
    assert subtitles.build_ass(CUES, header_title="하루 논문 한 편", total_sec=4.0, footer_text="") == ass


def test_build_ass_footer_default_empty_matches_no_arg():
    a = subtitles.build_ass(CUES, total_sec=4.0)
    b = subtitles.build_ass(CUES, total_sec=4.0, footer_text="")
    assert a == b


def test_footer_config_present():
    assert config.REPORT_DISCLAIMER_TEXT
    assert config.FOOTER_FONT_SIZE > 0
    assert config.REPORT_SERIES_TITLE_BY_LANG["ko"]


def test_report_scriptgen_drops_disclaimer_scene_keeps_ending():
    from engine.report_scriptgen import SCRIPT_SYSTEM
    # 전용 면책 씬 금지 규칙이 들어갔는지 + 엔딩 면책 문구는 유지(컴플라이언스 통과 조건).
    assert "전용 씬을 만들지 마라" in SCRIPT_SYSTEM
    assert "script_md 엔딩" in SCRIPT_SYSTEM
    assert "투자 권유가 아닙니다" in SCRIPT_SYSTEM   # 면책 마커 유지
    assert "면책+CTA" not in SCRIPT_SYSTEM           # 면책 낭독 씬 구조 제거


def test_report_scriptgen_shorts_structure():
    """숏폼 리텐션 구조: 후크 2~3초, 씬 6~7개, 마지막 씬은 페이오프(면책 아님)."""
    from engine.report_scriptgen import SCRIPT_SYSTEM
    assert "후크 (2~3초)" in SCRIPT_SYSTEM            # 후크 단축(기존 3~7초 → 2~3초)
    assert "씬 6~7개" in SCRIPT_SYSTEM
    assert "페이오프" in SCRIPT_SYSTEM                 # 마지막 씬 = 콘텐츠 마무리
    assert 'source_facts 에 "source.disclaimer" 만 있는 씬' in SCRIPT_SYSTEM


def test_edge_fn_prompt_parity_no_disclaimer_scene():
    """엣지 함수(대시보드 초안 생성 경로)의 프롬프트도 같은 구조인지 — 이중관리 동기화 가드."""
    from pathlib import Path
    src = Path("supabase/functions/generate-report-draft/index.ts").read_text(encoding="utf-8")
    assert "면책+CTA" not in src                       # 옛 면책 낭독 씬 구조 제거
    assert "후크(2~3초)" in src
    assert "페이오프" in src
    assert "source.disclaimer" in src                  # 면책-전용 씬 금지 규칙


def test_report_directive_system_has_compliance_and_schema():
    from engine.report_directive import REPORT_DIRECTIVE_SYSTEM, report_directive_user_prompt
    assert "컴플라이언스 금지" in REPORT_DIRECTIVE_SYSTEM
    assert "OO증권에 따르면" in REPORT_DIRECTIVE_SYSTEM   # 출처 귀속
    assert "source_facts" in REPORT_DIRECTIVE_SYSTEM      # 근거 스키마
    # user 프롬프트가 report_drafts.scenes 를 읽는지(video_prompts 아님).
    # ★ 씬은 **대본과 일치할 때만** 실린다(PR #94 후속 P1-1) — 픽스처도 일치시킨다.
    #   예전 픽스처는 script_md 와 scenes 가 서로 달랐는데, 그게 바로 이 변경이 막으려는
    #   상태다(운영자가 지운 문장이 지시서에 되살아나는 경로).
    up = report_directive_user_prompt(
        {"script_md": "나레", "fact_sheet": {"company": "SK"},
         "scenes": [{"narration_ko": "나레"}]}, "comic")
    assert "나레" in up and "기존 장면들(scenes" in up

    # 어긋나면 씬을 싣지 않는다 — 운영자가 지운 문장이 프롬프트에서 사라져야 한다.
    #   (지시 문구 자체에 "옛 문장"이 들어 있어, 픽스처는 구별되는 문자열을 쓴다.)
    stale = report_directive_user_prompt(
        {"script_md": "고친 대본입니다.", "fact_sheet": {},
         "scenes": [{"narration_ko": "삭제된원고문장ZZ"}]}, "comic")
    assert "삭제된원고문장ZZ" not in stale


def test_report_directive_reuses_paper_normalize():
    # 리포트 지시서는 논문 normalize_directive 를 그대로 써 enum 정화·total 재계산이 동작.
    from engine import directive as dv
    raw = {"header": {"aspect_ratio": "9:16"},
           "cuts": [{"cut_no": 1, "narration_ko": "a", "estimated_sec": 5,
                     "effects": ["bad_effect", "highlight"], "source_facts": ["numbers[0]"]},
                    {"cut_no": 2, "narration_ko": "b", "estimated_sec": 4, "source_facts": []}]}
    d = dv.normalize_directive(raw, "comic")
    assert d["cuts"][0]["effects"] == ["highlight"]          # 미허용 effect 드롭
    assert d["header"]["total_estimated_sec"] == 9           # 컷 합 재계산
    assert dv.ungrounded_cuts(d) == [2]                      # 근거 없는 컷 플래그
