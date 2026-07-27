"""Schema introspection helpers for migrations.

``0001_initial`` builds the schema from ``Base.metadata`` (see its docstring),
so it always produces whatever the models say *today*. That means a brand-new
database arrives at the later revisions with the current schema already in
place, while a database created earlier arrives with the old one.

Every migration that alters a table present in the initial revision must
therefore be written defensively, so both paths converge on the same schema.
These helpers make that check a one-liner.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def has_table(table: str) -> bool:
    return table in _inspector().get_table_names()


def has_column(table: str, column: str) -> bool:
    insp = _inspector()
    if table not in insp.get_table_names():
        return False
    return any(c["name"] == column for c in insp.get_columns(table))
