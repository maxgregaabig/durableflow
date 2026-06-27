# Deferred Verification Items — LangSmith Adapter

Per `verification-policy.md §8` and `docs/langsmith-adapter.md §16`. Deferred
claims are recorded here with rationale. They MUST NOT be claimed as implemented
(VER-013) and carry verdict `DEFERRED-VERIFICATION` in `ledger.json`.

## C-LSMITH-DEFER-001 — Live LangSmith SDK validation

**Claim:** Live LangSmith SDK validates root-run reopening (preferred) or
deterministic linked-segment behavior (fallback) against the pinned
`langsmith>=1.2,<2.0` SDK.

**Type:** Capability.

**Why deferred:** The claim is falsifiable only against a live LangSmith
endpoint, which requires (a) outbound network access and (b) a live
`LANGSMITH_API_KEY` against a configured project. Neither is available in the
offline, dependency-pinned build/CI environment that DurableFlow targets
(`docs/langsmith-adapter.md` core principle: local-first, no network in the
default path).

**Min evidence rank required when unblocking:** E2 (executable scenario against
the real endpoint) or E1 (reproduced by an independent verifier).

**How to unblock:**

1. Populate `LANGSMITH_API_KEY` (and `LANGSMITH_PROJECT`,
   `DURABLEFLOW_LANGSMITH_ENABLED=1`) in a networked environment.
2. Run the gated integration test:

   ```bash
   DURABLEFLOW_LANGSMITH_INTEGRATION=1 pytest \
     tests/test_langsmith_adapter.py -k live_sdk_roundtrip
   ```

3. If it passes, supersede `ledger-row-defer-001` with a new VERIFIED row
   (append-mostly: do not edit the deferred row in place) citing the run output
   as evidence, and write the compatibility note documenting the validated SDK
   version range (spec §21, Phase 2).
4. If root-run reopening proves unstable under live validation, the supported
   fallback is deterministic linked-segment runs (spec §22, Resolved Decisions).

**Interim behavior while deferred:** The adapter is validated against the
documented `FakeLangSmithClient` contract (`docs/langsmith-adapter.md §15.2`).
All network-free claims (C-LSMITH-001 … 012) advance to VERIFIED normally. The
adapter is export-functional against any client matching the contract; only
*live-API* conformance is deferred. This deferral blocks neither the network-free
scope COMPLETE verdict nor use of the adapter once credentials are supplied.
