from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from datetime import datetime, timedelta
import os

from database.database_user import get_db
from models.models_user import User
from passlib.hash import pbkdf2_sha256

router = APIRouter(tags=["auth"])

JWT_SECRET = os.getenv("JWT_SECRET", "change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7日

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
    created_at: datetime | None = None

def create_access_token(sub: str) -> str:
    to_encode = {"sub": sub, "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)}
    return jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)

def bearer_token(authorization: str = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    return authorization.split(" ", 1)[1]

def current_user(token: str = Depends(bearer_token), db: Session = Depends(get_db)) -> User:
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

@router.post("/register", response_model=MeOut)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    exists = db.query(User).filter(User.email == body.email).first()
    if exists:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=body.email, password_hash=pbkdf2_sha256.hash(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return MeOut(id=user.id, email=user.email, created_at=user.created_at)

@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not pbkdf2_sha256.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(sub=user.email)
    return TokenOut(access_token=token)

@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user)):
    return MeOut(id=user.id, email=user.email, created_at=user.created_at)
