"""P1 파이프라인 순수 로직(정규화) 테스트 — 네트워크/LLM 불필요."""

from engine.factsheet import normalize_factsheet
from engine.scriptgen import normalize_script
from engine.selfcheck import normalize_selfcheck


def test_normalize_factsheet_coerces_lists():
    fs = normalize_factsheet({
        "what_found": "단일 발견",       # 문자열 → 리스트
        "numbers": ["30%", 42],          # 혼합 → 문자열 리스트
        "claim_strength": "강",
    })
    assert fs["what_found"] == ["단일 발견"]
    assert fs["numbers"] == ["30%", "42"]
    assert fs["how"] == [] and fs["limitations"] == []
    assert fs["claim_strength"] == "강"


def test_normalize_script_fills_defaults():
    out = normalize_script({
        "script_md": "대본",
        "video_flow": {
            "logline": "AI도 늙는다",
            "total_duration_sec": "45",
            "beats": [
                {"order": "1", "label": "후크", "summary": "충격 오프닝", "transition": "급속 줌"},
                "garbage",  # dict 아닌 비트는 무시
            ],
        },
        "scenes": [
            {
                "narration_ko": "후크",
                "source_facts": "what_found[0]",
                "duration_sec": "3",
                "title": "오프닝",
                "image_prompt": "extreme close-up ...",
                "image_prompt_ko": "글리치가 이는 디지털 얼굴의 클로즈업 스틸",
                "video_prompt": "slow dolly-in ...",
                "video_prompt_ko": "천천히 다가가며 얼굴에 글리치가 번진다",
            },
            "garbage",  # dict 아닌 항목은 무시
        ],
    })
    assert out["script_md"] == "대본"
    # video_flow 정규화
    assert out["video_flow"]["logline"] == "AI도 늙는다"
    assert out["video_flow"]["total_duration_sec"] == 45
    assert len(out["video_flow"]["beats"]) == 1
    assert out["video_flow"]["beats"][0]["order"] == 1
    # scenes 정규화 + 새 필드
    assert len(out["scenes"]) == 1
    s = out["scenes"][0]
    assert s["scene"] == 1
    assert s["duration_sec"] == 3
    assert s["source_facts"] == ["what_found[0]"]
    assert s["title"] == "오프닝"
    assert s["image_prompt"].startswith("extreme close-up")
    assert s["video_prompt"].startswith("slow dolly-in")
    assert s["image_prompt_ko"] == "글리치가 이는 디지털 얼굴의 클로즈업 스틸"
    assert s["video_prompt_ko"] == "천천히 다가가며 얼굴에 글리치가 번진다"


def test_normalize_script_legacy_visual_prompt_fallback():
    # 옛 초안: 단일 visual_prompt 만 있고 image/video_prompt 없음 → video_prompt 로 승계.
    out = normalize_script({
        "scenes": [{"narration_ko": "x", "visual_prompt": "orbit shot, 9:16"}],
    })
    s = out["scenes"][0]
    assert s["video_prompt"] == "orbit shot, 9:16"
    assert s["image_prompt"] == ""
    # video_flow 없으면 빈 기본 shape(레거시 3키). content_plan·hook_candidates 는 그 위에
    # 병렬 추가된 신규 키다(수정명세 §4-2 — drafts 에 빈 컬럼이 없어 여기 얹었다).
    flow = out["video_flow"]
    assert flow["logline"] == "" and flow["total_duration_sec"] == 0 and flow["beats"] == []
    assert flow["hook_candidates"] == [] and flow["selected_hook_id"] == ""
    assert flow["content_plan"]["selected_mode"] == "flash"  # 근거 단위 3개(필수분)뿐 → 최단 모드


def test_normalize_selfcheck_recomputes_all_grounded():
    # LLM 이 grounded=true 라 우겨도 unsupported 가 있으면 false 로 강등
    out = normalize_selfcheck({
        "scenes": [
            {"scene": 1, "grounded": True, "unsupported": ["근거 없는 문장"]},
            {"scene": 2, "grounded": True, "unsupported": []},
        ],
        "all_grounded": True,
    })
    assert out["all_grounded"] is False
    assert out["scenes"][0]["grounded"] is False
    assert out["scenes"][1]["grounded"] is True


def test_normalize_selfcheck_all_grounded_true():
    out = normalize_selfcheck({"scenes": [{"scene": 1, "grounded": True, "unsupported": []}]})
    assert out["all_grounded"] is True
