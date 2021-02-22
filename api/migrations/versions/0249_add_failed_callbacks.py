"""

Revision ID: 0249
Revises: 0248
Create Date: 2020-06-23 17:43:51.872861

"""
from alembic import op
from sqlalchemy.dialects import postgresql
import sqlalchemy as sa


revision = '0249'
down_revision = '0248'


def upgrade():
    op.create_table('batches',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('client_reference', sa.String(), nullable=True),
        sa.Column('service_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('template_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('template_version', sa.Integer(), nullable=False),
        sa.Column('api_key_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('key_type', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['service_id'], ['services.id'], ),
        sa.ForeignKeyConstraint(['template_id'], ['templates.id'], ),
        sa.ForeignKeyConstraint(['api_key_id'], ['api_keys.id'], ),
        sa.ForeignKeyConstraint(['key_type'], ['key_types.name'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_batches_client_reference'), 'batches', ['client_reference'], unique=False)
    op.create_index(op.f('ix_batches_service_id'), 'batches', ['service_id'], unique=False)
    op.create_index(op.f('ix_batches_template_id'), 'batches', ['template_id'], unique=False)
    op.create_index(op.f('ix_batches_api_key_id'), 'batches', ['api_key_id'], unique=False)
    op.create_index(op.f('ix_batches_key_type'), 'batches', ['key_type'], unique=False)

    op.add_column('notifications', sa.Column('batch_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('notification_history', sa.Column('batch_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(op.f('ix_notifications_batch_id'), 'notifications', ['batch_id'], unique=False)
    op.create_index(op.f('ix_notification_history_batch_id'), 'notification_history', ['batch_id'], unique=False)
    op.create_foreign_key(None, 'notifications', 'batches', ['batch_id'], ['id'])
    op.create_foreign_key(None, 'notification_history', 'batches', ['batch_id'], ['id'])


def downgrade():
    op.drop_column('notification_history', 'batch_id')
    op.drop_column('notifications', 'batch_id')

    op.drop_index(op.f('ix_batches_key_type'), table_name='batches')
    op.drop_index(op.f('ix_batches_api_key_id'), table_name='batches')
    op.drop_index(op.f('ix_batches_template_id'), table_name='batches')
    op.drop_index(op.f('ix_batches_service_id'), table_name='batches')
    op.drop_index(op.f('ix_batches_client_reference'), table_name='batches')
    op.drop_table('batches')
