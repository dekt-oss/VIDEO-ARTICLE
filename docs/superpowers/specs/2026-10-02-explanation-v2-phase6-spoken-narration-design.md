# Explanation Engine v2 Phase 6 Spoken Narration — Design

**Date:** 2026-10-02

**Base:** Phase 5 Draft PR #93, head `eefc52e21660d41674da62dc59fc33b44e5c7ae9`

**Canonical requirement:** `docs/작업지시서_ExplanationEngine_v2.md` section 8

## 1. Goal

Turn a validated `READY` Narrative Plan into short Korean spoken narration without reopening the
unrestricted source or inventing new reasoning. Keep the result shadow-only so the current Paper and
Report script paths remain unchanged.

Phase 6 measures narration structure and deterministic safety signals. It does not claim clause-level
semantic entailment; that belongs to Phase 7.

## 2. Selected approach

Use a constrained model draft followed by deterministic normalization and an independent spoken
polish pass.

Alternatives rejected:

- Rule templates are safer but cannot establish whether spoken naturalness improves.
- Extending the existing Production script prompt would mix Phase 6 evaluation with current scene and
  directive behavior and would let the model reread broader source material.

## 3. Inputs and trust boundary

Required inputs:

- `evidence-pack-v1`
- `explanation-ir-v1`
- `prerequisite-resolution-v1`
- `narrative-plan-v1`

All four contracts are revalidated at the Phase 6 boundary. Only
`planning_status=READY` is accepted. `BLOCKED_PREREQUISITE` and `BLOCKED_NO_REASONING` return a blocked
result before any model call.

The model receives only:

- core question and thesis
- ordered narrative beats
- each beat's approved content points
- prerequisite explanations from the plan and guardrails from the validated resolution
- causal level, uncertainty, attribution, and transition relation carried by the plan

It does not receive full source text, arbitrary Fact Sheet fields, current Production scripts, or
legacy directives.

## 4. Draft contract

The model may return only `beat_id` and Korean spoken sentences. Code injects all IDs and provenance;
the model cannot author them.

```yaml
contract_version: spoken-narration-v1
domain: paper|report
content_id: string
generation_status: DRAFT_ACCEPTED|REJECTED_DRAFT|BLOCKED_UPSTREAM
core_question: string
narration_beats:
  - narration_id: SN01
    beat_id: NB01
    stage: HOOK|SETUP|CONFLICT|EXPLANATION|EVIDENCE|PAYOFF|BOUNDARY
    sentences: [string]
    reasoning_ids: [string]
    evidence_ids: [string]
    raw_refs: [string]
    concept_ids: [string]
    knowledge_refs: [string]
    causal_levels: [string]
    uncertainties: [string]
    attributions: [string]
qa:
  semantic_entailment: NOT_CHECKED
  errors: [string]
  warnings: [string]
  metrics: {}
polish: {}
```

Every Narrative Plan beat appears exactly once and in the same order. Empty, unknown, duplicated, or
missing beat IDs reject the draft.

`DRAFT_ACCEPTED` means only that Phase 6 deterministic guards passed. It does not mean the narration is
semantically entailed, publishable, or Production-ready. Phase 7 is the first stage allowed to change
`semantic_entailment` from `NOT_CHECKED`.

## 5. Deterministic draft guards

The first draft is rejected when any of these occur:

- the model changes, drops, or invents numeric values or units relative to the beat content
- a scope intensifier such as `모든`, `유일`, `항상`, `절대`, `오직`, `최초`, `전부`, `완전히`,
  or `반드시` appears without already being present in the approved content
- association language is replaced by determination or direct-cause language
- negation, uncertainty, or scope qualifiers disappear
- a Report beat with broker attribution drops that attribution
- a factual beat has no reasoning/evidence/knowledge trace
- a rhetorical hook introduces a factual assertion instead of asking the approved core question

The following are warnings, not Phase 6 semantic proof:

- sentence longer than the configured spoken-length target
- repeated core question
- too many spoken numbers
- untranslated or unexplained abbreviation
- nominal/academic register heuristics

Phase 8 will turn the relevant complexity warnings into regeneration or blocking actions.

## 6. Spoken polish

Polish is a separate pass and receives only the accepted first draft. It may change Korean expression,
sentence breaks, and connective phrasing, but not approved meaning.

For each beat, reuse `engine.script_polish.rejection_reason()` as a conservative guard. A rejected
polish candidate leaves the accepted first-draft text unchanged and records the rejection reason.
No Production `script_polish.py` behavior is modified in this phase.

## 7. Model and cost boundary

The implementation exposes pure prompt, normalize, validate, and apply-polish functions. The shadow
generator uses the existing `call_json` adapter, but automated tests use deterministic returned
payloads and never call an external model.

No live Gold Set generation, paid model call, DB write, or Production regeneration is part of the
implementation PR. A live same-source sample is a separate, explicitly approved validation step.

## 8. Shadow comparison

Phase 6 compares the stored Gold Set findings with machine-checkable narration properties:

- plan/beat coverage
- stable reasoning/evidence/raw-ref trace
- prerequisite before terminology
- rhetorical hook grounding
- preserved attribution, qualifier, association, negation, and numbers
- spoken-length and repetition warnings

It must report `semantic_entailment=not_measured` and
`final_directive_quality=not_measured`. No aggregate improvement percentage is allowed.

The existing Gold Set currently permits a generated READY narration only for Personality GWAS. The
other five cases remain upstream-blocked and are evaluated for correct fail-closed behavior, not prose
quality.

## 9. Production boundary and rollout

- Do not modify `engine/scriptgen.py`, `engine/report_scriptgen.py`, current prompts, Supabase, DB,
  directive generation, approval, render, or publish paths.
- Do not add a feature flag yet because there is no Production consumer.
- Persist nothing; the Phase 6 artifact is an in-memory shadow result.
- Open a stacked Draft PR based on the Phase 5 branch. Do not merge it automatically.

## 10. Verification and comparison milestones

Phase 6 completion enables deterministic and reviewer-visible comparison of current narration findings
against the V2 narration artifact. It does not yet validate the final directive.

- Phase 7: defensible Source/Evidence vs final narration comparison using clause-level fidelity QA.
- Phase 9: direct legacy directive vs V2 directive comparison after reasoning IDs reach existing Visual
  Stages and mutations.
- Phase 11: rendered output comparison.
- Phase 13–14: integrated publish gate and real A/B analytics.

## 11. Rollback

Remove the Phase 6-only module, tests, fixtures, and documentation. Because there is no persistence or
Production wiring, no data rollback is required.

## 12. Acceptance criteria

- READY plans produce deterministic normalized shape for identical model payloads.
- Blocked plans cause zero model calls.
- Model-authored IDs are impossible; all refs are copied from the validated plan.
- Missing/duplicated/reordered beats fail closed.
- Numeric, scope, association, negation, uncertainty, and attribution drift are detected.
- Unsafe polish is rejected without altering the accepted draft.
- Paper and Report contract tests pass.
- All six Gold Set cases have deterministic expected status.
- Production paths remain byte-for-byte unchanged by this phase.
- Full Python, Web tests, TypeScript, lint, build, CI, and adversarial review pass before delivery.
