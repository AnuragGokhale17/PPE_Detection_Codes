"""ORM models.

Legacy tables (users, password_history, otps, activity_logs, ppes, camera_health,
ppes_emails_records) are mirrored as the Flask app and inference.py use them today.
Changes to them must stay additive while both stacks share the database.
"""
from datetime import date, datetime, time

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

# JSONB on PostgreSQL, plain JSON elsewhere (SQLite in tests)
JsonType = JSON().with_variant(JSONB(), "postgresql")

# --- Legacy: authentication ------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column("_password_hash", String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    password_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_attempts: Mapped[int | None] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    permissions: Mapped[list["UserPermission"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def granted_permissions(self) -> set[str]:
        return {p.permission for p in self.permissions}


class PasswordHistory(Base):
    __tablename__ = "password_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column("_password_hash", String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LegacyOtp(Base):
    """Plaintext OTPs written by the Flask app. The new API uses AuthOtp instead."""

    __tablename__ = "otps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    otp_code: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer)
    user_email: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# --- Legacy: detection events ----------------------------------------------------


class PpeEvent(Base):
    """One row per violation image written by inference.py."""

    __tablename__ = "ppes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    class1: Mapped[str | None] = mapped_column(Text)
    production_house: Mapped[str | None] = mapped_column(Text)
    camera_unit: Mapped[str | None] = mapped_column(Text)
    date1: Mapped[date | None] = mapped_column(Date)
    time1: Mapped[time | None] = mapped_column(Time)
    image_url: Mapped[str | None] = mapped_column(Text)
    area: Mapped[str | None] = mapped_column(Text)
    camera_status: Mapped[bool | None] = mapped_column(Boolean, default=True)
    violation: Mapped[bool | None] = mapped_column(Boolean, default=True)
    violations: Mapped[str | None] = mapped_column(Text)
    compliance: Mapped[str | None] = mapped_column(Text)
    violation_count: Mapped[int | None] = mapped_column(Integer, default=0)
    compliance_count: Mapped[int | None] = mapped_column(Integer, default=0)
    people_count: Mapped[int | None] = mapped_column(Integer, default=0)
    violator_count: Mapped[int | None] = mapped_column(Integer, default=0)
    required_ppes: Mapped[str | None] = mapped_column(Text)

    # Added in v2 (0003). Rows written by the old inference.py leave these NULL.
    camera_id: Mapped[int | None] = mapped_column(Integer)
    raw_image_key: Mapped[str | None] = mapped_column(Text)
    detections: Mapped[list[dict[str, Any]] | None] = mapped_column(JsonType)
    frame_width: Mapped[int | None] = mapped_column(Integer)
    frame_height: Mapped[int | None] = mapped_column(Integer)
    model_version_id: Mapped[int | None] = mapped_column(Integer)
    review_status: Mapped[str | None] = mapped_column(String(20))
    reviewed_by: Mapped[int | None] = mapped_column(Integer)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)


class CameraHealth(Base):
    __tablename__ = "camera_health"

    camera_id: Mapped[str] = mapped_column(Text, primary_key=True)
    plant: Mapped[str | None] = mapped_column(Text)
    production_house: Mapped[str | None] = mapped_column(Text)
    area: Mapped[str | None] = mapped_column(Text)
    rtsp_link: Mapped[str | None] = mapped_column(Text)
    status: Mapped[bool | None] = mapped_column(Boolean)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime)


class EmailRecord(Base):
    __tablename__ = "ppes_emails_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    class_label: Mapped[str | None] = mapped_column(Text)
    production_house: Mapped[str | None] = mapped_column(Text)
    area: Mapped[str | None] = mapped_column(Text)
    to_recipients: Mapped[str | None] = mapped_column(Text)
    cc_recipients: Mapped[str | None] = mapped_column(Text)
    insert_date: Mapped[date | None] = mapped_column(Date)
    insert_time: Mapped[time | None] = mapped_column(Time)


# --- New: authentication & authorisation -----------------------------------------


class UserPermission(Base):
    __tablename__ = "user_permissions"
    __table_args__ = (UniqueConstraint("user_id", "permission", name="uq_user_permission"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission: Mapped[str] = mapped_column(String(64), nullable=False)
    granted_by: Mapped[int | None] = mapped_column(Integer)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="permissions")


class AuthOtp(Base):
    """Hashed one-time login codes with an attempt counter (one live row per user)."""

    __tablename__ = "auth_otps"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# --- New: plant configuration (replaces camera_list_*.json) --------------------


class Plant(Base):
    __tablename__ = "plants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    production_houses: Mapped[list["ProductionHouse"]] = relationship(
        back_populates="plant", cascade="all, delete-orphan", order_by="ProductionHouse.name"
    )


class ProductionHouse(Base):
    __tablename__ = "production_houses"
    __table_args__ = (UniqueConstraint("plant_id", "name", name="uq_production_house"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    plant: Mapped[Plant] = relationship(back_populates="production_houses")
    cameras: Mapped[list["Camera"]] = relationship(
        back_populates="production_house", cascade="all, delete-orphan", order_by="Camera.area"
    )


class PpeItem(Base):
    """A piece of PPE an area can require (helmet, gloves, ...)."""

    __tablename__ = "ppe_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CameraPpe(Base):
    __tablename__ = "camera_ppe"

    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), primary_key=True)
    ppe_item_id: Mapped[int] = mapped_column(ForeignKey("ppe_items.id", ondelete="CASCADE"), primary_key=True)


