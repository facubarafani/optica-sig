"""colours read out of product codes: remembered answers and rule

``color_aliases`` keeps what a shop decided each code tail means ("C1" is a
supplier number, "NERO" is Negro), and ``company_settings`` gains the rule that
finds the tail (separator + how many words), so an import starts from the
shop's own dialect instead of guessing it again.

Defensive per CLAUDE.md: 0001 is metadata-derived, so a fresh database already
has all of this by the time it lands here.

Revision ID: 0016_code_colors
Revises: 0015_roles_permisos_castellano
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.migration_utils import has_column, has_table

revision = "0016_code_colors"
down_revision = "0015_roles_permisos_castellano"
branch_labels = None
depends_on = None

# SQLAlchemy stores the member *name* (CLAUDE.md rule 7). Created once, up
# front; the column refers to it with create_type=False, which only the
# Postgres ENUM honours (a generic sa.Enum would CREATE TYPE again, empty).
LABELS = ("COLOR", "SUPPLIER_NUMBER", "NOT_COLOR")
KIND = postgresql.ENUM(*LABELS, name="color_alias_kind")


def upgrade() -> None:
    if not has_column("company_settings", "code_color_separator"):
        op.add_column("company_settings",
                      sa.Column("code_color_separator", sa.String(length=4)))
    if not has_column("company_settings", "code_color_max_words"):
        op.add_column("company_settings",
                      sa.Column("code_color_max_words", sa.Integer()))

    if not has_table("color_aliases"):
        KIND.create(op.get_bind(), checkfirst=True)
        op.create_table(
            "color_aliases",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("phrase", sa.String(length=40), nullable=False),
            sa.Column("kind", postgresql.ENUM(*LABELS, name="color_alias_kind",
                                              create_type=False),
                      nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"],
                                    ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("company_id", "phrase", name="uq_color_alias_phrase"),
        )
        op.create_index(op.f("ix_color_aliases_company_id"), "color_aliases",
                        ["company_id"])

    if not has_table("color_alias_colors"):
        op.create_table(
            "color_alias_colors",
            sa.Column("alias_id", sa.Integer(), nullable=False),
            sa.Column("color_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["alias_id"], ["color_aliases.id"],
                                    ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["color_id"], ["colors.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("alias_id", "color_id"),
        )


def downgrade() -> None:
    if has_table("color_alias_colors"):
        op.drop_table("color_alias_colors")
    if has_table("color_aliases"):
        op.drop_table("color_aliases")
    KIND.drop(op.get_bind(), checkfirst=True)
    if has_column("company_settings", "code_color_max_words"):
        op.drop_column("company_settings", "code_color_max_words")
    if has_column("company_settings", "code_color_separator"):
        op.drop_column("company_settings", "code_color_separator")
