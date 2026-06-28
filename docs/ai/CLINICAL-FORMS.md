# Clinical Self-Report Forms

This feature adds a separate behavioral-health clinical flow without changing
the Ohio Medicaid form pack.

## Form Pack

Bundled pack:

```text
backend/app/forms/packs/BH_SELF_REPORT_BATTERY/
  form.schema.json
  prompts/system.md
  prompts/field_overrides.json
  knowledgebase/*.md
  workflow.yaml
```

The pack is seeded like ODM by `app.forms.seed.seed_from_packs()` on startup.
The DB row is still authoritative after an admin edits the form.

## Selection Model

The landing page lets the user choose:

- Medicaid Application -> starts `ODM_07216`.
- Clinical Forms -> starts `BH_SELF_REPORT_BATTERY`.

Clinical tools are selected before EMR lookup. The frontend sends those choices
as `CreateSessionRequest.initial_answers`, for example:

```json
{
  "form_id": "BH_SELF_REPORT_BATTERY",
  "initial_answers": {
    "selected.phq9": true,
    "selected.gad7": true,
    "selected.cssrs": true,
    "selected.pcl5": false
  }
}
```

Every assessment section depends on its `selected.*` gate. That means a clinical
session only asks the selected instruments. Medicaid does not send
`initial_answers`, so its existing session flow is unchanged.

## Voice And Touch Flow

The clinical pack uses the same assistant endpoint as Medicaid:

```text
POST /api/session/{session_id}/agent
```

Question text lives in `form.schema.json`. Fixed answer choices live in each
field's `validation_rule.allowed_values`, so the assistant UI can show touch
chips for iPad users. The voice assistant also receives:

- `prompts/system.md` for clinical tone and self-report rules;
- `prompts/field_overrides.json` for field-level help;
- `knowledgebase/*.md` for scoring, recall periods, and safety guidance.

## Scoring

Scoring is deterministic in:

```text
backend/app/clinical/scoring.py
```

Prompts must not calculate or invent scores. The review API calculates scores
from stored answers and returns them as `review.scores`. Summary PDFs include a
"Clinical Screening Scores" section.

Score totals and item counts are separate values. For example, PHQ-9 has 9
questions, but its score range is 0-27. UI and PDFs should display both as
`Score <total>/<max>` and `<answered>/<items> items` to avoid making a score
range look like a question count.

Supported score summaries:

- DSM-5-TR Level 1 Cross-Cutting domain flags.
- PHQ-9 total and severity label.
- GAD-7 total and severity label.
- C-SSRS self-report risk flag.
- AUDIT-C total and common positive-screen notes.
- TAPS positive domains.
- DAST-10 total and severity label.
- PCL-5 total and elevated-screen note.
- MDQ positive-screen pattern.
- WHODAS 2.0 12-item simple and transformed score.
- DLA-20-style self-report functioning transformed score.

## EMR Results API

External EMR reads use API-key auth, separate from admin JWT.

Configure:

```env
CLINICAL_RESULTS_API_KEYS=key-one,key-two
```

Read one session:

```http
GET /api/clinical/results/{session_id}
X-API-Key: key-one
```

List recent clinical sessions:

```http
GET /api/clinical/results?patient_id=<external_patient_id>&limit=50
Authorization: Bearer key-one
```

Payload includes:

- `client.first_name`
- `client.last_name`
- `client.dob`
- `selected_assessments`
- `assessments[]` with `assessment_name`, `data`, and `score`
- `scores[]`
- `assessment_data`

The API filters values through the same schema validation contract used by the
assistant and review readiness. A stale invalid answer row is returned as missing
client data and is not emitted as assessment data.

## Adding Or Modifying Tools

1. Add a `selected.<tool>` boolean gate.
2. Add a section whose fields depend on that gate.
3. Use `select` fields with `allowed_values` when touch answers are expected.
4. Add field help in `prompts/field_overrides.json`.
5. Add scoring in `app/clinical/scoring.py`.
6. Add a regression test for the score and the EMR API payload.
7. Verify `ODM_07216` tests still pass; the Medicaid form must remain isolated.

Before production use, verify official instrument wording, scoring rules, and
license or permission requirements for each tool.
