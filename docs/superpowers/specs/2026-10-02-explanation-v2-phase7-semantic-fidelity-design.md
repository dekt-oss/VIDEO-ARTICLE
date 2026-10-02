# Explanation Engine v2 Phase 7 Semantic Fidelity QA — Design

**Date:** 2026-10-02

**Base:** Phase 6 Draft PR #94, head `6274cb0a5cca2950ae355e9e2cef9e9173077a77`

**Canonical requirement:** `docs/작업지시서_ExplanationEngine_v2.md` section 9

## 1. Goal

Add a shadow-only, clause-level semantic fidelity gate after `spoken-narration-v1`. The gate compares
each narration clause with the exact Evidence Pack items and Explanation IR units carried through the
validated Narrative Plan. It must fail closed on incomplete critic output, unsupported factual hooks,
scope expansion, causal upgrades, missing qualifiers, contradictions, and unsupported background.

Phase 7 does not alter current Paper or Report script generation, directives, approval, render, or
publish behavior. A passed Phase 7 artifact means the independent critic contract and deterministic
coverage gate accepted the narration; it is not a Production or final-video quality claim.

## 2. Selected approach

Use one independent structured critic call inside a deterministic validation envelope.

The critic performs the semantic judgment that string rules cannot reliably make. Code owns all IDs,
limits which evidence the critic may cite, verifies exact clause coverage, recomputes the aggregate
status, and rejects malformed or incomplete judgments. The writer's Phase 6 call and the Phase 7 critic
call have separate prompts, purposes, and model invocations.

Alternatives rejected:

- Deterministic rules only: useful for numbers and lexical red flags, but unable to judge paraphrased
  contradiction, invented mechanism, or unsupported replacement claims.
- Two-critic consensus: stronger but adds cost and adjudication complexity before one-critic shadow
  evidence exists. Revisit only after live false-positive and false-negative measurements.
- Extending the existing Production self-check: it would mix Phase 7 evaluation with legacy scene
  exemptions and warning-only approval behavior, and would change Production before shadow evidence.

## 3. Inputs and trust boundary

Required inputs:

- validated `evidence-pack-v1`
- validated `explanation-ir-v1`
- validated `prerequisite-resolution-v1`
- canonical `narrative-plan-v1`
- validated `spoken-narration-v1`

Only `generation_status=DRAFT_ACCEPTED` is critic-eligible. `BLOCKED_UPSTREAM` remains blocked without a
critic call. `REJECTED_DRAFT` is rejected upstream without a critic call. All five upstream contracts
are revalidated at the Phase 7 boundary, including canonical plan reconstruction and current Phase 6
guard recomputation.

The critic receives only the accepted narration, its beat-owned trace, the corresponding IR units, and
the referenced Evidence Pack items. It does not receive unrestricted full text, unrelated Fact Sheet
items, Production scripts, legacy directives, or permission to add IDs.

`verification_state=SUPPORTED` is never treated as blanket truth. The prompt includes
`verification_scope`, `source_refs`, causal strength, uncertainty, attribution, and raw references so
the critic can distinguish quote presence from semantic entailment. Evidence with `UNSUPPORTED` or
`STALE` state cannot support a passed factual clause. `NOT_CHECKED` and
`UNVERIFIABLE_AT_CURRENT_DEPTH` may be inspected but cannot produce an entailed gate result without
source material that directly supports the clause.

## 4. Clause contract

The model returns only judgments. Code assigns `SCxx` IDs and copies all provenance.

```yaml
contract_version: semantic-fidelity-v1
domain: paper|report
content_id: string
qa_status: PASSED|REJECTED|BLOCKED_UPSTREAM|REJECTED_UPSTREAM|CRITIC_ERROR
critic:
  independence: separate_call
  semantic_entailment: PASSED|FAILED|NOT_CHECKED
clauses:
  - clause_id: SC01
    narration_id: SN01
    beat_id: NB01
    sentence_index: 1
    clause_text: string
    clause_kind: FACTUAL|RHETORICAL
    verdict: ENTAILED|CONTRADICTED|UNSUPPORTED|UNVERIFIABLE|RHETORICAL
    evidence_ids: [string]
    reasoning_ids: [string]
    raw_refs: [string]
    finding_codes: [string]
    rationale: string
qa:
  errors: [string]
  warnings: [string]
  metrics: {}
```

