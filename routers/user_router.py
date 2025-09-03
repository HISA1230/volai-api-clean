# routers/user_router.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Query, status
from jose import jwt, JWTError
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from passlib.hash import pbkdf2_sha256
import os

from database.database_user import get_db
from models.models_user import User

router = APIRouter(tags=["Auth"])

# =========================
# JWT 設定
# =========================
JWT_SECRET = os.getenv("JWT_SECRET", "change-me")  # 本番では必ず安全な値に
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

# =========================
# Schemas
# =========================
class RegisterIn(BaseModel):
    email: EmailStr
    password: str

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"

class MeOut(BaseModel):
    id: int
    email: EmailStr
    created_at: Optional[datetime] = None

# =========================
# Token ユーティリティ
# =========================
def create_access_token(sub: str) -> str:
    to_encode = {"sub": sub, "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)}
    return jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)

def extract_token_lenient(
    authorization: Optional[str] = Header(None),
    access_token: Optional[str] = Query(None),
) -> str:
    """
    標準の `Authorization: Bearer <token>` を推奨しつつ、
    - `Authorization: <token>`（生トークン）
    - `?access_token=<token>`（HTTPS前提）
    も受け付ける緩い抽出器。
    """
    if authorization:
        val = authorization.strip()
        if val.lower().startswith("bearer "):
            return val[7:].strip()
        # 生トークン（JWTっぽさの簡易判定）
        if val.count(".") == 2:
            return val
    if access_token:
        return access_token.strip()
    raise HTTPException(status_code=401, detail="Missing Bearer token")

def get_current_user(
    token: str = Depends(extract_token_lenient),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.email == sub).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# =========================
# Endpoints
# =========================
@router.post("/register", response_model=MeOut, summary="Register")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    exists = db.query(User).filter(User.email == body.email).first()
    if exists:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=body.email, password_hash=pbkdf2_sha256.hash(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return MeOut(id=user.id, email=user.email, created_at=user.created_at)

@router.post("/login", response_model=TokenOut, summary="Login (get JWT)")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not pbkdf2_sha256.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(sub=user.email)
    return TokenOut(access_token=token)
@router.post("/auth/login", include_in_schema=False)
def login_alias(body: LoginIn, db: Session = Depends(get_db)):
    return login(body, db)

@router.get("/me", response_model=MeOut, summary="Me")
def me(user: User = Depends(get_current_user)):
    return MeOut(id=user.id, email=user.email, created_at=user.created_at)