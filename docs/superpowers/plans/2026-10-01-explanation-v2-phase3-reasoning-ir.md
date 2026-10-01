# Explanation Engine v2 Phase 3 Reasoning IR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, evidence-traceable Explanation IR shadow layer for paper and report content without changing the Production script path.

**Architecture:** A pure common IR normalizer indexes Phase 2 Evidence Pack items, derives raw references, assigns stable IDs, and validates semantic safety. A paper adapter maps Claim Ledger semantics without strengthening causality; a report adapter translates existing financial reasoning units while preserving broker attribution and Phase 1 depth ceilings.

**Tech Stack:** Python 3, pytest, `engine.evidence_pack`, `engine.report_reasoning`, `engine.source_adequacy`.

**Spec:** `docs/phase3_ExplanationEngine_v2_reasoning_ir.md`

## Global Constraints

- Keep script, directive, render, web, and Supabase paths unchanged.
- Add no dependency, migration, persistence, network call, or LLM call.
- Treat Paper and Report Fact Sheets as the source of truth through Evidence Pack.
- Do not treat `SUPPORTED` as semantic entailment when that scope is false.
- Do not use `UNSUPPORTED` or `STALE` evidence for positive reasoning.
- Assign `XR01…`, raw references, and chain in code.

## Review Focus

- Stronger Korean text must not raise the source causal level.
- Unknown, stale, or unsupported evidence must not survive as positive reasoning.
- Broker forecasts must not become objective current facts.
- Shallow reports must not recover reasoning removed by Source Adequacy.
- Repeated runs must not create dangling IDs or nondeterministic output.

---

### Task 1: Common Explanation IR contract

**Files:**
- Create: `engine/explanation_ir.py`
- Create: `tests/test_explanation_ir.py`

**Interfaces:**
- Consumes: `evidence_pack.validate(pack)` and an adapter candidate dict.
- Produces: `build_index(pack)`, `normalize(candidate, pack)`, and `validate(ir, pack=None)`.

- [ ] **Step 1: Write failing contract tests**

Test stable contract version, `XR01` IDs, code-derived `raw_refs`, chain reconstruction, duplicate removal, dangling evidence filtering, input immutability, one non-empty core question, domain mismatch, and repeated-output equality.

```python
ir = explanation_ir.normalize(candidate, pack)
assert ir["contract_version"] == "explanation-ir-v1"
assert [u["reasoning_id"] for u in ir["reasoning_units"]] == ["XR01"]
assert ir["reasoning_units"][0]["raw_refs"] == ["claims:C01"]
assert explanation_ir.validate(ir, pack) == []
```

