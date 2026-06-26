---
description: Full green-bar gate — pytest + frontend build + lint + PHI pre-flight.
---

Run the full **definition-of-done gate** for AI-Assistant and report the result.

1. **Backend tests:**
   ```bash
   cd backend && .\.venv\Scripts\Activate.ps1 && pytest tests/ -v
   ```
2. **Frontend typecheck + lint:**
   ```bash
   cd frontend && npm run build && npm run lint
   ```
3. **PHI pre-flight** on the working diff (`git diff`): confirm each item in
   [docs/ai/SECURITY-AND-PHI.md](../../docs/ai/SECURITY-AND-PHI.md) §9 —
   - no PHI in logs/errors/comments/test fixtures,
   - no secrets/connection strings/keys added; `.env*` untouched in git,
   - EMR SQL still parameterized + read-only,
   - new patient-data outputs masked or server-side-only,
   - new significant actions write a sanitized audit entry,
   - disclaimer preserved, CORS/auth not loosened.
4. **Test owed?** If behavior changed (validation, fields, masking, endpoint,
   prefill) without a new/updated test, flag it.

Report a clear ✅/❌ per gate. Only call the change done when **all** are green.
For a deeper adversarial PHI pass, delegate to the `security-phi-reviewer` agent.
