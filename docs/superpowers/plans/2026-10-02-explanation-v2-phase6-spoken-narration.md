# Explanation Engine v2 Phase 6 Spoken Narration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert a validated READY Narrative Plan into traceable Korean spoken narration in shadow mode while rejecting deterministic semantic drift and leaving Production output unchanged.

**Architecture:** `engine/spoken_narration.py` owns the constrained prompt payload, upstream revalidation, deterministic normalization, draft guards, generation wrapper, and independently guarded polish application. `engine/spoken_narration_shadow_compare.py` reports only machine-checkable Phase 6 axes against the stored Gold Set. The model may author sentences, but code injects all IDs and provenance from the validated plan.

**Tech Stack:** Python 3, pytest, existing `engine.llm.call_json`, existing Explanation Engine v2 contracts, existing `engine.script_polish.rejection_reason`.

**Spec:** `docs/superpowers/specs/2026-10-02-explanation-v2-phase6-spoken-narration-design.md`

## Global Constraints

- Shadow-only: do not modify `engine/scriptgen.py`, `engine/report_scriptgen.py`, prompts used by Production, Supabase, DB, directives, approval, render, or publish paths.
- Do not persist Phase 6 artifacts or make a live/paid model call in tests or implementation verification.
- Revalidate `evidence-pack-v1`, `explanation-ir-v1`, `prerequisite-resolution-v1`, and `narrative-plan-v1` at the Phase 6 boundary.
- Return `BLOCKED_UPSTREAM` before calling a model unless `planning_status=READY`.
- Code, never the model, supplies narration IDs and all evidence/reasoning/provenance fields.
- `DRAFT_ACCEPTED` means only deterministic Phase 6 guards passed; `qa.semantic_entailment` stays `NOT_CHECKED`.
- Unsafe polish keeps the accepted draft text unchanged and records why it was rejected.
- Open a stacked Draft PR against `codex/explanation-v2-phase5-narrative-planner`; do not merge automatically.

## Review Focus

- A syntactically valid but tampered upstream plan must fail before draft normalization or model invocation.
- Numeric normalization must distinguish unit changes (`30%` to `30배`) while permitting whitespace-only presentation changes.
- A beat containing association language must reject newly introduced determination or direct-cause language.
- Report attribution must remain present even when the model rearranges sentence order.
- Polish output with valid `script_polish` shape but changed Phase 6 trace-sensitive meaning must be rejected and leave the accepted draft immutable.

---

### Task 1: Spoken narration boundary, prompt, and deterministic draft guards

**Files:**
- Create: `engine/spoken_narration.py`
- Create: `tests/test_spoken_narration.py`

**Interfaces:**
- Consumes: `narrative_planner.validate(plan, ir, resolution, pack) -> list[str]`, validated plan beat fields, `llm.call_json`, `llm.set_text_purpose`, `config.MODEL_SCRIPT`.
- Produces: `prompt_payload(plan, ir, resolution, pack) -> dict`, `normalize_draft(payload, plan, ir, resolution, pack) -> dict`, `validate(result, plan, ir, resolution, pack) -> list[str]`, and `generate(plan, ir, resolution, pack, *, caller=None) -> dict`.

- [ ] **Step 1: Write failing boundary and shape tests**

  Add literal assertions proving: READY input produces `spoken-narration-v1`; blocked input returns `BLOCKED_UPSTREAM` with no caller invocation; malformed upstream contracts raise `ValueError`; unknown, missing, duplicated, reordered, or empty beat rows produce `REJECTED_DRAFT`; model-authored IDs/refs are ignored and output refs equal the plan exactly; inputs remain unchanged.

- [ ] **Step 2: Run the focused tests and confirm RED**

  Run: `python -m pytest tests/test_spoken_narration.py -q`

  Expected: collection/import failure because `engine.spoken_narration` does not exist.

- [ ] **Step 3: Implement the minimal boundary and normalized contract**

  Implement constants `CONTRACT_VERSION = "spoken-narration-v1"` and statuses `DRAFT_ACCEPTED`, `REJECTED_DRAFT`, `BLOCKED_UPSTREAM`. The model payload shape is exactly `{"beats": [{"beat_id": "NB01", "sentences": ["..."]}]}`. `generate` revalidates upstream data, returns a blocked artifact before resolving/calling `caller`, otherwise calls the injected caller or `call_json` using `MODEL_SCRIPT`, a bounded token limit, and purpose `spoken_narration_shadow`. `normalize_draft` copies plan order and provenance into `SN01`, `SN02`, ... output beats.

- [ ] **Step 4: Run the boundary tests and confirm GREEN**

  Run: `python -m pytest tests/test_spoken_narration.py -q`

  Expected: all boundary/shape tests pass without network access.

- [ ] **Step 5: Write failing semantic-drift tests**

  Add table-driven literal cases for changed/dropped/invented numbers and units, new scope intensifiers, association upgraded to determination/direct cause, removed negation/uncertainty/qualifiers, dropped Report broker attribution, factual beats without trace, and a factual assertion replacing the approved rhetorical hook. Add warning-only cases for long sentences, repeated core question, dense numbers, unexplained abbreviations, and academic register.

- [ ] **Step 6: Run the guard tests and confirm RED**

  Run each new named test directly with pytest `-q`.

  Expected: unsafe candidates are incorrectly accepted or warnings are missing before implementation.

- [ ] **Step 7: Implement the minimal guards and metrics**

  Tokenize numbers with attached units as a multiset, compare protected meaning classes using `script_polish.meaning_classes`, add explicit scope and determination/direct-cause term checks, require Report attributions in the corresponding beat text, require a question-form HOOK grounded in `core_question`, and require trace on factual beats. Put blocking codes in `qa.errors`, heuristic codes in `qa.warnings`, counts in `qa.metrics`, and derive status solely from whether errors are empty. Keep `semantic_entailment` fixed at `NOT_CHECKED`.

