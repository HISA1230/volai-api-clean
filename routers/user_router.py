from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from auth.auth_jwt import get_current_user, create_access_token
from database.database_user import get_db
from models.models_user import UserModel, UserCreate, UserLogin
from passlib.context import CryptContext
import traceback

router = APIRouter(tags=["User"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@router.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    try:
        existing_user = db.query(UserModel).filter(UserModel.email == user.email).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="User already registered")
        hashed_pw = pwd_context.hash(user.password)
        db_user = UserModel(email=user.email, hashed_password=hashed_pw)
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return {"msg": "User registered"}
    except Exception as e:
        with open("error_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[Register Error]\n{traceback.format_exc()}\n")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@router.post("/login")
def login(user: UserLogin, db: Session = Depends(get_db)):
    try:
        db_user = db.query(UserModel).filter(UserModel.email == user.email).first()
        if not db_user or not pwd_context.verify(user.password, db_user.hashed_password):
            raise HTTPException(status_code=400, detail="Invalid email or password")
        access_token = create_access_token(data={"sub": db_user.email})
        return {"access_token": access_token, "token_type": "bearer"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")

@router.get("/me")
def read_users_me(current_user: UserModel = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "created_at": current_user.created_at.isoformat(),
    }