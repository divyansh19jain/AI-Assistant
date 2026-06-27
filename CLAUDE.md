# CLAUDE.md - AI-Assistant

Start by reading `AGENTS.md`. It is the shared contract for Codex, Cursor, Claude
Code, and human developers. This file only adds Claude Code workflow notes.

## Claude Code Tooling

Slash commands in `.claude/commands/`:

- `/dev` - bring up DB, backend, and frontend in mock mode.
- `/test` - run backend tests and the frontend gate.
- `/check` - full green bar: pytest, `npm run build`, `npm run lint`.
- `/add-form-field` - add/change a field in a form pack or builder-exported form.
- `/emr-introspect` - inspect real EMR schema read-only before mapping new columns.
- `/security-audit` - PHI, secrets, SQL, auth, CORS, and web-submission review.
- `/pr-review` - review the current diff against repo rules.

Subagents in `.claude/agents/`:

- `backend-fastapi-expert`
- `frontend-next-expert`
- `security-phi-reviewer`
- `test-author`

Skills in `.claude/skills/`:

- `add-form-field`
- `emr-field-mapping`
- `pdf-field-mapping`
- `phi-security-review`

## Working Agreement

- Plan before touching security, auth, CORS, migrations, EMR, approval/workflows, or
  web submission.
- Default profile: mock EMR, no live AI key, no real portal submission.
- Form changes should usually touch `backend/app/forms/packs/<FORM_ID>/` or the
  builder/export format, not hardcoded Python.
- Keep session logic on `form_sessions.schema_json` snapshots.
- Finish on the green bar from `AGENTS.md`.
