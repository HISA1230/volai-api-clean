from sqlalchemy import create_engine
from models.models_user import Base
from database.database_user import SQLALCHEMY_DATABASE_URL

engine = create_engine(SQLALCHEMY_DATABASE_URL)
print("Creating tables if not exist...")
Base.metadata.create_all(bind=engine)
print("Done.")