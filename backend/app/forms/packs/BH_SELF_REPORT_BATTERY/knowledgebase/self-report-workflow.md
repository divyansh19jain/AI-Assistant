# Behavioral Health Self-Report Workflow

This form pack is a battery of self-administered behavioral health screening
tools. The client can complete one or more tools in a single voice or touch
session. The selected tools are stored as `selected.*` gate fields before the
interview starts, so only the chosen assessment sections become applicable.

The assistant should explain that these are screening tools, not diagnoses. The
client should choose the closest answer. If the client is unsure, the assistant
should repeat the answer choices and clarify the recall period.

Common recall periods:

- PHQ-9 and GAD-7: last two weeks.
- PCL-5: past month, tied to a stressful or traumatic experience.
- WHODAS 2.0 and DLA-20 self-report functioning: last 30 days.
- TAPS and DAST-10: past 12 months for this pack.
- C-SSRS self-report screener: past month for ideation questions, lifetime for
  behavior item.

The assistant should not calculate scores in free text. Scores are calculated by
`app.clinical.scoring` after answers are saved, then shown in review, PDF summary,
and the clinical results API.
