# check_db.py
from sqlalchemy.orm import Session
from database.database_user import SessionLocal
from models.models_user import UserModel, PredictionLog

def check_users():
    db: Session = SessionLocal()
    try:
        users = db.query(UserModel).all()
        print(f"🧑‍💻 ユーザー数: {len(users)}")
        for user in users:
            print(f" - {user.id}: {user.email}")
    except Exception as e:
        print("❌ UserModel 読み取りエラー:", str(e))
    finally:
        db.close()

def check_logs():
    db: Session = SessionLocal()
    try:
        logs = db.query(PredictionLog).all()
        print(f"📊 ログ数: {len(logs)}")
        for log in logs:
            print(f" - {log.id} | ユーザーID: {log.user_id} | 予測: {log.predicted_volatility}")
    except Exception as e:
        print("❌ PredictionLog 読み取りエラー:", str(e))
    finally:
        db.close()

if __name__ == "__main__":
    check_users()
    check_logs()