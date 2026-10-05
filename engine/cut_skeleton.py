"""결정론적 컷 골격 (2026-08-29 리뷰 §6).

무엇을 푸는가: 컷 수와 리듬이 **대본의 scenes 개수에 종속**돼 있었다. 대본이 씬 6~7개를 내면
지시서도 6~8컷이 됐고, 실사형 계약이 "40~50초면 10~14컷"이라고 말해도 LLM 이 그 수를 스스로
줄였다(실측 2026-08-28: 40초 8컷).

여기서는 **문장 경계와 목표 길이**로 골격을 먼저 만든다. LLM 은 그 골격의 칸을 시각 표현으로
채울 뿐, 칸 수를 정하지 않는다.

★ 코드가 정하는 것 / LLM 이 정하는 것을 나눈다:
    코드  — 몇 컷인가, 각 컷이 어느 문장을 말하는가, 대략 몇 초인가
    LLM   — 그 문장을 **무엇으로 보여줄 것인가**(visual_role · 도해 구조 · 프롬프트 · 오버레이)

순수 함수다(네트워크·DB 없음).
"""

from __future__ import annotations

import re
from typing import Any

from . import config

# 절 경계 — 여기서만 컷을 나눈다.
#
# ★★ 2026-09-04 실측이 드러낸 결함 셋(세마글루타이드 지시서 19컷). 종전 규칙
#   `,\s*|(?<=고)\s+|(?<=는데)\s+|(?<=지만)\s+` 이 만든 것:
#     ① "…장기 임상 연구가 더 필요하다고" / "**강조했습니다.**"
#        -다고/-라고 는 **인용 어미**다. 그 뒤에서 자르면 뒤 동사가 고아가 된다.
#        컷 하나가 "강조했습니다." 한 마디로 나왔다.
#     ② "심지어 탐색 행동 공간 기억" / "혈당 조절 능력에서는…"
#        **명사 나열 쉼표**에서 잘라 술어 없는 조각이 남았다.
#     ③ 한 문장이 3칸이 되면서 그 3칸이 전부 evidence_role='mechanism' 라벨을 받아
#        **기전 컷 수가 부풀었다**(게이트는 3개로 세고 통과시켰지만 내용은 결과 나열이다).
#   ①②는 운영자가 첫 렌더에서 말한 "나레이션이 문장이 안 끝났는데 화면이 넘어가서
#   뚝뚝 끊긴다"의 직접 원인이기도 하다.
#
# ★ 그래서 **연결 어미 뒤에서만** 자르고, 인용 어미는 명시적으로 제외한다.
#   -고 앞에 '다/라/냐/자' 가 오면 인용이다(…했다고, …하라고). 부정 전방탐색으로 막는다.
#   쉼표는 **연결 어미 뒤의 쉼표**만 경계로 본다(나열 쉼표는 자르지 않는다).
_CLAUSE_SPLIT = re.compile(
    r"(?<=[^다라냐자]고),?\s+"      # 연결 -고 (인용 -다고/-라고/-냐고/-자고 제외)
    r"|(?<=며),?\s+"                # -(으)며
    r"|(?<=지만),?\s+"              # -지만
    r"|(?<=는데),?\s+"              # -는데
    r"|(?<=하여),?\s+|(?<=해서),?\s+"
    r"|(?<=으나),?\s+|(?<=아서),?\s+|(?<=어서),?\s+"
)

# 컷 조각이 이것으로 끝나면 "말이 맺혔다"고 본다. 아니면 뒤 조각과 다시 붙인다.
# ★ 종결(다./요./까?) 뿐 아니라 연결 어미도 허용한다 — 연결로 끝나는 컷은 다음 컷으로
#   자연스럽게 이어지지만, **명사·조사로 끝나는 조각**은 말이 끊긴 것이다.
_CLAUSE_END = re.compile(r"(?:[.!?。]|고|며|지만|는데|하여|해서|으나|아서|어서)$")

