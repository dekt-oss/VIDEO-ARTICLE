# Explanation Engine v2 Phase 10 Directive Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Project canonical Phase 9 Visual Plans into traceable Production-shaped Shadow directives and produce a same-input before/after comparison.

**Architecture:** A pure `explanation_directive` projector validates a READY Visual Plan and deterministically maps it to header/cuts/visual-sequence structures without wiring Production. A separate comparator summarizes the old flat spec and new traced spec without claiming rendered quality.

**Tech Stack:** Python 3.12, pytest, existing Phase 3~9 pure contracts

**Spec:** `docs/superpowers/specs/2026-10-03-explanation-v2-phase10-directive-projection-design.md`

## Global Constraints

- No Production imports or runtime wiring from existing directive/render paths.
- No DB, model, asset, render, or paid calls.
- Reject non-READY plans.
- Preserve every upstream trace and semantic calibration field.
- Same input must always produce the same output.

## Review Focus

- Forged `planner_status=READY` with missing beats must be rejected.
- Unknown narration/stage/mutation/shot references must be rejected.
- Report broker attribution and `broker_projection` must survive to the cut.
- Empty trace must never become a renderable cut.
- A comparison must not claim Production or rendered quality.

---

### Task 1: Directive projector contract

**Files:**
- Create: `tests/test_explanation_directive.py`
- Create: `engine/explanation_directive.py`

**Interfaces:**
- Consumes: canonical `visual-plan-v1`, `spoken-narration-v1`, Explanation IR, Evidence Pack.
- Produces: `build(visual_plan, narration, ir, pack, *, version_type="image_sequence") -> dict` and `validate(result, visual_plan, narration, ir, pack, *, version_type="image_sequence") -> list[str]`.

- [x] **Step 1: Write failing Paper READY and blocked tests**

Assert exact contract/status, one cut per Visual Beat, complete trace chain, current Production shape, and rejection of `BLOCKED_GATE`.

- [x] **Step 2: Run targeted tests and verify RED**

Run: `pytest tests/test_explanation_directive.py -q`

Expected: FAIL because `engine.explanation_directive` does not exist.

- [x] **Step 3: Implement the minimal projector**

Implement closed mappings, narration lookup, duration calculation, cut projection, sequence projection, QA metrics, reference validation, and canonical validation.

- [x] **Step 4: Run targeted tests and verify GREEN**

Run: `pytest tests/test_explanation_directive.py -q`

Expected: all Task 1 tests pass.

- [x] **Step 5: Add adversarial tests before fixes**

Add tests for forged READY, dangling narration/stage trace, empty trace, and Report attribution/causal calibration.

- [x] **Step 6: Run new tests and verify RED, then implement minimal fixes**

Run: `pytest tests/test_explanation_directive.py -q`

Expected before fixes: the new adversarial cases fail for the named reason. Expected after fixes: all pass.

### Task 2: Same-input comparison and user-visible artifact

**Files:**
- Modify: `tests/test_explanation_directive.py`
- Create: `engine/explanation_directive_shadow_compare.py`
- Create: `docs/phase10_ExplanationEngine_v2_directive_projection.md`

**Interfaces:**
- Consumes: a flat legacy-shaped directive summary and a Phase 10 result for the same content/domain.
- Produces: `compare(legacy, projected, visual_plan, narration, ir, pack) -> dict` with
  verified same-input trace/calibration/directive-quality boundaries.

- [x] **Step 1: Write failing comparison tests**

Assert identity mismatch rejection, exact before/after shape, full trace verdict, and `rendered_video_quality=not_measured`.

- [x] **Step 2: Run targeted comparison tests and verify RED**

Run: `pytest tests/test_explanation_directive.py -q`

Expected: FAIL because the comparison module does not exist.

- [x] **Step 3: Implement the minimal comparator and comparison builder fixture**

Use only stored input values; do not infer visual quality. Record that the comparison input is deterministic repository fixture data, not a live Production replay.

- [x] **Step 4: Run targeted tests and verify GREEN**

Run: `pytest tests/test_explanation_directive.py -q`

Expected: all Phase 10 tests pass.

- [x] **Step 5: Document exact JSON before/after and limitations**

Document the same-input Paper comparison, Report calibration preservation, Production non-wiring, and live/render verification boundary.

### Task 3: Regression and delivery verification

**Files:**
- Modify only if a failing regression proves a Phase 10 defect.

**Interfaces:**
- Consumes: complete Phase 10 diff.
- Produces: verified branch and Draft stacked PR.

- [x] **Step 1: Run Phase 2~10 regressions**

Run the Evidence Pack through Phase 10 focused test set.

- [x] **Step 2: Run full Python and web checks**

Run full `pytest`, Node tests, TypeScript `--noEmit`, lint, and production build.

- [x] **Step 3: Run Fable Review**

Attack missing trace, qualifier loss, association/causation upgrades, projection/current-fact upgrades, unsupported/stale reuse, and cross-content comparison.

- [x] **Step 4: Fix Critical/Important findings with RED→GREEN tests**

Apply one bounded fix pass and rerun the relevant suite.

- [x] **Step 5: Commit, push, and open a Draft stacked PR**

Base the PR on `codex/explanation-v2-phase9-visual-planner`; do not merge either PR.