Allowed finding codes are closed and minimal:

- `contradiction`
- `scope_expansion`
- `causal_upgrade`
- `missing_qualifier`
- `unsupported_background`
- `attribution_loss`
- `unsupported_factual_hook`

The critic payload returns `narration_id`, `sentence_index`, exact clause text, clause kind, verdict,
chosen evidence IDs, finding codes, and rationale. Code assigns clause IDs; resolves the beat; copies
reasoning IDs; and rebuilds raw refs from the canonical artifacts. The critic cannot author clause IDs,
beat IDs, reasoning IDs, or raw refs, and it cannot cite evidence outside the input trace. Unknown or
out-of-beat references are contract errors, not warnings.

## 5. Exact clause coverage

Clause-level review must not omit the unsafe half of a sentence. For every narration sentence, the
critic returns ordered `clause_text` spans copied exactly from that sentence. Code normalizes only
whitespace and punctuation and requires the ordered clause spans to cover the complete normalized
sentence exactly once.

The following fail closed:

- a sentence with no clause judgment
- omitted, duplicated, reordered, or invented clause text
- a clause attributed to another sentence or beat
- duplicate or missing narration coverage
- empty rationale on a non-entailed verdict

Code does not attempt to solve Korean semantic segmentation itself. It verifies the critic's proposed
segmentation is lossless; semantic judgment remains the critic's responsibility.

## 6. Verdict and aggregation rules

A factual clause passes only when all of these are true:

- verdict is `ENTAILED`
- at least one cited Evidence Pack item belongs to the narration beat's evidence trace
- every cited Evidence Pack ID exists and is allowed for positive use
- no finding code is present
- reasoning IDs, evidence IDs, and raw refs match the canonical upstream artifacts
- Paper association-only, Report projection/opinion, uncertainty, qualifier, and attribution strength
  are not upgraded

`CONTRADICTED`, `UNSUPPORTED`, and `UNVERIFIABLE` all reject the shadow narration. They remain separate
in the artifact so verification failure is not confused with lack of evidence.

`RHETORICAL` passes only for a HOOK clause that is a pure question, contains no factual assertion, cites
no evidence, and remains grounded in the approved core question. A factual hook follows the same
evidence and entailment rules as every other factual clause.

The aggregate status is recomputed by code:

- `PASSED`: every factual clause is entailed and every rhetorical clause satisfies the hook exception
- `REJECTED`: any clause has a semantic failure or deterministic semantic guard failure
- `BLOCKED_UPSTREAM`: Phase 6 emitted no narration because its own upstream plan was blocked
- `REJECTED_UPSTREAM`: Phase 6 produced a draft but rejected it before semantic review
- `CRITIC_ERROR`: caller failure, malformed JSON shape, invalid coverage, invalid references, or missing
  judgments

Stored aggregate status, metrics, and error arrays are never trusted during validation.

## 7. Independent critic call

Use the existing `call_json` adapter with a distinct text-purpose label such as
`semantic_fidelity_shadow`. Default to the existing self-check model configuration rather than the
script-writing model configuration. Tests inject a deterministic caller and perform no external call.

Independence means a separate call with no writer conversation or self-reported Phase 6 QA verdict. It
does not yet mean a second provider or two-model consensus. The artifact records this boundary as
`independence=separate_call`.

Caller exceptions and invalid payloads return `CRITIC_ERROR`; they do not silently downgrade to a
warning or preserve `DRAFT_ACCEPTED` as a semantic pass.

## 8. Deterministic pre-guards

Phase 7 reruns the Phase 6 deterministic guards before invoking the critic and after normalizing the
critic output. This catches status or sentence tampering and prevents a critic from overriding known
numeric, scope-token, qualifier, association, projection, attribution, or hook failures.

Additional deterministic rules enforce:

- cited evidence is a subset of the current beat-owned evidence IDs
- cited reasoning IDs are a subset of the current beat-owned reasoning IDs
- raw refs are rebuilt from Evidence Pack and IR, never accepted from the critic
- positive clauses cannot cite `UNSUPPORTED` or `STALE` evidence
- rhetorical exemptions cannot appear outside HOOK
- no accepted factual clause is left without trace

