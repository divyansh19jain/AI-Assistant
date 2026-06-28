"""Guard: a field that depends on a gate must appear AFTER that gate in the schema.

A child-before-parent ordering (e.g. home_address before is_homeless) lets the agent
collect the child before the gate is set, after which correction-aware cleanup can drop
it as 'not applicable' — so it gets re-asked. This test fails loudly on any such defect.
"""

import pytest

from app.forms import registry
from app.forms.service import get_all_fields_from_schema, load_form_schema


def _violations(form_id: str) -> list[tuple[str, str]]:
    fields = get_all_fields_from_schema(load_form_schema(form_id))
    order = {f["field_key"]: i for i, f in enumerate(fields)}
    out: list[tuple[str, str]] = []
    for i, f in enumerate(fields):
        dep = f.get("depends_on")
        gate = dep.get("field_key") if isinstance(dep, dict) else None
        if gate and gate in order and order[gate] > i:
            out.append((f["field_key"], gate))  # child before parent
    return out


@pytest.mark.parametrize("form_id", [p.form_id for p in registry.list_packs(active_only=False)])
def test_no_child_before_parent_dependency(form_id):
    violations = _violations(form_id)
    assert not violations, f"{form_id}: field(s) appear before their gate: {violations}"
