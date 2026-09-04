"""check

Revision ID: ebdda1d15ae5
Revises: 3c97235fa47a
Create Date: 2026-08-11 01:23:54.262799

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'ebdda1d15ae5'
down_revision: Union[str, Sequence[str], None] = '3c97235fa47a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('file_hashes', 'verified_at',
               existing_type=postgresql.TIMESTAMP(),
               type_=sa.DateTime(timezone=True),
               existing_nullable=True)
    op.create_unique_constraint(None, 'file_hashes', ['file_id'])
    op.alter_column('files', 'invalidated_at',
               existing_type=postgresql.TIMESTAMP(),
               type_=sa.DateTime(timezone=True),
               existing_nullable=True)
    op.create_index(op.f('ix_files_patient_id'), 'files', ['patient_id'], unique=False)
    op.create_index('ix_patient_assignments_user_patient', 'patient_assignments', ['user_id', 'patient_id'], unique=False)
    op.drop_column('patient_assignments', 'last_checked_at')
    op.alter_column('patients', 'height', new_column_name='height_cm')
    op.alter_column('patients', 'weight', new_column_name='weight_kg')
    op.create_index(op.f('ix_treatment_notes_patient_id'), 'treatment_notes', ['patient_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_treatment_notes_patient_id'), table_name='treatment_notes')
    op.alter_column('patients', 'height_cm', new_column_name='height')
    op.alter_column('patients', 'weight_kg', new_column_name='weight')
    op.add_column('patient_assignments', sa.Column('last_checked_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True))
    op.drop_index('ix_patient_assignments_user_patient', table_name='patient_assignments')
    op.drop_index(op.f('ix_files_patient_id'), table_name='files')
    op.alter_column('files', 'invalidated_at',
               existing_type=sa.DateTime(timezone=True),
               type_=postgresql.TIMESTAMP(),
               existing_nullable=True)
    op.drop_constraint(None, 'file_hashes', type_='unique')
    op.alter_column('file_hashes', 'verified_at',
               existing_type=sa.DateTime(timezone=True),
               type_=postgresql.TIMESTAMP(),
               existing_nullable=True)