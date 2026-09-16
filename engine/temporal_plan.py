"""Invest Temporal Contract — **8초를 어떻게 쓸 것인가** (v2 Phase E2).

무엇을 푸는가: 등급제가 기전 컷에 8초를 준다. 그런데 8초는 **품질이 아니라 품질을 만들
수 있는 시간 예산**이다(코덱스 리뷰 §7). 같은 8초라도

    A. 피사체 하나, 카메라 고정, 미세한 움직임을 8초 유지
    B. 0~2.5s 구조 전체 wide reveal → 2.5~5.5s 작동 부위 lateral follow
       → 5.5~8s 핵심 부위 rapid push-in

은 완전히 다른 영상이다. 길이만 늘리면 A 가 되고, 그건 **지루한 8초**다.

벤치마크 실측이 그것을 말한다(`docs/benchmark-realistic-shorts-2026-08-19.md`):
"8초에 비트 2개, 횡이동 + 마지막 급속 푸시인. 한 컷에 2~3샷을 넣는 멀티샷."
즉 벤치마크의 8초는 **8초짜리 한 장면이 아니라 8초 안에 든 작은 편집 시퀀스**다.

그래서 invest 등급은 길이와 함께 **연출 계약**을 받는다:

    temporal_plan = [ {t0, t1, entity_id, mutation, camera}, ... ]

★★ **자기보고로 끝내지 않는다**(리뷰 §8 조건). 이 저장소가 여덟 번 겪은 실패가
  "필드를 만들었는데 소비자가 안 읽는다"이므로:
    ① `build_motion_prompt` 가 이 비트를 **실제로 프롬프트에 조립한다**(providers/video).
    ② 게이트가 [비트 수 · enum 준수 · 상태 변화 존재]를 코드로 검사한다(`evaluate`).
  둘 다 없으면 이 모듈은 장식이다.

★ 어휘는 **닫힌 목록**만 쓴다 — 카메라는 `config.CAMERA_OPERATIONS`, 변화는
  `config.MUTATION_OPERATIONS`. 자유 문장을 받으면 규격 토큰이 화면에 글자로 박히는
  사고(Phase 0 §3-3 "35°")가 되돌아온다.

순수 모듈. 네트워크·LLM 없음.
"""

from __future__ import annotations

import re
from typing import Any

from . import config


def normalize_beat(raw: Any, index: int, clip_sec: int) -> dict[str, Any] | None:
    """비트 하나 정규화. 쓸 수 없으면 None(호출측이 버린다 — dangling 규율).

    ★ 시간 구간은 클립 안에 있어야 한다. 밖으로 나가면 그 비트는 화면에 없는 시간을
      가리키는 것이고, 프롬프트에 실으면 모델이 없는 시간을 채우려 한다.
    """
    d = raw if isinstance(raw, dict) else {}
    try:
        t0 = float(d.get("t0"))
        t1 = float(d.get("t1"))
    except (TypeError, ValueError):
        return None
    if not (0 <= t0 < t1 <= float(clip_sec)):
        return None
    camera = str(d.get("camera") or "").strip().upper()
    if camera not in config.CAMERA_OPERATIONS:
        return None                       # 닫힌 목록 밖 — 자유 문장을 받지 않는다
    mutation = str(d.get("mutation") or "").strip().upper()
    if mutation and mutation not in config.MUTATION_OPERATIONS:
        mutation = ""                     # 변화는 선택 — 카메라만 있는 비트도 있다
    return {
        "beat": index,
        "t0": round(t0, 2), "t1": round(t1, 2),
        "entity_id": str(d.get("entity_id") or "").strip(),
        "mutation": mutation,
        "camera": camera,
    }


def normalize(raw: Any, clip_sec: int) -> list[dict[str, Any]]:
    """`temporal_plan` 정규화. 시간 순으로 정렬하고 겹치는 비트는 버린다.

    ★ 겹치면 프롬프트가 같은 순간에 두 가지를 요구한다 — 모델은 둘 다 못 하거나
      둘 다 어중간하게 한다. 순서를 코드가 정리해 그 모순을 없앤다.
    """
    items = raw if isinstance(raw, list) else []
    beats: list[dict[str, Any]] = []
    for i, b in enumerate(items, 1):
        got = normalize_beat(b, i, clip_sec)
        if got:
            beats.append(got)
    beats.sort(key=lambda b: (b["t0"], b["t1"]))
    out: list[dict[str, Any]] = []
    for b in beats:
        if out and b["t0"] < out[-1]["t1"]:
            continue                      # 앞 비트와 겹친다
        b["beat"] = len(out) + 1
        out.append(b)
        if len(out) >= config.TEMPORAL_MAX_BEATS:
            break
    return out


