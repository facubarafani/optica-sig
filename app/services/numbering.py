"""Auto-numbering for documents (sales, quotes, work orders, repairs).

Counters live in ``number_sequences`` (one per company + key). Formatted output
is ``f"{prefix}{value:0{padding}d}"`` — e.g. key=``sale`` prefix=``V-`` →
``V-000123``.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import NumberSequence

# Well-known sequence keys (transactional modules will consume these).
KEY_SALE = "sale"
KEY_QUOTE = "quote"
KEY_WORK_ORDER = "work_order"
KEY_REPAIR = "repair"

DEFAULT_PREFIXES = {
    KEY_SALE: "V-",
    KEY_QUOTE: "P-",
    KEY_WORK_ORDER: "OT-",
    KEY_REPAIR: "AR-",
}


def peek_sequence(db: Session, company_id: int, key: str) -> NumberSequence | None:
    return db.execute(
        select(NumberSequence).where(
            NumberSequence.company_id == company_id, NumberSequence.key == key
        )
    ).scalar_one_or_none()


def next_number(
    db: Session,
    company_id: int,
    key: str,
    *,
    default_prefix: str | None = None,
    default_padding: int = 6,
    commit: bool = True,
) -> str:
    """Atomically consume and return the next formatted number for ``key``.

    Creates the sequence on first use. Uses ``SELECT ... FOR UPDATE`` to avoid
    duplicate numbers under concurrency (no-op on SQLite used in tests).
    """
    stmt = select(NumberSequence).where(
        NumberSequence.company_id == company_id, NumberSequence.key == key
    )
    if db.bind is not None and db.bind.dialect.name != "sqlite":
        stmt = stmt.with_for_update()
    seq = db.execute(stmt).scalar_one_or_none()

    if seq is None:
        prefix = default_prefix if default_prefix is not None else DEFAULT_PREFIXES.get(key, "")
        seq = NumberSequence(
            company_id=company_id, key=key, prefix=prefix, next_value=1,
            padding=default_padding,
        )
        db.add(seq)
        db.flush()

    value = seq.next_value
    seq.next_value = value + 1
    db.add(seq)
    if commit:
        db.commit()
    return f"{seq.prefix}{value:0{seq.padding}d}"
