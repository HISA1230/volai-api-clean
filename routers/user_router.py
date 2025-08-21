from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, constr
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from jose import jwt, JWTError
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
import os
import logging

# DB接続は database_user 側に集約
from database.database_user import get_db, engine
from models.models_user import UserModel, Base

# ----------------------------------
# 設定 / セキュリティ
# ----------------------------------
SECRET_KEY = os.environ.get("JWT_SECRET", "dev-secret-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "10080"))  # 7日
ALLOW_REGISTER = os.environ.get("ALLOW_REGISTER", "1")  # 本番は "0" 推奨

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=True)

# ----------------------------------
# ロガー（500対策のエラーログ）
# ----------------------------------
logging.basicConfig(
    filename="error_log.txt",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ----------------------------------
# ユーティリティ
# ----------------------------------
def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        # 未知ハッシュ等は False として扱う
        return False

def create_access_token(sub: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": sub, "exp": expire}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> str:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return sub
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from e

# ----------------------------------
# スキーマ
# ----------------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: constr(min_length=8, max_length=128)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class MeResponse(BaseModel):
    id: int
    email: EmailStr
    created_at: datetime

# ----------------------------------
# DB初期化（開発時のみ）
#   環境変数 RUN_DB_CREATE_ON_IMPORT=1 で有効化
# ----------------------------------
if os.environ.get("RUN_DB_CREATE_ON_IMPORT") == "1":
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        logger.exception("DB init on import failed: %s", e)

# ----------------------------------
# 依存: 現在ユーザー
# ----------------------------------
def get_current_user(
    cred: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> UserModel:
    token = cred.credentials
    email = decode_token(token)
    user = db.query(UserModel).filter(UserModel.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user

# ----------------------------------
# ルーター
# ----------------------------------
router = APIRouter(prefix="", tags=["User"])

@router.post("/register", response_model=MeResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> MeResponse:
    try:
        # 本番で登録を止めたい場合は ALLOW_REGISTER=0 にする
        if ALLOW_REGISTER != "1":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Registration disabled")

        email_norm = str(body.email).strip().lower()

        # 409: 既存メール（事前チェック：削除しても動作はするが、残すのが推奨）
        existed = db.query(UserModel).filter(UserModel.email == email_norm).first()
        if existed:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already registered")

        user = UserModel(
            email=email_norm,
            password_hash=get_password_hash(body.password),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return MeResponse(id=user.id, email=user.email, created_at=user.created_at)

    except IntegrityError:
        db.rollback()
        # ユニーク制約に引っかかった場合も 409 に丸め
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already registered")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("/register failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Registration failed")

@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        email_norm = str(body.email).strip().lower()
        user = db.query(UserModel).filter(UserModel.email == email_norm).first()
        if not user or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        token = create_access_token(sub=user.email)
        return TokenResponse(access_token=token)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("/login failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Login failed")

@router.get("/me", response_model=MeResponse)
def me(current_user: UserModel = Depends(get_current_user)) -> MeResponse:
    return MeResponse(id=current_user.id, email=current_user.email, created_at=current_user.created_at)