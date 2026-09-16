"""대본 한국어 다듬기 — **표현만** 고치고 사실은 못 건드리게 한다 (2026-09-10).

운영자 지시:
> "한국어 구조가 어색한게 없는지 한번더 대본리뷰한 후 생성하는 절차를 넣어야할듯합니다."

무엇을 푸는가: `selfcheck.py` 는 **사실 검증관**이다 — 문장이 Fact Sheet 로 뒷받침되는지를
본다. 한국어가 자연스러운지는 아무도 안 봤다. 이 대본은 소리 내어 읽히므로(Edge TTS),
눈으로 말이 되는 것으로는 부족하다.

구조는 이 저장소의 기존 자세를 그대로 쓴다:

  ① 판정   `selfcheck` 의 `korean_natural` 축(같은 호출 — 추가 비용 0)
  ② 되먹임 여기서 **어색하다고 찍힌 씬만** 다시 쓰게 한다(전체 재생성 아님)
  ③ 방어   ★ **사실이 바뀌면 코드가 그 문장을 버린다.**

★★ ③ 이 이 모듈의 존재 이유다. 문장을 매끄럽게 만들다가 숫자·범위가 어긋나는 것은 이
  저장소가 이미 겪은 실패 유형이고, "사실을 바꾸지 마라"고 프롬프트에 적는 것만으로는
  막히지 않는다(실측 교훈: 금지와 대안을 다 줘도 모델은 부분만 지킨다 —
  `config.PHOTO_OPTICS_REWRITES` 주석). 그래서 기계가 대조한다:

    · 숫자·단위가 **다중집합으로 같아야** 한다(순서는 달라도 된다)
    · **줄기가 남아 있어야** 한다 — 숫자도 뜻도 그대로인데 문장 하나가 통째로 빠지는 교정을
      앞의 둘은 통과시킨다(발견 하나가 조용히 사라진다)
    · 글자 수가 크게 달라지면 안 된다. 다만 **줄어드는 쪽을 더 허용한다** — 번역투 제거는
      정의상 문장을 줄이고, 늘어나는 것은 없던 설명을 덧붙였다는 뜻이라 위험하다.
      짧은 문장은 비율로 재지 않는다(`SCRIPT_POLISH_LEN_FLOOR_CHARS`)
    · **뜻의 갈래**가 같아야 한다 — 증감 방향(up/down)·범위 단서·불확실성·연관·부정.
      낱말이 아니라 부류로 본다: `늘`→`증가` 는 통과하고 `늘`→`줄` 은 거부된다

  한 조건이라도 어긋나면 **원문을 그대로 둔다.** 버린 사실은 보고에 남는다 —
  조용히 버리면 "다듬었다"고 믿는 채로 아무 일도 안 일어난다.

순수 모듈 + LLM 호출 하나. DB 를 모른다.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import config
from .llm import call_json, set_text_purpose

POLISH_SYSTEM = f"""너는 한국어 나레이션 교정자다. 입력: 어색하다고 표시된 대본 씬들.

■ 하는 일은 **하나뿐이다: 한국어를 자연스럽게 다듬는다.**
  이 글은 소리 내어 읽힌다. 귀로 들어 걸리는 데가 없게 고쳐라.
  · 번역투를 우리말로 — "~에 대한 연구" → "~를 다룬 연구", "~를 통해" → "~로",
    "가지고 있다" → "있다", "~되어진다" → "~된다".
  · 조사를 바로잡는다(은/는·이/가·을/를).
  · 문체를 통일한다 — 한 대본 안에서 "~합니다" 와 "~한다" 를 섞지 마라.
  · 수식이 겹치면 문장을 **끊어라**. 한 문장은 한 호흡(60자 안쪽)이 좋다.
  · 소리 내 읽었을 때 모호한 것을 풀어라 — 영어 약어는 한글 표기를 덧붙이고
    ("NAD+" → "엔에이디 플러스"), 숫자·단위는 읽히는 대로 띄어 준다.

