---
description: Review the current branch diff against repo conventions + PHI rules.
---

Review the current branch's diff against the master branch as a senior engineer on
this repo. Be concrete and cite `file:line`.

Get the diff (default base is `master`):
```bash
git fetch origin master --quiet
git diff origin/master...HEAD
```

Review against the canonical docs (don't re-derive — cite them):

- **🔒 PHI / security** — run the full
  [docs/ai/SECURITY-AND-PHI.md](../../docs/ai/SECURITY-AND-PHI.md) checklist
  (logs, secrets, parameterized read-only EMR, masking, audit, sensitive fields,
  CORS/auth, disclaimer). This is blocking. Use `/security-audit` or the
  `security-phi-reviewer` agent for depth.
- **Backend** — [docs/ai/BACKEND-CONVENTIONS.md](../../docs/ai/BACKEND-CONVENTIONS.md):
  router/service/schemas separation, `get_settings()`, SQLAlchemy 2.0 sync,
  `str | None`, sync-vs-async, graceful EMR/AI degradation, AI only via `llm.py`.
- **Frontend** — [docs/ai/FRONTEND-CONVENTIONS.md](../../docs/ai/FRONTEND-CONVENTIONS.md):
  backend access only via `lib/api.ts`, shared types in `lib/types.ts`, Tailwind
  shared classes, voice guard, disclaimer/MOCK banner not regressed.
- **AI** — [docs/ai/AI-LLM-INTEGRATION.md](../../docs/ai/AI-LLM-INTEGRATION.md):
  rule-based fallback present and exercised with no key; `temperature=0.0`; no
  sensitive values sent to the LLM.
- **Form changes** — schema-driven via `odm_07216.json`; PDF mapping + validation
  + dependency branches covered.
- **Tests & gate** — behavior change has a matching test; `pytest tests/ -v` and
  `npm run build && npm run lint` pass.
- **Scope** — no out-of-scope additions (browser automation, portal submission,
  multi-person) without an explicit ask.

Output: grouped findings (**Blocking / Should-fix / Nit**) with file:line and a
suggested fix, then a short overall verdict.
