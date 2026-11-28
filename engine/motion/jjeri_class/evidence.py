"""Bind each beat and screen field to claims from the approved review."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
import unicodedata

from engine import config, drinks_script_check as script_check
from .claims import has_health_claim, sensitive_text_block
from .schema import SLOTS, TEXT, price_issue, validate_episode

SERIES = "째리의 술 수업"
MUSIC_CREDIT = '음악: "Upbeat Corporate" — Soundrider/Dope (CC BY)'
VOICE_CREDIT = "내레이션: AI 음성(Microsoft Edge TTS)"
NEUTRAL_TEXT = {
    "한눈에 보기", "집 규칙", "당신은 어느 쪽?", "저는 ○○파예요", "댓글로 알려 주세요!",
    "술째리고에서 검색", "라벨에서 캐스크 이름을 먼저 찾아보세요.", "궁금하면 술째리고에서 바로 검색해 보세요.",
    "라벨에서 통 이름을 찾아보세요.",
}
_NEUTRAL_INTERACTION = re.compile(
    r"(?:(?:같이|함께|직접|지금)\s+)?"
    r"(?:비교|검색|(?:라벨을\s+)?확인|(?:댓글로\s+)?투표)해\s*(?:봐요|보세요|보자|주세요)[.!?…]*"
)
_REWRITE = {
    "price_ambiguous": (
        "금액과 지시어가 겹쳐 판단할 수 없습니다. 금액은 빼고, 가리키는 물건은 '이 원형'이나 '이 불꽃'처럼 적어 주세요."
    ),
    "number_ambiguous": (
        "지시어와 수량이 겹쳐 단위를 판단할 수 없습니다. 수치라면 '2년'이나 '2배'처럼, "
        "지시어라면 '올해'나 '이 선박'처럼 적어 주세요."
    ),
}


@dataclass
class EvidenceError(ValueError):
    code: str
    field: str

    @property
    def rewrite_instruction(self):
        return _REWRITE.get(self.code)

    def __str__(self):
        detail = self.rewrite_instruction
        return f"{self.code}: {self.field}" + (f" — {detail}" if detail else "")


def approved_records(evidence):
    if not isinstance(evidence, dict) or evidence.get("approved") is not True:
        raise EvidenceError("evidence_not_approved", "review")
    selected = evidence.get("selected_claim_ids")
    if not isinstance(selected, list) or not selected or any(not isinstance(cid, str) for cid in selected):
        raise EvidenceError("evidence_not_approved", "selected_claim_ids")
    claims, sources = evidence.get("claims"), evidence.get("sources")
    if (not isinstance(claims, list) or not isinstance(sources, list)
            or any(not isinstance(row, dict) for row in [*claims, *sources])):
        raise EvidenceError("evidence_invalid", "review")
    by_id = {c["claim_id"]: c for c in claims if isinstance(c.get("claim_id"), str)}
    available = {s["snapshot_id"]: s for s in sources if isinstance(s.get("snapshot_id"), str)}
    if len(by_id) != len(claims) or len(available) != len(sources) or set(selected) - by_id.keys():
        raise EvidenceError("evidence_invalid", "review")
    approved = {identifier: by_id[identifier] for identifier in selected}
    return approved, available


def _source_refs(claim, sources, field):
    if script_check._is_derived(claim):
        raise EvidenceError("derived_claim_cited", field)
    if claim.get("support_review") != "supported":
        raise EvidenceError("claim_unapproved", field)
    refs = claim.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise EvidenceError("source_unverified", field)
    result = {}
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("snapshot_id"), str):
            raise EvidenceError("source_unverified", field)
        source_id = ref["snapshot_id"]
        original = ref.get("original_quote")
        source = sources.get(source_id)
        if (ref.get("quote_check") != "matched" or not isinstance(original, str) or not original.strip()
                or original.lstrip().startswith(("(계산", "(추론", "(원문 아님"))
                or not source or not str(source.get("url") or "").startswith(("https://", "http://"))):
            raise EvidenceError("source_unverified", field)
        label = source.get("publisher") or source.get("title")
        if (not isinstance(label, str) or not label.strip() or len(label) > config.JJERI_CHIP_MAX_CHARS
                or re.search(r"[\r\n<>]", label) or has_health_claim(label)):
            raise EvidenceError("source_label_invalid", field)
        if issue := price_issue(label):
            raise EvidenceError("price_ambiguous" if issue == "price_ambiguous" else "source_label_invalid", field)
        result.setdefault(source_id, (label.strip(), []))[1].append(original)
    return result


def _text_slots(spec, value, prefix):
    if spec == TEXT:
        yield prefix, value
    elif isinstance(spec, dict):
        for key, child in spec.items():
            key = key.rstrip("?")
            if key in value:
                yield from _text_slots(child, value[key], f"{prefix}.{key}")
    elif isinstance(spec, tuple):
        for i, child in enumerate(value):
            yield from _text_slots(spec[2], child, f"{prefix}.{i}")
    elif spec == "recap_item":
        yield f"{prefix}.1", value[1]


def _neutral(field, text):
    normalized = " ".join(text.split())
    if field == "series":
        return normalized == SERIES
    if field == "episode":
        return re.fullmatch(r"[1-9]\d{0,2}교시", normalized) is not None
    return normalized in NEUTRAL_TEXT or _NEUTRAL_INTERACTION.fullmatch(normalized) is not None


def text_fields(episode):
    for key in ("series", "episode", "topic"):
        yield key, episode[key], None
    for i, chapter in enumerate(episode["chapters"]):
        yield f"chapters.{i}.title", chapter["title"], chapter["from_scene"]
    for i, scene in enumerate(episode["scenes"]):
        prefix = f"scenes.{i}"
        if scene.get("tag"):
            yield f"{prefix}.tag.text", scene["tag"]["text"], scene["id"]
        for key, text in _text_slots(SLOTS[scene["template"]], scene["slots"], f"{prefix}.slots"):
            yield key, text, scene["id"]
    for i, line in enumerate(episode["caption_draft"].splitlines()):
        if line.strip():
            yield f"caption_draft.{i}", line, None


def _verify_text(field, text, ids, claims, sources):
    if not isinstance(ids, list) or any(not isinstance(cid, str) or not cid for cid in ids):
        raise EvidenceError("claim_refs_invalid", field)
    neutral = _neutral(field, text)
    if neutral and not ids:
        return {}
    # Numbers on a legitimate series identifier are part of the fixed title protocol.
    if not ids:
        raise EvidenceError("fact_scene_no_claim", field)
    references = {}
    checked_claims = []
    for identifier in dict.fromkeys(ids):
        if identifier not in claims:
            raise EvidenceError("claim_unknown", field)
        claim = claims[identifier]
        resolved = _source_refs(claim, sources, field)
        references.update(resolved)
        # Numeric checks may draw only on quotes from verified refs.
        checked_claims.append({
            "claim_id": identifier, "kind": script_check._kind(claim),
            "source_refs": [{"original_quote": quote} for _, quotes in resolved.values() for quote in quotes],
        })
    if neutral:
        return {identifier: label for identifier, (label, _) in references.items()}
    if code := sensitive_text_block(text, checked_claims):
        raise EvidenceError(code, field)
    report = script_check.check({
        "scenes": [{"narration": " ".join(text.split()), "claim_ids": ids, "visual_role": "text_card"}],
        "claims": checked_claims,
    })
    if not report.ok:
        raise EvidenceError(report.blocks[0].code, field)
    return {identifier: label for identifier, (label, _) in references.items()}


def _chip_em(text):
    # Source chips have an 880px text area at 28px, including mixed-width labels.
    width = 0.0
    for ch in text:
        if unicodedata.east_asian_width(ch) in {"F", "W", "A"} or ch in "WwMm":
            width += 1.0
        elif ch.isspace() or ch in ".,()[]":
            width += 0.4
        elif ch.isupper():
            width += 0.8
        else:
            width += 0.65
    return width


def audit_episode(episode, evidence, *, music_credit=MUSIC_CREDIT):
    errors = validate_episode(episode)
    if errors:
        raise EvidenceError(errors[0], "episode")
    claims, sources = approved_records(evidence)
    refs = episode.get("text_claim_ids")
    if not isinstance(refs, dict):
        raise EvidenceError("claim_refs_invalid", "text_claim_ids")
    if any(scene.get("source_chip") is not None for scene in episode["scenes"]):
        raise EvidenceError("source_chip_supplied", "scenes")
    fields = list(text_fields(episode))
    if refs.keys() - {field for field, _, _ in fields}:
        raise EvidenceError("claim_refs_invalid", "text_claim_ids")
    checked = deepcopy(episode)
    scene_sources = {scene["id"]: {} for scene in checked["scenes"]}
    checked_fields = {}
    for i, scene in enumerate(checked["scenes"]):
        for j, beat in enumerate(scene["beats"]):
            field = f"scenes.{i}.beats.{j}.text"
            attached = _verify_text(field, beat["text"], beat["claim_ids"], claims, sources)
            checked_fields[field] = sorted(attached)
            scene_sources[scene["id"]].update(attached)
    for field, text, scene_id in fields:
        if field.startswith("caption_draft.") and re.match(r"\s*(출처|음악|내레이션|sources?)\s*[:：]", text, re.I):
            raise EvidenceError("caption_credit_supplied", field)
        attached = _verify_text(field, text, refs.get(field, []), claims, sources)
        checked_fields[field] = sorted(attached)
        if scene_id is not None:
            scene_sources[scene_id].update(attached)
    for scene in checked["scenes"]:
        attached = scene_sources[scene["id"]]
        labels = sorted(set(attached.values()), key=lambda label: (label.casefold(), label))
        # Duplicate labels for separate snapshots would obscure the actual citation.
        if len(labels) != len(attached):
            raise EvidenceError("source_chip_ambiguous", scene["id"])
        chip = " · ".join(labels)
        if len(chip) > config.JJERI_CHIP_MAX_CHARS or _chip_em(chip) > config.JJERI_CHIP_TEXT_BUDGET_EM:
            raise EvidenceError("source_chip_overflow", scene["id"])
        scene["source_chip"] = chip or None
    checked["caption_draft"] = f'{checked["caption_draft"].rstrip()}\n\n{music_credit}\n{VOICE_CREDIT}'
    return checked, {"source_ids_by_scene": {key: sorted(ids) for key, ids in scene_sources.items()},
                     "source_ids_by_field": checked_fields, "human_source_review_required": True}
