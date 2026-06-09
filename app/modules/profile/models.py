import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.core.database.base import Base

# Imported here so SQLAlchemy can resolve the "UserSession" string in User.sessions
import app.modules.auth.models  # noqa: F401, E402


class User(Base):
    __tablename__ = "users"

    # UUID kept for auth — JWT carries this ID before the DB row is created
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    country_code: Mapped[str] = mapped_column(String(5))
    phone_number: Mapped[str] = mapped_column(String(15))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    fcm_token: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    access_token: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    __table_args__ = (
        UniqueConstraint("country_code", "phone_number", name="uq_phone"),
    )

    profile: Mapped[Optional["Profile"]] = relationship("Profile", back_populates="user", passive_deletes=True)
    sessions: Mapped[list["UserSession"]] = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")  # type: ignore[name-defined]


# ---------------------------------------------------------------------------
# Lookup tables — seeded with fixed int IDs (1, 2, 3)
# --------------------------------------------------------------------------

class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # 1=Trader 2=Broker 3=Exporter
    name: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    profiles: Mapped[list["Profile"]] = relationship("Profile", back_populates="role")


class Commodity(Base):
    __tablename__ = "commodities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # 1=Rice 2=Cotton 3=Sugar
    name: Mapped[str] = mapped_column(String(50), unique=True)

    profile_commodities: Mapped[list["Profile_Commodity"]] = relationship("Profile_Commodity", back_populates="commodity")


class Interest(Base):
    __tablename__ = "interests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # 1=Connections 2=Leads 3=News
    name: Mapped[str] = mapped_column(String(50), unique=True)

    profile_interests: Mapped[list["Profile_Interest"]] = relationship("Profile_Interest", back_populates="interest")


# ---------------------------------------------------------------------------
# Profile — business location lives in the Business table (1:1)
# ---------------------------------------------------------------------------

class Profile(Base):
    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    users_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    role_id: Mapped[int] = mapped_column(Integer, ForeignKey("roles.id"))

    name: Mapped[str] = mapped_column(String(100))
    
    quantity_min: Mapped[Decimal] = mapped_column(Numeric)
    quantity_max: Mapped[Decimal] = mapped_column(Numeric)

    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    is_user_verified: Mapped[bool] = mapped_column(default=False)
    is_business_verified: Mapped[bool] = mapped_column(default=False)
    followers_count: Mapped[int] = mapped_column(Integer, default=0)
    following_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship("User", back_populates="profile")
    role: Mapped["Role"] = relationship("Role", back_populates="profiles")
    commodities: Mapped[list["Profile_Commodity"]] = relationship("Profile_Commodity", back_populates="profile", cascade="all, delete-orphan")
    interests: Mapped[list["Profile_Interest"]] = relationship("Profile_Interest", back_populates="profile", cascade="all, delete-orphan")
    business: Mapped["Business"] = relationship("Business", back_populates="profile", uselist=False, cascade="all, delete-orphan")


class Business(Base):
    __tablename__ = "business"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profile.id", ondelete="CASCADE"), unique=True)

    business_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)

    profile: Mapped["Profile"] = relationship("Profile", back_populates="business")

# ---------------------------------------------------------------------------
# Junction tables
# ---------------------------------------------------------------------------

class Profile_Commodity(Base):
    __tablename__ = "profile_commodities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profile.id", ondelete="CASCADE"))
    commodity_id: Mapped[int] = mapped_column(Integer, ForeignKey("commodities.id"))

    __table_args__ = (
        UniqueConstraint("profile_id", "commodity_id", name="uq_profile_commodity"),
    )

    profile: Mapped["Profile"] = relationship("Profile", back_populates="commodities")
    commodity: Mapped["Commodity"] = relationship("Commodity", back_populates="profile_commodities")


class Profile_Interest(Base):
    __tablename__ = "profile_interests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profile.id", ondelete="CASCADE"))
    interest_id: Mapped[int] = mapped_column(Integer, ForeignKey("interests.id"))

    __table_args__ = (
        UniqueConstraint("profile_id", "interest_id", name="uq_profile_interest"),
    )

    profile: Mapped["Profile"] = relationship("Profile", back_populates="interests")
    interest: Mapped["Interest"] = relationship("Interest", back_populates="profile_interests")

# ---------------------------------------------------------------------------
# User embeddings — 11-dim IS vector, rebuilt on profile create/update
# Layout: [3 commodity | 3 role | 3 geo | 2 qty]  (same as group_embeddings)
# ---------------------------------------------------------------------------

class UserEmbedding(Base):
    __tablename__ = "user_embeddings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # 11-dim pgvector IS vector — indexed with HNSW for cosine ANN search
    is_vector: Mapped[Optional[list]] = mapped_column(Vector(11), nullable=True)

    # 10-dim post feed vector — built from same profile fields
    post_feed_vector: Mapped[Optional[list]] = mapped_column(Vector(10), nullable=True)
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
