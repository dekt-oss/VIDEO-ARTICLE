"""Phase 4 shadow prerequisite knowledge resolver.

The resolver is deliberately pure after loading the checked-in glossary. It
does not call a model, database, or network and it never mutates Explanation IR
or Evidence Pack inputs.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from . import explanation_ir


CONTRACT_VERSION = "prerequisite-resolution-v1"
GLOSSARY_CONTRACT_VERSION = "explanation-glossary-v1"
STATUSES = frozenset({"RESOLVED_SOURCE", "RESOLVED_GLOSSARY", "UNRESOLVED"})


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _default_glossary_path() -> Path:
    return Path(__file__).with_name("explanation_glossary.json")


def load_glossary(path: str | Path | None = None) -> list[dict[str, Any]]:
    payload = json.loads((Path(path) if path else _default_glossary_path()).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("contract_version") != GLOSSARY_CONTRACT_VERSION:
        raise ValueError("glossary_invalid:contract_version_invalid")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("glossary_invalid:entries_not_list")
    errors = validate_glossary(entries)
    if errors:
        raise ValueError("glossary_invalid:" + ",".join(errors))
    return deepcopy(entries)


def validate_glossary(entries: Any) -> list[str]:
    if not isinstance(entries, list):
        return ["entries_not_list"]
    errors: list[str] = []
    seen: set[str] = set()
    for position, entry in enumerate(entries, 1):
        prefix = f"entry:{position}"
        if not isinstance(entry, dict):
            errors.append(f"{prefix}:not_dict")
            continue
        concept_id = _text(entry.get("concept_id"))
        if not concept_id:
            errors.append(f"{prefix}:concept_id_missing")
        elif concept_id in seen:
            errors.append(f"{prefix}:concept_id_duplicate:{concept_id}")
        seen.add(concept_id)
        domains = _strings(entry.get("domains"))
        if not domains or any(domain not in ("paper", "report") for domain in domains):
            errors.append(f"{prefix}:domains_invalid")
        if not _text(entry.get("label")):
            errors.append(f"{prefix}:label_missing")
        if not _text(entry.get("simple_explanation")):
            errors.append(f"{prefix}:simple_explanation_missing")
        source = entry.get("source")
        if not isinstance(source, dict):
            errors.append(f"{prefix}:source_missing")
            continue
        for field in ("publisher", "title", "url", "checked_at"):
            if not _text(source.get(field)):
                errors.append(f"{prefix}:source_{field}_missing")
        if _text(source.get("url")) and not _text(source.get("url")).startswith("https://"):
            errors.append(f"{prefix}:source_url_invalid")
    return sorted(set(errors))


def _glossary_entries(glossary: Any) -> list[dict[str, Any]]:
    if glossary is None:
        return load_glossary()
    if isinstance(glossary, dict):
        if glossary.get("contract_version") != GLOSSARY_CONTRACT_VERSION:
            raise ValueError("glossary_invalid:contract_version_invalid")
        glossary = glossary.get("entries")
    errors = validate_glossary(glossary)
    if errors:
        raise ValueError("glossary_invalid:" + ",".join(errors))
    return deepcopy(glossary)


def _source_resolution(
    request: dict[str, Any], evidence_index: dict[str, dict[str, Any]], warnings: list[str]
) -> tuple[str, list[str], list[str]] | None:
    concept_id = _text(request.get("concept_id"))
    for evidence_id in _strings(request.get("evidence_ids")):
        item = evidence_index.get(evidence_id)
        if item is None:
            warnings.append(f"source_evidence_unknown:{concept_id}:{evidence_id}")
            continue
        if _text(item.get("verification_state")) != "SUPPORTED":
            warnings.append(
                f"source_evidence_not_supported:{concept_id}:{evidence_id}:"
                f"{_text(item.get('verification_state')) or 'UNKNOWN'}"
            )
            continue
        scope = item.get("verification_scope")
        if not isinstance(scope, dict) or scope.get("semantic_entailment") is not True:
            warnings.append(f"source_semantic_entailment_unverified:{concept_id}:{evidence_id}")
            continue
        explanation = _text(item.get("text")) or _text(item.get("display"))
        if not explanation:
            warnings.append(f"source_explanation_missing:{concept_id}:{evidence_id}")
            continue
        return explanation, [evidence_id], [f"evidence:{evidence_id}"]
    return None


def resolve(
    ir: dict[str, Any],
    pack: dict[str, Any],
    requested_concepts: list[dict[str, Any]],
    *,
    glossary: Any = None,
) -> dict[str, Any]:
    """Resolve explicitly requested concepts without inventing missing knowledge."""
    ir_errors = explanation_ir.validate(ir, pack)
    if ir_errors:
        raise ValueError("explanation_ir_invalid:" + ",".join(ir_errors))
    if not isinstance(requested_concepts, list):
        raise ValueError("requested_concepts_not_list")

    glossary_entries = _glossary_entries(glossary)
    glossary_index = {_text(entry.get("concept_id")): entry for entry in glossary_entries}
    evidence_index = explanation_ir.build_index(pack)
    warnings: list[str] = []
    concepts: list[dict[str, Any]] = []
    required_unresolved: list[str] = []

    for position, raw in enumerate(requested_concepts, 1):
        request = raw if isinstance(raw, dict) else {}
        concept_id = _text(request.get("concept_id"))
        if not concept_id:
            warnings.append(f"requested_concept_invalid:{position}")
            continue
        required = request.get("required") is not False
        base = {
            "concept_id": concept_id,
            "label": "",
            "reason": _text(request.get("reason")),
            "required": required,
            "simple_explanation": "",
            "status": "UNRESOLVED",
            "evidence_ids": [],
            "knowledge_refs": [],
            "guardrails": [],
            "source": {},
        }

        source_match = _source_resolution(request, evidence_index, warnings)
        if source_match is not None:
            explanation, evidence_ids, knowledge_refs = source_match
            base.update(
                label=_text(request.get("label")) or concept_id,
                simple_explanation=explanation,
                status="RESOLVED_SOURCE",
                evidence_ids=evidence_ids,
                knowledge_refs=knowledge_refs,
            )
        else:
            entry = glossary_index.get(concept_id)
            if entry is None:
                warnings.append(f"glossary_concept_unknown:{concept_id}")
            elif ir.get("domain") not in _strings(entry.get("domains")):
                warnings.append(f"glossary_domain_mismatch:{concept_id}:{ir.get('domain')}")
            else:
                base.update(
                    label=_text(entry.get("label")),
                    simple_explanation=_text(entry.get("simple_explanation")),
                    status="RESOLVED_GLOSSARY",
                    knowledge_refs=[f"glossary:{concept_id}"],
                    guardrails=_strings(entry.get("guardrails")),
                    source=deepcopy(entry.get("source") or {}),
                )

        if base["status"] == "UNRESOLVED" and required:
            required_unresolved.append(concept_id)
        concepts.append(base)

    result = {
        "contract_version": CONTRACT_VERSION,
        "domain": ir.get("domain"),
        "content_id": ir.get("content_id"),
        "concepts": concepts,
        "unresolved_concepts": [
            concept["concept_id"] for concept in concepts if concept["status"] == "UNRESOLVED"
        ],
        "scope_action": "NARROW_SCOPE" if required_unresolved else "KEEP",
        "warnings": sorted(set(warnings)),
    }
    errors = validate(result, ir, pack)
    if errors:
        raise ValueError("prerequisite_resolution_invalid:" + ",".join(errors))
    return result


def validate(result: dict[str, Any], ir: dict[str, Any], pack: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(result, dict):
        return ["resolution_not_dict"]
    if result.get("contract_version") != CONTRACT_VERSION:
        errors.append("contract_version_invalid")
    if result.get("domain") != ir.get("domain") or result.get("domain") != pack.get("domain"):
        errors.append("domain_mismatch")
    if result.get("content_id") != ir.get("content_id"):
        errors.append("content_id_mismatch")
    concepts = result.get("concepts")
    if not isinstance(concepts, list):
        return sorted(set(errors + ["concepts_not_list"]))
    evidence_index = explanation_ir.build_index(pack)
    expected_unresolved: list[str] = []
    required_unresolved = False
    for position, concept in enumerate(concepts, 1):
        if not isinstance(concept, dict):
            errors.append(f"concept_invalid:{position}")
            continue
        concept_id = _text(concept.get("concept_id"))
        status = concept.get("status")
        if not concept_id:
            errors.append(f"concept_id_missing:{position}")
        if status not in STATUSES:
            errors.append(f"concept_status_invalid:{concept_id or position}")
        evidence_ids = _strings(concept.get("evidence_ids"))
        knowledge_refs = _strings(concept.get("knowledge_refs"))
        if status == "RESOLVED_SOURCE":
            if not evidence_ids or knowledge_refs != [f"evidence:{eid}" for eid in evidence_ids]:
                errors.append(f"source_trace_invalid:{concept_id}")
            for evidence_id in evidence_ids:
                item = evidence_index.get(evidence_id)
                scope = item.get("verification_scope") if isinstance(item, dict) else None
                if (
                    item is None
                    or item.get("verification_state") != "SUPPORTED"
                    or not isinstance(scope, dict)
                    or scope.get("semantic_entailment") is not True
                ):
                    errors.append(f"source_evidence_invalid:{concept_id}:{evidence_id}")
        elif status == "RESOLVED_GLOSSARY":
            if evidence_ids or knowledge_refs != [f"glossary:{concept_id}"]:
                errors.append(f"glossary_trace_invalid:{concept_id}")
            source = concept.get("source")
            if not isinstance(source, dict) or not all(
                _text(source.get(field)) for field in ("publisher", "title", "url", "checked_at")
            ):
                errors.append(f"glossary_source_invalid:{concept_id}")
        else:
            expected_unresolved.append(concept_id)
            required_unresolved = required_unresolved or concept.get("required") is not False
            if evidence_ids or knowledge_refs or _text(concept.get("simple_explanation")):
                errors.append(f"unresolved_payload_invalid:{concept_id}")
    if result.get("unresolved_concepts") != expected_unresolved:
        errors.append("unresolved_concepts_invalid")
    expected_action = "NARROW_SCOPE" if required_unresolved else "KEEP"
    if result.get("scope_action") != expected_action:
        errors.append("scope_action_invalid")
    return sorted(set(errors))
