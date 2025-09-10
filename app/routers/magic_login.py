# app/routers/magic_login.py
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
import os, datetime, jwt

router = APIRouter(prefix="/auth", tags=["auth"])

class MagicLoginIn(BaseModel):
    token: str
    email: EmailStr

def create_access_token(sub: str, expires_minutes: int = 60) -> str:
    """
    既存のJWT仕様がHS256/SECRET_KEYでsubを見ている前提のシンプル版。
    もし既存の create_access_token が別モジュールにあるなら、それをimportして使ってOK。
    """
    secret = os.environ.get("SECRET_KEY")
    if not secret:
        raise RuntimeError("SECRET_KEY is not set")
    alg = "HS256"
    now = datetime.datetime.utcnow()
    payload = {"sub": sub, "iat": now, "exp": now + datetime.timedelta(minutes=expires_minutes)}
    return jwt.encode(payload, secret, algorithm=alg)

@router.post("/magic_login")
def magic_login(body: MagicLoginIn):
    admin = os.environ.get("ADMIN_TOKEN")
    if not admin or body.token != admin:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad token")
    # 簡易: email だけでトークン発行（既存の認証がsub=emailを見ていればそのまま有効）
    access_token = create_access_token(sub=body.email)
    return {"access_token": access_token, "token_type": "bearer"}