def prose(beats: list[dict[str, Any]]) -> str:
    """비트 → 프롬프트에 실을 시간 순 문장. **이것이 실제로 발주된다.**

    ★ 형태를 "장면 묘사"가 아니라 **시간 구간별 동작**으로 유지한다. 시작 프레임이
      이미 장면이므로 다시 묘사하면 Veo 가 애니메이트하지 않고 다시 그린다
      (`build_motion_prompt` 독스트링의 그 사고).
    """
    if not beats:
        return ""
    parts: list[str] = []
    for b in beats:
        move = config.CAMERA_PROSE.get(b["camera"], b["camera"].lower().replace("_", " "))
        seg = f"{b['t0']:.1f}-{b['t1']:.1f}s {move}"
        change = config.MUTATION_PROSE.get(b["mutation"], "")
        # ★ 한글 개체 id 는 이름을 싣지 않는다(entity_name 주석 — 2026-09-14 스윕).
        if change and entity_name(b["entity_id"]):
            seg += f" as the {entity_name(b['entity_id'])} {change}"
        elif change:
            seg += f" as it {change}"
        parts.append(seg)
    return "shot sequence within the clip: " + "; then ".join(parts)


_CAMERA_CLAUSE = re.compile(config.MOTION_CAMERA_CLAUSE_PATTERN, re.I)
# ★ "…, symbolizing accumulating life outcomes" 는 **뜻 설명**이지 화면이 아니다. A/B(2026-09-14)에서
#   이 구절이 붙은 문장이 떠다니는 호박색 아이콘 배지로 그려졌다 — 상징을 그리라는 말로 읽혔다.
#   ★ 저장 지시서 251컷 무료 스윕(2026-09-14)에서 같은 부류가 더 나왔다 — represented by·indicated by·
#     emphasizing·highlighting·creating a sense of·illustrating·confirming. 한 번에 다 뺀다.
_MEANING_CLAUSE = re.compile(
    r",?\s*\b(?:symboli[sz]ing|symboli[sz]es|representing|represented\s+by|indicating|indicated\s+by|"
    r"implying|suggesting|signifying|emphasi[sz]ing|highlighting|illustrating|confirming|"
    r"creating\s+a\s+sense\s+of|to\s+show\s+that|as\s+a\s+metaphor)\b[^,.;]*", re.I)
# 발주 문장에 실으면 안 되는 것 — 기존 게이트와 **같은 어휘**를 쓴다(따로 적으면 어긋난다).
#   화면 글자·그래프·게이지·아이콘·숫자·따옴표 라벨·화풍어·한글(이미지 모델이 글자로 그린다).
#   ★ split screen 도 뺀다 — 8c4a0ac A/B 의 "화면분할로 넘어가는 이상한 전환"과 같은 어휘다.
_ICON_WORDS = re.compile(
    r"\b(?:icons?|symbols?|emoji|badges?|pictograms?|arrows?|checkmarks?|glyphs?|"
    r"split[- ]?screens?|picture[- ]in[- ]picture|side[- ]by[- ]side\s+panels?)\b", re.I)
_UNSAFE_NUMBER = re.compile(r"\d{2,}|\d\s*%|\d,\d")
_NON_ASCII_LETTER = re.compile(r"[^\x00-\x7F]")


def _unsafe_for_video(text: str) -> bool:
    from . import photo_contract as pc          # 순환 방지: 호출 시점에 가져온다
    t = str(text or "")
    return bool(pc._FORBIDDEN_SCREEN.search(pc._NEGATED.sub(" ", t))
                or pc._FORBIDDEN_NUMBER_ON_SCREEN.search(t) or pc._TEXT_REQUEST.search(t)
                or pc._QUOTED_LABEL.search(t) or pc._RENDER_STYLE_RE.search(t)
                or pc._ROLE_NAME_LEAK.search(t) or _ICON_WORDS.search(t)
                or _UNSAFE_NUMBER.search(t) or _NON_ASCII_LETTER.search(t))


