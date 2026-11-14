from datetime import datetime, timezone
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from flask_login import UserMixin
from sqlalchemy import CheckConstraint, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.extensions import db


_password_hasher = PasswordHasher()


def utc_now():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')", name="valid_role"),
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(db.String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(db.String(512), nullable=False)
    role: Mapped[str] = mapped_column(db.String(16), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    is_active: Mapped[bool] = mapped_column(db.Boolean, default=True, nullable=False)

    resumes: Mapped[list["Resume"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    roadmaps: Mapped[list["CareerRoadmap"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    progress: Mapped[list["LearningProgress"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    job_matches: Mapped[list["JobMatch"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    resume_drafts: Mapped[list["ResumeDraft"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    interview_sessions: Mapped[list["InterviewSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    usage_events: Mapped[list["AIUsageEvent"]] = relationship(back_populates="user")

    def set_password(self, password: str) -> None:
        self.password_hash = _password_hasher.hash(password)

    def check_password(self, password: str) -> bool:
        try:
            return _password_hasher.verify(self.password_hash, password)
        except VerifyMismatchError:
            return False


class Resume(db.Model):
    __tablename__ = "resumes"
    __table_args__ = (Index("ix_resumes_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    original_filename: Mapped[str] = mapped_column(db.String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(db.String(64), unique=True, default=lambda: uuid4().hex, nullable=False)
    file_type: Mapped[str] = mapped_column(db.String(8), nullable=False)
    extracted_text: Mapped[str] = mapped_column(db.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    user: Mapped[User] = relationship(back_populates="resumes")
    analyses: Mapped[list["ResumeAnalysis"]] = relationship(back_populates="resume", cascade="all, delete-orphan")
    drafts: Mapped[list["ResumeDraft"]] = relationship(back_populates="resume")


class ResumeAnalysis(db.Model):
    __tablename__ = "resume_analyses"
    __table_args__ = (
        Index("ix_resume_analyses_user_created", "user_id", "created_at"),
        CheckConstraint("ats_estimate IS NULL OR (ats_estimate >= 0 AND ats_estimate <= 100)", name="valid_ats_estimate"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    resume_id: Mapped[int] = mapped_column(db.ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    criteria_version: Mapped[str] = mapped_column(db.String(32), nullable=False)
    ats_estimate: Mapped[float | None] = mapped_column(db.Float)
    feedback: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    resume: Mapped[Resume] = relationship(back_populates="analyses")


class CareerRoadmap(db.Model):
    __tablename__ = "career_roadmaps"
    __table_args__ = (Index("ix_career_roadmaps_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    target_role: Mapped[str] = mapped_column(db.String(120), nullable=False)
    current_skills: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    required_skills: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    skill_gaps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    roadmap: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    related_roles: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    user: Mapped[User] = relationship(back_populates="roadmaps")
    progress: Mapped[list["LearningProgress"]] = relationship(back_populates="roadmap")


class LearningResource(db.Model):
    __tablename__ = "learning_resources"
    __table_args__ = (
        CheckConstraint("access_type IN ('free', 'freemium', 'paid', 'unknown')", name="valid_access_type"),
        CheckConstraint("verification_status IN ('verified', 'unverified', 'failed')", name="valid_verification_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(db.String(255), nullable=False)
    url: Mapped[str] = mapped_column(db.String(2048), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(db.String(120), nullable=False)
    resource_type: Mapped[str] = mapped_column(db.String(32), nullable=False)
    access_type: Mapped[str] = mapped_column(db.String(16), nullable=False, default="unknown")
    level: Mapped[str] = mapped_column(db.String(16), nullable=False)
    topics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    verification_status: Mapped[str] = mapped_column(db.String(16), nullable=False, default="unverified")
    verified_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    progress: Mapped[list["LearningProgress"]] = relationship(back_populates="resource")


class LearningProgress(db.Model):
    __tablename__ = "learning_progress"
    __table_args__ = (
        CheckConstraint("status IN ('not_started', 'in_progress', 'completed')", name="valid_progress_status"),
        UniqueConstraint("user_id", "resource_id", name="uq_learning_progress_user_resource"),
        Index("ix_learning_progress_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    resource_id: Mapped[int | None] = mapped_column(db.ForeignKey("learning_resources.id", ondelete="SET NULL"))
    roadmap_id: Mapped[int | None] = mapped_column(db.ForeignKey("career_roadmaps.id", ondelete="SET NULL"))
    topic: Mapped[str] = mapped_column(db.String(255), nullable=False)
    status: Mapped[str] = mapped_column(db.String(16), nullable=False, default="not_started")
    updated_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    user: Mapped[User] = relationship(back_populates="progress")
    resource: Mapped[LearningResource | None] = relationship(back_populates="progress")
    roadmap: Mapped[CareerRoadmap | None] = relationship(back_populates="progress")


class JobListing(db.Model):
    __tablename__ = "job_listings"
    __table_args__ = (
        UniqueConstraint("provider", "provider_job_id", name="uq_job_listings_provider_job"),
        Index("ix_job_listings_title_location", "title", "location"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(db.String(64), nullable=False)
    provider_job_id: Mapped[str] = mapped_column(db.String(255), nullable=False)
    title: Mapped[str] = mapped_column(db.String(255), nullable=False)
    employer: Mapped[str] = mapped_column(db.String(255), nullable=False)
    location: Mapped[str] = mapped_column(db.String(255), nullable=False)
    apply_url: Mapped[str] = mapped_column(db.String(2048), nullable=False)
    description: Mapped[str] = mapped_column(db.Text, nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    matches: Mapped[list["JobMatch"]] = relationship(back_populates="job_listing", cascade="all, delete-orphan")


class JobMatch(db.Model):
    __tablename__ = "job_matches"
    __table_args__ = (UniqueConstraint("user_id", "resume_id", "job_listing_id", name="uq_job_matches_user_resume_job"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    resume_id: Mapped[int] = mapped_column(db.ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    job_listing_id: Mapped[int] = mapped_column(db.ForeignKey("job_listings.id", ondelete="CASCADE"), nullable=False)
    compatibility: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    user: Mapped[User] = relationship(back_populates="job_matches")
    job_listing: Mapped[JobListing] = relationship(back_populates="matches")


class ResumeDraft(db.Model):
    __tablename__ = "resume_drafts"
    __table_args__ = (Index("ix_resume_drafts_user_updated", "user_id", "updated_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    resume_id: Mapped[int | None] = mapped_column(db.ForeignKey("resumes.id", ondelete="SET NULL"))
    job_description: Mapped[str | None] = mapped_column(db.Text)
    content: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    user: Mapped[User] = relationship(back_populates="resume_drafts")
    resume: Mapped[Resume | None] = relationship(back_populates="drafts")


class InterviewSession(db.Model):
    __tablename__ = "interview_sessions"
    __table_args__ = (Index("ix_interview_sessions_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    target_role: Mapped[str] = mapped_column(db.String(120), nullable=False)
    mode: Mapped[str] = mapped_column(db.String(16), nullable=False, default="mixed")
    session_data: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    user: Mapped[User] = relationship(back_populates="interview_sessions")


class AIUsageEvent(db.Model):
    __tablename__ = "ai_usage_events"
    __table_args__ = (
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="nonnegative_token_counts"),
        Index("ix_ai_usage_user_created", "user_id", "created_at"),
        Index("ix_ai_usage_feature_created", "feature", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(db.ForeignKey("users.id", ondelete="SET NULL"))
    request_id: Mapped[str] = mapped_column(db.String(64), default=lambda: uuid4().hex, unique=True, nullable=False)
    feature: Mapped[str] = mapped_column(db.String(48), nullable=False)
    model: Mapped[str] = mapped_column(db.String(120), nullable=False)
    estimated_input_tokens: Mapped[int] = mapped_column(db.Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(db.Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(db.Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(db.String(24), nullable=False)
    error_code: Mapped[str | None] = mapped_column(db.String(64))
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    user: Mapped[User | None] = relationship(back_populates="usage_events")

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class AIUsageSetting(db.Model):
    __tablename__ = "ai_usage_settings"

    setting_name: Mapped[str] = mapped_column(db.String(48), primary_key=True)
    numeric_value: Mapped[float] = mapped_column(db.Float, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(db.ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