# 문장 경계. 한국어 종결(다./요./까?/!) + 서구식 마침표를 함께 본다.
# 숫자 소수점(15.3)·약어에서 끊기지 않도록 종결 뒤에 공백/끝을 요구한다.
_SENT_SPLIT = re.compile(r"(?<=[.!?。])\s+|(?<=[다요까죠][.!?])\s*")
# 마크다운 장식·머리표·화자 표기는 나레이션이 아니다.
_MD_NOISE = re.compile(r"^\s*(?:#{1,6}\s*|[-*+]\s+|>\s*|\d+\.\s+|\[[^\]]*\]\s*)")
_INLINE_MD = re.compile(r"[*_`~]{1,3}")
# 면책·CTA 처럼 화면 컷으로 만들지 않는 줄(하단 고정 자막으로 렌더된다).
_SKIP_LINE = re.compile(r"(정보\s*제공\s*목적|투자\s*권유가\s*아닙니다|판단·책임|구독|좋아요)")


def sentences(script_md: str) -> list[str]:
    """대본 마크다운 → 나레이션 문장 목록. 장식·면책은 뺀다."""
    out: list[str] = []
    for raw_line in (script_md or "").split("\n"):
        line = _INLINE_MD.sub("", _MD_NOISE.sub("", raw_line)).strip()
        if not line or _SKIP_LINE.search(line):
            continue
        for part in _SENT_SPLIT.split(line):
            part = (part or "").strip()
            if len(part) >= config.CUT_SKELETON_MIN_CHARS:
                out.append(part)
    return out


def estimate_sec(sentence: str) -> float:
    """문장 → 예상 나레이션 초. 글자수 ÷ 말속도.

    ★ 정확할 필요는 없다 — 골격은 "몇 칸인가"를 정하는 것이고, 실제 길이는 렌더가 TTS 를
      실측해 다시 맞춘다(engine/render.py). 여기서는 칸을 고르게 나누는 데만 쓴다.
    """
    return max(1.0, len(sentence) / config.SPEECH_CHARS_PER_SEC)


def _split_long(sentence: str, max_sec: float) -> list[str]:
    """한 문장이 한 컷에 담기엔 너무 길면 **의미 단위**로 쪼갠다.

    쉼표·접속 부사 경계에서 자른다. 자를 곳이 없으면 그대로 둔다 — 글자수로 억지로 자르면
    말이 끊겨 나레이션이 이상해진다(그 경우는 컷이 길어질 뿐이고 게이트가 경고로 잡는다).
    """
    if estimate_sec(sentence) <= max_sec:
        return [sentence]
    parts = [p.strip() for p in _CLAUSE_SPLIT.split(sentence) if p and p.strip()]
    if len(parts) < 2:
        return [sentence]
    merged: list[str] = []
    buf = ""
    for p in parts:
        cand = f"{buf} {p}".strip()
        # ★ 조각이 아직 "한 마디"면 길이를 넘더라도 계속 붙인다(2026-08-29 실측).
        #   실측 사고: "즉, 이 결과는 …" 이 쉼표에서 갈려 **컷10 = "즉," (3초)** 가 나왔다.
        #   "하지만," 도 마찬가지. 접속사 하나로 컷을 만들면 화면은 3초 동안 아무 말도 하지
        #   않는다 — 조금 긴 컷이 한 마디짜리 컷보다 낫다. 길이 초과는 게이트가 경고로 잡는다
        #   (photo_cut_too_long)지만, 한 마디 컷은 아무도 안 잡고 있었다.
        if buf and estimate_sec(cand) > max_sec and len(buf) >= config.CUT_SKELETON_MIN_CHARS:
            merged.append(buf)
            buf = p
        else:
            buf = cand
    if buf:
        # 마지막 조각이 한 마디면 앞 칸에 되돌려 붙인다(뒤에 붙일 곳이 없다).
        if merged and len(buf) < config.CUT_SKELETON_MIN_CHARS:
            merged[-1] = f"{merged[-1]} {buf}".strip()
        else:
            merged.append(buf)
    return _heal_unfinished(merged)


