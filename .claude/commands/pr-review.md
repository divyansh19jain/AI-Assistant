---
description: Review the current branch diff against repo conventions and PHI rules.
---

Review the current branch's diff against the master branch as a senior engineer on
this repo. Be concrete and cite `file:line`.

Get the diff:

```bash
git fetch origin master --quiet
git diff origin/master...HEAD
```

Review against the canonical docs:

- **PHI / security** - run the full
  [docs/ai/SECURITY-AND-PHI.md](../../docs/ai/SECURITY-AND-PHI.md) checklist.
  This is blocking.
- **Backend** - [docs/ai/BACKEND-CONVENTIONS.md](../../docs/ai/BACKEND-CONVENTIONS.md):
  router/service/schemas separation, `get_settings()`, SQLAlchemy 2.0 sync,
  graceful EMR/AI degradation, AI only via `llm.py`, schema snapshots for sessions.
- **Frontend** - [docs/ai/FRONTEND-CONVENTIONS.md](../../docs/ai/FRONTEND-CONVENTIONS.md):
  backend access only via `lib/api.ts`, shared types in `lib/types.ts`, Tailwind
  shared classes, voice guard, disclaimer and mock banner not regressed.
- **AI** - [docs/ai/AI-LLM-INTEGRATION.md](../../docs/ai/AI-LLM-INTEGRATION.md):
  rule-based fallback present and exercised with no key, `temperature=0.0`, no
  sensitive values sent to the LLM.
- **Form changes** - schema-driven via `forms.schema_json` or a form pack under
  `backend/app/forms/packs/<FORM_ID>/`; PDF/workflow mapping, validation, schema
  snapshots, and dependency branches covered.
- **Workflow** - unsupported tasks fail closed; `web_submit` requires a real recipe
  with `portal_url`.
- **Tests and gate** - behavior changes have matching tests; `pytest`, frontend
  build, and frontend lint pass.

Output grouped findings (**Blocking / Should-fix / Nit**) with file:line and a
suggested fix, then a short verdict.
