# app/routers/user_router.py
# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.auth_guard import create_access_token, require_user

router = APIRouter()

class LoginIn(BaseModel):
    email: str
    password: str

@router.post("/login")
def login(body: LoginIn):
    # デモ用途: 何でも受けてトークン発行（必要なら検証を後で追加）
    token = create_access_token(sub=body.email)
    return {"access_token": token, "token_type": "bearer"}

@router.get("/me")
def me(user = Depends(require_user)):
    return user