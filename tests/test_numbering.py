"""Auto-numbering service unit tests."""
from app.services import numbering


def test_sequence_increments_and_formats(db):
    n1 = numbering.next_number(db, 1, numbering.KEY_SALE)
    n2 = numbering.next_number(db, 1, numbering.KEY_SALE)
    assert n1 == "V-000001"
    assert n2 == "V-000002"


def test_sequences_are_independent_per_key(db):
    sale = numbering.next_number(db, 1, numbering.KEY_SALE)
    quote = numbering.next_number(db, 1, numbering.KEY_QUOTE)
    assert sale == "V-000001"
    assert quote == "P-000001"


def test_custom_prefix_and_padding(db):
    n = numbering.next_number(
        db, 1, "custom", default_prefix="C#", default_padding=4
    )
    assert n == "C#0001"


def test_audit_record_change(db):
    from app.services import audit

    audit.record_change(
        db, company_id=1, entity_type="product", entity_id=5,
        field_name="current_cost", old_value=100, new_value=120, commit=True,
    )
    changes = audit.list_changes(db, company_id=1, entity_type="product", entity_id=5)
    assert len(changes) == 1
    assert changes[0].old_value == "100"
    assert changes[0].new_value == "120"
