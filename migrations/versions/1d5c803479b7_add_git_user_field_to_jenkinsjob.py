"""Add git_user field to JenkinsJob

Revision ID: 1d5c803479b7
Revises: dbdf92bdeb1b
Create Date: 2025-04-14 18:26:49.267682

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1d5c803479b7'
down_revision = 'dbdf92bdeb1b'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('jenkins_job', schema=None) as batch_op:
        batch_op.add_column(sa.Column('git_user', sa.String(length=100), nullable=False))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('jenkins_job', schema=None) as batch_op:
        batch_op.drop_column('git_user')

    # ### end Alembic commands ###
