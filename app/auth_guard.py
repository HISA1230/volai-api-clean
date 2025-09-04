# app/auth_guard.py
# -*- coding: utf-8 -*-
import os, time
from typing import Optional, Dict, Any
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")
JWT_ALG = "HS256"

API_REQUIRE_JWT = os.getenv("API_REQUIRE_JWT", "0") == "1"
ADMIN_EMAIL = (os.getenv("ADMIN_EMAIL") or "").strip()

bearer = HTTPBearer(auto_error=False)

def create_access_token(sub: str, exp_seconds: int = 60*60) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "iat": now,
        "exp": now + exp_seconds,
        "iss": "volai-api",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)

def _decode(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except Exception:
        raise HTTPException(401, "Invalid token")

def _dev_user() -> Dict[str, Any]:
    return {"id": 0, "email": "dev@local", "created_at": None}

def _user_from_sub(sub: str) -> Dict[str, Any]:
    # 本来はDB照合。ここでは簡易にメールだけ返す
    return {"id": 1, "email": sub, "created_at": None}

def require_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer)):
    if not API_REQUIRE_JWT:
        return _dev_user()
    if credentials is None or not credentials.scheme.lower() == "bearer":
        raise HTTPException(401, "Missing Bearer token")
    data = _decode(credentials.credentials)
    sub = data.get("sub")
    if not sub:
        raise HTTPException(401, "Invalid token payload")
    return _user_from_sub(sub)

def require_admin(user = Depends(require_user)):
    # ADMIN_EMAIL が設定されていれば一致必須、無ければ dev でも通す
    if ADMIN_EMAIL:
        if (user.get("email") or "").lower() != ADMIN_EMAIL.lower():
            raise HTTPException(403, "Admin privileges required")
    return user