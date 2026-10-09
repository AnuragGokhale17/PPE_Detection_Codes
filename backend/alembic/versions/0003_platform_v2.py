"""Platform v2: plant config, class registry, review columns, annotation, training

Additive only. New nullable columns on ppes are metadata-only changes in PostgreSQL.
Seeds the PPE items, the 12-class registry (thresholds taken from inference.py) and
the current best12classes.pt as the active baseline model.

Revision ID: 0003_platform_v2
Revises: 0002_permissions
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_platform_v2"
down_revision = "0002_permissions"
branch_labels = None
depends_on = None

Json = sa.JSON().with_variant(JSONB(), "postgresql")


def _ts(name: str, **kw):
    return sa.Column(name, sa.DateTime(timezone=True), **kw)


def _created():
    return _ts("created_at", nullable=False, server_default=sa.func.now())


PPE_ITEMS = [
    # id, key, display, sort
    (1, "helmet", "Helmet", 1),
    (2, "gloves", "Gloves", 2),
    (3, "goggles", "Goggles", 3),
    (4, "mask", "Mask", 4),
    (5, "suit", "Suit", 5),
    (6, "shoes", "Shoes", 6),
]
PPE_ID = {key: pid for pid, key, _, _ in PPE_ITEMS}

# class_id, name, ppe key, is_violation, threshold (DetectTray.class_thresholds)
MODEL_CLASSES = [
    (0, "Gloves", "gloves", False, 0.70),
    (1, "Goggles", "goggles", False, 0.60),
    (2, "Helmet", "helmet", False, 0.70),
    (3, "Mask", "mask", False, 0.60),
    (4, "No Gloves", "gloves", True, 0.80),
    (5, "No Goggles", "goggles", True, 0.60),
    (6, "No Helmet", "helmet", True, 0.78),
    (7, "No Mask", "mask", True, 0.58),
    (8, "No Shoes", "shoes", True, 0.80),
    (9, "No Suit", "suit", True, 0.65),
    (10, "Shoes", "shoes", False, 0.70),
    (11, "Suit", "suit", False, 0.65),
]


def upgrade() -> None:
    # --- Plant configuration -------------------------------------------------
    op.create_table(
        "plants",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        _created(),
    )
    op.create_table(
        "production_houses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("plant_id", sa.Integer, sa.ForeignKey("plants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        _created(),
        sa.UniqueConstraint("plant_id", "name", name="uq_production_house"),
    )
    ppe_items = op.create_table(
        "ppe_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String(50), nullable=False, unique=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "cameras",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "production_house_id",
            sa.Integer,
            sa.ForeignKey("production_houses.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("area", sa.String(150), nullable=False),
        sa.Column("stream_url", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("scale_up", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text),
        _created(),
        _ts("updated_at", nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("production_house_id", "area", name="uq_camera_area"),
    )
    op.create_table(
        "camera_ppe",
        sa.Column("camera_id", sa.Integer, sa.ForeignKey("cameras.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("ppe_item_id", sa.Integer, sa.ForeignKey("ppe_items.id", ondelete="CASCADE"), primary_key=True),
    )
    model_classes = op.create_table(
        "model_classes",
        sa.Column("class_id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("ppe_item_id", sa.Integer, sa.ForeignKey("ppe_items.id", ondelete="SET NULL")),
        sa.Column("is_violation", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("threshold", sa.Float, nullable=False, server_default="0.55"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "alert_recipients",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("channel", sa.String(20), nullable=False, server_default="violation"),
        sa.Column("production_house_id", sa.Integer, sa.ForeignKey("production_houses.id", ondelete="CASCADE")),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(3), nullable=False, server_default="to"),
        sa.Column("designation", sa.String(150)),
    )
    op.create_index("ix_alert_recipients_lookup", "alert_recipients", ["channel", "production_house_id"])

    # --- Runtime coordination ------------------------------------------------
    runtime_state = op.create_table(
        "runtime_state",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("config_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("inference_paused", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("pause_reason", sa.Text),
        sa.Column("active_model_id", sa.Integer),
        _ts("updated_at", nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255)),
    )
    op.create_table(
        "worker_heartbeats",
        sa.Column("name", sa.String(50), primary_key=True),
        _ts("last_seen", nullable=False),
        sa.Column("info", Json),
    )

    # --- Detection events: v2 columns ----------------------------------------
    for column in (
        sa.Column("camera_id", sa.Integer),
        sa.Column("raw_image_key", sa.Text),
        sa.Column("detections", Json),
        sa.Column("frame_width", sa.Integer),
        sa.Column("frame_height", sa.Integer),
        sa.Column("model_version_id", sa.Integer),
        sa.Column("review_status", sa.String(20)),
        sa.Column("reviewed_by", sa.Integer),
        _ts("reviewed_at"),
        sa.Column("review_notes", sa.Text),
    ):
        op.add_column("ppes", column)
    # Indexes recommended in the KT document; production may already have some of them
    op.create_index("idx_ppes_date_violation", "ppes", ["date1", "violation"], if_not_exists=True)
    op.create_index("idx_ppes_area_ph", "ppes", ["production_house", "area"], if_not_exists=True)
    op.create_index("idx_ppes_review_status", "ppes", ["review_status"], if_not_exists=True)
    op.create_index("idx_camera_health_status", "camera_health", ["status"], if_not_exists=True)

    # --- Annotation ------------------------------------------------------------
    op.create_table(
        "samples",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("image_key", sa.Text, nullable=False),
        sa.Column("width", sa.Integer, nullable=False),
        sa.Column("height", sa.Integer, nullable=False),
        sa.Column("image_sha1", sa.String(40), index=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("ppes_id", sa.Integer, index=True),
        sa.Column("camera_id", sa.Integer),
        sa.Column("production_house", sa.String(100)),
        sa.Column("area", sa.String(150)),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft", index=True),
        sa.Column("split", sa.String(5)),
        sa.Column("notes", sa.Text),
        sa.Column("reject_reason", sa.Text),
        sa.Column("created_by", sa.Integer),
        _created(),
        _ts("updated_at", nullable=False, server_default=sa.func.now()),
        _ts("submitted_at"),
        sa.Column("approved_by", sa.Integer),
        _ts("approved_at"),
    )
    op.create_table(
        "sample_labels",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("sample_id", sa.Integer, sa.ForeignKey("samples.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("class_id", sa.Integer, nullable=False),
        sa.Column("cx", sa.Float, nullable=False),
        sa.Column("cy", sa.Float, nullable=False),
        sa.Column("w", sa.Float, nullable=False),
        sa.Column("h", sa.Float, nullable=False),
        sa.Column("origin", sa.String(10), nullable=False, server_default="human"),
        sa.Column("conf", sa.Float),
    )

    # --- Datasets, training, models --------------------------------------------
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="building"),
        sa.Column("val_ratio", sa.Float, nullable=False, server_default="0.2"),
        sa.Column("s3_prefix", sa.Text, nullable=False),
        sa.Column("sample_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("train_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("val_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("class_names", Json),
        sa.Column("class_counts", Json),
        sa.Column("notes", sa.Text),
        sa.Column("error", sa.Text),
        sa.Column("created_by", sa.Integer),
        _created(),
        _ts("finished_at"),
    )
    op.create_table(
        "dataset_samples",
        sa.Column(
            "dataset_version_id", sa.Integer, sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("sample_id", sa.Integer, sa.ForeignKey("samples.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("split", sa.String(5), nullable=False),
    )
    model_versions = op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("weights_path", sa.Text, nullable=False),
        sa.Column("class_names", Json),
        sa.Column("metrics", Json),
        sa.Column("source", sa.String(20), nullable=False, server_default="training"),
        sa.Column("training_run_id", sa.Integer),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text),
        _created(),
        _ts("activated_at"),
        sa.Column("activated_by", sa.String(255)),
    )
    op.create_table(
        "training_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("dataset_version_id", sa.Integer, sa.ForeignKey("dataset_versions.id"), nullable=False),
        sa.Column("base_model_id", sa.Integer, sa.ForeignKey("model_versions.id"), nullable=False),
        sa.Column("params", Json, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued", index=True),
        sa.Column("cancel_requested", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("progress", Json),
        sa.Column("metrics", Json),
        sa.Column("baseline_metrics", Json),
        sa.Column("log_tail", sa.Text),
        sa.Column("error", sa.Text),
        sa.Column("result_model_id", sa.Integer),
        sa.Column("created_by", sa.Integer),
        _created(),
        _ts("started_at"),
        _ts("finished_at"),
    )

    # --- Seed data ----------------------------------------------------------------
    op.bulk_insert(
        ppe_items,
        [{"id": i, "key": k, "display_name": d, "sort_order": s, "enabled": True} for i, k, d, s in PPE_ITEMS],
    )
    op.bulk_insert(
        model_classes,
        [
            {
                "class_id": cid,
                "name": name,
                "ppe_item_id": PPE_ID[ppe],
                "is_violation": violation,
                "threshold": threshold,
                "enabled": True,
            }
            for cid, name, ppe, violation, threshold in MODEL_CLASSES
        ],
    )
    op.bulk_insert(
        model_versions,
        [
            {
                "id": 1,
                "name": "best12classes (baseline)",
                "weights_path": "model/best12classes.pt",
                "class_names": [name for _, name, _, _, _ in MODEL_CLASSES],
                "source": "baseline",
                "is_active": True,
                "notes": "Model in production before the v2 platform",
            }
        ],
    )
    op.bulk_insert(runtime_state, [{"id": 1, "config_version": 1, "inference_paused": False, "active_model_id": 1}])

    # Explicit ids above; move the PostgreSQL sequences past them
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in ("ppe_items", "model_versions", "runtime_state"):
            op.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT MAX(id) FROM {table}))")


def downgrade() -> None:
    for table in (
        "training_runs",
        "model_versions",
        "dataset_samples",
        "dataset_versions",
        "sample_labels",
        "samples",
    ):
        op.drop_table(table)
    op.drop_index("idx_ppes_review_status", table_name="ppes")
    for column in (
        "review_notes",
        "reviewed_at",
        "reviewed_by",
        "review_status",
        "model_version_id",
        "frame_height",
        "frame_width",
        "detections",
        "raw_image_key",
        "camera_id",
    ):
        op.drop_column("ppes", column)
    for table in (
        "worker_heartbeats",
        "runtime_state",
        "alert_recipients",
        "model_classes",
        "camera_ppe",
        "cameras",
        "ppe_items",
        "production_houses",
        "plants",
    ):
        op.drop_table(table)
