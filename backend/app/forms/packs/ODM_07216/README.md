# Form Pack — ODM 07216 (Ohio Medicaid)

A **form pack** is the self-contained unit of the multi-form platform. Everything
the app needs to drive *this* form lives in this directory; the core code stays
form-agnostic and loads packs through `app/forms/registry.py`. To add a new form
tomorrow, copy this directory's shape — see
[`docs/ai/FORM-PACK-AUTHORING.md`](../../../../../docs/ai/FORM-PACK-AUTHORING.md).

## What this form is

Ohio Department of Medicaid **ODM 07216** — "Application for Health Coverage & Help
Paying Costs". Completed EMR-assisted + voice-assisted into a **filled PDF**. Online
portal submission is **not** enabled for this form (`output_targets: ["pdf"]`).

## Layout

| Path | Purpose | Consumed by |
|------|---------|-------------|
| `manifest.json` | Pack metadata: id, version, output targets, prompt/KB/voice config | `app/forms/registry.py` |
| `form.schema.json` | Field schema — the engine for all form logic (fields, validation, skip-logic, sections, `sensitive` flags) | `app/forms/service.py` via the registry |
| `prefill.json` | Declarative EMR → field-key mapping (named transforms) | `app/forms/mapper.py` |
| `pdf.mapping.json` | AcroForm widget mapping (`field_key` → widget) | `app/pdf/pdf_service.py` via the registry |
| `prompts/system.md` | Per-form AI persona / system prompt | `app/forms/prompts.py` (Phase 2) |
| `prompts/field_overrides.json` | Per-field question/help overrides | `app/forms/prompts.py` (Phase 2) |
| `knowledgebase/` | PHI-free guidance docs → embedded for RAG help | `app/ai/kb.py` (Phase 3) |
| `workflow.yaml` | Web-submission recipe (URL, selectors, steps) | `app/outputs/` (Phase 5) — absent until web is enabled |

## Prefill transforms

`prefill.json` maps a form `field_key` to either a `const` value or a `source`
(dotted attribute path into `EMRPatient`) plus an optional named `transform`. The
transform registry lives in `app/forms/mapper.py` (`_TRANSFORMS`): `strip`,
`clean_phone`, `clean_ssn`, `format_dob`, `map_sex`, `map_marital`,
`insurance_summary`, `income_summary`, `employee_name_if_employed`,
`first_employer`. Missing EMR attributes resolve safely to `None` and are skipped.

## 🔒 Compliance notes

- The `schema.json` `sensitive: true` flag (SSN, DOB, …) is a safety control: those
  values are never echoed via TTS, never sent to the LLM, and masked at output.
- `knowledgebase/` and `prompts/` must contain **NO PHI** — see
  [`knowledgebase/SOURCES.md`](./knowledgebase/SOURCES.md).
- The base fillable PDF currently resolves from `backend/app/pdf/ODM07216fillx.pdf`
  (legacy location); generated PDFs contain full PHI and are written to the
  gitignored `PDF_OUTPUT_DIR`, served only by the session-scoped download endpoint.
