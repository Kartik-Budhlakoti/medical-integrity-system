"""add doctor specialty field

Revision ID: 1898b5471c4b
Revises: ebdda1d15ae5
Create Date: 2026-09-10 08:59:11.255622

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1898b5471c4b'
down_revision: Union[str, Sequence[str], None] = 'ebdda1d15ae5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('nursing_notes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('patient_id', sa.Integer(), nullable=False),
        sa.Column('nursing_by_id', sa.Integer(), nullable=False),
        sa.Column('care_notes', sa.String(), nullable=False),
        sa.Column('blood_pressure', sa.String(), nullable=True),
        sa.Column('heart_rate', sa.Integer(), nullable=True),
        sa.Column('respiratory_rate', sa.Integer(), nullable=True),
        sa.Column('pain_level', sa.Integer(), nullable=True),
        sa.Column('temperature_celsius', sa.Float(), nullable=True),
        sa.Column('oxygen_saturation', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.CheckConstraint('heart_rate >= 0 AND heart_rate <= 300', name='heart_rate_range'),
        sa.CheckConstraint('oxygen_saturation >= 0 AND oxygen_saturation <= 100', name='spo2_range'),
        sa.CheckConstraint('pain_level >= 0 AND pain_level <= 10', name='pain_level_range'),
        sa.CheckConstraint('respiratory_rate >= 0 AND respiratory_rate <= 60', name='respiratory_rate_range'),
        sa.CheckConstraint('temperature_celsius >= 25 AND temperature_celsius <= 45', name='temp_range'),
        sa.ForeignKeyConstraint(['nursing_by_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_nursing_notes_id'), 'nursing_notes', ['id'], unique=False)
    op.create_index(op.f('ix_nursing_notes_patient_id'), 'nursing_notes', ['patient_id'], unique=False)
    op.add_column('users', sa.Column('specialty', sa.String(), nullable=True))
    op.create_check_constraint(
        'specialty_valid_values',
        'users',
        "specialty IN ('General Medicine', 'Cardiology', 'Orthopedics', 'Neurology', 'Pediatrics', 'Emergency Medicine')"
    )
    op.create_index(op.f('ix_users_role_id'), 'users', ['role_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_users_role_id'), table_name='users')
    op.drop_constraint('specialty_valid_values', 'users', type_='check')
    op.drop_column('users', 'specialty')
    op.drop_index(op.f('ix_nursing_notes_patient_id'), table_name='nursing_notes')
    op.drop_index(op.f('ix_nursing_notes_id'), table_name='nursing_notes')
    op.drop_table('nursing_notes')