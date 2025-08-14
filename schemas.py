from pydantic import BaseModel

class PredictInput(BaseModel):
    rci: float
    atr: float
    vix: float