def _heal_unfinished(parts: list[str]) -> list[str]:
    """**말이 맺히지 않은 조각을 뒤 조각과 다시 붙인다.**

    ★ 왜 필요한가: 위 정규식을 아무리 다듬어도 예외는 남는다(실측 ②의 명사 나열처럼).
      규칙을 계속 늘리는 대신, **결과를 보고 고친다** — 조각이 연결/종결 어미로 끝나지
      않으면 그건 문장의 반쪽이므로 뒤와 합친다. 마지막 조각은 앞과 합친다.
    ★ 이 안전망이 없으면 "심지어 탐색 행동 공간 기억" 같은 술어 없는 컷이 그대로 나간다.
    """
    out: list[str] = []
    carry = ""
    for p in parts:
        cur = f"{carry} {p}".strip() if carry else p
        if _CLAUSE_END.search(cur):
            out.append(cur)
            carry = ""
        else:
            carry = cur                    # 아직 말이 안 맺혔다 — 다음 조각까지 기다린다
    if carry:
        if out:
            out[-1] = f"{out[-1]} {carry}".strip()
        else:
            out.append(carry)
    return out


def build(script_md: str, *, total_sec: int | None = None,
          version_type: str = "photo") -> list[dict[str, Any]]:
    """대본 → 컷 골격. 반환: [{cut_no, sentence, estimated_sec}].

    ★ 컷 수는 **문장 수에서 나온다**(대본 scenes 개수가 아니라). 한 컷 = 한 문장이 계약이고,
      너무 긴 문장만 의미 단위로 쪼갠다. 짧은 문장을 억지로 합치지 않는다 — 합치기 시작하면
      "한 컷에 메시지 두 개"가 되어 계약이 처음부터 깨진다.
    """
    max_sec = float(config.PHOTO_CUT_SEC_MAX if version_type == "photo" else config.CUT_MAX_SEC)
    units: list[str] = []
    for s in sentences(script_md):
        units.extend(_split_long(s, max_sec))
    if not units:
        return []
    return [
        {"cut_no": i, "sentence": u, "estimated_sec": max(config.CUT_MIN_SEC,
                                                          round(estimate_sec(u)))}
        for i, u in enumerate(units, 1)
    ]


def skeleton_block(skeleton: list[dict[str, Any]]) -> str:
    """지시서 프롬프트에 박을 골격 구간. 비면 **빈 문자열**(빈 마커 금지)."""
    if not skeleton:
        return ""
    lines = [f"  {c['cut_no']:>2}. ({c['estimated_sec']}초) {c['sentence']}" for c in skeleton]
    total = sum(c["estimated_sec"] for c in skeleton)
    return (
        f"\n\n[컷 골격 — 코드가 문장 경계로 계산했다. **칸 수를 줄이지 마라**]\n"
        f"총 {len(skeleton)}컷 / 약 {total}초. 각 칸은 나레이션 한 문장이다.\n"
        + "\n".join(lines)
        + "\n★ 네가 정하는 것은 **각 칸을 무엇으로 보여줄 것인가**다(visual_role · mechanism 구조 ·\n"
          "  visual_prompt · overlay_plan). 칸을 합치거나 빼지 마라 — 합치면 한 컷에 메시지가\n"
          "  둘이 되고, 그 순간 이 버전의 화면 문법이 깨진다.\n"
          "  문장을 다듬는 것은 허용한다(구어체·길이). 다만 칸의 순서와 개수는 유지하라."
    )


