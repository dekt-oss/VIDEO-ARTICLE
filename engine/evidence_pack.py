"""Explanation Engine v2 Phase 2 — common Evidence Pack adapters.

The project already has two mature evidence stores:
- paper: Fact Sheet Claim Ledger (claims)
- report: qualitative report facts + validated number_facts

This module does NOT create a third persistent source of truth.  It projects the
existing structures into one read-only contract for the future Explanation Core.
Every projected item keeps a raw_ref back to the original Fact Sheet field.

No DB/network/LLM calls.  No input mutation.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import paper_evidence, source_adequacy


CONTRACT_VERSION = "evidence-pack-v1"

VERIFICATION_STATES = frozenset({
    "SUPPORTED",
    "UNSUPPORTED",
    "UNVERIFIABLE_AT_CURRENT_DEPTH",
    "NOT_CHECKED",
    "STALE",
})


def _list_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if str(x).strip()]


def _source_block(fact_sheet: dict[str, Any], domain: str) -> dict[str, Any]:
    policy = source_adequacy.from_fact_sheet(fact_sheet, domain)
    source = fact_sheet.get("source") if isinstance(fact_sheet.get("source"), dict) else {}
    if domain == "paper":
        prov = fact_sheet.get("source_provenance")
        prov = prov if isinstance(prov, dict) else {}
        depth = str((policy or {}).get("source_depth") or prov.get("source_depth") or "none")
        chars = int((policy or {}).get("source_chars") or prov.get("char_count") or 0)
        provider = str(prov.get("provider") or "")
        attribution = {
            "title": str(source.get("title") or ""),
            "venue": str(source.get("venue") or ""),
            "authors": list(source.get("authors") or []) if isinstance(source.get("authors"), list) else [],
            "institutions": (
                list(source.get("institutions") or [])
                if isinstance(source.get("institutions"), list) else []
            ),
            "url": str(source.get("url") or ""),
        }
    else:
        depth = str((policy or {}).get("source_depth") or fact_sheet.get("source_depth") or "none")
        chars = int((policy or {}).get("source_chars") or fact_sheet.get("source_chars") or 0)
        provider = ""
        attribution = {
            "broker": str(source.get("broker") or ""),
            "analyst": str(source.get("analyst") or ""),
            "company": str(source.get("company") or fact_sheet.get("company") or ""),
            "url": str(source.get("url") or ""),
        }
    return {
        "source_depth": depth,
        "source_chars": chars,
        "source_mode": str((policy or {}).get("source_mode") or ""),
        "provider": provider,
        "attribution": attribution,
    }


def _paper_verification(claim: dict[str, Any]) -> str:
    validation = claim.get("validation")
    if not isinstance(validation, dict):
        return "NOT_CHECKED"
    if not paper_evidence.is_current(validation):
        return "STALE"
    state = str(validation.get("evidence_state") or "")
    if state in VERIFICATION_STATES:
        return state
    verified = validation.get("quote_verified")
    if verified is True:
        return "SUPPORTED"
    if verified is False:
        return "UNSUPPORTED"
    return "UNVERIFIABLE_AT_CURRENT_DEPTH"


def _verification_scope(*, quote: bool = False, value: bool = False,
                        unit: bool = False, period: bool = False,
                        semantic_entailment: bool = False) -> dict[str, bool]:
    """Expose exactly what a verification state proves.

    IMPORTANT: paper_evidence verifies that a quoted span exists in the source;
    it does not prove that the generated Korean claim is semantically entailed
    by that span.  Phase 3 must not read SUPPORTED as a blanket truth label.
    """
    return {
        "quote_presence": quote,
        "numeric_value": value,
        "unit": unit,
        "period": period,
        "semantic_entailment": semantic_entailment,
    }


def _paper_claims(fact_sheet: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(fact_sheet.get("claims") or [], 1):
        if not isinstance(raw, dict):
            continue
        cid = str(raw.get("claim_id") or f"C{index:02d}")
        validation = raw.get("validation") if isinstance(raw.get("validation"), dict) else {}
        quote = str(raw.get("source_quote") or "").strip()
        source_refs: list[dict[str, Any]] = []
        if quote:
            source_refs.append({
                "quote": quote,
                "chunk_id": str(validation.get("chunk_id") or ""),
                "source_section": str(raw.get("source_section") or ""),
                "source_page": raw.get("source_page"),
                "table_or_figure": raw.get("table_or_figure"),
            })
        out.append({
            "evidence_id": f"paper:{cid}",
            "raw_ref": f"claims:{cid}",
            "text": str(raw.get("claim_ko") or ""),
            "claim_type": str(raw.get("claim_kind") or ""),
            "domain_role": "claim",
            "causal_strength": str(raw.get("causal_strength") or ""),
            "evidence_grade": str(raw.get("evidence_grade") or ""),
            "verification_state": _paper_verification(raw),
            # paper_evidence only checks that source_quote exists in the source. It does NOT
            # establish semantic entailment between claim_ko and that quote.
            "verification_scope": _verification_scope(
                quote=(validation.get("quote_verified") is True),
                semantic_entailment=False,
            ),
            "source_refs": source_refs,
            "uncertainty": raw.get("uncertainty"),
            "limitations": _list_text(raw.get("limitations")),
            "attribution": "",
            "domain_fields": {
                key: deepcopy(raw.get(key))
                for key in (
                    "population", "sample_size", "geography", "study_period", "study_design",
                    "treatment_or_exposure", "comparison", "outcome", "outcome_definition",
                    "effect_direction", "effect_size", "effect_unit", "statistical_significance",
                )
                if raw.get(key) not in (None, "", [])
            },
        })
    return out


def _report_text_claims(fact_sheet: dict[str, Any]) -> list[dict[str, Any]]:
    """Project qualitative report statements without pretending they were individually verified.

    what/basis/opinion are valuable reasoning inputs but do not have per-item source refs in
    the current report Fact Sheet.  Marking them SUPPORTED would manufacture confidence.
    """
    source = fact_sheet.get("source") if isinstance(fact_sheet.get("source"), dict) else {}
    broker = str(source.get("broker") or "")
    out: list[dict[str, Any]] = []
    specs = (
        ("what", "reported_claim"),
        ("basis", "reported_reason"),
    )
    for field, claim_type in specs:
        for index, text in enumerate(_list_text(fact_sheet.get(field)), 1):
            out.append({
                "evidence_id": f"report:{field}:{index:02d}",
                "raw_ref": f"{field}[{index - 1}]",
                "text": text,
                "claim_type": claim_type,
                "domain_role": field,
                "causal_strength": "",
                "evidence_grade": "",
                "verification_state": "NOT_CHECKED",
                "verification_scope": _verification_scope(),
                "source_refs": [],
                "uncertainty": None,
                "limitations": [],
                "attribution": broker,
                "domain_fields": {},
            })
    opinion = str(fact_sheet.get("opinion") or "").strip()
    if opinion:
        out.append({
            "evidence_id": "report:opinion:01",
            "raw_ref": "opinion",
            "text": opinion,
            "claim_type": "broker_opinion",
            "domain_role": "opinion",
            "causal_strength": "",
            "evidence_grade": "",
            "verification_state": "NOT_CHECKED",
            "verification_scope": _verification_scope(),
            "source_refs": [],
            "uncertainty": None,
            "limitations": [],
            "attribution": broker,
            "domain_fields": {},
        })
    return out


def _report_number_state(fact: dict[str, Any]) -> str:
    validation = fact.get("validation")
    if not isinstance(validation, dict):
        return "NOT_CHECKED"
    quote = validation.get("quote_supports_claim")
    number = validation.get("number_match")
    if quote is False or number is False:
        return "UNSUPPORTED"
    if quote is True and (number is True or fact.get("value") is None):
        return "SUPPORTED"
    if quote is None and number is None:
        return "UNVERIFIABLE_AT_CURRENT_DEPTH"
    return "NOT_CHECKED"


def _report_numbers(fact_sheet: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(fact_sheet.get("number_facts") or [], 1):
        if not isinstance(raw, dict):
            continue
        fid = str(raw.get("fact_id") or f"num_{index}")
        refs = []
        for ref in raw.get("source_refs") or []:
            if isinstance(ref, dict) and str(ref.get("quote") or "").strip():
                refs.append({
                    "quote": str(ref.get("quote") or ""),
                    "chunk_id": str(ref.get("chunk_id") or ""),
                    "source_page": raw.get("source_page"),
                })
        validation = raw.get("validation") if isinstance(raw.get("validation"), dict) else {}
        out.append({
            "evidence_id": f"report:{fid}",
            "raw_ref": f"number_facts:{fid}",
            "value": raw.get("value"),
            "unit": str(raw.get("unit_norm") or raw.get("unit") or ""),
            "period": str(raw.get("period") or ""),
            "metric": str(raw.get("metric") or ""),
            "scope": str(raw.get("scope") or ""),
            "basis": str(raw.get("basis") or ""),
            "attribution": str(raw.get("attribution") or ""),
            "display": str(raw.get("display") or ""),
            "comparator": deepcopy(raw.get("comparator") or {}),
            "interpretation": str(raw.get("interpretation") or ""),
            "verification_state": _report_number_state(raw),
            "verification_scope": _verification_scope(
                quote=(validation.get("quote_supports_claim") is True),
                value=(validation.get("number_match") is True),
                unit=(validation.get("unit_match") is True),
                period=(validation.get("period_match") is True),
                semantic_entailment=False,
            ),
            "validation": {
                "number_match": validation.get("number_match"),
                "unit_match": validation.get("unit_match"),
                "period_match": validation.get("period_match"),
                "quote_supports_claim": validation.get("quote_supports_claim"),
            },
            "source_refs": refs,
        })
    return out


def _paper_numbers(fact_sheet: dict[str, Any]) -> list[dict[str, Any]]:
    """Paper legacy number strings are kept as text; do not invent numeric parsing."""
    return [
        {
            "evidence_id": f"paper:number:{index:02d}",
            "raw_ref": f"numbers[{index - 1}]",
            "value": None,
            "unit": "",
            "period": "",
            "metric": "",
            "scope": "",
            "basis": "",
            "attribution": "",
            "display": text,
            "comparator": {},
            "interpretation": "",
            "verification_state": "NOT_CHECKED",
            "verification_scope": _verification_scope(),
            "validation": {},
            "source_refs": [],
        }
        for index, text in enumerate(_list_text(fact_sheet.get("numbers")), 1)
    ]


def build(fact_sheet: dict[str, Any] | None, domain: str,
          *, content_id: str = "") -> dict[str, Any]:
    """Project an existing Fact Sheet into the common read-only Evidence Pack."""
    fs = fact_sheet if isinstance(fact_sheet, dict) else {}
    if domain not in ("paper", "report"):
        raise ValueError(f"unknown evidence-pack domain: {domain}")

    if domain == "paper":
        claims = _paper_claims(fs)
        numbers = _paper_numbers(fs)
        risks: list[dict[str, Any]] = []
        limitations = [
            {
                "evidence_id": f"paper:limitation:{i:02d}",
                "raw_ref": f"limitations[{i - 1}]",
                "text": text,
                "verification_state": "NOT_CHECKED",
                "verification_scope": _verification_scope(),
            }
            for i, text in enumerate(_list_text(fs.get("limitations")), 1)
        ]
        context = [
            *({"evidence_id": f"paper:context:finding:{i:02d}",
               "role": "finding_summary", "raw_ref": f"what_found[{i - 1}]",
               "text": text, "verification_state": "NOT_CHECKED",
               "verification_scope": _verification_scope()}
              for i, text in enumerate(_list_text(fs.get("what_found")), 1)),
            *({"evidence_id": f"paper:context:method:{i:02d}",
               "role": "method_summary", "raw_ref": f"how[{i - 1}]",
               "text": text, "verification_state": "NOT_CHECKED",
               "verification_scope": _verification_scope()}
              for i, text in enumerate(_list_text(fs.get("how")), 1)),
        ]
    else:
        claims = _report_text_claims(fs)
        numbers = _report_numbers(fs)
        source = fs.get("source") if isinstance(fs.get("source"), dict) else {}
        broker = str(source.get("broker") or "")
        risks = [
            {
                "evidence_id": f"report:risk:{i:02d}",
                "raw_ref": f"risks[{i - 1}]",
                "text": text,
                "verification_state": "NOT_CHECKED",
                "verification_scope": _verification_scope(),
                "attribution": broker,
            }
            for i, text in enumerate(_list_text(fs.get("risks")), 1)
        ]
        limitations = []
        company = str(fs.get("company") or "").strip()
        context = ([{"evidence_id": "report:context:company",
                     "role": "company", "raw_ref": "company", "text": company,
                     "verification_state": "NOT_CHECKED",
                     "verification_scope": _verification_scope()}]
                   if company else [])

    return {
        "contract_version": CONTRACT_VERSION,
        "domain": domain,
        "content_id": str(content_id or ""),
        "source": _source_block(fs, domain),
        "claims": claims,
        "numbers": numbers,
        "risks": risks,
        "limitations": limitations,
        "background_context": context,
    }


def validate(pack: dict[str, Any]) -> list[str]:
    """Return deterministic contract errors; empty means the pack is usable."""
    errors: list[str] = []
    if pack.get("contract_version") != CONTRACT_VERSION:
        errors.append("contract_version_invalid")
    if pack.get("domain") not in ("paper", "report"):
        errors.append("domain_invalid")
    if not isinstance(pack.get("source"), dict):
        errors.append("source_missing")
    for key in ("claims", "numbers", "risks", "limitations", "background_context"):
        if not isinstance(pack.get(key), list):
            errors.append(f"{key}_not_list")

    seen: set[str] = set()
    for section in ("claims", "numbers", "risks", "limitations", "background_context"):
        for item in pack.get(section) or []:
            if not isinstance(item, dict):
                errors.append(f"{section}_item_invalid")
                continue
            eid = str(item.get("evidence_id") or "")
            if not eid:
                errors.append(f"{section}_evidence_id_missing")
            elif eid in seen:
                errors.append(f"evidence_id_duplicate:{eid}")
            seen.add(eid)
            if not str(item.get("raw_ref") or ""):
                errors.append(f"{section}_raw_ref_missing:{eid or '?'}")
            state = item.get("verification_state")
            if state not in VERIFICATION_STATES:
                errors.append(f"verification_state_invalid:{eid or '?'}")
            scope = item.get("verification_scope")
            if not isinstance(scope, dict) or set(scope) != {
                "quote_presence", "numeric_value", "unit", "period", "semantic_entailment"
            } or not all(isinstance(v, bool) for v in scope.values()):
                errors.append(f"verification_scope_invalid:{eid or '?'}")
    return sorted(set(errors))
