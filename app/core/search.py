"""Case- and accent-insensitive text matching, portable across our two engines.

Spanish catalogues are full of accents ("Armazón", "Bordó") but nobody types
them into a search box. Postgres could fold them with the ``unaccent``
extension; the test suite runs on in-memory SQLite, which has no such thing
(see CLAUDE.md — models and queries stay portable). A chain of ``replace()``
calls is less elegant but behaves identically on both, and these tables are
small enough that the sequential scan costs nothing.

If a catalogue ever grows past that assumption, the fix is a stored normalised
column with an index on it — not a new dependency.
"""
from __future__ import annotations

from sqlalchemy import ColumnElement, and_, func, or_

# Only the letters Spanish actually needs; ç/à etc. would just add work.
_FOLD = (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
         ("ü", "u"), ("ñ", "n"))


def normalize(text: str | None) -> str:
    """Lower-case and strip accents, the Python-side twin of ``searchable``."""
    out = (text or "").strip().lower()
    for accented, plain in _FOLD:
        out = out.replace(accented, plain)
    return out


def searchable(col) -> ColumnElement[str]:
    """SQL expression folding a column exactly the way ``normalize`` folds a str."""
    expr = func.lower(col)
    for accented, plain in _FOLD:
        expr = func.replace(expr, accented, plain)
    return expr


def terms(q: str | None) -> list[str]:
    return [t for t in normalize(q).split() if t]


def matches(q: str | None, *cols) -> ColumnElement[bool] | None:
    """Build "every term appears in at least one of these columns".

    Splitting on whitespace is what makes ``armazon negro`` find *Armazón
    clásico negro*: the words need not be adjacent, in order, or in the same
    column. Returns None when there is nothing to search for, so callers can
    skip the clause entirely.
    """
    clauses = [
        or_(*[searchable(c).like(f"%{term}%") for c in cols])
        for term in terms(q)
    ]
    return and_(*clauses) if clauses else None
