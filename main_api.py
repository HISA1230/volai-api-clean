"""
Volatility AI - Public API (Render 用)
main_api.py  v2025-11-12

・FastAPI 単体で完結するシンプル構成
・DB にはまだ接続せず、ダミーデータを返す
・以下のエンドポイントを提供：
  - GET /health
  - GET /          （API概要）
  - GET /predict/latest
  - GET /summary/size
  - GET /signals
  - GET /predict/logs
  - GET /macro/forecast
  - GET /macro/highlights
  - GET /recommendations/today
  - GET /heatmap/summary

※ あとで本番DBに繋ぎたい場合は、
   ダミーデータ部分を差し替えていけばOKな形にしてあります。
"""

# ============================================================
# 1. 標準ライブラリ & サードパーティの import
# ============================================================
import logging
import os
from datetime import date, datetime
from typing import List, Literal, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# ============================================================
# 2. ロガー設定
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] main_api - %(message)s",
)
logger = logging.getLogger("main_api")


# ============================================================
# 3. FastAPI アプリ本体の生成
# ============================================================
app = FastAPI(
    title="Volatility AI Public API",
    description=(
        "Volatility AI（ボラ予測AI）の公開APIです。\n"
        "Streamlit UI からの参照を前提とした、READ ONLY なエンドポイントを提供します。"
    ),
    version="2025.11.12",
)

# CORS 設定（必要に応じてホストを追加）
origins = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:8501",
    "http://localhost:8515",
    "http://localhost:8519",
    # 例: Streamlit を後で Render or 他サービスに載せる場合
    # "https://volai-ui.onrender.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# 4. Pydantic モデル定義
# ============================================================

class HealthResponse(BaseModel):
    status: Literal["ok"]
    app: str
    version: str
    timestamp: datetime


class PredictionItem(BaseModel):
    run_date: date
    run_time: str  # "HH:MM" 形式
    sector: str
    size: str
    time_block: str
    symbol: str
    model_name: str
    prob_nobori_ryu: float
    prob_fake: float
    expected_return: float
    comment: str


class PredictionLatestResponse(BaseModel):
    run_at: datetime
    items: List[PredictionItem]


class SizeSummaryItem(BaseModel):
    size: str
    signal_count: int
    avg_confidence: float
    avg_fake_rate: float


class SizeSummaryResponse(BaseModel):
    run_at: datetime
    items: List[SizeSummaryItem]


class SignalItem(BaseModel):
    sector: str
    size: str
    time_block: str
    symbol: str
    direction: Literal["long", "short", "flat"]
    confidence: float
    fake_rate: float
    emoji: str
    comment: str


class SignalResponse(BaseModel):
    run_at: datetime
    items: List[SignalItem]


class PredictLogItem(BaseModel):
    run_at: datetime
    sector: str
    size: str
    time_block: str
    symbol: str
    model_name: str
    prob_nobori_ryu: float
    prob_fake: float
    realized_return: Optional[float] = None
    note: Optional[str] = None


class PredictLogsResponse(BaseModel):
    items: List[PredictLogItem]


class MacroForecastItem(BaseModel):
    name: str
    value: float
    unit: str
    direction: Literal["up", "down", "flat"]
    comment: str


class MacroForecastResponse(BaseModel):
    run_date: date
    items: List[MacroForecastItem]


class MacroHighlightItem(BaseModel):
    title: str
    importance: Literal["high", "medium", "low"]
    date: date
    time: Optional[str] = None
    detail: str


class MacroHighlightsResponse(BaseModel):
    run_date: date
    items: List[MacroHighlightItem]


class RecommendationItem(BaseModel):
    sector: str
    size: str
    time_block: str
    theme: str
    comment: str


class RecommendationTodayResponse(BaseModel):
    run_date: date
    summary: str
    items: List[RecommendationItem]


class HeatmapCell(BaseModel):
    sector: str
    size: str
    time_block: str
    score: float  # -1～+1 などの地合いスコア
    label: str


class HeatmapSummaryResponse(BaseModel):
    run_date: date
    items: List[HeatmapCell]


# ============================================================
# 5. ダミーデータ生成用のヘルパー
# ============================================================

def _now() -> datetime:
    """現在時刻を取得（タイムゾーンは簡略化）"""
    return datetime.utcnow()


def _today() -> date:
    return _now().date()