def entity_name(entity_id: str) -> str:
    """개체 id → 발주 문장의 이름. **한글 id 는 이름을 싣지 않는다**(빈 문자열).

    ★ 스윕 실측: "the 광고 품질 게이지 stands out" 이 Veo 문장에 그대로 나갔다 — 한글이 화면에
      글자로 그려질 수 있고, 한국어판·영어판이 공유하는 영상이다. 종전 prose() 에도 있던 결함이다.
    """
    name = str(entity_id or "").lower().replace("_", " ").strip()
    # ★ 이름 자체가 그래프·아이콘·삽화면("spectral graph", "extrovert human icon") 이름을 싣지 않는다
    #   (같은 스윕). 대명사 "it" 으로 물러나도 시작 프레임이 무엇인지 이미 보여 준다.
    return "" if (_NON_ASCII_LETTER.search(name) or _unsafe_for_video(name)) else name


def _generic_action(entity_id: str, mutation: str) -> str:
    verb = config.MUTATION_PROSE.get(mutation, "")
    if not verb:
        return ""
    name = entity_name(entity_id)
    return f"the {name} {verb}" if name else f"it {verb}"


def clean_action(text: str) -> str:
    """선언된 행동 문장 → 발주 가능한 형태. 뜻풀이 구절을 빼고, 그래도 위험하면 빈 문자열."""
    t = _MEANING_CLAUSE.sub("", str(text or "")).strip().strip(",").strip().rstrip(".")
    return "" if (not t or _unsafe_for_video(t)) else t


def action_prose(beats: list[dict[str, Any]], mutations: list[dict[str, Any]] | None) -> str:
    """비트 → **행동이 앞에 오는** 시간 순 문장(config.VEO_BEAT_ACTION_PROSE).

    ★ 행동 문장은 stage 에 선언된 result_state 를 쓴다 — 지어내지 않는다. 찾는 순서:
      (개체, 연산) 일치 → 같은 개체의 아무 선언(스윕: 129비트가 연산만 달라 일반 동사로 떨어졌다)
      → 종전 일반 동사. 선언 문장이 발주 금지 어휘에 걸리면 일반 동사로 물러난다(clean_action).
    """
    if not beats:
        return ""
    exact: dict[tuple[str, str], str] = {}
    by_entity: dict[str, str] = {}
    for m in (mutations or []):
        if isinstance(m, dict) and m.get("entity_id") and str(m.get("result_state") or "").strip():
            eid, rs = str(m["entity_id"]), str(m["result_state"])
            exact.setdefault((eid, str(m.get("operation") or "").upper()), rs)
            by_entity.setdefault(eid, rs)
    parts: list[str] = []
    used: set[str] = set()
    for b in beats:
        move = config.CAMERA_PROSE.get(b["camera"], b["camera"].lower().replace("_", " "))
        action = ""
        if b["mutation"]:
            declared = exact.get((b["entity_id"], b["mutation"])) or by_entity.get(b["entity_id"], "")
            action = clean_action(declared)
            if action in used:                      # 같은 행동을 두 구간에 싣지 않는다
                action = ""
            action = action or _generic_action(b["entity_id"], b["mutation"])
            used.add(action)
        seg = f"{b['t0']:.1f}-{b['t1']:.1f}s: "
        seg += f"{action[:1].lower() + action[1:]}, while {move}" if action else move
        parts.append(seg)
    return "what happens in the clip: " + "; then ".join(parts)


def strip_camera_clauses(text: str) -> str:
    """motion_prompt 에서 카메라 구절을 빼고 **피사체 행동만** 남긴다(비트가 카메라를 정한다).

    ★ 같은 규칙으로 뜻풀이 구절·발주 금지 구절도 뺀다 — 행동 문장과 다른 기준을 쓰면 그 틈으로 샌다.
    """
    out: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", str(text or "").strip()):
        sentence = _MEANING_CLAUSE.sub("", sentence)
        pieces = re.split(r",\s+|\s+as\s+|\s+while\s+|\s+then\s+", sentence.strip().rstrip(".!?"))
        keep = [re.sub(r"^(?:and|then|as|while)\s+", "", p.strip()) for p in pieces]
        keep = [p for p in keep if p and not _CAMERA_CLAUSE.search(p) and not _unsafe_for_video(p)
                and not re.fullmatch(r"(?i)(?:seamless\s+)?(?:subtle\s+)?loop(?:\s+safe)?", p)]
        if keep:
            out.append(", ".join(keep))
    return ". ".join(out)


