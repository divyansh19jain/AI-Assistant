# Sources And Licensing Notes

This pack contains assistant-friendly self-report prompts and deterministic
scoring logic for a demo/implementation framework. Before production deployment,
the organization should verify the exact official instrument text, scoring rules,
and license/permission requirements for each assessment it intends to use.

Tools represented:

- DSM-5-TR Level 1 Cross-Cutting symptom domains.
- PHQ-9.
- GAD-7.
- C-SSRS Self-Report style screener.
- AUDIT-C.
- TAPS screen.
- DAST-10.
- PCL-5.
- MDQ.
- WHODAS 2.0 12-item simple scoring.
- DLA-20-style self-report functioning domains.

Implementation note: patient answers are not stored in this knowledgebase. Scores
are computed from `form_answers` at runtime.
