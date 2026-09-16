r"""컷 골격이 **말을 끊지 않는가** — 세마글루타이드 지시서 실측(2026-09-04).

운영자가 첫 렌더에서 한 지적: "나레이션이 문장이 안끝났는데 화면넘어가서 뚝뚝끊기는게
너무 열받는다". 그때는 클립 길이(tail pad)만 고쳤는데, **원인 절반은 골격이 자르는
자리**였다. 세마글루타이드 지시서 19컷에서 실제로 나온 것:

    컷 15 "…장기 임상 연구가 더 필요하다고"   컷 16 "**강조했습니다.**"
    컷 10 "심지어 탐색 행동 공간 기억"        컷 11 "혈당 조절 능력에서는…"

원인 셋:
  ① `(?<=고)\s+` 가 **인용 어미** -다고/-라고 뒤에서도 잘랐다 → 뒤 동사가 고아가 된다.
  ② 맨몸 쉼표가 **명사 나열**을 잘랐다 → 술어 없는 조각이 남는다.
  ③ 한 문장이 3칸이 되면 그 3칸이 전부 같은 evidence_role 을 받는다 →
     **기전 컷 수가 부풀어** 게이트가 통과시킨다(내용은 결과 나열인데).

★ 규칙을 계속 늘리는 대신 **결과를 보고 고치는** 안전망을 뒀다(_heal_unfinished):
  조각이 연결·종결 어미로 끝나지 않으면 뒤와 다시 붙인다.
"""

from __future__ import annotations

import re

from engine import cut_skeleton as cs


def _cuts(text: str, max_sec: float = 5.0) -> list[str]:
    return cs._split_long(text, max_sec)


def _norm(t: str) -> str:
    return re.sub(r"[\s,]", "", t)


# ── ① 인용 어미 ──────────────────────────────────────────────
def test_a_quotative_ending_never_strands_its_verb():
    """★ 실측 그대로: '…필요하다고 강조했습니다' 를 자르면 '강조했습니다.' 만 남는다."""
    s = ("따라서 GLP-1R 활성화가 인간의 노화 궤적과 수명에 영향을 미치는지 여부는 "
         "노인 인구를 대상으로 한 장기 임상 연구가 더 필요하다고 강조했습니다.")
    for part in _cuts(s):
        assert not part.strip().startswith("강조"), part
        assert not part.rstrip().endswith("필요하다고"), part


def test_other_quotative_forms_are_also_protected():
    for verb, quote in (("밝혔습니다", "늘어났다고"), ("전했습니다", "하라고"),
                        ("물었습니다", "가느냐고"), ("제안했습니다", "가자고")):
        s = f"연구팀은 이번 실험에서 관찰된 변화가 매우 뚜렷하게 {quote} {verb}."
        for part in _cuts(s, max_sec=1.0):
            assert not part.strip().startswith(verb), (s, part)


# ── ② 나열 쉼표 ──────────────────────────────────────────────
def test_a_noun_list_is_not_split_into_a_predicateless_fragment():
    """★ 실측: '심지어 탐색 행동 공간 기억' — 술어가 없는 컷이 화면에 나갔다."""
    s = "심지어 탐색 행동, 공간 기억, 혈당 조절 능력에서는 칼로리 제한보다도 더 나은 변화를 보였습니다."
    parts = _cuts(s, max_sec=2.0)
    assert all("공간 기억" not in p or "보였습니다" in p or p.endswith(("고", "며", "지만")) or
               len(p) > 20 for p in parts), parts
    for p in parts:
        assert cs._CLAUSE_END.search(p.strip()), f"말이 안 맺힌 조각: {p}"


# ── ③ 연결 어미에서는 여전히 자른다(계약 유지) ──────────────
def test_a_real_connective_ending_still_splits():
    """길이를 넘는 문장은 나뉘어야 한다 — 안 나뉘면 컷 수가 모자라 승인이 막힌다."""
    s = "이 약물은 쥐의 생리적 기능을 향상시키고 노화의 특징을 약화시켰으며 유전자 조절에도 영향을 미쳤습니다."
    assert len(_cuts(s, max_sec=2.0)) > 1


def test_a_short_sentence_is_never_touched():
    s = "최근 네이처에 발표된 연구 결과입니다."
    assert _cuts(s) == [s]


# ── 불변식: 글자를 잃지 않는다 ───────────────────────────────
def test_splitting_never_loses_text():
    """★★ 경계의 쉼표 말고는 한 글자도 사라지면 안 된다 — 나레이션이 곧 사실이다."""
    for s in ("이 약물은 기능을 향상시키고, 노화 특징을 약화시켰으며, 유전자 조절에도 영향을 미쳤습니다.",
              "대조군은 742일이었지만, 치료군은 834일로 92일 더 오래 살았습니다.",
              "따라서 장기 임상 연구가 더 필요하다고 강조했습니다."):
        assert _norm("".join(_cuts(s, max_sec=1.5))) == _norm(s), s


def test_every_piece_ends_where_speech_can_pause():
    """조각마다 말이 맺혀야 화면 전환이 자연스럽다."""
    s = ("캘리포니아 버클리 대학교와 코펜하겐 대학교 연구팀은 생애 후반 세마글루타이드 치료가 "
         "암컷 쥐의 노화를 늦추고 수명을 연장했다고 밝혔습니다.")
    for p in _cuts(s, max_sec=2.0):
        assert cs._CLAUSE_END.search(p.strip()), f"말이 안 맺힌 조각: {p}"


def test_the_healer_merges_a_dangling_head_into_the_next_piece():
    assert cs._heal_unfinished(["심지어 탐색 행동", "공간 기억을 보였습니다."]) == \
        ["심지어 탐색 행동 공간 기억을 보였습니다."]


def test_the_healer_merges_a_dangling_tail_backwards():
    """뒤에 붙일 곳이 없으면 앞으로 붙인다 — 버리지 않는다."""
    assert cs._heal_unfinished(["앞 문장입니다.", "꼬리 조각"]) == ["앞 문장입니다. 꼬리 조각"]
