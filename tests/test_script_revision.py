"""대본 정본 — 지문·씬 동기화 (PR #94 후속 리뷰 P1-1·P1-2).

이 모듈이 막는 사고: 운영자가 ④ 에서 지운 문장이 ⑤ 지시서 프롬프트에 되살아나는 것.
"""

from __future__ import annotations

import hashlib

from engine import config
from engine import script_revision as sr

SCRIPT = (
    "북미에서 배터리 출하량이 83% 폭증했습니다. 무슨 일일까요?\n\n"
    "iM증권에 따르면, 전기차가 아닌 'ESS' 시장 얘기입니다.\n\n"
    "점유율은 20%까지 올랐습니다.\n\n"
    "본 영상은 정보 제공 목적이며 투자 권유가 아닙니다. 투자 판단과 책임은 본인에게 있습니다."
)

SCENES = [
    {"scene": 1, "narration_ko": "북미에서 배터리 출하량이 83% 폭증했습니다. 무슨 일일까요?",
     "scene_role": "HOOK", "source_facts": ["numbers[0]"], "duration_sec": 4},
    {"scene": 2, "narration_ko": "iM증권에 따르면, 전기차가 아닌 'ESS' 시장 얘기입니다.",
     "scene_role": "REVEAL", "source_facts": ["what[0]"], "duration_sec": 4},
    {"scene": 3, "narration_ko": "점유율은 20%까지 올랐습니다.",
     "scene_role": "PROOF", "source_facts": ["numbers[1]"], "duration_sec": 3},
]


# ── 지문 ──────────────────────────────────────────────────────

def test_fingerprint_changes_when_one_character_changes():
    a = sr.fingerprint("매출은 20% 증가할 전망입니다.")
    b = sr.fingerprint("매출은 21% 증가할 전망입니다.")
    assert a and b and a != b


def test_fingerprint_ignores_surrounding_whitespace_only():
    assert sr.fingerprint("  같은 글  ") == sr.fingerprint("같은 글")
    assert sr.fingerprint("") == ""
    assert sr.fingerprint(None) == ""


