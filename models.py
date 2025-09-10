# models.py
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from db import Base

class Owner(Base):
    __tablename__ = "owners"
    id:   Mapped[int]  = mapped_column(primary_key=True)
    name: Mapped[str]  = mapped_column(String(100), unique=True, index=True)
