from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

RoleName = Literal["admin", "user"]


class PermissionInfo(BaseModel):
    key: str
    label: str
    description: str
    grantable: bool
    default: bool


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    is_active: bool
    locked: bool
    password_expired: bool
    granted: list[str]
    effective: list[str]


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)
    role: RoleName = "user"
    permissions: list[str] = []


class UserUpdate(BaseModel):
    role: RoleName | None = None
    is_active: bool | None = None


class PermissionsUpdate(BaseModel):
    permissions: list[str]


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    user_email: str | None
    action: str
    details: str | None
    ip_address: str | None


class AuditLogPage(BaseModel):
    items: list[AuditLogOut]
    total: int
