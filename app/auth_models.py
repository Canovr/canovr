"""Auth-Modelle: User, RefreshToken und Pydantic-Schemas."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.database import Athlete


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, default=None)
    password_hash: Mapped[str | None] = mapped_column(String(255), default=None)
    strava_id: Mapped[int | None] = mapped_column(unique=True, index=True, default=None)
    strava_access_token: Mapped[str | None] = mapped_column(String(500), default=None)
    strava_refresh_token: Mapped[str | None] = mapped_column(String(500), default=None)
    strava_token_expires_at: Mapped[dt.datetime | None] = mapped_column(default=None)
    first_name: Mapped[str | None] = mapped_column(String(100), default=None)
    last_name: Mapped[str | None] = mapped_column(String(100), default=None)
    auth_provider: Mapped[str] = mapped_column(String(20))  # "strava" | "email"
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    athlete: Mapped[Athlete | None] = relationship(back_populates="user")
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(back_populates="user")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[dt.datetime]
    revoked_at: Mapped[dt.datetime | None] = mapped_column(default=None)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


# ---------------------------------------------------------------------------
#  Pydantic request/response schemas
# ---------------------------------------------------------------------------

class StravaAuthRequest(BaseModel):
    code: str


class EmailRegisterRequest(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(max_length=100)


class EmailLoginRequest(BaseModel):
    email: str
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class StravaProfile(BaseModel):
    first_name: str
    last_name: str


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    needs_onboarding: bool
    strava_profile: StravaProfile | None = None
