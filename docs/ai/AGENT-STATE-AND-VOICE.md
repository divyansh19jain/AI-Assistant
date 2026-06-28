# Agent State And Voice Contracts

This document explains the state-machine guardrails behind the conversational
assistant. The goal is not to make the interview rigid. The LLM should still act
like a human case worker: choose a natural order, explain terms plainly, save
extra facts the user volunteers, and avoid sounding like a survey. The code below
exists so that human-sounding behavior cannot corrupt form state, lose the current
field binding, or silently approve uncertain voice captures.

## Main Code Paths

Frontend:

- `frontend/app/assistant/[sessionId]/page.tsx`
- `frontend/lib/api.ts`

Backend:

- `backend/app/sessions/router.py`
- `backend/app/ai/agent.py`
- `backend/app/sessions/service.py`
- `backend/app/forms/missing_fields.py`
- `backend/app/forms/readiness.py`

Tests:

- `backend/tests/test_agent_turn.py`
- `backend/tests/test_correction_aware.py`
- `backend/tests/test_form_logic.py`

## Turn Flow

1. The assistant page calls `POST /api/session/{session_id}/agent`.
2. The request includes the user's text and the `field_key` for the field that
   the previous assistant message asked about.
3. `run_agent_turn()` first tries deterministic handling for that explicit field:
   skip words, pending read-back confirmations, booleans, and validated direct
   field saves.
4. The LLM then sees the current form state, case notes, KB snippets, and tools.
5. If the LLM wants to ask a question, it must call the `ask` tool with the
   field key it is about to ask.
6. The backend returns that same `next_field` to the UI so answer chips, voice
   hints, and the next request's `field_key` stay aligned.

The LLM chooses the human order. The deterministic layer only enforces the field
identity and state rules.

## Startup Contract

The first assistant message must orient the user before collecting data. It
should say the assistant is a smart AI assistant for the current form, that the
user can answer by voice or typing, that the interview usually takes about 10 to
15 minutes, and that the user reviews everything before anything is submitted.

It must also give a short "have this nearby" checklist. `agent.py` builds that
with `_prep_checklist()`: ODM 07216 gets a Medicaid-specific checklist, while
future forms get a schema-derived checklist based on fields such as contact,
SSN/citizenship, income, insurance, and care details.

This is enforced in two places:

- the LLM startup system message, for normal AI turns;
- `_opening_prompt()`, for no-key, timeout, quota, or empty-response fallbacks.

Do not make startup behavior prompt-only. If OpenAI credits expire or the model
times out, the user should still get a human opening instead of a bare first
question.

## Field Binding Contract

The most common repeated-question bug is a mismatch between the spoken question
and the field key sent with the next answer. The app prevents that as follows:

- The backend returns `next_field`.
- The frontend stores it in `nextFieldRef`.
- `sendToAgent()` sends `nextFieldRef.current.field_key` with the next answer.
- The frontend also persists the field snapshot in `sessionStorage` so a browser
  reload restores the binding.
- On restore, both `nextFieldRef` and `nextKey` are restored. `nextFieldRef`
  controls backend saving; `nextKey` controls visible progress and Whisper hints.

Do not remove the stored `next_field` snapshot unless you replace it with an API
that returns the current pending field on page load.

## Agent Tool Contract

The LLM path in `backend/app/ai/agent.py` has these tools:

- `save_answers`: persist one or more field values.
- `skip_fields`: mark optional fields as intentionally blank.
- `screen_income` and `screen_income_sources`: Ohio Medicaid screening helpers.
- `ask`: declare the one field the assistant is about to ask.
- `go_to_review`: request review only after readiness passes.

Important rule: `ask` is a declaration, not validation. The backend still checks
that the declared field is currently missing and applicable before returning it
as `next_field`.

## Deterministic Save Before The LLM

`run_agent_turn()` handles the explicit `answered_field_key` before the LLM runs.
This prevents the assistant from asking the same question again after a valid
answer. The direct path handles:

- skip words like `skip`, `none`, and `not applicable`;
- yes/no booleans, including natural answers such as `just me`;
- validated text, date, phone, number, select, and SSN values;
- pending low-confidence confirmation replies.

