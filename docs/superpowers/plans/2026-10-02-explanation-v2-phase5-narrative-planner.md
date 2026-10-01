# Explanation Engine v2 Phase 5 Narrative Planner Implementation Plan

**Goal:** Convert validated Explanation IR and prerequisite resolution into a deterministic,
traceable narrative order without changing Production output.

**Architecture:** A pure planner validates the two upstream shadow contracts against the Evidence
Pack. Required unresolved
knowledge blocks planning. Otherwise it emits one rhetorical hook, resolved prerequisite setup,
then stage-grouped IR units without rewriting their content or references. A separate comparator
reports contract-level changes against the existing six Gold Set cases.

## Constraints

- No model, network, DB, migration, script prompt, directive, or render change.
- No new factual hook or narration prose.
- Never plan through `NARROW_SCOPE`.
- Preserve IR order, reasoning IDs, evidence IDs, raw refs, attribution, uncertainty, and causal level.
- Keep final-video quality explicitly unmeasured.

## Tasks

### 1. Planner contract

- [x] Write RED tests for deterministic READY and BLOCKED plans, prerequisite ordering, exact
  trace preservation, input immutability, malformed contracts, and report attribution.
- [x] Implement `engine/narrative_planner.py` and make the tests GREEN.

### 2. Gold Set shadow comparison

- [x] Write RED tests for Paper and Report, including all six Production failures.
- [x] Implement `engine/narrative_shadow_compare.py` and deterministic fixture expectations.
- [x] Prove the comparator cannot claim narration/directive/render/retention improvement.

### 3. Review and delivery

- [x] Run adjacent and full verification.
- [x] Perform adversarial Fable Review and fix blocking findings test-first.
- [x] Push and open a Draft PR; do not merge.
