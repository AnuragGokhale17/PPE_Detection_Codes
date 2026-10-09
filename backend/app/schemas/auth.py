from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    otp_required: bool = True
    email_hint: str
    resend_in: int


class OtpRequest(BaseModel):
    otp: str = Field(pattern=r"^\d{6}$")


class ResendResponse(BaseModel):
    resend_in: int


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(max_length=256)
    confirm_password: str = Field(max_length=256)


class ResetTokenInfo(BaseModel):
    valid: bool
    email_hint: str | None = None


class MessageResponse(BaseModel):
    message: str


class Me(BaseModel):
    id: int
    email: str
    name: str
    role: str
    permissions: list[str]
