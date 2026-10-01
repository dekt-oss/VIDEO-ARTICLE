# Explanation Engine v2 Phase 4 Prerequisite Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve viewer prerequisite concepts from explicit, traceable knowledge and measure the contract-level improvement against the existing Gold Set directives without changing Production output.

**Architecture:** A checked-in, validated glossary contains only reviewed explanations and source provenance. A pure resolver accepts `explanation-ir-v1`, its Evidence Pack, and explicit concept requests; it resolves from semantically verified source evidence first, then the glossary, and otherwise requires scope reduction. A shadow comparator reports failure-axis improvement separately from final narration or render quality.

**Tech Stack:** Python 3, JSON, pytest, existing `engine.explanation_ir` and `engine.evidence_pack`.

**Spec:** `docs/작업지시서_ExplanationEngine_v2.md` section 6, with Phase 3 contract in `docs/phase3_ExplanationEngine_v2_reasoning_ir.md`.

## Global Constraints

- Keep script, directive, render, web, Supabase, and persistence paths unchanged.
- Add no model call, network call, dependency, or migration.
- Never use LLM general knowledge as evidence.
- Resolve in this order: semantically verified primary-source evidence, reviewed glossary, otherwise narrow scope.
- Preserve the Phase 3 Evidence Pack and Explanation IR; Phase 4 emits a separate shadow artifact.
- Report structural improvement separately from unverified final video quality.

## Review Focus

- A merely present quote with `semantic_entailment=false` must not become source-backed prerequisite knowledge.
- Unknown glossary IDs and malformed provenance must fail closed.
- A glossary explanation must not strengthen association into causation or forecast into current fact.
- An unresolved required concept must produce `NARROW_SCOPE`, not a fabricated explanation.
- Shadow comparison must not claim script, directive, render, or retention improvement.

---

### Task 1: Reviewed glossary and resolver contract

**Files:**
- Create: `engine/explanation_glossary.json`
- Create: `engine/prerequisite_resolver.py`
- Create: `tests/test_prerequisite_resolver.py`

**Interfaces:**
- Consumes: `explanation-ir-v1`, its `evidence-pack-v1`, and `requested_concepts` entries with `concept_id`, optional `evidence_ids`, and `reason`.
- Produces: `resolve(ir, pack, requested_concepts, glossary=None) -> prerequisite-resolution-v1` and `validate(result, ir, pack) -> list[str]`.

- [x] **Step 1: Write failing contract tests**

Pin deterministic output, input immutability, domain checks, verified-source priority, rejection of `semantic_entailment=false`, glossary fallback, provenance validation, unknown concept handling, and `NARROW_SCOPE` for unresolved required concepts.

- [x] **Step 2: Run tests and verify RED**

Run `python -m pytest tests/test_prerequisite_resolver.py -q` and confirm import failure.

- [x] **Step 3: Implement the minimal resolver**

Load the checked-in glossary without side effects, validate every entry, build evidence and glossary indexes, and emit deterministic concept records plus warnings and scope action.

- [x] **Step 4: Run tests and verify GREEN**

Run the Task 1 test command and require all tests to pass.

- [x] **Step 5: Commit**

Commit the glossary, resolver, and tests as one independently reviewable contract change.

### Task 2: Gold Set shadow comparison

**Files:**
- Create: `engine/explanation_shadow_compare.py`
- Create: `tests/fixtures/prerequisite_resolution_gold_cases.json`
- Modify: `tests/test_prerequisite_resolver.py`

**Interfaces:**
- Consumes: a legacy Gold Set case, its Phase 3 IR, and Phase 4 resolution.
- Produces: `compare(legacy_case, ir, resolution) -> explanation-shadow-comparison-v1` with per-axis `improved|unchanged|unresolved|not_applicable` outcomes and explicit non-claims.

- [x] **Step 1: Write failing comparison tests**

Cover Paper and Report cases, especially Personality GWAS prerequisite recovery, unresolved concepts causing scope reduction, evidence trace retention, source-depth compliance, and the prohibition on claiming final output improvement.

- [x] **Step 2: Run tests and verify RED**

Run the Phase 4 tests and confirm the comparator/fixture is missing.

- [x] **Step 3: Implement comparator and fixtures**

Compare only machine-checkable contract axes: prerequisite coverage, traceability, semantic calibration, one-core-question shape, and source-depth safety. Keep narration, directive, render, and retention as `not_measured`.

- [x] **Step 4: Run adjacent regressions**

Run Phase 4, Phase 3 IR, Evidence Pack, Source Adequacy, and Explanation Quality tests.

- [x] **Step 5: Commit**

Commit the comparator and deterministic fixtures.

### Task 3: Documentation, adversarial review, and Draft PR

**Files:**
- Create: `docs/phase4_ExplanationEngine_v2_prerequisite_resolver.md`
- Modify: `docs/superpowers/plans/2026-10-02-explanation-v2-phase4-prerequisite-resolver.md`

**Interfaces:**
- Consumes: implemented APIs and actual verification output.
- Produces: scope, comparison table, rollback, risks, and Draft PR evidence.

- [x] **Step 1: Document the current-to-target flow and comparison limits**

Record that Phase 4 is shadow-only and that improved contracts do not prove improved Production directives.

- [x] **Step 2: Perform adversarial Fable Review**

Attack evidence-free knowledge, qualifier loss, association-to-causation, forecast-to-fact, stale evidence, shallow-source overexpansion, dangling IDs, and misleading improvement claims. Fix every blocking finding with a failing test first.

- [x] **Step 3: Run full verification**

Run targeted tests, full Python pytest, web tests, TypeScript typecheck, lint, build, and `git diff --check`.

- [ ] **Step 4: Push and open a Draft PR**

Include current problem, contract, architecture, changed files, tests, Gold Set comparison, unverified items, rollback, and next phase. Do not merge.
