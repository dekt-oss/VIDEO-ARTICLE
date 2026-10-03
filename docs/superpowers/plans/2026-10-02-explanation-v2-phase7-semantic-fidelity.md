# Explanation Engine v2 Phase 7 Semantic Fidelity QA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a shadow-only independent critic that checks every accepted narration clause against eligible Evidence Pack support and fails closed on semantic drift without changing Production output.

**Architecture:** `engine/semantic_fidelity.py` owns the constrained critic payload, upstream boundary, clause coverage, provenance reconstruction, deterministic aggregation, validation, and injected critic call. `engine/semantic_fidelity_shadow_compare.py` reports only Phase 7 contract observations against the fixed Gold Set. The critic chooses semantic verdicts and beat-owned evidence citations; code owns identity, trace, support eligibility, coverage, and final status.

**Tech Stack:** Python 3, pytest, existing `engine.llm.call_json`, `engine.config.MODEL_SELFCHECK`, Explanation Engine v2 contracts from Phases 2–6.

**Spec:** `docs/superpowers/specs/2026-10-02-explanation-v2-phase7-semantic-fidelity-design.md`

## Global Constraints

- Shadow-only: do not modify `engine/scriptgen.py`, `engine/report_scriptgen.py`, Production self-check prompts/modules, directive, approval, render, publish, web, Supabase, or DB paths.
- Do not persist Phase 7 artifacts or make a live/paid model call in tests or implementation verification.
- Revalidate Evidence Pack, Explanation IR, prerequisite resolution, canonical Narrative Plan, and Spoken Narration at the Phase 7 boundary.
- `BLOCKED_UPSTREAM` and `REJECTED_UPSTREAM` cause zero critic calls and remain distinct.
- `SUPPORTED` never means full semantic truth; positive support requires a direct source span, verified structured numeric surface, or prior `semantic_entailment=true`.
- Code assigns clause IDs, resolves beat identity, copies canonical reasoning/prerequisite trace, and rebuilds raw refs.
- Every narration sentence must be covered exactly once by ordered critic clauses after whitespace-only normalization; meaning-bearing punctuation, numeric signs, decimals, and units remain exact.
- `PASSED` is a Phase 7 shadow-contract result, not Production readiness, directive quality, or rendered-video quality.
- Open a stacked Draft PR against `codex/explanation-v2-phase6-spoken-narration`; do not merge automatically.

## Review Focus

- A critic that omits only the unsafe second clause must produce `CRITIC_ERROR`, never `PASSED`; Task 2 adds `test_clause_coverage_rejects_omitted_or_reordered_text`.
- A critic must not launder `UNSUPPORTED`, `STALE`, quote-presence-only, or another beat's evidence into an entailed clause; Task 2 adds `test_entailed_clause_requires_eligible_beat_owned_support`.
- A factual assertion disguised as `RHETORICAL` must be rejected even inside HOOK; Task 2 adds `test_rhetorical_exemption_is_only_for_pure_grounded_hook_question`.
- Stored `qa_status`, semantic-entailment summary, errors, warnings, and metrics must not forge a pass after clause mutation; Task 2 adds `test_validate_recomputes_status_metrics_and_trace`.
- A blocked/rejected narration or critic exception must not call again, leak a partial pass, or collapse failure states; Task 3 adds `test_upstream_nonaccepted_states_never_call_critic` and `test_critic_exception_returns_error_without_passed_clauses`.

---

### Task 1: Phase 7 boundary and constrained critic payload

**Files:**
- Create: `engine/semantic_fidelity.py`
- Create: `tests/test_semantic_fidelity.py`

**Interfaces:**
- Consumes: `spoken_narration.validate(narration, plan, ir, resolution, pack) -> list[str]`, `narrative_planner.build(ir, resolution, pack) -> dict`, `explanation_ir.build_index(pack) -> dict`.
- Produces: `prompt_payload(narration, plan, ir, resolution, pack) -> dict` and Phase 7 closed enums.

- [x] **Step 1: Write literal fixtures and failing prompt-boundary tests**

  Create self-contained Paper and Report fixtures with complete Evidence Pack shapes, IR, prerequisite resolution, canonical plan, and Phase 6 narration. The Paper evidence must include a real `source_refs` quote; the Report number must set `numeric_value`, `unit`, and `period` verification scopes to true.

  Add tests that malformed/tampered upstream artifacts raise `ValueError`, input objects remain unchanged,
  and an accepted narration produces a prompt containing only its beat-owned IR units/evidence items and
  no unrelated pack item. Assert the prompt preserves `verification_scope`, source spans, structured
  numeric fields, causal level, uncertainty, attribution, and prerequisite guardrails.

