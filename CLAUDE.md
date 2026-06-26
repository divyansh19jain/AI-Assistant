# CLAUDE.md — AI-Assistant

**Start by reading [`AGENTS.md`](./AGENTS.md)** — it is the master contract
(rules, conventions, commands, definition of done) shared by every agent and
human on this repo. This file adds only the **Claude Code–specific** workflow on
top of it. The deep references live in [`docs/ai/`](./docs/ai/README.md).

## The one thing that matters most

This is a **healthcare app handling PHI**. The 🔒 non-negotiable rules in
`AGENTS.md` and [`docs/ai/SECURITY-AND-PHI.md`](./docs/ai/SECURITY-AND-PHI.md)
are not optional. Never log PHI, never hardcode secrets, EMR is read-only +
parameterized, mask at output, audit significant actions. If a task would relax
any of these, **stop and flag it** in your response.

## Claude Code tooling in this repo

Slash commands (`.claude/commands/`):

- `/dev` — how to bring the stack up (db + backend + frontend, mock mode).
- `/test` — run the backend test suite (and the frontend gate).
- `/check` — full green-bar gate: pytest + `npm run build` + `npm run lint`.
- `/add-form-field` — guided ODM 07216 field addition (schema → prefill →
  validation → PDF mapping → tests).
- `/emr-introspect` — safely discover real EMR schema (read-only) and map a column.
- `/security-audit` — run the PHI / secrets / SQL-safety review on the diff.
- `/pr-review` — review the current branch diff against repo conventions + PHI rules.

Subagents (`.claude/agents/`) — delegate deep work to these:

- `backend-fastapi-expert` — backend changes in the established package style.
- `frontend-next-expert` — Next.js/React/Tailwind changes.
- `security-phi-reviewer` — adversarial PHI/secrets/SQL/auth review (use before
  finishing anything that touches patient data, EMR, auth, logging, or CORS).
- `test-author` — write/extend pytest (and Playwright/RTL) coverage.

Skills (`.claude/skills/`) — invoked automatically when relevant, or on request:

- `add-form-field`, `emr-field-mapping`, `pdf-field-mapping`, `phi-security-review`.

## Working agreement

- **Plan before multi-file changes.** Touching security, auth, CORS, the data
  model, or the EMR adapter → say what you'll change and why first.
- **Default run profile:** `USE_MOCK_EMR=true`, no `OPENAI_API_KEY` (rule-based
  fallback). Don't connect to the real EMR or a real LLM unless asked.
- **The form is data-driven** — prefer editing
  `backend/app/forms/schemas/odm_07216.json` over adding imperative code.
- **Finish on the green bar** (see `AGENTS.md` → Definition of done) and run the
  PHI pre-flight checklist.
- **Windows/PowerShell** is the primary shell here; a Bash tool is also
  available. Use the commands in `AGENTS.md`.
- Before any non-trivial deploy/infra/migration action, re-check the relevant
  notes — this repo handles real patient data.

## When asked to improve the app

Pick from [`docs/ai/IMPROVEMENT-BACKLOG.md`](./docs/ai/IMPROVEMENT-BACKLOG.md)
(prioritized, with file pointers) and follow the matching recipe in
[`docs/ai/WORKFLOWS.md`](./docs/ai/WORKFLOWS.md). Don't action a P0 security item
against a real environment without confirming it's wanted there.