- [ ] **Step 8: Run Task 1 tests and commit**

  Run: `python -m pytest tests/test_spoken_narration.py -q`

  Expected: all Task 1 tests pass.

  Commit: `feat: add Phase 6 spoken narration shadow contract`

---

### Task 2: Guarded polish and Gold Set shadow comparison

**Files:**
- Modify: `engine/spoken_narration.py`
- Create: `engine/spoken_narration_shadow_compare.py`
- Modify: `tests/test_spoken_narration.py`

**Interfaces:**
- Consumes: Task 1 accepted narration artifacts and `script_polish.rejection_reason(before, after) -> str`.
- Produces: `apply_polish(narration, payload, plan, ir, resolution, pack) -> dict` and `spoken_narration_shadow_compare.compare(legacy_case, narration, plan, ir, resolution, pack) -> dict`.

- [ ] **Step 1: Write failing polish tests**

  Prove an accepted polish can change expression while preserving exact output trace; a numeric, association/causal, qualifier, attribution, beat-coverage, or empty-text drift is rejected; rejected polish retains every original sentence; the input narration is not mutated; blocked/rejected drafts cannot be polished.

- [ ] **Step 2: Run polish tests and confirm RED**

  Run: `python -m pytest tests/test_spoken_narration.py -q -k polish`

  Expected: failure because `apply_polish` is absent.

- [ ] **Step 3: Implement minimal independent polish application**

  Accept only exact beat coverage and sentence arrays. Join each beat before/after for `script_polish.rejection_reason`, then run the full Task 1 draft guards on the candidate. Apply a beat only when both checks pass; otherwise keep the original sentences and append `{beat_id, reason}` to `polish.rejected`. Return a deep-copied artifact and never change semantic-entailment status.

- [ ] **Step 4: Run polish tests and confirm GREEN**

  Run: `python -m pytest tests/test_spoken_narration.py -q -k polish`

  Expected: all polish tests pass.

- [ ] **Step 5: Write failing comparison and Gold Set tests**

  For a literal Personality GWAS payload assert READY -> `DRAFT_ACCEPTED`, exact trace, prerequisite-before-terminology, question hook, association preservation, and `semantic_entailment=not_measured`. For Heel Strike, Retinotopic Remapping, Samsung, NH Mid Cycle, and Shipbuilding assert upstream `BLOCKED_UPSTREAM` with zero caller calls. Reject legacy domain/content mismatches and prohibit `improvement_percent` and final-output claims.

- [ ] **Step 6: Run comparison tests and confirm RED**

  Run: `python -m pytest tests/test_spoken_narration.py -q -k 'shadow or gold'`

  Expected: failure because the comparator does not exist.

- [ ] **Step 7: Implement the comparator**

  Validate all supplied contracts, then emit only the axes `plan_coverage`, `stable_trace`, `prerequisite_order`, `hook_grounding`, `qualifier_preservation`, `spoken_structure`, `semantic_entailment`, and `final_directive_quality`. The last two always report `not_measured`; blocked cases report fail-closed outcomes, not prose improvement.

- [ ] **Step 8: Run Task 2 and adjacent tests, then commit**

  Run: `python -m pytest tests/test_spoken_narration.py tests/test_narrative_planner.py tests/test_prerequisite_resolver.py tests/test_explanation_ir.py tests/test_evidence_pack.py -q`

  Expected: all selected tests pass.

  Commit: `test: add Phase 6 narration shadow regressions`

---

### Task 3: Documentation, adversarial review, and delivery

**Files:**
- Create: `docs/phase6_ExplanationEngine_v2_spoken_narration.md`
- Modify: `docs/superpowers/plans/2026-10-02-explanation-v2-phase6-spoken-narration.md`

**Interfaces:**
- Consumes: the final Task 1/2 contracts and observed verification output.
- Produces: operator-facing Phase 6 boundary/rollback/limitations documentation and a stacked Draft PR.

- [ ] **Step 1: Document the shipped shadow contract**

  Record current problem, inputs/outputs, status meanings, guards versus warnings, `NOT_CHECKED` semantic-entailment boundary, no-paid-call/no-persistence/no-Production-wiring rule, Gold Set statuses, rollback, and Phase 7/9/11 comparison milestones.

- [ ] **Step 2: Run focused and full local verification**

  Run targeted Phase 6 tests, adjacent Explanation Engine tests, full `pytest`, Web `node --test lib/*.test.ts lib/work/*.test.ts`, `npx tsc --noEmit`, `npm run lint`, `npm run build`, and `git diff --check`.

  Expected: zero failures. Existing Node module-type warnings are recorded, not fixed in this phase.

- [ ] **Step 3: Perform a separate Fable Review**

  Assume the implementation is wrong and inspect evidence-free reasoning, scope expansion, qualifier loss, association-to-causation, projection/current-fact drift, broker-attribution loss, stale/unsupported reuse, shallow-source overexpansion, ID/ref loss, malformed model payloads, mutation, and false quality claims. Rate each reproducible finding; fix Critical/High findings in one TDD pass and rerun the full suite.

- [ ] **Step 4: Complete plan evidence and commit**

  Mark only evidenced checkboxes complete and commit documentation/plan results as `docs: complete Phase 6 spoken narration plan`.

- [ ] **Step 5: Push and open a stacked Draft PR**

  Push `codex/explanation-v2-phase6-spoken-narration`, open a Draft PR with base `codex/explanation-v2-phase5-narrative-planner`, include problem/contract/architecture/files/tests/Gold Set/unverified/rollback/next phase, attach it to the current task, and wait for GitHub Actions/Vercel. Do not merge.

