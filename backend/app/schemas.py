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


class DocumentTagOut(BaseModel):
    id: int
    code: str
    name: str
    color: Optional[str] = None

    class Config:
        from_attributes = True


class DocumentOut(BaseModel):
    id: int
    title: str
    original_filename: str
    mime_type: Optional[str]
    created_at: datetime
    uploaded_by_name: Optional[str] = None
    allowed_role_codes: list[str] = []
    tags: list[DocumentTagOut] = []

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
    rag_query_id: Optional[int] = None
    rag_uncertain: bool = False
    top_score: Optional[float] = None
    suggested_department_code: Optional[str] = None
    suggested_department_name: Optional[str] = None


class FeedbackRequest(BaseModel):
    rag_query_id: int
    is_helpful: bool
    comment: Optional[str] = Field(None, max_length=2000)


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


# ---------------------------------------------------------------------------
# Подсистема внутренних заявок и эскалации
# ---------------------------------------------------------------------------


class DepartmentOut(BaseModel):
    id: int
    code: str
    name: str

    class Config:
        from_attributes = True


class RequestCreate(BaseModel):
    """Создаёт заявку из текущего диалога.

    Если ``escalate=True`` — заявка сразу переходит в статус ``escalated``
    и адресуется отделу: явно указанному в ``department_code`` либо
    подобранному rule-based классификатором.
    """

    body: str = Field(..., min_length=1, max_length=8000)
    title: Optional[str] = Field(None, max_length=255)
    session_id: Optional[int] = None
    rag_query_id: Optional[int] = None
    department_code: Optional[str] = None
    escalate: bool = True


class RequestUserRef(BaseModel):
    id: int
    full_name: str
    role_code: Optional[str] = None
    department_name: Optional[str] = None

    class Config:
        from_attributes = True


class RequestMessageOut(BaseModel):
    id: int
    author: RequestUserRef
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class RequestMessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=8000)


class RequestOut(BaseModel):
    id: int
    title: str
    body: str
    status: str
    resolution_kind: Optional[str] = None
    department: Optional[DepartmentOut] = None
    author: RequestUserRef
    assignee: Optional[RequestUserRef] = None
    chat_session_id: Optional[int] = None
    rag_query_id: Optional[int] = None
    created_at: datetime
    escalated_at: Optional[datetime] = None
    claimed_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    messages_count: int = 0

    class Config:
        from_attributes = True


class RequestDetailOut(RequestOut):
    messages: list[RequestMessageOut] = []
    can_claim: bool = False
    can_close: bool = False
    can_reply: bool = False


class NotificationOut(BaseModel):
    id: int
    kind: str
    title: str
    body: Optional[str] = None
    request_id: Optional[int] = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationsSummary(BaseModel):
    unread: int
    items: list[NotificationOut]
