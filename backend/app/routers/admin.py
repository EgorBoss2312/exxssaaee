from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth_core import hash_password
from app.database import get_db
from app.deps import require_admin
from app.models import Role, User
from app.schemas import AdminUserCreate, AdminUserUpdate, RoleOut, UserOut

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
):
    return db.query(Role).order_by(Role.id.asc()).all()


@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
):
    users = db.query(User).order_by(User.id.asc()).all()
    out: list[UserOut] = []
    for u in users:
        r = u.role
        out.append(
            UserOut(
                id=u.id,
                email=u.email,
                full_name=u.full_name,
                role_id=u.role_id,
                role_code=r.code,
                role_name=r.name,
                is_active=u.is_active,
            )
        )
    return out


@router.post("/users", response_model=UserOut)
def create_user(
    body: AdminUserCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
):
    if db.query(User).filter(User.email == body.email.lower().strip()).first():
        raise HTTPException(status_code=400, detail="Email уже занят")
    role = db.query(Role).filter(Role.id == body.role_id).first()
    if not role:
        raise HTTPException(status_code=400, detail="Роль не найдена")
    u = User(
        email=body.email.lower().strip(),
        hashed_password=hash_password(body.password),
        full_name=body.full_name.strip(),
        role_id=body.role_id,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    r = u.role
    return UserOut(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        role_id=u.role_id,
        role_code=r.code,
        role_name=r.name,
        is_active=u.is_active,
    )


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: AdminUserUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Не найден")
    if body.full_name is not None:
        u.full_name = body.full_name.strip()
    if body.role_id is not None:
        role = db.query(Role).filter(Role.id == body.role_id).first()
        if not role:
            raise HTTPException(status_code=400, detail="Роль не найдена")
        u.role_id = body.role_id
    if body.is_active is not None:
        u.is_active = body.is_active
    if body.password:
        u.hashed_password = hash_password(body.password)
    db.commit()
    db.refresh(u)
    r = u.role
    return UserOut(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        role_id=u.role_id,
        role_code=r.code,
        role_name=r.name,
        is_active=u.is_active,
    )
