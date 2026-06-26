# AI coding framework — index

This folder is the **canonical knowledge base** for AI agents (Claude Code,
Cursor, Codex/OpenAI CLI, and humans) working on this repo. The tool-specific
configs (`/AGENTS.md`, `/CLAUDE.md`, `.cursor/rules/*`, `.claude/*`) are thin and
point here so there's **one source of truth**.

## Read order

1. [ARCHITECTURE.md](./ARCHITECTURE.md) — what the app is, the module map, the
   request flow, the data model, run profiles.
2. [SECURITY-AND-PHI.md](./SECURITY-AND-PHI.md) — **non-negotiable** rules. This
   is a healthcare app with PHI; read before writing code.
3. [BACKEND-CONVENTIONS.md](./BACKEND-CONVENTIONS.md) — FastAPI/Python style.
4. [FRONTEND-CONVENTIONS.md](./FRONTEND-CONVENTIONS.md) — Next.js/React/TS style.
5. [AI-LLM-INTEGRATION.md](./AI-LLM-INTEGRATION.md) — the LLM factory + the
   mandatory rule-based fallback pattern.
6. [TESTING.md](./TESTING.md) — how to test; the green-bar gate.
7. [WORKFLOWS.md](./WORKFLOWS.md) — step-by-step recipes for common tasks.
8. [IMPROVEMENT-BACKLOG.md](./IMPROVEMENT-BACKLOG.md) — prioritized, agent-ready
   work found during the deep review.

## How the tool configs map to these docs

| Tool | Entry file(s) | Role |
|------|---------------|------|
| **Codex / OpenAI CLI**, generic agents | `/AGENTS.md` | Cross-tool standard; the master rules + pointers here |
| **Cursor** | `/AGENTS.md` + `.cursor/rules/*.mdc` | Always-on overview + PHI rules; path-scoped backend/frontend/ai/testing rules |
| **Claude Code** | `/CLAUDE.md` + `.claude/` | Memory + slash commands + subagents + skills |

> Keep this folder current. If you change a convention or the architecture,
> update the relevant doc here in the same change — the tool configs inherit it
> automatically.