def _dummy_predictions() -> List[PredictionItem]:
    """とりあえず UI が表示できるようにするための仮データ"""
    today = _today()
    return [
        PredictionItem(
            run_date=today,
            run_time="09:30",
            sector="energy",
            size="mid",
            time_block="A",
            symbol="XOM",
            model_name="vol_model_top_features",
            prob_nobori_ryu=0.68,
            prob_fake=0.18,
            expected_return=0.022,
            comment="エネルギー中型・朝イチののぼり竜候補。",
        ),
        PredictionItem(
            run_date=today,
            run_time="09:30",
            sector="tech",
            size="small",
            time_block="A",
            symbol="NVDA",
            model_name="vol_model_top_features",
            prob_nobori_ryu=0.61,
            prob_fake=0.24,
            expected_return=0.019,
            comment="テック小型・押し目狙いの候補。",
        ),
    ]


# ============================================================
# 6. ルート定義
# ============================================================

@app.on_event("startup")
async def on_startup() -> None:
    """起動時にルート一覧をログに出す（デバッグ用）"""
    for route in app.routes:
        if hasattr(route, "methods"):
            logger.info("ROUTE %s %s", list(route.methods), route.path)
    logger.info("Volatility AI API started.")


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health_check() -> HealthResponse:
    """ヘルスチェック用エンドポイント"""
    return HealthResponse(
        status="ok",
        app="volai-api",
        version=app.version,
        timestamp=_now(),
    )


@app.get("/", tags=["system"])
async def root():
    """簡単なトップメッセージ"""
    return {
        "message": "Volatility AI Public API",
        "version": app.version,
        "docs": "/docs",
        "redoc": "/redoc",
    }


# ------------------------------
# /predict/latest
# ------------------------------
@app.get("/predict/latest", response_model=PredictionLatestResponse, tags=["predict"])
async def get_latest_predictions() -> PredictionLatestResponse:
    """
    直近の予測結果（のぼり竜候補など）を返す。

    TODO: 実運用では DB or モデル推論の結果に差し替える。
    """
    items = _dummy_predictions()
    return PredictionLatestResponse(run_at=_now(), items=items)


# ------------------------------
# /summary/size
# ------------------------------
@app.get("/summary/size", response_model=SizeSummaryResponse, tags=["summary"])
async def get_size_summary() -> SizeSummaryResponse:
    """
    サイズ別（large/mid/small/penny）のサマリー。
    UI 側の「サイズ別ヒートマップ」などを想定。
    """
    run_at = _now()
    items = [
        SizeSummaryItem(size="large", signal_count=5, avg_confidence=0.58, avg_fake_rate=0.22),
        SizeSummaryItem(size="mid", signal_count=7, avg_confidence=0.63, avg_fake_rate=0.20),
        SizeSummaryItem(size="small", signal_count=4, avg_confidence=0.60, avg_fake_rate=0.25),
        SizeSummaryItem(size="penny", signal_count=2, avg_confidence=0.55, avg_fake_rate=0.30),
    ]
    return SizeSummaryResponse(run_at=run_at, items=items)


# ------------------------------
# /signals
# ------------------------------
@app.get("/signals", response_model=SignalResponse, tags=["signals"])
async def get_signals() -> SignalResponse:
    """
    実際に「シグナル一覧」で使うためのテーブル相当。
    Streamlit 側でフィルターして表示する想定。
    """
    run_at = _now()
    items = [
        SignalItem(
            sector="energy",
            size="mid",
            time_block="A",
            symbol="XOM",
            direction="long",
            confidence=0.68,
            fake_rate=0.18,
            emoji="🚀",
            comment="のぼり竜パターンA候補。",
        ),
        SignalItem(
            sector="healthcare",
            size="large",
            time_block="B",
            symbol="UNH",
            direction="long",
            confidence=0.62,
            fake_rate=0.20,
            emoji="📈",
            comment="地合い良好・順張り候補。",
        ),
        SignalItem(
            sector="tech",
            size="small",
            time_block="C",
            symbol="NVDA",
            direction="flat",
            confidence=0.52,
            fake_rate=0.30,
            emoji="🤔",
            comment="ボラ高すぎ・様子見推奨。",
        ),
    ]
    return SignalResponse(run_at=run_at, items=items)


# ------------------------------
# /predict/logs
# ------------------------------
@app.get("/predict/logs", response_model=PredictLogsResponse, tags=["predict"])
async def get_predict_logs(limit: int = 50) -> PredictLogsResponse:
    """
    予測ログの一覧。
    Streamlit 側の「予測履歴」タブなどで使う想定。
    """
    now = _now()
    items = [
        PredictLogItem(
            run_at=now,
            sector="energy",
            size="mid",
            time_block="A",
            symbol="XOM",
            model_name="vol_model_top_features",
            prob_nobori_ryu=0.68,
            prob_fake=0.18,
            realized_return=0.021,
            note="パターン通り上昇。",
        ),
        PredictLogItem(
            run_at=now,
            sector="tech",
            size="small",
            time_block="A",
            symbol="NVDA",
            model_name="vol_model_top_features",
            prob_nobori_ryu=0.61,
            prob_fake=0.24,
            realized_return=-0.012,
            note="寄り天でロスカット。",
        ),
    ]
    return PredictLogsResponse(items=items[:limit])