def shortfall(skeleton: list[dict[str, Any]], cuts: list[dict[str, Any]]) -> str:
    """골격 대비 컷이 얼마나 줄었는가. 문제 없으면 빈 문자열.

    ★ 왜 이 검사가 필요한가(2026-08-29 실측): 골격을 프롬프트에 넣기만 하고 지켰는지 보지
      않았더니, **11칸을 줬는데 모델이 7컷을 냈다.** 대본 씬 6개의 리듬으로 되돌아간 것이다.
      "칸을 합치지 마라"는 문장은 지시일 뿐이고, 지시는 검사되지 않으면 지켜지지 않는다 —
      이 저장소가 화면 계약에서 이미 배운 것이다.

    ★ 관용을 둔다: 문장 분해가 완벽하지 않아 두세 칸이 자연스럽게 합쳐지는 경우가 있다.
      CUT_SKELETON_TOLERANCE 비율 아래로 떨어질 때만 위반으로 본다.
    """
    if not skeleton:
        return ""
    need = max(1, int(len(skeleton) * config.CUT_SKELETON_TOLERANCE))
    got = len(cuts)
    return f"photo_skeleton_shortfall:{got}<{need}(골격 {len(skeleton)}칸)" if got < need else ""


# ─────────────────────────────────────────────────────────────
# 대사 고정 (2026-10-05, Explanation Engine v2 설계 점검 A — 운영자 결정 ①)
# ─────────────────────────────────────────────────────────────
# ★ 왜: 원 작업지시서는 "독립 검증자가 **최종 대본**을 원문과 대조한다"(§9.4)와 "대본은 검증된 논리
#   밖의 새 이야기를 만들지 못한다"(Phase 6)를 요구한다. V2 대본은 그 검증을 통과했는데, 리포트
#   지시서 생성기가 대본을 "초안"으로 보고 다시 썼다(실측 Samsung: 14컷 중 V2 문장 0개, 말하는 숫자
#   2→5개, 없던 주주환원 문장 추가). 위 `skeleton_block` 은 컷 **개수·순서**만 고정하고 "문장을 다듬는
#   것은 허용"한다 — 그래서 대사까지 글자 그대로 고정하는 장치를 따로 둔다.
# ★ 초안에 `NARRATION_LOCK_KEY` 가 참일 때만 작동한다. 그 값은 V2 브리지(`v2_directive_bridge`)만
#   넣는다 — Production 초안에는 없으므로 Production 지시서 동작은 바뀌지 않는다.
NARRATION_LOCK_KEY = "narration_lock"
_LOCK_IGNORED = re.compile(r"[\s.,!?·\"'“”‘’…~]+")


def lock_min_cuts(skeleton: list[dict[str, Any]]) -> int:
    """실사형 게이트(`photo_contract.target_cut_range`)와 같은 식의 최소 컷 수 — **목표치**다.

    ★ 게이트는 모델이 적은 컷 길이 합으로 세고, 골격은 `SPEECH_CHARS_PER_SEC`(5.5자/초)로 잰다.
      골격 쪽이 길게 나와(Samsung V2 355자 → 65초 → 13컷) 목표가 게이트보다 높다. 그래서 이 값은
      "의미 경계가 허락하는 만큼 나눈다"의 상한으로만 쓴다 — 바닥값 `PHOTO_MIN_CUTS` 는 반드시 채우려 한다.
    """
    total = sum(int(c.get("estimated_sec") or 0) for c in skeleton)
    return max(config.PHOTO_MIN_CUTS, round(total / config.PHOTO_CUT_SEC_MAX))