def evaluate(cut: dict[str, Any], tier: str) -> list[str]:
    """연출 계약 위반 사유. 빈 목록이면 통과.

    ★ 차단이 아니라 **강등 신호**다(작업명세서 TC-1): invest 인데 계약을 못 지키면
      8초를 줄 근거가 없다 — 재생성 1회 뒤에도 미달이면 standard 로 내린다.
      이것은 **비용 강등이 아니라 품질 계약 미이행**이다. 돈을 아끼려는 것이 아니라,
      채울 내용이 없는 컷에 시간을 주면 정지 화면이 되기 때문이다.
    """
    profile = config.tier_profile(tier)
    if int(profile.get("min_beats") or 0) <= 0:
        return []
    beats = cut.get("temporal_plan") or []
    out: list[str] = []
    if len(beats) < int(profile["min_beats"]):
        out.append(f"temporal_beats_too_few:{len(beats)}<{profile['min_beats']}")
    if profile.get("camera_plan") == "required":
        if not any(b.get("camera") for b in beats):
            out.append("temporal_camera_plan_missing")
        # ★★ **필드가 있는 것과 움직이는 것은 다르다**(2026-09-04). `HOLD` 는 "카메라가
        #   가만히 있다"인데 종전 검사는 그것도 "카메라 계획 있음"으로 통과시켰다.
        #   실측: 오늘 지시서의 invest 컷 둘이 전부 HOLD 였고, 8초를 받고도 정지 화면이었다.
        #   달 클립(G2)의 좋았던 팔은 DOLLY_OUT→TRACK→DOLLY_IN 으로 셋 다 움직였고,
        #   Apify 벤치마크도 "횡이동 + 마지막 급속 푸시인"을 제작 공식으로 공개했다.
        elif not any(str(b.get("camera") or "").upper() in config.MOVING_CAMERAS
                     for b in beats):
            out.append("temporal_camera_never_moves")
        # ★ 같은 카메라만 반복하면 8초 내내 한 동작이다 — 벤치마크의 "멀티샷"과 반대다.
        elif len({str(b.get("camera") or "").upper() for b in beats if b.get("camera")}) < 2 \
                and len(beats) >= 2:
            out.append("temporal_camera_monotone")
    if profile.get("state_change") == "required":
        if not any(b.get("mutation") for b in beats):
            # ★ 카메라만 움직이면 "같은 것을 다른 각도에서" 보는 것이지 기전이 아니다.
            out.append("temporal_state_change_missing")
        # ★★ APPEAR·HIGHLIGHT 만으로는 기전이 아니다 — "나타났다"는 정지 화면으로도 성립한다.
        #   최소 하나는 실제로 변형돼야 한다(config.TRANSFORMING_MUTATIONS 주석의 근거 둘).
        elif not any(str(b.get("mutation") or "").upper() in config.TRANSFORMING_MUTATIONS
                     for b in beats):
            out.append("temporal_no_transforming_mutation")
    return out


def beats_from_stage(cut: dict[str, Any], stage: dict[str, Any],
                     clip_sec: int | None = None) -> list[dict[str, Any]]:
    """stage 선언(mutations)에서 **비트를 만들어 준다**. 모델이 1개만 쓸 때 코드가 채운다.

    ★ 왜 코드가 하나(2026-09-12 실측): 최근 실사형 지시서 10편 · 컷 124개에서 invest 는 1개뿐이고
      81개(65%)가 **비트 부족 하나로만** 탈락했다. 프롬프트에 "2~3개를 채워라"가 이미 있고
      재생성 되먹임까지 도는데도 그렇다 — 어느 컷이 invest 가 될지는 코드가 나중에 정하므로
      모델은 그걸 모른 채 기본값 1개를 쓴다(닭과 달걀). 이 저장소의 자세 그대로 코드가 고친다
      (`photo_video_camera_repaired`·`photo_visual_role_backfilled`).
    ★ 지어내지 않는다. 무엇이 변하는지는 **stage.mutations 에 이미 선언된 것**만 쓴다.
      선언이 없으면 빈 목록을 돌려준다 — 그 컷은 그대로 강등된다(그건 어휘가 아니라 내용 문제다).
    ★ 카메라는 벤치마크 공식을 따른다: 횡이동·오비트 → **마지막 비트에 급속 푸시인**.
      그래야 evaluate 의 "움직이는 카메라 2종" 계약도 함께 선다.
    """
    profile = config.tier_profile("invest")
    clip = int(clip_sec or profile.get("clip_sec") or 8)
    want = int(profile.get("min_beats") or 2)
    cap = int(profile.get("max_beats") or 3)

    ops: list[tuple[str, str]] = []
    for m in (stage.get("mutations") or []):
        if not isinstance(m, dict):
            continue
        op = str(m.get("operation") or "").strip().upper()
        if op in config.MUTATION_OPERATIONS:
            ops.append((op, str(m.get("entity_id") or "").strip()))
    if not ops:
        return []
    # 변형 변이를 **뒤로** 보낸다 — 마지막 푸시인과 겹쳐야 기전이 보인다.
    ops.sort(key=lambda t: t[0] in config.TRANSFORMING_MUTATIONS)
    n = min(max(want, len(ops)), cap)
    ops = ops[-n:]
    while len(ops) < n:              # 변이가 비트 수보다 적으면 앞 비트는 카메라만 움직인다
        ops.insert(0, ("", ""))

    step = float(clip) / n
    raw: list[dict[str, Any]] = []
    for i, (op, ent) in enumerate(ops):
        camera = "DOLLY_IN" if i == n - 1 else ("TRACK", "ORBIT")[i % 2]
        raw.append({"t0": round(i * step, 2), "t1": round((i + 1) * step, 2),
                    "entity_id": ent, "mutation": op, "camera": camera})
    return normalize(raw, clip)


