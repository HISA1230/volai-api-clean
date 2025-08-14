# create_tables.py
from sqlalchemy import inspect
from database.database_user import engine
from models.models_user import Base, ModelMeta  # ← ModelMeta を import しておく

def create_missing_tables():
    insp = inspect(engine)
    existing = set(insp.get_table_names())

    # Baseに定義されている全テーブルのうち、未作成のものだけ作成
    all_tables = Base.metadata.tables.keys()
    to_create = [t for t in all_tables if t not in existing]

    if to_create:
        print("🛠 Creating tables:", ", ".join(to_create))
        Base.metadata.create_all(bind=engine, tables=[Base.metadata.tables[name] for name in to_create])
    else:
        print("✅ All tables already exist. No action needed.")

if __name__ == "__main__":
    create_missing_tables()
    print("✅ Done.")