class Camera(Base):
    """One monitored area. The legacy JSON keyed these as plant -> production house -> area."""

    __tablename__ = "cameras"
    __table_args__ = (UniqueConstraint("production_house_id", "area", name="uq_camera_area"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    production_house_id: Mapped[int] = mapped_column(
        ForeignKey("production_houses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    area: Mapped[str] = mapped_column(String(150), nullable=False)
    stream_url: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # The old non_uniform_scale flag: upscale 2x before resizing to 1080p (low-res streams)
    scale_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    production_house: Mapped[ProductionHouse] = relationship(back_populates="cameras")
    ppe_items: Mapped[list[PpeItem]] = relationship(
        secondary="camera_ppe", order_by="PpeItem.sort_order", lazy="selectin"
    )

    @property
    def health_id(self) -> str:
        """camera_health.camera_id, built the same way inference.py builds it."""
        ph = self.production_house
        return f"{ph.plant.name}_{ph.name}_{self.area}"


class ModelClass(Base):
    """Class registry. class_id is the YOLO index and stays contiguous (0..N-1).
    Classes are disabled, never deleted, so indices never shift."""

    __tablename__ = "model_classes"

    class_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    ppe_item_id: Mapped[int | None] = mapped_column(ForeignKey("ppe_items.id", ondelete="SET NULL"))
    is_violation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.55)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    ppe_item: Mapped[PpeItem | None] = relationship(lazy="joined")


class AlertRecipient(Base):
    """channel 'violation' is per production house (cooldown.py).
    channel 'camera_health' is the plant-wide daily digest (production_house_id NULL)."""

    __tablename__ = "alert_recipients"
    __table_args__ = (Index("ix_alert_recipients_lookup", "channel", "production_house_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="violation")
    production_house_id: Mapped[int | None] = mapped_column(ForeignKey("production_houses.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(3), nullable=False, default="to")  # to | cc | bcc
    designation: Mapped[str | None] = mapped_column(String(150))


# --- New: coordination between the API, inference and the trainer -------------


class RuntimeState(Base):
    """Single row (id=1) the workers poll. config_version bumps on every config write."""

    __tablename__ = "runtime_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    inference_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pause_reason: Mapped[str | None] = mapped_column(Text)
    active_model_id: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_by: Mapped[str | None] = mapped_column(String(255))


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    info: Mapped[dict[str, Any] | None] = mapped_column(JsonType)


# --- New: annotation -------------------------------------------------------------


class Sample(Base):
    """An image being labelled for training: a reviewed event, an upload or a camera snapshot."""

    __tablename__ = "samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image_key: Mapped[str] = mapped_column(Text, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    image_sha1: Mapped[str | None] = mapped_column(String(40), index=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # review | upload | snapshot
    ppes_id: Mapped[int | None] = mapped_column(Integer, index=True)
    camera_id: Mapped[int | None] = mapped_column(Integer)
    production_house: Mapped[str | None] = mapped_column(String(100))
    area: Mapped[str | None] = mapped_column(String(150))
    # draft | submitted | approved | rejected
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    # Fixed the first time the sample enters a dataset, so it never moves between train and val
    split: Mapped[str | None] = mapped_column(String(5))
    notes: Mapped[str | None] = mapped_column(Text)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[int | None] = mapped_column(Integer)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    labels: Mapped[list["SampleLabel"]] = relationship(
        back_populates="sample", cascade="all, delete-orphan", order_by="SampleLabel.id", lazy="selectin"
    )


class SampleLabel(Base):
    """One box in normalised YOLO form: centre x/y, width, height, all 0..1."""

    __tablename__ = "sample_labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sample_id: Mapped[int] = mapped_column(ForeignKey("samples.id", ondelete="CASCADE"), nullable=False, index=True)
    class_id: Mapped[int] = mapped_column(Integer, nullable=False)
    cx: Mapped[float] = mapped_column(Float, nullable=False)
    cy: Mapped[float] = mapped_column(Float, nullable=False)
    w: Mapped[float] = mapped_column(Float, nullable=False)
    h: Mapped[float] = mapped_column(Float, nullable=False)
    origin: Mapped[str] = mapped_column(String(10), nullable=False, default="human")  # model | human
    conf: Mapped[float | None] = mapped_column(Float)

    sample: Mapped[Sample] = relationship(back_populates="labels")


# --- New: datasets, training runs and the model registry ------------------------


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="building")  # building | ready | failed
    val_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    s3_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    train_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    val_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    class_names: Mapped[list[str] | None] = mapped_column(JsonType)
    class_counts: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    notes: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DatasetSample(Base):
    __tablename__ = "dataset_samples"

    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="CASCADE"), primary_key=True
    )
    sample_id: Mapped[int] = mapped_column(ForeignKey("samples.id", ondelete="CASCADE"), primary_key=True)
    split: Mapped[str] = mapped_column(String(5), nullable=False)


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Path on the GPU server, relative to the repository root
    weights_path: Mapped[str] = mapped_column(Text, nullable=False)
    class_names: Mapped[list[str] | None] = mapped_column(JsonType)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="training")  # baseline | training
    training_run_id: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_by: Mapped[str | None] = mapped_column(String(255))


class TrainingRun(Base):
    __tablename__ = "training_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id"), nullable=False)
    base_model_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    # queued | running | succeeded | failed | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    progress: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    # The active model evaluated on the same validation split, for a fair comparison
    baseline_metrics: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    log_tail: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    result_model_id: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