- [x] **Step 2: Run Task 1 tests and confirm RED**

  Run: `python -m pytest tests/test_semantic_fidelity.py -q -k 'boundary or prompt or immutable'`

  Expected: collection/import failure because `engine.semantic_fidelity` does not exist.

- [x] **Step 3: Implement the minimal boundary and prompt**

  Implement these exact constants:

  ```python
  CONTRACT_VERSION = "semantic-fidelity-v1"
  QA_STATUSES = frozenset({
      "PASSED", "REJECTED", "BLOCKED_UPSTREAM", "REJECTED_UPSTREAM", "CRITIC_ERROR",
  })
  VERDICTS = frozenset({
      "ENTAILED", "CONTRADICTED", "UNSUPPORTED", "UNVERIFIABLE", "RHETORICAL",
  })
  FINDING_CODES = frozenset({
      "contradiction", "scope_expansion", "causal_upgrade", "missing_qualifier",
      "unsupported_background", "attribution_loss", "unsupported_factual_hook",
  })

  ```

  Add `prompt_payload(narration, plan, ir, resolution, pack) -> dict`. Revalidate the canonical upstream
  chain before constructing the payload. The model-visible prompt contains ordered narration sentences,
  beat-owned metadata, the corresponding IR units, prerequisite concepts, and only referenced Evidence
  Pack items including verification state/scope, structured numeric fields, and source refs.

- [x] **Step 4: Run boundary tests and confirm GREEN**

  Run: `python -m pytest tests/test_semantic_fidelity.py -q -k 'boundary or prompt or immutable'`

  Expected: all selected tests pass and caller count remains zero for both nonaccepted states.

- [x] **Step 5: Commit Task 1**

  Run: `git add -- engine/semantic_fidelity.py tests/test_semantic_fidelity.py && git commit -m "feat: add Phase 7 semantic fidelity boundary"`

---

### Task 2: Lossless clause normalization, provenance, and fail-closed aggregation

**Files:**
- Modify: `engine/semantic_fidelity.py`
- Modify: `tests/test_semantic_fidelity.py`

**Interfaces:**
- Consumes: Task 1 validated prompt boundary and critic payload rows.
- Produces: `normalize_review(payload, narration, plan, ir, resolution, pack) -> dict`, `validate(result, narration, plan, ir, resolution, pack) -> list[str]`.

- [x] **Step 1: Write failing accepted-clause shape and coverage tests**

  The critic payload is flat and contains only judgment fields:

  ```python
  payload = {
      "clauses": [{
          "narration_id": "SN01",
          "sentence_index": 1,
          "clause_text": "변이는 성격을 결정하는가?",
          "clause_kind": "RHETORICAL",
          "verdict": "RHETORICAL",
          "evidence_ids": [],
          "finding_codes": [],
          "rationale": "핵심 질문만 제시한다.",
      }]
  }
  ```

  Add a complete literal payload for every sentence and assert sequential `SC01`, `SC02`, and subsequent
  identity, canonical beat/reasoning/concept/knowledge trace, Evidence Pack-derived raw refs,
  deterministic metrics, input immutability, and byte-equivalent output for repeated normalization.

  Add `test_clause_coverage_rejects_omitted_or_reordered_text` with three literal mutations: omit the unsafe suffix, reverse two clause rows, and duplicate one clause. Each must return `CRITIC_ERROR` with a coverage error and no `PASSED` semantic summary.

- [x] **Step 2: Run shape/coverage tests and confirm RED**

  Run: `python -m pytest tests/test_semantic_fidelity.py -q -k 'normalize or coverage or deterministic'`

  Expected: failure because `normalize_review` and `validate` are absent.

- [x] **Step 3: Implement lossless coverage and canonical provenance**

  Add public functions `normalize_review(payload, narration, plan, ir, resolution, pack) -> dict` and
  `validate(result, narration, plan, ir, resolution, pack) -> list[str]`. Normalize only whitespace for coverage
  with `re.sub(r"\s+", "", text)` so punctuation, numeric signs, decimals, and units remain meaning-bearing. Group rows by exact
  `(narration_id, sentence_index)`, preserve row order, and require concatenated normalized clauses to
  equal the normalized source sentence exactly once. Code assigns sequential clause IDs, resolves
  `beat_id`, copies reasoning/concept/knowledge refs from narration, validates chosen evidence is
  beat-owned, and rebuilds raw refs from the Evidence Pack index. Invalid shape, IDs, enum values,
  coverage, or references yield `CRITIC_ERROR`.

