from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    """Без EmailStr: библиотека email-validator отклоняет домены .local (как admin@edda.local)."""

    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_login_email(cls, v: str) -> str:
        return v.strip().lower()


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role_id: int
    role_code: str
    role_name: str
    is_active: bool

    class Config:
        from_attributes = True


class RoleOut(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None

    class Config:
        from_attributes = True


class LlmStatusOut(BaseModel):
    """Какой режим генерации ответа активен (по настройкам и доступности Ollama)."""

    mode: str  # "gemini" | "openai" | "ollama" | "extractive"
    model: Optional[str] = None
    hint: Optional[str] = None


class DocumentOut(BaseModel):
    id: int
    title: str
    original_filename: str
    mime_type: Optional[str]
    created_at: datetime
    uploaded_by_name: Optional[str] = None
    allowed_role_codes: list[str] = []

    class Config:
        from_attributes = True


class DocumentUploadMeta(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    allowed_role_ids: str = Field(
        ...,
        description="JSON array of role ids, e.g. [1,2,3]",
    )


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: Optional[int] = None


class SourceRef(BaseModel):
    document_id: int
    document_title: str
    chunk_index: int
    excerpt: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceRef]
    session_id: int


class AdminUserCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=6, max_length=128)
    full_name: str
    role_id: int

    @field_validator("email")
    @classmethod
    def normalize_admin_email(cls, v: str) -> str:
        return v.strip().lower()


class AdminUserUpdate(BaseModel):
    full_name: Optional[str] = None
    role_id: Optional[int] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=6, max_length=128)


class ChatSessionOut(BaseModel):
    id: int
    title: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    sources_json: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