def coverage(beats: list[dict[str, Any]], clip_sec: int) -> float:
    """비트가 클립 길이의 몇 %를 덮는가. 낮으면 정지 구간이 길다는 뜻이다.

    ★ Phase G3 의 Static Hold Ratio 와 같은 축이지만 이쪽은 **계획 단계** 지표다 —
      렌더 전에 "이 8초는 절반이 비어 있다"를 볼 수 있다.
    """
    if not beats or clip_sec <= 0:
        return 0.0
    covered = sum(b["t1"] - b["t0"] for b in beats)
    return round(min(1.0, covered / float(clip_sec)), 3)


def shortfall_feedback(cut_nos: list[int], cuts: list[dict[str, Any]] | None = None) -> str:
    """TC-1 되먹임 — **어느 컷에** 비트가 필요한지 찍어서 알려준다.

    ★ "2~3개 비트로 채워라"는 지시는 이미 프롬프트에 있다. 그런데도 모델이 1개만 쓰는 이유는
      **어떤 컷이 invest 인지 모르기 때문**이다 — 그 판정은 시퀀스·라우터를 보고 코드가
      나중에 한다. 1차 생성이 구조를 드러낸 지금은 컷 번호를 찍어 줄 수 있다.
      되먹임은 "다시 해라"가 아니라 **무엇이 왜 부족하고 어떻게 고치는지**다(저장소 규율).
    """
    if not cut_nos:
        return ""
    by_no = {c.get("cut_no"): c for c in (cuts or [])}
    lines = []
    for n in cut_nos:
        cut = by_no.get(n) or {}
        missing = evaluate(cut, "invest")
        have = len(cut.get("temporal_plan") or [])
        lines.append(f"  · 컷 {n}: 지금 비트 {have}개 — {', '.join(missing) or '계약 미달'}")
    return (
        "\n\n[연출 계약 미이행 — 이 컷들은 8초를 받을 자격이 있는데 계획이 없어서 놓친다]\n"
        + "\n".join(lines)
        + "\n★ 위 컷들은 기전 시퀀스에 속하고 진행도 하고 주장도 붙어 있다. **딱 하나,"
        " temporal_plan 이 모자라서** 8초 대신 4초를 받는다 — 그러면 그 컷의 설명력이 준다.\n"
        "★ 각 컷의 temporal_plan 을 **비트 2~3개**로 채워라. 비트마다 반드시:\n"
        "   t0·t1(겹치지 않게 앞에서 뒤로) · entity_id(무엇이) · mutation(어떻게 변하나)"
        " · camera(카메라 토큰)\n"
        "★ mutation 이 빈 비트는 '같은 것을 다른 각도에서' 보는 것이라 기전이 아니다 —"
        " 반드시 무엇이 변하는지 적어라.\n"
        "★★ APPEAR·HIGHLIGHT 만으로는 계약을 못 채운다 — '나타났다'·'빛난다'는 정지 화면으로도"
        " 성립하기 때문이다. 비트 중 **최소 하나**는 실제로 변형돼야 한다. 쓸 수 있는 변형: "
        + " · ".join(config.TRANSFORMING_MUTATIONS) + "\n"
        "★ 나머지 컷은 그대로 둬라. 이 되먹임은 위 컷 번호에 대한 것이다."
    )