def lock_skeleton(script_md: str, *, version_type: str = "photo") -> list[dict[str, Any]]:
    """대사 고정용 골격 — 실사형 최소 컷 수에 모자라면 긴 문장을 **의미 경계에서** 더 나눈다.

    ★ 왜(2026-10-05 실측): V2 대본은 숫자를 화면으로 보내 짧다(Samsung 355자, 기존 518자). 문장 경계로
      나누면 7칸인데 실사형 바닥값은 8컷이다(`PHOTO_MIN_CUTS`, "이보다 적으면 슬라이드쇼"). 대사가
      고정이라 모델이 칸을 늘릴 수 없어 `photo_cut_count_low:7<8` 로 막혔다. 같은 "컷 수"를 골격과
      게이트가 다르게 셌던 것이다.
    ★ 대사는 한 글자도 바뀌지 않는다 — 칸만 나뉜다. 나누는 규칙은 `_split_long` 그대로(연결 어미
      경계, 말이 맺히지 않은 조각은 다시 붙임). 자를 의미 경계가 없으면 억지로 자르지 않는다 — 그때는
      게이트가 그대로 막는다(슬라이드쇼를 숨기지 않는다).
    """
    bones = build(script_md, version_type=version_type)
    if version_type != "photo" or not bones:
        return bones
    need = lock_min_cuts(bones)
    units = [b["sentence"] for b in bones]
    while len(units) < need:
        for index in sorted(range(len(units)), key=lambda i: -estimate_sec(units[i])):
            parts = _split_long(units[index], max(1.0, estimate_sec(units[index]) / 2))
            if len(parts) < 2:
                parts = _split_at_connective_comma(units[index])
            if len(parts) >= 2:
                units[index:index + 1] = parts
                break
        else:
            break                                   # 더 나눌 의미 경계가 없다
    return [
        {"cut_no": i, "sentence": u,
         "estimated_sec": max(config.CUT_MIN_SEC, round(estimate_sec(u)))}
        for i, u in enumerate(units, 1)
    ]


# 쉼표 앞이 이 글자로 끝나면 연결 어미다("힘입어," "늘어나고," "오르면,") — 그 쉼표는 절 경계다.
# 숫자·명사 나열 쉼표("18.0%, 16.0%" "DRAM, NAND")는 앞 글자가 숫자·기호·명사라 걸리지 않는다.
_CONNECTIVE_TAIL = frozenset("어아여고며서면데만게지니")


def _split_at_connective_comma(sentence: str) -> list[str]:
    """`_CLAUSE_SPLIT` 에 없는 연결 어미 쉼표("…힘입어, …")에서 한 번 나눈다. 가운데에 가까운 곳."""
    candidates = [
        i for i, ch in enumerate(sentence)
        if ch == "," and i > 0 and sentence[i - 1] in _CONNECTIVE_TAIL
        and len(sentence[:i + 1].strip()) >= config.CUT_SKELETON_MIN_CHARS
        and len(sentence[i + 1:].strip()) >= config.CUT_SKELETON_MIN_CHARS
    ]
    if not candidates:
        return [sentence]
    cut = min(candidates, key=lambda i: abs(i - len(sentence) / 2))
    return [sentence[:cut + 1].strip(), sentence[cut + 1:].strip()]


# 원리 도해 제안은 칸의 문장이 **과정(원인 → 결과)** 을 말할 때만 붙인다. 단락 전체에 붙이면
# "가격이 크게 상승할 것" 같은 숫자 문장도 도해 후보가 되고, 리포트 게이트는 숫자 단계를 도해로
# 그리면 승인을 막는다(`photo_mechanism_on_number`). 실측 Samsung 단락에서 이 표현들이 과정 칸을 갈랐다.
_CAUSAL_MARKERS = ("힘입어", "견인", "때문", "따라", "인해", "이어져", "이어지", "늘리", "줄이", "바꾸",
                   "하면서", "으로써", "통해")


def _hint_for(sentence: str, hints: list[dict[str, Any]] | None) -> str:
    key = _LOCK_IGNORED.sub("", sentence)
    for row in hints or []:
        if key and key in _LOCK_IGNORED.sub("", str(row.get("text") or "")):
            hint = str(row.get("hint") or "")
            if hint == "MECHANISM" and not any(marker in sentence for marker in _CAUSAL_MARKERS):
                return ""
            return hint
    return ""


