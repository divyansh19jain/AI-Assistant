# AI coding framework - index

This folder is the canonical knowledge base for AI agents (Claude Code, Cursor,
Codex/OpenAI CLI, and humans) working on this repo. The tool-specific configs
(`/AGENTS.md`, `/CLAUDE.md`, `.cursor/rules/*`, `.claude/*`) are thin and point
here so there is one source of truth.

## Read order

0. [PLATFORM.md](./PLATFORM.md) - start here. The app is now a DB-backed,
   UI-managed multi-form builder; this is the current architecture: entities,
   the builder, workflows, and web submission.
1. [ARCHITECTURE.md](./ARCHITECTURE.md) - original single-form module map,
   request flow, data model, and run profiles. Still accurate for the engine
   internals.
2. [SECURITY-AND-PHI.md](./SECURITY-AND-PHI.md) - security rules for healthcare
   deployments.
3. [BACKEND-CONVENTIONS.md](./BACKEND-CONVENTIONS.md) - FastAPI/Python style.
4. [FRONTEND-CONVENTIONS.md](./FRONTEND-CONVENTIONS.md) - Next.js/React/TS style.
5. [AI-LLM-INTEGRATION.md](./AI-LLM-INTEGRATION.md) - LLM factory, prompt
   conventions, provider fallback, and conversational-agent overview.
6. [AGENT-STATE-AND-VOICE.md](./AGENT-STATE-AND-VOICE.md) - field binding,
   dependency cleanup, read-back confirmation, and voice-agent state contracts.
7. [FORM-PACK-AUTHORING.md](./FORM-PACK-AUTHORING.md) - how to add future forms.
8. [TESTING.md](./TESTING.md) - how to test; the green-bar gate.
9. [WORKFLOWS.md](./WORKFLOWS.md) - step-by-step recipes for common tasks.
10. [IMPROVEMENT-BACKLOG.md](./IMPROVEMENT-BACKLOG.md) - prioritized,
    agent-ready work found during deep review.

## How the tool configs map to these docs

| Tool | Entry file(s) | Role |
|------|---------------|------|
| Codex / OpenAI CLI, generic agents | `/AGENTS.md` | Cross-tool standard; the master rules plus pointers here |
| Cursor | `/AGENTS.md` + `.cursor/rules/*.mdc` | Always-on overview plus path-scoped backend/frontend/ai/testing rules |
| Claude Code | `/CLAUDE.md` + `.claude/` | Memory, slash commands, subagents, and skills |

Keep this folder current. If you change a convention or the architecture, update
the relevant doc here in the same change. The tool configs inherit it
automatically.