# ------------------------------
# /macro/forecast
# ------------------------------
@app.get("/macro/forecast", response_model=MacroForecastResponse, tags=["macro"])
async def get_macro_forecast() -> MacroForecastResponse:
    """
    翌営業日などのマクロ指標の「ざっくり見通し」。
    UI 上ではカードや簡易テーブルで表示する想定。
    """
    today = _today()
    items = [
        MacroForecastItem(
            name="VIX",
            value=15.2,
            unit="pt",
            direction="flat",
            comment="ボラ水準は平常〜やや低め。",
        ),
        MacroForecastItem(
            name="US10Y",
            value=4.15,
            unit="%",
            direction="down",
            comment="金利低下基調でグロースに追い風。",
        ),
        MacroForecastItem(
            name="CPI (YoY)",
            value=3.1,
            unit="%",
            direction="flat",
            comment="インフレは落ち着きつつある。",
        ),
    ]
    return MacroForecastResponse(run_date=today, items=items)


# ------------------------------
# /macro/highlights
# ------------------------------
@app.get("/macro/highlights", response_model=MacroHighlightsResponse, tags=["macro"])
async def get_macro_highlights() -> MacroHighlightsResponse:
    """
    重要イベントカレンダー的な一覧。
    """
    today = _today()
    items = [
        MacroHighlightItem(
            title="FOMC 声明発表",
            importance="high",
            date=today,
            time="14:00",
            detail="金利据え置き予想が優勢。サプライズに注意。",
        ),
        MacroHighlightItem(
            title="パウエル議長会見",
            importance="high",
            date=today,
            time="14:30",
            detail="今後の利下げペースに関する発言に要注目。",
        ),
        MacroHighlightItem(
            title="週間失業保険申請件数",
            importance="medium",
            date=today,
            time="08:30",
            detail="雇用の強さをチェック。",
        ),
    ]
    return MacroHighlightsResponse(run_date=today, items=items)


# ------------------------------
# /recommendations/today
# ------------------------------
@app.get("/recommendations/today", response_model=RecommendationTodayResponse, tags=["summary"])
async def get_recommendations_today() -> RecommendationTodayResponse:
    """
    今日のざっくり戦略メモ。
    Streamlit ダッシュボード上部の「マーケット概要」などで使える想定。
    """
    today = _today()
    items = [
        RecommendationItem(
            sector="energy",
            size="mid",
            time_block="A",
            theme="のぼり竜狙い",
            comment="エネルギー中型の強いトレンド継続に注目。",
        ),
        RecommendationItem(
            sector="healthcare",
            size="large",
            time_block="B",
            theme="ディフェンシブ",
            comment="指数が荒れる場合の逃げ場候補。",
        ),
        RecommendationItem(
            sector="tech",
            size="small",
            time_block="C",
            theme="ボラ高・短期スキャル",
            comment="ロットを絞りつつ短期勝負向き。",
        ),
    ]
    summary = "地合いは中立〜やや強気。エネルギー中型とヘルスケア大型を中心に監視。"
    return RecommendationTodayResponse(run_date=today, summary=summary, items=items)


# ------------------------------
# /heatmap/summary
# ------------------------------
@app.get("/heatmap/summary", response_model=HeatmapSummaryResponse, tags=["summary"])
async def get_heatmap_summary() -> HeatmapSummaryResponse:
    """
    セクター × サイズ × 時間帯 のヒートマップ用スコア。
    """
    today = _today()
    items = [
        HeatmapCell(
            sector="energy",
            size="mid",
            time_block="A",
            score=0.7,
            label="強気",
        ),
        HeatmapCell(
            sector="healthcare",
            size="large",
            time_block="B",
            score=0.4,
            label="やや強気",
        ),
        HeatmapCell(
            sector="tech",
            size="small",
            time_block="C",
            score=-0.3,
            label="弱気",
        ),
    ]
    return HeatmapSummaryResponse(run_date=today, items=items)


# ============================================================
# 7. ローカル実行用エントリポイント（Render では通常不要）
# ============================================================
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8092"))
    logger.info(f"Starting local server on 0.0.0.0:{port}")
    uvicorn.run("main_api:app", host="0.0.0.0", port=port, reload=True)