- [x] **Step 4: Run shape/coverage tests and confirm GREEN**

  Run: `python -m pytest tests/test_semantic_fidelity.py -q -k 'normalize or coverage or deterministic'`

  Expected: all selected tests pass.

- [x] **Step 5: Write failing support, hook, finding, and stale-QA tests**

  Add literal table-driven cases pairing `CONTRADICTED` with `contradiction`, `UNSUPPORTED` with
  `unsupported_background`, and `UNVERIFIABLE` with `missing_qualifier`. For each literal critic
  payload assert `qa_status == "REJECTED"`, semantic entailment is `FAILED`, the final clause retains
  the input verdict, and its finding list retains the expected code.

  Add `test_entailed_clause_requires_eligible_beat_owned_support` covering `UNSUPPORTED`, `STALE`, quote-presence-only without source span, and a valid evidence ID owned by another beat. The first three are semantic rejection; the cross-beat citation is `CRITIC_ERROR`.

  Add `test_rhetorical_exemption_is_only_for_pure_grounded_hook_question` covering a pure core question pass, factual suffix, non-HOOK rhetorical label, and evidence-citing rhetorical label.

  Add the canonical failure forms with explicit expected codes: Heel Strike -> `scope_expansion`; retinotopic cross-sensory transfer -> `unsupported_background`; Personality determination -> `causal_upgrade`; Shipbuilding current replacement -> `unsupported_background`; Report projection without broker attribution -> `attribution_loss`.

  Add `test_validate_recomputes_status_metrics_and_trace`: mutate a passed artifact's verdict, evidence ID, stored status, semantic summary, and metrics one at a time; `validate` must report stale/invalid derived fields.

- [x] **Step 6: Run semantic gate tests and confirm RED**

  Run: `python -m pytest tests/test_semantic_fidelity.py -q -k 'support or rhetorical or semantic or scope or causal or attribution or recomputes'`

  Expected: unsafe critic judgments are accepted, support eligibility is not enforced, or stale aggregates are trusted.

- [x] **Step 7: Implement support eligibility and aggregation**

  Implement support eligibility with this conservative helper:

  ```python
  def _eligible_support(item: dict, section: str) -> bool:
      if item.get("verification_state") in {"UNSUPPORTED", "STALE"}:
          return False
      scope = item.get("verification_scope") or {}
      has_source_span = any(
          isinstance(ref, dict) and str(ref.get("quote") or "").strip()
          for ref in item.get("source_refs") or []
      )
      if has_source_span or scope.get("semantic_entailment") is True:
          return True
      if section != "numbers" or scope.get("numeric_value") is not True:
          return False
      return (
          (not str(item.get("unit") or "").strip() or scope.get("unit") is True)
          and (not str(item.get("period") or "").strip() or scope.get("period") is True)
      )
  ```

  Require `ENTAILED` factual clauses to cite eligible beat-owned evidence and contain no finding. Permit an empty reasoning list only for canonical SETUP beats with concept and knowledge trace. Permit `RHETORICAL` only for a HOOK pure question whose normalized text is covered by the approved core question, with no evidence or finding. Derive `PASSED` only when every clause passes; derive `REJECTED` for semantic failures or ineligible positive support. Recompute error/warning arrays, verdict counts, clause/sentence counts, and semantic summary inside both normalization and validation.

- [x] **Step 8: Run all Task 2 tests and commit**

  Run: `python -m pytest tests/test_semantic_fidelity.py -q`

  Expected: all Task 1–2 tests pass.

  Commit: `feat: enforce Phase 7 clause fidelity contract`

---

### Task 3: Independent critic invocation and caller-failure hardening

**Files:**
- Modify: `engine/semantic_fidelity.py`
- Modify: `tests/test_semantic_fidelity.py`

