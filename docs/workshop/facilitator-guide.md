# Facilitator Guide

Teaching notes for delivering the [DurableFlow workshop](README.md). Pair with [curriculum.md](curriculum.md) for timing and [workshop-exercises.md](workshop-exercises.md) for lab solutions.

---

## Before the workshop

### Environment

- Room with projector; participants on macOS or Linux (WSL2 acceptable).
- Python 3.11+ installed; `sqlite3` CLI available.
- Clone repo before Day 1; verify `./start.sh test` on one machine.

### Pre-read (send 48 h ahead)

1. [README.md](../../README.md) — skim positioning
2. [dflow-arch.md](../dflow-arch.md) — "Core Invariants" and inbox triage diagram
3. Run `./start.sh crash` locally

### Materials to print (optional)

- Core invariants (5 bullets)
- Inbox triage step index table (0–5)
- [field-pattern.md](../field-pattern.md) checklist
- Production mapping template from [curriculum.md](curriculum.md)

---

## Room setup

| Item | Notes |
|------|-------|
| Screen | Show SQLite output large enough to read `current_step` |
| Pairs | Labs W1–W8 work well in pairs; capstone in pairs |
| DB paths | Remind: use `/tmp/ws-*.sqlite` — demos overwrite `examples/*.sqlite` |

---

## Module facilitation notes

### Module 1 — The operational gap

**Energy:** High-level; avoid code for first 20 minutes.

**Common confusion:** "Is this LangGraph?" — Reinforce: orchestration vs durability layer.

**Hook question:** "What happens to your agent if the process dies after sending email but before logging it?"

### Module 2 — Durable engine

**Critical teaching moment:** `current_step` is last **completed**, not next to run.

**Demo tip:** Run crash demo twice; second time show parent resume without child re-ingest.

**If demo fails:** Check Python 3.11+, `PYTHONPATH`, delete stale `examples/crash_resume_demo.sqlite`.

**Pitfall:** Learners think `approve()` resumes workflow — preview Module 3 early if asked.

### Module 3 — Human gates

**Draw on whiteboard:** Two layers (approval_queue vs workflows.status).

**Live reject:** Run `./start.sh inbox` and press `n` — show zero `side_effect_log` rows.

**Time saver:** E6 can be pytest-only if short on time.

### Module 4 — Cost and context

**Split room optional:** Half on E3/W4 (routing), half on E4/W6 (context); reconvene for E5.

**Talking point:** TF-IDF is deliberately boring — tests are the point.

**W4 snag:** Learners struggle wiring custom `RoutingPolicy` — point to `InboxTriageWorkflow.__init__` and dependencies dict.

### Module 5 — Observability

**Keep short** if running 1-day Essentials format.

**Exercise:** jq one-liner: `jq -r '.event_type' file.jsonl | sort | uniq -c`

### Module 6 — Colony

**Emphasize humility:** Mock benchmark, narrow claim, methodology doc required reading.

**Debate:** "Would you bet production on +10 pts?" — correct answer: only with live profile and your workload.

**Skip live Vast** unless API key and time budget agreed in advance.

### Module 7 — Readiness

**Verdict-first:** Read `readiness_report.md` aloud before explaining code.

**MCP demo:** Optional `[mcp]` install; stdio fallback still teaches gating.

**Hard topic:** Authorization policy replacing human approval — 5 min discussion, no lab required.

---

## Timing adjustments

### 1-day Essentials (6–7 h)

| Block | Content |
|-------|---------|
| 0:00–0:45 | Module 1 |
| 0:45–2:15 | Module 2 (E1, W1 only) |
| 2:15–3:15 | Module 3 (E2, E6) |
| 3:15–4:45 | Module 4 (E3, E4, E5) |
| 4:45–5:15 | Module 5 (E8) |
| 5:15–5:45 | Production mapping template + Q&A |

Skip Modules 6–7 or assign as pre-read.

### 2-day Standard

Day 1: Modules 1–3 + E1–E2  
Day 2: Modules 4–7 + E3–E8, W4–W11, capstone intro

### 3-day Deep dive

Add capstone build Day 3 AM, presentations PM.

---

## Discussion prompts (by theme)

**Durability**

- Where does your team persist workflow state today?
- What is lost on pod restart in your current agent deployment?

**Approval**

- Which actions should never auto-execute for your domain?
- How long can `paused_approval` wait before SLA breach?

**Cost**

- Do you have per-workflow inference budgets?
- Who gets paged when a runaway loop spikes token usage?

**Readiness**

- Would you show a customer the naked vs wrapped delta?
- What single scenario would block your current agent from shipping?

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError: src` | `export PYTHONPATH=.` or use `./start.sh` |
| SQLite locked | Close other shells; WAL mode should tolerate reads |
| Crash demo no resume | Delete `examples/crash_resume_demo.sqlite*` and rerun |
| pytest collection errors | `pip install -e ".[dev]"` |
| Inbox demo no prompt | Email may be informational — check fixture or force action-required email |

---

## Assessment facilitation

Use quizzes in [curriculum.md](curriculum.md#assessment-quizzes) as exit tickets.

**Proficiency signal:** Learner explains crash recovery using only SQLite queries, without opening `engine.py`.

**Mastery signal:** Capstone track with peer review score ≥ 4.

---

## After the workshop

**Follow-up resources:**

- [dflow-spec.md](../dflow-spec.md) — implementers
- [CONTRIBUTING.md](../../CONTRIBUTING.md) — contribute exercises back
- Temporal / LangGraph docs for production mapping

**Feedback form suggestions:**

1. Which primitive was most new?
2. Which lab was most valuable?
3. What production tool will you evaluate first?

---

## Co-facilitator roles

| Role | Responsibility |
|------|----------------|
| **Lead** | Lecture, diagrams, timing |
| **Lab** | Screen-share terminal, debug PYTHONPATH/SQLite |
| **Roam** | Pair rooms, unblock W4 and capstone |

---

## License and attribution

Workshop materials are part of the DurableFlow repo (MIT). Adapt modules freely; credit the repo when redistributing slides derived from these docs.
