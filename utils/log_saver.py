# utils/log_saver.py

from sqlalchemy.orm import Session
from models.models_user import PredictionLog
from models.models_user import UserModel

def save_prediction_log(db: Session, user_email: str, input_data: dict, predicted_volatility: float):
    log = PredictionLog(
        user_email=user_email,
        rci=input_data["rci"],
        atr=input_data["atr"],
        vix=input_data["vix"],
        volume_rate=input_data["volume_rate"],
        cpi_delta=input_data["cpi_delta"],
        us10y_yield=input_data["us10y_yield"],
        btc_return=input_data["btc_return"],
        gold_volatility=input_data["gold_volatility"],
        predicted_volatility=predicted_volatility
    )
    db.add(log)
    db.commit()