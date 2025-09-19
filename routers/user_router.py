# routers/user_router.py
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel, EmailStr

# JWT
try:
    from jose import jwt, JWTError
except Exception as e:
    raise RuntimeError("python-jose[cryptography] が必要です: pip install 'python-jose[cryptography]'") from e

# ====== 可変: 環境 ======
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

# ====== 可能ならDBを使う（無ければNoneでフォールバック） ======
engine = None
SessionLocal = None
User = None
try:
    from sqlalchemy.orm import sessionmaker
    from database.database_user import engine as _engine
    from models.models_user import User as _User
    engine = _engine
    User = _User
    if engine is not None:
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
except Exception:
    # DB が未設定でも動くようにフォールバック
    pass

# ====== パスワード検証（passlib があれば使う） ======
def _verify_password(plain: str, hashed: Optional[str]) -> bool:
    if not hashed:
        return False
    try:
        # passlib 優先
        import passlib.context
        ctx = passlib.context.CryptContext(schemes=["bcrypt"], deprecated="auto")
        return ctx.verify(plain, hashed)
    except Exception:
        # bcrypt のみでの簡易検証 or 平文（開発時の想定外保存）にも一応対応
        try:
            import bcrypt
            if hashed.startswith("$2") or hashed.startswith("$2b$"):
                return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
            # 最悪のフォールバック（DBに平文が入っている場合）
            return plain == hashed
        except Exception:
            return plain == hashed

def _get_user_from_db(email: str):
    if not (SessionLocal and User):
        return None
    with SessionLocal() as db:
        try:
            return db.query(User).filter(User.email == email).first()
        except Exception:
            return None

# ====== 開発用の仮ユーザー（DBが無い時だけ有効） ======
DEV_EMAIL = os.getenv("DEV_EMAIL", "test@example.com")
DEV_PASSWORD = os.getenv("DEV_PASSWORD", "test1234")

# ====== JWT 作成/検証 ======
def create_access_token(sub: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": sub, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> str:
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = data.get("sub")
        if not sub:
            raise JWTError("No sub")
        return sub
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from e

# ====== FastAPI Router ======
router = APIRouter(tags=["auth"])

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class MeResponse(BaseModel):
    email: EmailStr

@router.post("/login", response_model=TokenResponse, summary="ログインしてJWTを取得")
def login(body: LoginRequest):
    email = body.email
    password = body.password

    # 1) DB があれば DB を使って認証
    u = _get_user_from_db(email)
    if u:
        # よくあるカラム名に対応（なければ None）
        hashed = getattr(u, "hashed_password", None) or getattr(u, "password_hash", None) or getattr(u, "password", None)
        if not _verify_password(password, hashed):
            raise HTTPException(status_code=401, detail="invalid credentials")
        return TokenResponse(access_token=create_access_token(email))

    # 2) DBが無い/ユーザー未登録 → 開発用アカウントで認証
    if email == DEV_EMAIL and password == DEV_PASSWORD:
        return TokenResponse(access_token=create_access_token(email))

    # 3) どれでもない
    raise HTTPException(status_code=401, detail="invalid credentials")

def _bearer_token(authorization: Optional[str] = Header(None)) -> str:
    # "Bearer xxxxx" 形式の取り出し
    if not authorization:
        raise HTTPException(status_code=401, detail="missing Authorization")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="invalid Authorization header")
    return parts[1]

@router.get("/me", response_model=MeResponse, summary="自分の情報（トークン要）")
def me(token: str = Depends(_bearer_token)):
    email = decode_token(token)
    return MeResponse(email=email)