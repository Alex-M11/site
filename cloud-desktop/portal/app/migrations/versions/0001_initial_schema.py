"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-11-25 12:30:07.916012
"""
from alembic import op
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=48), nullable=False),
    sa.Column('details', sa.Text(), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_log_action'), ['action'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_log_created_at'), ['created_at'], unique=False)

    op.create_table('groups',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('settings',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('full_name', sa.String(length=128), nullable=False),
    sa.Column('email', sa.String(length=128), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('quota_mb', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('last_login', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_username'), ['username'], unique=True)

    op.create_table('teacher_groups',
    sa.Column('teacher_id', sa.Integer(), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['teacher_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('teacher_id', 'group_id')
    )
    op.create_table('templates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('subject', sa.String(length=128), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('os_family', sa.String(length=32), nullable=False),
    sa.Column('image', sa.String(length=255), nullable=False),
    sa.Column('cpu', sa.Float(), nullable=False),
    sa.Column('memory_mb', sa.Integer(), nullable=False),
    sa.Column('shm_mb', sa.Integer(), nullable=False),
    sa.Column('env', sa.JSON(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('assignments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=False),
    sa.Column('template_id', sa.Integer(), nullable=True),
    sa.Column('teacher_id', sa.Integer(), nullable=True),
    sa.Column('due_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['teacher_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['template_id'], ['templates.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('desktop_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('template_id', sa.Integer(), nullable=False),
    sa.Column('container_id', sa.String(length=80), nullable=True),
    sa.Column('container_name', sa.String(length=128), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('host', sa.String(length=64), nullable=True),
    sa.Column('port', sa.Integer(), nullable=True),
    sa.Column('vnc_password', sa.String(length=64), nullable=False),
    sa.Column('error', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('last_activity', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['template_id'], ['templates.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'template_id', name='uq_session_user_template')
    )
    with op.batch_alter_table('desktop_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_desktop_sessions_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_desktop_sessions_user_id'), ['user_id'], unique=False)

    op.create_table('template_groups',
    sa.Column('template_id', sa.Integer(), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['template_id'], ['templates.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('template_id', 'group_id')
    )
    op.create_table('submissions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('assignment_id', sa.Integer(), nullable=False),
    sa.Column('student_id', sa.Integer(), nullable=False),
    sa.Column('comment', sa.Text(), nullable=False),
    sa.Column('files', sa.JSON(), nullable=False),
    sa.Column('submitted_at', sa.DateTime(), nullable=False),
    sa.Column('grade', sa.String(length=32), nullable=False),
    sa.Column('feedback', sa.Text(), nullable=False),
    sa.Column('graded_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['assignment_id'], ['assignments.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['student_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('assignment_id', 'student_id', name='uq_submission')
    )
    with op.batch_alter_table('submissions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_submissions_assignment_id'), ['assignment_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('submissions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_submissions_assignment_id'))

    op.drop_table('submissions')
    op.drop_table('template_groups')
    with op.batch_alter_table('desktop_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_desktop_sessions_user_id'))
        batch_op.drop_index(batch_op.f('ix_desktop_sessions_status'))

    op.drop_table('desktop_sessions')
    op.drop_table('assignments')
    op.drop_table('templates')
    op.drop_table('teacher_groups')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_username'))

    op.drop_table('users')
    op.drop_table('settings')
    op.drop_table('groups')
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_log_created_at'))
        batch_op.drop_index(batch_op.f('ix_audit_log_action'))

    op.drop_table('audit_log')