■■ **절대 하지 마라 — 사실을 건드리는 것.**
  · 숫자·단위·퍼센트·배수를 **바꾸거나 빼거나 더하지 마라.** 원문에 있는 그대로 옮긴다.
  · 대상·기간·지역의 **범위를 넓히거나 좁히지 마라**("일부 쥐에서" → "쥐에서" 금지).
  · 단서·조건을 **지우지 마라**("평균적으로", "특정 조건에서", "~로 보입니다").
  · 인과를 **세게 만들지 마라**("연관이 있었다" → "때문이다" 금지).
  · 없던 설명·비유·감상을 **덧붙이지 마라.** 문장 수와 길이를 크게 바꾸지 마라.
  ★ 고칠 것이 없으면 원문을 그대로 돌려줘라. 억지로 바꾸지 마라.

JSON only. 설명·마크다운·코드펜스 금지.
{{
  "scenes": [
    {{ "scene": <int>, "narration_ko": "<다듬은 나레이션 전문>",
      "changed": <bool>, "note": "<무엇을 고쳤는지 한 줄>" }}
  ]
}}"""

# 숫자 + 붙어 있는 단위. "92일" · "1.5배" · "30%" · "2026년" 을 한 덩어리로 본다.
#   ★ 단위를 함께 잡는 이유: 숫자만 보면 "30%" → "30배" 가 통과한다.
#   ★ 긴 단위를 앞에 둔다(개월 > 개, ml > m). 정규식 교대는 먼저 맞는 것을 고르므로
#     `m` 이 `ml` 앞에 있으면 "30ml" 가 "30m" 으로 잘린다. 양쪽이 같이 잘리면 대조는
#     그대로 통과하지만, "30ml"→"30mg" 같은 단위 변경을 놓친다.
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|퍼센트|배|년|개월|주|일|시간|분|초|"
                     r"명|마리|건|개|회|kg|km|mg|ml|mm|cm|g|m|L)?")

def _numbers(text: str) -> list[str]:
    """숫자·단위 다중집합. 순서는 달라도 되지만 **구성은 같아야** 한다."""
    return sorted(m.group(0).replace(" ", "") for m in _NUMBER.finditer(str(text or ""))
                  if any(ch.isdigit() for ch in m.group(0)))


# 지켜야 할 **뜻의 갈래**. 낱말이 아니라 **부류**로 본다.
#
# ★ 처음에는 낱말을 그대로 대조했는데 **정상 교정이 막혔다**(2026-09-10 실측):
#   "평균 30% 늘었습니다" → "평균 30% 증가했습니다" 가 '늘' 이 사라졌다고 거부됐다.
#   그건 사실이 바뀐 것이 아니라 같은 뜻을 다르게 쓴 것이다 — 다듬기의 목적 자체다.
#   그래서 부류로 본다: `늘`→`증가` 는 같은 부류(up)라 통과하고, `늘`→`줄` 은 부류가
#   바뀌므로 거부된다.
# ★★ 부분 문자열로 찾는다(어미 변화 때문에). 오탐 방향은 **거부**이고, 거부되면 원문이
#   그대로 남는다 — 안전한 쪽으로 틀린다.
_MEANING_CLASSES: dict[str, tuple[str, ...]] = {
    # 증감 방향 — 뒤집히면 결론이 정반대가 된다.
    "up": ("증가", "늘", "상승", "높", "향상", "개선"),
    "down": ("감소", "줄", "하락", "낮", "악화"),
    # 범위·확실성 단서 — 지워지면 주장이 넓어진다.
    "hedge": ("평균", "일부", "약", "가량", "정도", "경향", "특정", "대체로"),
    # ★ `보이다` 는 **완곡 어미일 때만** 단서다(2026-09-10 실측). 바로 그 이중피동을 고치는
    #   것이 다듬기의 일이라 어간만 보면 정상 교정이 막힌다("보여집니다"→"보입니다" 가 거부됐다).
    #   그렇다고 `보여` 를 통째로 넣으면 "보여주고 있습니다"(= shows, 단서가 아니다)까지 잡혀
    #   반대쪽 오탐이 난다. 그래서 **구성 단위**로 적는다.
    "uncertain": ("가능성", "추정", "보입", "보인", "보여집", "보여진", "듯", "예상", "시사"),
    # 인과가 아니라 **연관**이라는 표시.
    "assoc": ("연관", "상관", "관련"),
    # 부정 — 가장 조용히 뒤집히는 자리다.
    "negation": ("않", "못", "없", "아니"),
}


def meaning_classes(text: str) -> set[str]:
    """이 문장이 담고 있는 **뜻의 갈래**. 다듬기 전후로 같아야 한다."""
    t = str(text or "")
    return {name for name, terms in _MEANING_CLASSES.items()
            if any(term in t for term in terms)}


_HANGUL_WORD = re.compile(r"[가-힣]+")


def _stems(text: str) -> set[str]:
    """어절의 앞 두 글자. 조사·어미가 붙어도 줄기는 남는다(약물의→약물, 투여에→투여).

    ★ 형태소 분석기를 쓰지 않는 이유: 의존성 하나를 더 들이는 값어치가 없다. 두 글자
      자르기는 거친 대리 판정이고, **틀리는 방향이 안전하다** — 못 맞히면 거부하고,
      거부하면 원문이 그대로 남는다.
    """
    return {w[:2] for w in _HANGUL_WORD.findall(str(text or "")) if len(w) >= 2}


def stem_retention(before: str, after: str) -> float:
    """다듬은 문장이 원문의 낱말 줄기를 얼마나 지켰는가(0~1)."""
    b = _stems(before)
    return len(b & _stems(after)) / len(b) if b else 1.0


def rejection_reason(before: str, after: str) -> str:
    """다듬은 문장을 **버려야 하는 이유** — 없으면 빈 문자열.

    ★ 프롬프트의 금지만으로는 안 막힌다(이 저장소 실측 교훈). 기계가 대조한다.
    """
    a, b = str(before or "").strip(), str(after or "").strip()
    if not b:
        return "polish_empty"
    if _numbers(a) != _numbers(b):
        return "polish_numbers_changed"
    ca, cb = meaning_classes(a), meaning_classes(b)
    if ca != cb:
        drift = sorted((ca - cb) | (cb - ca))
        return "polish_meaning_changed:" + ",".join(drift[:3])
    if a and stem_retention(a, b) < config.SCRIPT_POLISH_MIN_STEM_RETENTION:
        return "polish_content_dropped"
    gap = len(b) - len(a)
    limit = (config.SCRIPT_POLISH_LEN_TOLERANCE if gap > 0
             else config.SCRIPT_POLISH_SHRINK_TOLERANCE)
    if (a and abs(gap) > config.SCRIPT_POLISH_LEN_FLOOR_CHARS
            and abs(gap) / len(a) > limit):
        return "polish_length_drift"
    return ""


def awkward_scenes(check: dict[str, Any] | None) -> list[int]:
    """자기검증이 **어색하다고 찍은** 씬 번호."""
    return sorted({int(s.get("scene") or 0)
                   for s in ((check or {}).get("scenes") or [])
                   if isinstance(s, dict) and not s.get("korean_natural", True)}
                  - {0})


def polish_user_prompt(scenes: list[dict[str, Any]],
                       check: dict[str, Any] | None) -> str:
    """어색하다고 찍힌 씬 + **무엇이 어색한지** 를 함께 준다."""
    by_no = {int(s.get("scene") or 0): s for s in ((check or {}).get("scenes") or [])
             if isinstance(s, dict)}
    payload = []
    for s in scenes:
        no = int(s.get("scene") or 0)
        judged = by_no.get(no) or {}
        payload.append({
            "scene": no,
            "narration_ko": str(s.get("narration_ko") or ""),
            "어색한_구절": judged.get("awkward_spans") or [],
            "어색함의_종류": judged.get("fluency_issues") or [],
        })
    return ("아래 씬들의 한국어를 다듬어라. 사실·숫자·범위·단서는 그대로 둔다.\n"
            + json.dumps(payload, ensure_ascii=False, indent=2))


def apply_polish(scenes: list[dict[str, Any]],
                 polished: dict[str, Any]) -> dict[str, Any]:
    """다듬은 결과를 **검사하고** 씬에 적용한다(제자리 수정) → 보고.

    반환: {"applied": [씬번호], "rejected": [{"scene", "reason"}], "unchanged": [씬번호]}
    """
    by_no = {int(s.get("scene") or 0): s for s in scenes if isinstance(s, dict)}
    applied: list[int] = []
    rejected: list[dict[str, Any]] = []
    unchanged: list[int] = []
    for row in (polished.get("scenes") or []):
        if not isinstance(row, dict):
            continue
        no = int(row.get("scene") or 0)
        target = by_no.get(no)
        if not target:
            continue
        before = str(target.get("narration_ko") or "")
        after = str(row.get("narration_ko") or "").strip()
        if after == before.strip():
            unchanged.append(no)
            continue
        reason = rejection_reason(before, after)
        if reason:
            rejected.append({"scene": no, "reason": reason})
            continue
        target["narration_ko"] = after
        applied.append(no)
    return {"applied": sorted(applied), "rejected": rejected,
            "unchanged": sorted(unchanged)}


def rewrite_script_md(script_md: str, replacements: list[tuple[str, str]]) -> tuple[str, int]:
    """읽기용 대본에도 같은 교정을 반영한다 → (새 대본, 반영된 개수).

    ★ 왜 필요한가: 한 편에 대본이 두 벌 있다 — `script_md`(④ 화면이 보여주고 운영자가 고치는 것)와
      `scenes`(씬별 나레이션). ⑤ 지시서 생성기는 **둘을 함께** 입력으로 넣는다
      (`engine/script_revision.py` 머리말). 씬만 다듬고 대본을 두면 두 원고가 어긋난 채
      한 프롬프트에 들어가고, 다듬기 전 문장이 영상에 다시 등장할 수 있다.

    ★★ **그대로 있는 문장만** 바꾼다. 못 찾으면 손대지 않는다 — 형식이 고정이 아니라
      (문단만 있는 초안도, `**씬1 (후크)**` 머리글이 붙은 초안도 실측된다) 자리로 맞추면
      엉뚱한 곳을 덮어쓸 수 있다.
    """
    out = str(script_md or "")
    hit = 0
    for before, after in replacements:
        b = str(before or "").strip()
        if b and b in out:
            out = out.replace(b, str(after or "").strip())
            hit += 1
    return out, hit


def polish(scenes: list[dict[str, Any]],
           check: dict[str, Any] | None) -> dict[str, Any]:
    """어색하다고 찍힌 씬만 한 번 다시 쓰게 한다. **씬을 제자리에서 고친다.**

    어색한 씬이 없으면 LLM 을 부르지 않는다(비용 0).
    """
    if not config.SCRIPT_POLISH_ENABLED:
        return {"ran": False, "reason": "disabled"}
    want = set(awkward_scenes(check))
    targets = [s for s in scenes if int(s.get("scene") or 0) in want]
    if not targets:
        return {"ran": False, "reason": "no_awkward_scene"}
    set_text_purpose("script_polish")     # 비용 원장의 용도 라벨(engine/llm.py)
    obj = call_json(
        model=config.MODEL_SCRIPT,
        system=POLISH_SYSTEM,
        user=polish_user_prompt(targets, check),
        max_tokens=4096,
    )
    report = apply_polish(scenes, obj)
    report["ran"] = True
    report["targets"] = sorted(want)
    return report
