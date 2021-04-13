"""

Revision ID: 0250
Revises: 0249
Create Date: 2020-10-26 12:16:17.119733

"""
from alembic import op
import sqlalchemy as sa


revision = '0250'
down_revision = '0249'


def upgrade():
    op.add_column('users', sa.Column('time_zone', sa.String(), nullable=True))


def downgrade():
    op.drop_column('users', 'time_zone')
