"""create job_postings table

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    employment_type = sa.Enum(
        "full_time", "part_time", "contract", "internship", name="employment_type"
    )
    job_status = sa.Enum("draft", "open", "closed", name="job_status")

    op.create_table(
        "job_postings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=False),
        sa.Column("employment_type", employment_type, nullable=False),
        sa.Column("status", job_status, nullable=False, server_default="draft"),
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("salary_max", sa.Integer(), nullable=True),
        sa.Column("recruiter_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["recruiter_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_job_postings_status", "job_postings", ["status"])
    op.create_index("ix_job_postings_recruiter_id", "job_postings", ["recruiter_id"])


def downgrade() -> None:
    op.drop_index("ix_job_postings_recruiter_id", table_name="job_postings")
    op.drop_index("ix_job_postings_status", table_name="job_postings")
    op.drop_table("job_postings")
    sa.Enum(name="job_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="employment_type").drop(op.get_bind(), checkfirst=True)
