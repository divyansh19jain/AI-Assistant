"""Household builder — model the household once, then populate ODM person fields.

A real caseworker establishes the household up front (who lives here, who is applying,
who files taxes with whom) and *derives* the form answers from it, instead of asking
raw PDF questions one by one. This module turns a small structured household model into
ODM_07216 field values (applicant + Person 2) and the household size used for MAGI
income screening.

ODM_07216 has slots for the applicant (carried into Person 1) plus one additional
Person 2; larger households still inform the household-size estimate used for screening.
"""

from __future__ import annotations

from dataclasses import dataclass

# Relationship roles, relative to the applicant.
SELF = "self"
SPOUSE = "spouse"
CHILD = "child"
DEPENDENT = "dependent"
OTHER = "other"

_ODM_RELATIONSHIP = {SELF: "Self", SPOUSE: "Spouse", CHILD: "Child", DEPENDENT: "Dependent"}


@dataclass
class HouseholdMember:
    first_name: str = ""
    middle_name: str = ""
    last_name: str = ""
    relationship: str = OTHER       # relationship TO the applicant
    applying: bool = True           # is this person applying for coverage?
    dob: str | None = None          # MM/DD/YYYY or YYYY-MM-DD
    sex: str | None = None          # Male | Female | Other
    is_tax_dependent: bool = False  # claimed as a tax dependent by the applicant


def household_size(members: list[HouseholdMember]) -> int:
    """A simple MAGI-style household-size estimate: the applicant, their spouse, and
    anyone claimed as a tax dependent. This is an ESTIMATE used to screen income — the
    deterministic ODM screen tools and the county confirm the official size."""
    size = 0
    for m in members:
        rel = (m.relationship or "").strip().lower()
        if rel in (SELF, SPOUSE) or m.is_tax_dependent or rel in (CHILD, DEPENDENT):
            size += 1
    return max(size, 1)


def to_odm_field_values(members: list[HouseholdMember]) -> dict:
    """Map a household into ODM_07216 applicant/Person 2 field values.

    Returns an insertion-ordered dict so the Person 2 gate (``adding_person2``) is set
    before the dependent Person 2 fields — important when values are applied one at a
    time through validation + correction-aware invalidation.
    """
    values: dict = {}
    self_member = next((m for m in members if (m.relationship or "").strip().lower() == SELF), None)
    if self_member:
        if self_member.first_name:
            values["applicant.first_name"] = self_member.first_name
        if self_member.middle_name:
            values["applicant.middle_name"] = self_member.middle_name
        if self_member.last_name:
            values["applicant.last_name"] = self_member.last_name

    others = [m for m in members if m is not self_member and m.applying]
    if others:
        p2 = others[0]
        values["person2.adding_person2"] = True   # gate first
        if p2.first_name:
            values["person2.first_name"] = p2.first_name
        if p2.middle_name:
            values["person2.middle_name"] = p2.middle_name
        if p2.last_name:
            values["person2.last_name"] = p2.last_name
        values["person2.relationship_to_applicant"] = _odm_relationship(p2.relationship)
        if p2.dob:
            values["person2.dob"] = p2.dob
        if p2.sex:
            values["person2.sex"] = p2.sex
    return values


def _odm_relationship(rel: str) -> str:
    rel = (rel or "").strip().lower()
    return _ODM_RELATIONSHIP.get(rel, (rel.title() if rel else "Other"))
