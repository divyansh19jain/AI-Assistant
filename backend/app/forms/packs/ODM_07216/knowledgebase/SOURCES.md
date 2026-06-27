# Knowledgebase sources - ODM 07216

The AI uses this knowledgebase, via `app/ai/kb.py`, to help the user understand
ODM 07216 questions - for example "what counts as income?", "who is in my
household?", "do I qualify?", or "why do you need this?"

## No-PHI attestation

Every document placed in this directory must be general, form-level guidance with
no patient data: no patient names, DOB, SSN, addresses, phone numbers, raw
answers, transcripts, or real applicant examples. Patient answers are never
embedded or stored in the vector index. Retrieval queries are built from field
metadata or fixed topic phrases, not raw applicant answers.

## Provenance

| Document | Source | Retrieved | Notes |
|----------|--------|-----------|-------|
| `application-interview-playbook.md` | ODM 07216 Rev. 11/2025; ODM MEPL 192 | 2026-06-27 | Voice interview behavior for a case-manager-like assistant. |
| `eligibility-screening-2026.md` | ODM 07216 Rev. 11/2025; ODM MEPL 194; ODM 2026 Monthly Financial Eligibility chart | 2026-06-27 | Current 2026 income-screening guide and safe eligibility language. |
| `household-and-income-guidance.md` | ODM 07216 Rev. 11/2025; ODM MEPL 194 | 2026-06-27 | Household, tax, income, self-employment, other-income, and expense explanations. |
| `special-pathways-and-coverage.md` | ODM 07216 Rev. 11/2025; ODM MEPL 192; ODM MEPL 194 | 2026-06-27 | Pregnancy, retroactive bills, immigration, ABD/LTC/Appendix E, MPAP, and coverage guidance. |
| `documents-and-next-steps.md` | ODM 07216 Rev. 11/2025; Ohio Medicaid consumer guidance | 2026-06-27 | What documents to gather and what happens after submitting (county review, ~45-day decision, retroactive coverage, annual renewal). |

Bundled KB documents are seeded automatically on FastAPI startup by
`app.forms.seed.seed_kb_from_packs`. Admin-created KB documents can still be added
from the builder and are left intact by the bundled seeder.

## Official URLs

- ODM 07216, Application for Health Coverage and Help Paying Costs:
  https://dam.assets.ohio.gov/image/upload/medicaid.ohio.gov/Resources/Publications/Forms/ODM07216fillx.pdf
- ODM MEPL 192, ODM 07216 application update:
  https://dam.assets.ohio.gov/image/upload/medicaid.ohio.gov/About%20Us/PoliciesGuidelines/MEPL/MEPL_192_-_ODM_07216_Application_for_Health_Coverage.pdf
- ODM MEPL 194, 2026 Federal Poverty Level Income Guidelines:
  https://dam.assets.ohio.gov/image/upload/medicaid.ohio.gov/About%20Us/PoliciesGuidelines/MEPL/MEPL_194_-_2026_Federal_Poverty_Level_Income_Guidelines.pdf
- ODM 2026 Monthly Financial Eligibility chart:
  https://dam.assets.ohio.gov/image/upload/medicaid.ohio.gov/Families%2C%20Individuals/Programs/whoQualifies/2026_Children_Families_Adults.pdf
