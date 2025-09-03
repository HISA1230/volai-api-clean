from app.database.session import session_scope
from sqlalchemy import text
with session_scope() as s:
    n = s.execute(text("select count(*) from model_eval")).scalar_one()
    print("model_eval rows:", n)
