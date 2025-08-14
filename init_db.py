# init_db.py
from sqlalchemy import text
from database.database_user import engine
from models.models_user import Base

def force_reset():
    with engine.connect() as conn:
        print("✅ DBに接続中...")
        try:
            print("⚠️ すべてのテーブルを削除します（CASCADE）...")
            conn.execute(text("DROP TABLE IF EXISTS prediction_log CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS users CASCADE"))
            conn.commit()
            print("🧹 CASCADE削除完了")
        except Exception as e:
            print("❌ DROPエラー:", str(e))

        try:
            Base.metadata.create_all(bind=engine)
            print("✅ テーブル再作成完了")
        except Exception as e:
            print("❌ CREATEエラー:", str(e))

if __name__ == "__main__":
    force_reset()