# Capstone Project

The capstone is the synthesis exercise for the [DurableFlow workshop](README.md). Participants apply one primitive deeply and document how it maps to production tooling.

**Duration:** 2–4 hours (solo or pair)  
**Prerequisite:** Modules 1–5 minimum; Modules 6–7 recommended for tracks C and D.

---

## Choose a track

| Track | Focus | Difficulty |
|-------|-------|------------|
| [A — Extend the workflow](#track-a-extend-the-workflow) | New checkpointed step | Intermediate |
| [B — New side effect](#track-b-new-side-effect) | Approval + idempotency | Advanced |
| [C — Readiness scenario](#track-c-readiness-scenario) | Failure harness extension | Advanced |
| [D — Colony chaos profile](#track-d-colony-chaos-profile) | Benchmark methodology | Intermediate |

---

## Track A: Extend the workflow

**Builds on:** Exercise E7, Module 2

### Brief

Add a seventh step to `InboxTriageWorkflow` after `send_reply`, e.g. `archive_thread`, that records archive metadata in `step_data` only (no external API).

### Requirements

1. Register step in `register()` with correct ordering.
2. Checkpoint runs after step completes (`save_checkpoint` via engine — no manual DB hacks).
3. Step reads prior `step_data` (email id, send result) and returns `StepResult`.
4. New test in `tests/` asserts seventh row in `step_results` and expected `step_data` keys.
5. Full `./start.sh test` passes.

### Acceptance demo

```bash
pytest tests/test_your_archive.py -v
sqlite3 /tmp/capstone-a.sqlite "SELECT step_name FROM step_results ORDER BY step_index;"
```

### Design note (1 paragraph)

When would this step need approval? When would it need idempotency?

---

## Track B: New side effect

**Builds on:** Modules 3–4, E5

### Brief

Add a mock side effect: `schedule_followup` that writes a calendar hold (mock JSON file or in-memory store with persistence).

### Requirements

1. Side effect runs only after approval (reuse or extend approval gate pattern).
2. Idempotency key: `sha256("{workflow_id}:schedule_followup:{payload_hash}")` or equivalent documented scheme.
3. Test: execute twice after simulated crash — second run returns `idempotent_skip=True`.
4. Telemetry: log side effect with distinct event or `step_complete` metadata.
5. Rejection path: no calendar write when operator rejects.

### Suggested files

- `src/workflows.py` — new step method
- `tests/test_capstone_schedule.py` — idempotency + rejection tests
- Optional: `data/mock_calendar.json` append with clear test isolation

### Design note

Compare your gate to MCP gated write in `examples/mcp_demo.py`. What is the same? What is different?

---

## Track C: Readiness scenario

**Builds on:** Module 7, `readiness/harness.py`

### Brief

Add a seventh readiness scenario, e.g. **duplicate tool call** or **rate limit exceeded**, and score naked vs wrapped agents.

### Requirements

1. Scenario function in harness with deterministic fixture (no network).
2. Naked agent fails scenario; wrapped agent passes (or document intentional partial pass).
3. Scoring dimension assigned (safety, reliability, cost, or observability) with rationale in `readiness/vocabulary.py` or scoring module.
4. `readiness_demo.py` still runs zero-dependency; new scenario appears in report output.
5. Test: `pytest tests/test_readiness.py -v` (extend or add focused test).

### Example scenario ideas

| Scenario | Wrapped expected behavior |
|----------|---------------------------|
| Duplicate tool call | Idempotency returns cached result |
| Rate limit | Structured error observation; turn checkpointed |
| Unauthorized tool | Write gate blocks before execution |

### Design note

How would this scenario appear in a customer-facing readiness PDF? One sentence verdict + one metric.

---

## Track D: Colony chaos profile

**Builds on:** Module 6, `data/chaos_profiles.json`

### Brief

Add a new chaos profile `bursty` to the Colony benchmark and document expected naive vs durable behavior.

### Requirements

1. New profile in `data/chaos_profiles.json` with documented loss rate / burst parameters.
2. `chaos_benchmark_demo.py --profile bursty` runs without error.
3. Run three seeds; record completion table (see [W9](workshop-exercises.md#w9-seed-sensitivity-colony)).
4. Short methodology addendum (½ page): assumptions, threats to validity, when bursty matters vs hostile.
5. No change to core completion definition (artifact upload commits).

### Deliverable files

- `data/chaos_profiles.json` — profile definition
- `docs/workshop/capstone-d-bursty-notes.md` — your methodology note (participant-created; optional commit)

### Design note

What real-world failure mode does `bursty` model? (e.g. maintenance window, AZ evacuation)

---

## Submission checklist (all tracks)

```markdown
## Capstone submission

- [ ] Branch or patch with code changes
- [ ] Test command and output (paste or CI link)
- [ ] SQLite or JSONL evidence (screenshot or query output)
- [ ] Design note (production mapping paragraph)
- [ ] Peer review completed (W12 rubric) if in classroom setting
```

---

## Evaluation rubric (facilitators)

| Score | Description |
|-------|-------------|
| **5 — Exemplary** | Meets all requirements; test clear; design note maps to Temporal/LiteLLM/etc. with nuance |
| **4 — Proficient** | Meets requirements; minor doc gaps |
| **3 — Developing** | Core behavior works; missing idempotency test or checkpoint gap |
| **2 — Incomplete** | Partial implementation; tests fail |
| **1 — Not submitted** | — |

**Pass threshold:** 3+ with green tests on capstone-specific file.

---

## Presentation format (30 min per team)

1. **Problem** (2 min) — Which production pain does this address?
2. **Mechanism** (5 min) — Walk through code path and SQLite/JSONL evidence
3. **Demo** (5 min) — Crash, reject, or chaos run
4. **Production mapping** (3 min) — What you would use instead of SQLite
5. **Q&A** (15 min)

---

## Optional extensions

- Wire capstone step to real Anthropic call behind `ANTHROPIC_API_KEY` (optional extra).
- Export telemetry to OpenTelemetry span names (design only, no full OTel required).
- Add terminal UI panel in `colony/render_terminal.py` for new profile.