If a direct save fails validation, the LLM still gets the turn and can split a
combined utterance, clarify, or save multiple volunteered facts. This preserves
smart behavior while keeping one-field answers reliable.

## Help And Explanation Contract

Questions like "what is WIC?", "what does that mean?", or "can you explain?" are
not answers. Before deterministic field saving runs, `run_agent_turn()` checks
the active field with `help_intent.classify_intent()`. Help turns call
`explain_field()` and return the same `next_field`, so the UI stays bound to the
same question after the explanation.

Field-specific help should live in `prompts/field_overrides.json` or the form
knowledgebase. The fallback explanation path uses those overrides even when an
LLM key exists but the model call fails because of quota, timeout, or provider
errors.

## Recursive Dependency Contract

Form field dependencies can be multiple levels deep. Example:

```text
person2.adding_person2
  -> person2.tax_file_next_year
    -> person2.file_jointly_with_spouse
      -> person2.spouse_name
```

`backend/app/forms/missing_fields.py:is_field_applicable()` must evaluate the
entire dependency chain. A stale grandchild must not remain applicable just
because its direct parent still has an old value in the database.

Callers that have a schema field list should pass `fields_by_key` into
`is_field_applicable()`. This is used by missing-field detection, readiness,
review data, case profile generation, document OCR candidates, and the agent's
form-state prompt.

## Correction Cleanup Contract

`backend/app/sessions/service.py:_invalidate_stale_answers()` removes answers
that no longer belong to an active branch after a user correction.

It intentionally preserves a child value if the child was collected before its
gate was answered and that gate is still active. Example: if a home address is
saved before `applicant.is_homeless` is answered, the app keeps the address until
the homelessness answer proves it should be removed.

It does not preserve orphan grandchildren. If a missing direct gate is itself on
an inactive branch, the descendant is stale and must be cleared.

## Voice Read-Back Contract

Voice transcription can be wrong even when validation passes. For critical voice
captures, the assistant must read the value back and get confirmation before the
application can be approved.

Current read-back fields:

- dates;
- phone numbers;
- ZIP fields.

Implementation:

- The agent saves these voice answers with confidence `0.5`.
- `forms/readiness.py` treats confidence below `0.75` as a blocker.
- `_first_low_confidence_field()` finds the first applicable low-confidence
  answer.
- The response is forced back onto that same field with Yes/No confirmation
  chips.
- A `yes` reply promotes confidence to `1.0`.
- A `no` reply deletes the answer so the same field is asked again.

This deliberately reuses the existing `FormAnswer.confidence` column. There is no
separate pending-confirmation table. If you add one later, keep review,
readiness, and reload behavior equivalent.

## Completion Authority

The agent is never the authority for completion. These must all use
`backend/app/forms/readiness.py`:

- agent `done`;
- `go_to_review`;
- review UI;
- approval route;
- PDF generation;
- workflow launch.

Session status `ready_for_review` means answer collection has no remaining
applicable missing fields. It does not by itself mean approval is allowed. Low
confidence, invalid answers, or PDF mapping blockers still prevent readiness.

## Extending Future Forms

When adding a new form:

1. Model branching with `depends_on` in the schema.
2. Put parent gates before child fields where possible.
3. Add tests for every non-trivial dependency chain.
4. Use prompt/KB content for form knowledge and human wording.
5. Do not hard-code form-specific interview order in `agent.py` unless the same
   behavior applies platform-wide.
6. If a new field type needs read-back, update `_needs_agent_readback()` and add
   an agent-turn test.

## Troubleshooting Repeated Questions

Check these in order:

1. Did the UI send `field_key` on the agent request?
2. Did `nextFieldRef` restore correctly after reload?
3. Did `set_field()` return `ok: false` due to validation?
4. Is the field actually still applicable after recursive dependencies?
5. Is the answer low-confidence and waiting for read-back confirmation?
6. Did the LLM fail to call `ask`, causing fallback to schema order?

The tests named around agent turns, correction awareness, and form logic are the
best starting point for reproducing these issues.