- [ ] **Step 2: Verify RED**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
C:\tmp\PaperClip-regen-render\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -p no:anyio --basetemp .pytest-phase3 tests/test_explanation_ir.py -q
```

Expected: import failure because `engine.explanation_ir` does not exist.

- [ ] **Step 3: Implement the minimal normalizer**

Use copies, fixed enums, an Evidence Pack index, code-assigned IDs, derived raw refs, status filtering, sorted warnings, and structural validation.

- [ ] **Step 4: Verify GREEN**

Run the Step 2 command. Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit**

```powershell
git add -- engine/explanation_ir.py tests/test_explanation_ir.py
git commit -m "feat: add explanation IR contract"
```

### Task 2: Paper Reasoning Adapter

**Files:**
- Create: `engine/paper_reasoning_adapter.py`
- Modify: `tests/test_explanation_ir.py`

**Interfaces:**
- Consumes: an `evidence-pack-v1` Paper pack.
- Produces: `build(pack, *, core_question="", thesis="") -> explanation-ir-v1 dict`.

- [ ] **Step 1: Write failing Paper tests**

Test association preservation, unsupported evidence exclusion, author interpretation, limitation preservation, semantic-entailment warning, stable fallback question/thesis, and Paper domain rejection.

```python
ir = paper_reasoning_adapter.build(pack)
assert ir["reasoning_units"][0]["causal_level"] == "association_only"
assert ir["reasoning_units"][0]["evidence_ids"] == ["paper:C01"]
```

- [ ] **Step 2: Verify RED**

Run Task 1 tests. Expected: missing Paper adapter.

- [ ] **Step 3: Implement the Paper adapter**

Map Claim Ledger kinds to minimal roles, retain causal strength and uncertainty, emit limitations with the same trace, and never synthesize absent bridges or mechanisms.

- [ ] **Step 4: Verify GREEN**

Expected: all `tests/test_explanation_ir.py` tests pass.

- [ ] **Step 5: Commit**

```powershell
git add -- engine/paper_reasoning_adapter.py tests/test_explanation_ir.py
git commit -m "feat: adapt paper evidence to explanation IR"
```

### Task 3: Report Adapter and Gold Set shadow regression

**Files:**
- Create: `engine/report_reasoning_adapter.py`
- Create: `tests/fixtures/explanation_ir_gold_cases.json`
- Modify: `tests/test_explanation_ir.py`

**Interfaces:**
- Consumes: a Report Evidence Pack and normalized `{"units": [...]}` financial reasoning.
- Produces: `build(pack, financial_reasoning, *, core_question="", thesis="")`.

- [ ] **Step 1: Write failing Report and fixture tests**

Test known fact-ID mapping, broker attribution, source order, Paper/Report three cases each, and byte-equivalent serialized output across two runs.

```python
ir = report_reasoning_adapter.build(pack, reasoning)
assert ir["reasoning_units"][0]["evidence_ids"] == ["report:num_op"]
assert ir["reasoning_units"][0]["attribution"] == "하나증권"
```

The cases pin heel-strike scope, retinotopic modality, personality association, Samsung trace, NH partial-depth ceiling, and shipbuilding projection.

- [ ] **Step 2: Verify RED**

Run Phase 3 tests. Expected: missing Report adapter or fixture.

- [ ] **Step 3: Implement the Report adapter and fixtures**

Translate existing steps, map only known `fact_ids` to `report:<fact_id>`, preserve attribution and order, and never reconstruct removed steps.

- [ ] **Step 4: Run adjacent regressions**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
C:\tmp\PaperClip-regen-render\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -p no:anyio --basetemp .pytest-phase3 tests/test_explanation_ir.py tests/test_evidence_pack.py tests/test_report_reasoning.py tests/test_source_adequacy.py tests/test_explanation_quality.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add -- engine/report_reasoning_adapter.py tests/test_explanation_ir.py tests/fixtures/explanation_ir_gold_cases.json
git commit -m "test: add Phase 3 shadow regressions"
```

### Task 4: Documentation, full verification, and Draft PR

**Files:**
- Modify: `docs/phase3_ExplanationEngine_v2_reasoning_ir.md`

**Interfaces:**
- Consumes: implemented APIs and real verification output.
- Produces: accurate usage, scope, rollback, review record, and Draft PR.

- [ ] **Step 1: Update the Phase 3 document**

Add concrete adapter examples, warning behavior, changed files, and the explicit Production non-integration statement.

- [ ] **Step 2: Run full verification**

Run full Python pytest, web node tests, typecheck, lint, and build when checked-in dependencies permit. Record unavailable checks as unverified instead of changing dependencies.

- [ ] **Step 3: Run scope checks**

```powershell
git diff --check origin/main...HEAD
git diff --name-only origin/main...HEAD
```

Expected: only Phase 3 modules, tests, fixture, spec, and plan.

- [ ] **Step 4: Perform adversarial Fable Review**

Attack every semantic failure class from the spec. Fix each Critical or Important finding with a new failing test first.

- [ ] **Step 5: Commit documentation**

```powershell
git add -- docs/phase3_ExplanationEngine_v2_reasoning_ir.md docs/superpowers/plans/2026-10-01-explanation-v2-phase3-reasoning-ir.md
git commit -m "docs: record Phase 3 reasoning IR implementation"
```

- [ ] **Step 6: Push and open a Draft PR**

The PR body records the problem, contract, architecture, changed files, tests, Gold Set regression, unverified items, rollback, and next phase. Do not merge.