**Interfaces:**
- Consumes: Task 1 `prompt_payload`, Task 2 `normalize_review`, `llm.call_json`, `llm.set_text_purpose`, `config.MODEL_SELFCHECK`, `config.LLM_SELFCHECK_MAX_TOKENS`.
- Produces: `_empty_result(narration, status, *, errors=None) -> dict` and complete `review(narration, plan, ir, resolution, pack, *, caller=None)` independent-critic wrapper.

- [x] **Step 1: Write failing upstream-state, invocation, and error tests**

  Add this complete upstream-state test before the exception test:

  ```python
  def test_upstream_nonaccepted_states_never_call_critic():
      blocked_pack, blocked_ir, blocked_resolution, blocked_plan, blocked = (
          _blocked_paper_artifacts()
      )
      calls = []
      result = semantic_fidelity.review(
          blocked, blocked_plan, blocked_ir, blocked_resolution, blocked_pack,
          caller=lambda **kwargs: calls.append(kwargs),
      )
      assert result["qa_status"] == "BLOCKED_UPSTREAM"

      pack, ir, resolution, plan, accepted = _paper_artifacts()
      rejected = spoken_narration.normalize_draft(
          {"beats": [{"beat_id": beat["beat_id"], "sentences": []}
                     for beat in plan["beats"]]},
          plan, ir, resolution, pack,
      )
      result = semantic_fidelity.review(
          rejected, plan, ir, resolution, pack,
          caller=lambda **kwargs: calls.append(kwargs),
      )
      assert result["qa_status"] == "REJECTED_UPSTREAM"
      assert calls == []
  ```

  Capture accepted-input caller arguments and assert model=`config.MODEL_SELFCHECK`, purpose is set to
  `semantic_fidelity_shadow`, input JSON contains only the constrained prompt payload, and the returned
  payload is normalized rather than trusted.

  ```python
  def test_critic_exception_returns_error_without_passed_clauses():
      pack, ir, resolution, plan, narration = _paper_artifacts()

      def boom(**kwargs):
          raise RuntimeError("critic unavailable")

      result = semantic_fidelity.review(
          narration, plan, ir, resolution, pack, caller=boom,
      )
      assert result["qa_status"] == "CRITIC_ERROR"
      assert result["critic"]["semantic_entailment"] == "NOT_CHECKED"
      assert result["clauses"] == []
      assert result["qa"]["errors"] == ["critic_call_failed:RuntimeError"]
  ```

  Add malformed `None`, list, missing-clauses, and non-list-clauses payloads. They must return deterministic `CRITIC_ERROR` results, not raise after the upstream boundary succeeds.

- [x] **Step 2: Run invocation tests and confirm RED**

  Run: `python -m pytest tests/test_semantic_fidelity.py -q -k 'critic or invocation or malformed'`

  Expected: caller errors escape or model/purpose/payload assertions fail.

- [x] **Step 3: Complete the independent critic wrapper**

  Set purpose immediately before invocation. Use the injected caller or `call_json`; pass `MODEL_SELFCHECK`, the closed JSON system prompt, sorted Korean-preserving JSON user payload, and `LLM_SELFCHECK_MAX_TOKENS`. Catch `Exception` only around the external call and return `_critic_error("critic_call_failed:<ClassName>")`. Send successful output through `normalize_review`; never accept model-authored aggregate status or provenance.

- [x] **Step 4: Run Task 3 and adjacent Phase 6 tests**

  Run: `python -m pytest tests/test_semantic_fidelity.py tests/test_spoken_narration.py -q`

  Expected: all selected tests pass without network access.

- [x] **Step 5: Commit Task 3**

  Commit: `test: harden Phase 7 independent critic failures`

---

### Task 4: Shadow comparison, Gold Set accounting, documentation, and delivery

**Files:**
- Create: `engine/semantic_fidelity_shadow_compare.py`
- Modify: `tests/test_semantic_fidelity.py`
- Create: `docs/phase7_ExplanationEngine_v2_semantic_fidelity.md`
- Modify: `docs/superpowers/plans/2026-10-02-explanation-v2-phase7-semantic-fidelity.md`

**Interfaces:**
- Consumes: Task 2 validated `semantic-fidelity-v1`, stored Gold Set cases, Phase 3–6 fixture chain.
- Produces: `semantic_fidelity_shadow_compare.compare(legacy_case, fidelity, narration, plan, ir, resolution, pack) -> dict`, final Phase 7 documentation, stacked Draft PR.