## 9. Shadow comparison and Gold Set

The Phase 7 comparator reports only machine-observed properties:

- full sentence-to-clause coverage
- evidence and reasoning trace integrity
- clause verdict distribution
- scope, causal, qualifier, attribution, contradiction, and background findings
- factual versus rhetorical hook treatment
- fail-closed behavior for blocked upstream cases

It must not report final directive quality, rendered-video quality, or an aggregate improvement
percentage.

Gold Set regression includes the six canonical failures:

- Heel strike: an exclusivity clause cannot pass without explicit exclusive evidence.
- Retinotopic remapping: cross-sensory transfer is unsupported by visual-system redistribution evidence.
- Personality GWAS: association cannot entail determination.
- Samsung report: the narration-to-reasoning/evidence link remains stable or fails closed upstream.
- NH Mid Cycle: shallow-source blocked narration never calls the critic.
- Shipbuilding: opportunity/pipeline evidence cannot entail current replacement.

Because five current cases are already blocked before narration, deterministic tests prove zero critic
calls for those artifacts. Separate accepted synthetic narration fixtures reproduce their semantic
failure forms so critic normalization and aggregation are exercised without claiming that a mocked
critic proves real model recall.

## 10. File and Production boundary

Expected Phase 7 changes:

- create `engine/semantic_fidelity.py`
- create `engine/semantic_fidelity_shadow_compare.py`
- create `tests/test_semantic_fidelity.py`
- create Phase 7 contract and implementation documentation

Do not modify:

- `engine/scriptgen.py`
- `engine/report_scriptgen.py`
- current Production self-check modules or prompts
- directive, approval, render, publish, web, Supabase, or DB paths
- existing Phase 6 normalization behavior

The first Phase 7 PR is stacked on Phase 6, remains Draft, persists nothing, and is not merged
automatically.

## 11. Error handling

- Invalid upstream artifacts raise a deterministic boundary error before critic invocation.
- Blocked narration returns `BLOCKED_UPSTREAM`; rejected narration returns `REJECTED_UPSTREAM`; both
  cause zero critic calls.
- Critic transport or parse failure becomes `CRITIC_ERROR` with no passed clauses.
- Malformed clause coverage or illegal references becomes `CRITIC_ERROR`.
- Semantically negative or unverifiable judgments become `REJECTED`, not `CRITIC_ERROR`.
- Input artifacts are never mutated.

## 12. Verification

- TDD for normalization, exact coverage, reference restrictions, aggregation, and caller failure
- Paper and Report happy-path fixtures
- adversarial scope, causality, qualifier, projection, attribution, and hook fixtures
- all six Gold Set cases with explicit blocked-versus-evaluated expectations
- adjacent Phase 2–7 contract tests
- full Python pytest
- Web Node tests
- TypeScript typecheck
- lint
- production build
- `git diff --check`
- independent Fable Review focused on critic omission, reference laundering, stale QA reuse, and false
  rhetorical exemptions

Live critic accuracy, paid model behavior, Production source-to-approval behavior, directive comparison,
and rendered-video comparison remain explicitly unverified.

## 13. Rollback

Remove the Phase 7-only modules, tests, and documentation. There is no persistence, migration, feature
flag, or Production consumer, so no data rollback is required.

## 14. Acceptance criteria

- Identical accepted inputs and critic payloads produce deterministic byte-equivalent artifacts.
- Blocked or rejected upstream narration causes zero critic calls and retains its distinct state.
- Every narration sentence is covered exactly once by ordered critic clauses.
- Every factual clause has valid beat-owned evidence and reasoning trace.
- Unsupported/stale evidence cannot produce an entailed clause.
- Rhetorical exemption is limited to pure grounded HOOK questions.
- Scope expansion, causal upgrade, qualifier loss, contradiction, unsupported background, attribution
  loss, and factual-hook failures remain distinct.
- Aggregate QA status is code-derived and stale stored QA cannot forge a pass.
- Gold Set representative failures cannot produce a Phase 7 pass under their expected fixtures.
- Production paths remain unchanged.
- Full local verification, CI, and adversarial review complete before delivery.