def lock_block(skeleton: list[dict[str, Any]],
               hints: list[dict[str, Any]] | None = None) -> str:
    """대사 고정 지시문. 칸마다 말할 문장을 글자 그대로 주고, 있으면 화면 제안을 붙인다."""
    if not skeleton:
        return ""
    lines = []
    for c in skeleton:
        hint = _hint_for(c["sentence"], hints)
        suffix = f"   ← 화면 제안: {hint}" if hint else ""
        lines.append(f"  {c['cut_no']:>2}. ({c['estimated_sec']}초) {c['sentence']}{suffix}")
    return (
        f"\n\n[대사 고정 — 검증을 마친 대본이다] 총 {len(skeleton)}컷. 각 칸의 narration_ko 는 아래 문장을\n"
        "**글자 그대로** 쓴다. 다듬지도, 합치지도, 나누지도, 새 문장을 더하지도 마라 — 이 문장들은 원문 근거와\n"
        "대조를 이미 마쳤고, 바뀌면 검증받지 않은 대본이 된다. Fact Sheet 나 논증 단위에 다른 내용이 있어도\n"
        "대사에 넣지 마라. 네가 정하는 것은 **각 칸을 무엇으로 보여줄 것인가**뿐이다.\n"
        "'화면 제안: MECHANISM' 이 붙은 칸은 그 문장이 과정(원인 → 결과)을 말한다 — 원리 도해(MECHANISM)\n"
        "컷으로 만드는 것을 먼저 검토하라. 숫자·리스크 문장은 도해로 그리지 마라.\n"
        + "\n".join(lines)
    )


def lock_hints(draft_row: dict[str, Any]) -> list[dict[str, Any]]:
    """초안의 대사 고정 값에 실린 화면 제안(V2 브리지가 넣는다). 없으면 빈 목록."""
    value = draft_row.get(NARRATION_LOCK_KEY)
    rows = value.get("visual_hints") if isinstance(value, dict) else None
    return [row for row in rows or [] if isinstance(row, dict)]


def _same_words(a: Any, b: Any) -> bool:
    return _LOCK_IGNORED.sub("", str(a or "")) == _LOCK_IGNORED.sub("", str(b or ""))


def lock_narration(cuts: list[dict[str, Any]], skeleton: list[dict[str, Any]]) -> dict[str, Any]:
    """모델이 낸 컷의 대사를 골격 문장으로 되돌린다. 컷 수가 다르면 되돌리지 않고 불일치로 보고한다.

    ★ 화면은 모델이 칸마다 받은 문장을 보고 만들었으므로, 칸 수가 같으면 대사만 되돌려도 화면과
      대사가 같은 칸을 가리킨다. 칸 수가 다르면 어느 화면이 어느 문장인지 알 수 없다 — 승인 차단.
    """
    rows = [cut for cut in cuts if isinstance(cut, dict)]
    if len(rows) != len(skeleton):
        return {"status": "CUT_COUNT_MISMATCH", "expected_cuts": len(skeleton),
                "actual_cuts": len(rows), "restored": []}
    restored = []
    for cut, bone in zip(rows, skeleton):
        # 낱말이 바뀐 것만 '되돌림'으로 기록하고, 문장부호까지 검증된 원문으로 늘 맞춘다.
        if not _same_words(cut.get("narration_ko"), bone["sentence"]):
            restored.append({"cut_no": bone["cut_no"], "model_text": str(cut.get("narration_ko") or "")})
        cut["narration_ko"] = bone["sentence"]
    return {"status": "LOCKED", "expected_cuts": len(skeleton), "actual_cuts": len(rows),
            "restored": restored}


def lock_reason(report: dict[str, Any]) -> str:
    """대사 고정 승인 차단 사유(없으면 빈 문자열)."""
    if report.get("status") == "CUT_COUNT_MISMATCH":
        return f"narration_lock_cut_count:{report['actual_cuts']}!={report['expected_cuts']}"
    return ""