- [x] **Step 1: Write failing comparator and six-case tests**

  Assert legacy case identity/domain/findings validation. For evaluated artifacts, report axes `clause_coverage`, `stable_trace`, `semantic_entailment`, `scope_calibration`, `causal_calibration`, `qualifier_preservation`, `attribution_preservation`, and `hook_grounding`. For blocked/rejected upstream artifacts, report the exact upstream outcome rather than a prose-quality pass.

  The six Gold Set expectations are literal:

  ```python
  assert statuses == {
      "heel-strike-2026-09": "BLOCKED_UPSTREAM",
      "deaf-retinotopic-remap-2026-09": "BLOCKED_UPSTREAM",
      "personality-gwas-2026-09": "REJECTED",
      "samsung-memory-cycle-2026-09": "BLOCKED_UPSTREAM",
      "nh-ai-mid-cycle-2026-09": "BLOCKED_UPSTREAM",
      "shipbuilding-rerating-2026-09": "BLOCKED_UPSTREAM",
  }
  assert critic_call_counts == {
      "heel-strike-2026-09": 0,
      "deaf-retinotopic-remap-2026-09": 0,
      "personality-gwas-2026-09": 1,
      "samsung-memory-cycle-2026-09": 0,
      "nh-ai-mid-cycle-2026-09": 0,
      "shipbuilding-rerating-2026-09": 0,
  }
  ```

  Personality remains `REJECTED` in deterministic fixtures when its Evidence Pack has quote-presence verification but no source span or prior semantic-entailment proof. This is an intentional fail-closed result, not a claim that the live critic found an error.

  Separately exercise the four accepted synthetic failure forms from Task 2 with fixed critic payloads, and prohibit `improvement_percent`, `final_directive_quality=passed`, or rendered-quality claims.

- [x] **Step 2: Run comparison tests and confirm RED**

  Run: `python -m pytest tests/test_semantic_fidelity.py -q -k 'shadow or gold or comparison'`

  Expected: failure because `semantic_fidelity_shadow_compare` does not exist.

- [x] **Step 3: Implement the shadow comparator**

  Revalidate every supplied artifact and recompute the observed axes from normalized clauses. Use `passed`, `failed`, `blocked_upstream`, `rejected_upstream`, or `critic_error` outcomes with evidence arrays. Always report `final_directive_quality=not_measured` and omit aggregate percentages.

- [x] **Step 4: Run Phase 2–7 adjacent tests and commit functional regressions**

  Run: `python -m pytest tests/test_semantic_fidelity.py tests/test_spoken_narration.py tests/test_narrative_planner.py tests/test_prerequisite_resolver.py tests/test_explanation_ir.py tests/test_evidence_pack.py -q`

  Expected: all selected tests pass.

  Commit: `test: add Phase 7 semantic fidelity shadow regressions`

- [x] **Step 5: Document the contract and honest comparison boundary**

  Document current problem, architecture, input/output/status contracts, support-surface eligibility, clause coverage, critic independence level, Gold Set results, zero-call blocked cases, Production boundary, rollback, and unverified live-model/directive/render behavior. Explicitly state that mocked critic payloads prove contract behavior, not critic recall or improved final video quality.

- [x] **Step 6: Run full local verification**

  Run targeted Phase 7 tests, adjacent Phase 2–7 tests, full Python `pytest`, Web Node tests, TypeScript `tsc --noEmit --incremental false`, lint, production build, and `git diff --check`.

  Expected: zero test/build failures. Record existing tool deprecation or module-type warnings without changing unrelated configuration.

- [x] **Step 7: Perform independent Fable Review and one fix pass**

  Package the whole branch from Phase 6 head to current HEAD. The reviewer must attack critic omission, clause reordering, evidence laundering, quote-presence overclaim, cross-beat refs, rhetorical exemption abuse, stale aggregate reuse, caller exceptions, association-to-causation, projection-to-fact, attribution loss, and unsupported background. Re-grade findings by user effect. Fix Critical/Important findings in one TDD pass; defer Minor findings and report them.

- [x] **Step 8: Complete evidence, commit documentation, and open Draft PR**

  Mark plan checkboxes only after fresh evidence, commit documentation/plan, push `codex/explanation-v2-phase7-semantic-fidelity`, and open a Draft PR with base `codex/explanation-v2-phase6-spoken-narration`. Include problem, contract, architecture, files, tests, Gold Set results, unverified items, rollback, and Phase 8 recommendation. Attach the PR, wait for GitHub Actions/Vercel, and do not merge.
