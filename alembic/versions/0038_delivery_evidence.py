"""مدرک تحویل تغییرناپذیر: هر آپلود ردیف و فایل مستقل دارد

ردیف delivery_evidence متن آزاد ندارد و با تریگر تغییرناپذیر است. توضیح روش «سایر» در delivery_evidence_notes است تا هنگام پاک‌سازی
بدون دست زدن به مدرک حذف شود، و پاک شدن فایل یا توضیح در delivery_evidence_events می‌ماند.
ردیف‌های قدیمی فقط با چیزی که واقعاً ثبت شده بود ساخته می‌شوند: روش unrecorded و آپلودکننده، زمان، نوع، حجم و hash خالی.

برگشت: downgrade جدول‌ها و ردیف‌های تازه را حذف می‌کند و فایل‌ها روی دیسک می‌مانند. پس از ثبت مدرک واقعی این کار برای برگشت عملیاتی
توصیه نمی‌شود؛ کد قبلی با همین جدول‌ها هم کار می‌کند و photo_path به تازه‌ترین فایل اشاره دارد.

Revision ID: 0038_delivery_evidence
Revises: 0037_pg_stat_statements
"""
from alembic import op
import sqlalchemy as sa

revision = '0038_delivery_evidence'
down_revision = '0037_pg_stat_statements'
branch_labels = None
depends_on = None


def _org():
    return sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True)


def upgrade() -> None:
    op.create_table(
        'delivery_evidence',
        sa.Column('id', sa.Integer(), primary_key=True),
        _org(),
        sa.Column('attempt_id', sa.Integer(), sa.ForeignKey('delivery_attempts.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('storage_key', sa.String(255), nullable=False, unique=True),
        sa.Column('photo_type', sa.String(16), nullable=True),
        sa.Column('delivery_method', sa.String(24), nullable=False),
        sa.Column('media_type', sa.String(32), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=True),
        sa.Column('sha256', sa.String(64), nullable=True),
        sa.Column('uploaded_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=True, index=True),
        sa.Column('uploaded_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("delivery_method IN ('handed_to_recipient', 'left_at_door', 'other', 'unrecorded')", name='ck_delivery_evidence_method'),
        sa.CheckConstraint("delivery_method = 'unrecorded' OR (uploaded_by_id IS NOT NULL AND uploaded_at IS NOT NULL AND media_type IS NOT NULL "
                           "AND size_bytes IS NOT NULL AND sha256 IS NOT NULL)", name='ck_delivery_evidence_recorded'),
    )
    op.create_table(
        'delivery_evidence_notes',
        sa.Column('id', sa.Integer(), primary_key=True),
        _org(),
        sa.Column('evidence_id', sa.Integer(), sa.ForeignKey('delivery_evidence.id', ondelete='RESTRICT'), nullable=False, unique=True),
        sa.Column('note', sa.String(300), nullable=False),
    )
    op.create_table(
        'delivery_evidence_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        _org(),
        sa.Column('evidence_id', sa.Integer(), sa.ForeignKey('delivery_evidence.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('event_type', sa.String(16), nullable=False),
        sa.Column('reason', sa.String(200), nullable=False),
        sa.Column('at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("event_type IN ('file_deleted', 'note_redacted')", name='ck_delivery_evidence_events_type'),
    )
    op.execute("""
        INSERT INTO delivery_evidence (organization_id, attempt_id, storage_key, photo_type, delivery_method)
        SELECT organization_id, id, photo_path, photo_type, 'unrecorded' FROM delivery_attempts WHERE photo_path IS NOT NULL
    """)
    for table in ('delivery_evidence', 'delivery_evidence_events'):
        op.execute(f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION pasineh_immutable_row()")


def downgrade() -> None:
    op.drop_table('delivery_evidence_events')
    op.drop_table('delivery_evidence_notes')
    op.drop_table('delivery_evidence')