def test_fingerprint_contract_is_sha256_prefix():
    """웹(Next)이 같은 값을 계산해 비교한다 — 알고리즘이 갈리면 경고가 늘 켜진다."""
    text = "정본 계약"
    assert sr.fingerprint(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    assert len(sr.fingerprint(text)) == 16


# ── 문단 → 씬 ─────────────────────────────────────────────────

def test_disclaimer_is_not_a_scene():
    """면책은 화면 하단 고정 자막으로 나간다 — 씬으로 세면 컷이 하나 늘어난다."""
    paras = sr.script_paragraphs(SCRIPT)
    assert len(paras) == 3
    assert all("투자 권유가 아" not in p for p in paras)
    assert sr.is_disclaimer(config.REPORT_DISCLAIMER_TEXT)


def test_edited_sentence_replaces_the_scene_narration():
    edited = SCRIPT.replace("점유율은 20%까지 올랐습니다.",
                            "iM증권은 점유율이 20%까지 올랐다고 밝혔습니다.")
    out = sr.sync_scenes(SCENES, edited)
    assert out[2]["narration_ko"] == "iM증권은 점유율이 20%까지 올랐다고 밝혔습니다."
    # 근거·역할·길이는 운영자가 고친 것이 아니므로 보존한다.
    assert out[2]["source_facts"] == ["numbers[1]"]
    assert out[2]["scene_role"] == "PROOF"
    assert out[2]["duration_sec"] == 3


def test_deleted_paragraph_drops_the_scene():
    """지운 문장이 씬에 남으면 ⑤ 지시서에서 되살아난다 — 이 테스트가 그것을 막는다."""
    edited = SCRIPT.replace("점유율은 20%까지 올랐습니다.\n\n", "")
    out = sr.sync_scenes(SCENES, edited)
    assert len(out) == 2
    assert all("점유율은 20%" not in s["narration_ko"] for s in out)


def test_added_paragraph_becomes_a_scene_without_borrowed_evidence():
    """새 문장에 앞 씬의 근거를 물려주면 **검증 안 된 문장이 검증된 것처럼** 보인다."""
    edited = SCRIPT.replace(
        "본 영상은", "다만 정책 이연 수요가 일부 반영됐을 수 있습니다.\n\n본 영상은")
    out = sr.sync_scenes(SCENES, edited)
    assert len(out) == 4
    assert out[3]["narration_ko"].startswith("다만 정책 이연")
    assert out[3]["source_facts"] == []


def test_sync_does_not_mutate_the_input():
    before = SCENES[0]["narration_ko"]
    sr.sync_scenes(SCENES, SCRIPT.replace(before, "바뀐 문장입니다."))
    assert SCENES[0]["narration_ko"] == before


def test_empty_script_keeps_existing_scenes():
    """대본이 비었으면 판단 근거가 없다 — 있는 씬을 파괴하지 않는다."""
    assert len(sr.sync_scenes(SCENES, "")) == len(SCENES)


# ── ⑤ 입력에 씬을 실을지 ──────────────────────────────────────

def test_scenes_match_when_untouched():
    assert sr.scenes_match_script(SCENES, SCRIPT) is True


def test_scenes_do_not_match_after_an_edit():
    edited = SCRIPT.replace("점유율은 20%까지 올랐습니다.", "점유율은 25%까지 올랐습니다.")
    assert sr.scenes_match_script(SCENES, edited) is False
    # 동기화하면 다시 맞는다.
    assert sr.scenes_match_script(sr.sync_scenes(SCENES, edited), edited) is True


# ── 씬 머리글이 붙는 대본 형식 (실측 회귀) ────────────────────

HEADED_SCRIPT = (
    "**씬1 (후크)**\n"
    "로봇 회사 하나가 5년 만에 몸값 29배로 뛰었다?\n\n"
    "**씬2 (맥락)**\n"
    "신한 리서치에 따르면, 현대차그룹이 품은 보스턴다이나믹스 이야기다.\n\n"
    "정보 제공 목적이며 투자 권유가 아닙니다. 판단·책임은 본인에게."
)

HEADED_SCENES = [
    {"scene": 1, "narration_ko": "로봇 회사 하나가 5년 만에 몸값 29배로 뛰었다?",
     "scene_role": "HOOK", "source_facts": ["num_valuation"], "duration_sec": 3},
    {"scene": 2, "narration_ko": "신한 리서치에 따르면, 현대차그룹이 품은 보스턴다이나믹스 이야기다.",
     "scene_role": "CONTEXT", "source_facts": ["what[0]"], "duration_sec": 4},
]


def test_scene_headings_are_not_read_aloud():
    """`script_md` 형식은 고정이 아니다 — 어떤 초안은 `**씬1 (후크)**` 머리글이 붙는다.

    ★ 실측 회귀: 머리글을 걸러내지 않으면 동기화가 나레이션을
      "**씬1 (후크)** 로봇 회사 하나가…" 로 덮어써서 **TTS 가 별표와 '씬일'을 읽는다.**
      운영 초안(a2348c26)에서 그 직전까지 갔다.
    """
    paras = sr.script_paragraphs(HEADED_SCRIPT)
    assert paras[0] == "로봇 회사 하나가 5년 만에 몸값 29배로 뛰었다?"
    assert all("**" not in p and not p.startswith("씬") for p in paras)


def test_headed_script_matches_its_scenes():
    """머리글 형식이라고 씬이 항상 '어긋난 것'으로 판정되면 ⑤ 가 근거를 늘 잃는다."""
    assert sr.scenes_match_script(HEADED_SCENES, HEADED_SCRIPT) is True


def test_sync_keeps_narration_clean_for_headed_scripts():
    edited = HEADED_SCRIPT.replace("29배로 뛰었다?", "30배로 뛰었다?")
    out = sr.sync_scenes(HEADED_SCENES, edited)
    assert out[0]["narration_ko"] == "로봇 회사 하나가 5년 만에 몸값 30배로 뛰었다?"
    assert out[0]["source_facts"] == ["num_valuation"]     # 근거 보존
