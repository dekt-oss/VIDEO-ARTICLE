from __future__ import annotations

from copy import deepcopy

import pytest

from engine import explanation_ir, prerequisite_resolver


def _scope(*, semantic: bool) -> dict[str, bool]:
    return {
        "quote_presence": True,
        "numeric_value": False,
        "unit": False,
        "period": False,
        "semantic_entailment": semantic,
    }


def _pack(*, semantic: bool = False, state: str = "SUPPORTED") -> dict:
    return {
        "contract_version": "evidence-pack-v1",
        "domain": "paper",
        "content_id": "paper-1",
        "source": {
            "source_depth": "full_body",
            "source_chars": 5000,
            "source_mode": "FULL_EXPLAINER",
            "provider": "publisher",
            "attribution": {},
        },
        "claims": [{
            "evidence_id": "paper:C01",
            "raw_ref": "claims:C01",
            "text": "GWAS는 변이와 성격 사이의 통계적 연관을 찾는다.",
            "claim_type": "background_context",
            "domain_role": "claim",
            "causal_strength": "association_only",
            "evidence_grade": "A",
            "verification_state": state,
            "verification_scope": _scope(semantic=semantic),
            "source_refs": [{"quote": "variants associated with personality"}],
            "uncertainty": None,
            "limitations": [],
            "attribution": "",
            "domain_fields": {},
        }],
        "numbers": [],
        "risks": [],
        "limitations": [],
        "background_context": [],
    }


def _ir(pack: dict) -> dict:
    candidate = {
        "domain": "paper",
        "core_question": "성격과 유전 변이의 관계를 어떻게 해석해야 하는가?",
        "thesis": "변이는 성격과 연관됐지만 성격을 결정한다고 입증하지 않았다.",
        "reasoning_units": [{
            "role": "result",
            "text": pack["claims"][0]["text"],
            "evidence_ids": ["paper:C01"],
            "causal_level": "association_only",
        }],
    }
    return explanation_ir.normalize(candidate, pack)


def _request(concept_id: str, *, evidence_ids: list[str] | None = None) -> list[dict]:
    return [{
        "concept_id": concept_id,
        "reason": "결과를 인과로 오해하지 않으려면 먼저 필요하다.",
        "evidence_ids": evidence_ids or [],
        "required": True,
    }]


def test_resolver_prefers_semantically_verified_primary_source():
    pack = _pack(semantic=True)
    ir = _ir(pack)

    result = prerequisite_resolver.resolve(
        ir,
        pack,
        _request("gwas_association", evidence_ids=["paper:C01"]),
    )

    concept = result["concepts"][0]
    assert concept["status"] == "RESOLVED_SOURCE"
    assert concept["evidence_ids"] == ["paper:C01"]
    assert concept["knowledge_refs"] == ["evidence:paper:C01"]
    assert result["scope_action"] == "KEEP"
    assert prerequisite_resolver.validate(result, ir, pack) == []


def test_quote_presence_without_semantic_entailment_falls_back_to_glossary():
    pack = _pack(semantic=False)
    ir = _ir(pack)

    result = prerequisite_resolver.resolve(
        ir,
        pack,
        _request("gwas_association", evidence_ids=["paper:C01"]),
    )

    concept = result["concepts"][0]
    assert concept["status"] == "RESOLVED_GLOSSARY"
    assert concept["evidence_ids"] == []
    assert concept["knowledge_refs"] == ["glossary:gwas_association"]
    assert concept["guardrails"] == [
        "통계적 연관은 해당 변이가 특성을 직접 결정하거나 원인임을 뜻하지 않는다."
    ]
    assert "source_semantic_entailment_unverified:gwas_association:paper:C01" in result["warnings"]


def test_unknown_required_concept_fails_closed_and_narrows_scope():
    pack = _pack()
    ir = _ir(pack)

    result = prerequisite_resolver.resolve(ir, pack, _request("unknown-concept"))

    assert result["concepts"][0]["status"] == "UNRESOLVED"
    assert result["unresolved_concepts"] == ["unknown-concept"]
    assert result["scope_action"] == "NARROW_SCOPE"
    assert "glossary_concept_unknown:unknown-concept" in result["warnings"]


def test_non_required_unknown_concept_does_not_force_scope_reduction():
    pack = _pack()
    ir = _ir(pack)
    request = _request("unknown-concept")
    request[0]["required"] = False

    result = prerequisite_resolver.resolve(ir, pack, request)

    assert result["scope_action"] == "KEEP"
    assert result["unresolved_concepts"] == ["unknown-concept"]


def test_resolver_is_deterministic_and_does_not_mutate_inputs():
    pack = _pack()
    ir = _ir(pack)
    requests = _request("gwas_association", evidence_ids=["paper:C01"])
    before = deepcopy((ir, pack, requests))

    first = prerequisite_resolver.resolve(ir, pack, requests)
    second = prerequisite_resolver.resolve(ir, pack, requests)

    assert first == second
    assert (ir, pack, requests) == before


def test_invalid_glossary_provenance_is_rejected():
    pack = _pack()
    ir = _ir(pack)
    glossary = [{
        "concept_id": "gwas_association",
        "domains": ["paper"],
        "label": "GWAS 연관",
        "simple_explanation": "설명",
        "guardrails": [],
        "source": {"publisher": "", "title": "", "url": "", "checked_at": ""},
    }]

    with pytest.raises(ValueError, match="glossary_invalid"):
        prerequisite_resolver.resolve(ir, pack, _request("gwas_association"), glossary=glossary)


def test_domain_mismatch_is_rejected():
    pack = _pack()
    ir = _ir(pack)
    ir["domain"] = "report"

    with pytest.raises(ValueError, match="explanation_ir_invalid"):
        prerequisite_resolver.resolve(ir, pack, _request("gwas_association"))
