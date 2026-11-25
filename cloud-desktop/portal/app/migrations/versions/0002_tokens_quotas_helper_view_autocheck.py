"""tokens quotas helper view autocheck

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-25 12:30:29.165357
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('revoked_tokens',
    sa.Column('jti', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('jti')
    )
    with op.batch_alter_table('revoked_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_revoked_tokens_expires_at'), ['expires_at'], unique=False)

    with op.batch_alter_table('assignments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('check_script', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('check_image', sa.String(length=255), server_default='', nullable=False))
        batch_op.add_column(sa.Column('check_timeout', sa.Integer(), server_default='60', nullable=False))
        batch_op.add_column(sa.Column('show_check_to_student', sa.Boolean(), server_default='1', nullable=False))

    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.create_index('ix_audit_user_action_time', ['username', 'action', 'created_at'], unique=False)

    with op.batch_alter_table('desktop_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('helper_name', sa.String(length=128), server_default='', nullable=False))
        batch_op.add_column(sa.Column('helper_mode', sa.String(length=8), server_default='', nullable=False))
        batch_op.add_column(sa.Column('helper_seen_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('submissions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('check_status', sa.String(length=16), server_default='', nullable=False))
        batch_op.add_column(sa.Column('check_output', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('checked_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('token_version', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('must_change_password', sa.Boolean(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('disk_used_bytes', sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column('disk_checked_at', sa.DateTime(), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('disk_checked_at')
        batch_op.drop_column('disk_used_bytes')
        batch_op.drop_column('must_change_password')
        batch_op.drop_column('token_version')

    with op.batch_alter_table('submissions', schema=None) as batch_op:
        batch_op.drop_column('checked_at')
        batch_op.drop_column('check_output')
        batch_op.drop_column('check_status')

    with op.batch_alter_table('desktop_sessions', schema=None) as batch_op:
        batch_op.drop_column('helper_seen_at')
        batch_op.drop_column('helper_mode')
        batch_op.drop_column('helper_name')

    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_index('ix_audit_user_action_time')

    with op.batch_alter_table('assignments', schema=None) as batch_op:
        batch_op.drop_column('show_check_to_student')
        batch_op.drop_column('check_timeout')
        batch_op.drop_column('check_image')
        batch_op.drop_column('check_script')

    with op.batch_alter_table('revoked_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_revoked_tokens_expires_at'))

    op.drop_table('revoked_tokens')
