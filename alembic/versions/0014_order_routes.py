"""order routes on the Iran map: warehouse origin city, frozen route, driver checkpoints

Revision ID: 0014_order_routes
Revises: 0013_request_referral
Create Date: 2026-10-12

۱. warehouses.province/city — مبدأ مسیر؛ از روی متن «location» انبارهای موجود (اگر نام یک شهر شناخته‌شده باشد) پر می‌شود.
۲. orders.route — مسیر شهربه‌شهری که با شروع حرکت ثابت می‌شود.
۳. order_checkpoints — گزارش «رسیدم به شهر ...» راننده.
"""
from alembic import op
import sqlalchemy as sa

from app.core import geo

revision = '0014_order_routes'
down_revision = '0013_request_referral'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('warehouses', sa.Column('province', sa.String(64), nullable=True))
    op.add_column('warehouses', sa.Column('city', sa.String(64), nullable=True))
    op.add_column('orders', sa.Column('route', sa.JSON(), nullable=True))
    op.create_table(
        'order_checkpoints',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('city', sa.String(64), nullable=False),
        sa.Column('province', sa.String(64), nullable=True),
        sa.Column('reached_at', sa.DateTime(), nullable=False),
        sa.Column('reported_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.UniqueConstraint('order_id', 'seq', name='uq_order_checkpoints_order_seq'),
    )

    # انبارهای موجود: اگر «location» نام یک شهر شناخته‌شده است (یا با آن شروع می‌شود)، شهر و استان پر شود
    bind = op.get_bind()
    for wid, location in bind.execute(sa.text("SELECT id, location FROM warehouses")).fetchall():
        text = (location or "").replace("،", " ").replace(",", " ").strip()
        city = geo.find_city(text) or next((geo.find_city(w) for w in text.split() if geo.find_city(w)), None)
        if city:
            bind.execute(sa.text("UPDATE warehouses SET province = :p, city = :c WHERE id = :id"),
                         {"p": city.province, "c": city.name, "id": wid})


def downgrade():
    op.drop_table('order_checkpoints')
    op.drop_column('orders', 'route')
    op.drop_column('warehouses', 'city')
    op.drop_column('warehouses', 'province')
