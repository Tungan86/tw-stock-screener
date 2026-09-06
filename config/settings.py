"""Application Settings and Strategy Configuration.

Loads settings from environment variables, .env file, or provides sensible defaults.
"""

from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Global configuration settings for Taiwan Stock Screener."""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # 專案路徑設定
    PROJECT_DIR: Path = BASE_DIR
    DATA_DIR: Path = BASE_DIR / "data"
    CACHE_DIR: Path = BASE_DIR / "data" / "cache"
    ARCHIVE_DIR: Path = BASE_DIR / "data" / "archive"
    OUTPUT_DIR: Path = BASE_DIR / "output"

    # 大師多頭策略 (Master Bull Strategy / Minervini Trend Template) 參數
    MIN_PRICE: float = Field(default=10.0, description="最低股價門檻 (排除雞蛋水餃股)")
    MIN_VOLUME_SHARES: int = Field(default=500_000, description="20日平均最低成交量 (股)，500張")
    MIN_RSI: float = Field(default=50.0, description="RSI(14) 最低動能門檻")
    MIN_DIST_52W_LOW_PCT: float = Field(default=0.25, description="高於 52 週低點至少 25%")
    MAX_DIST_52W_HIGH_PCT: float = Field(default=0.25, description="距離 52 週高點在 25% 內")
    MA200_TREND_LOOKBACK_DAYS: int = Field(default=20, description="200日均線上揚確認天數")

    # 數據獲取設定
    HISTORY_DAYS: int = Field(default=380, description="歷史回溯天數 (確保足夠計算 200MA 與 52W 高低點)")
    BATCH_SIZE: int = Field(default=50, description="yfinance 批次下載切片大小")
    MAX_WORKERS: int = Field(default=8, description="並發執行緒數")
    FINMIND_TOKEN: Optional[str] = Field(default=None, description="FinMind 備援 API Token")

    # Google 雲端同步設定
    SERVICE_ACCOUNT_FILE: str = Field(
        default=str(BASE_DIR / "service_account.json"),
        description="Google Cloud 服務帳號 JSON 檔案路徑"
    )
    GOOGLE_SHEET_ID: Optional[str] = Field(default=None, description="目標 Google Sheet ID")
    GOOGLE_SHEET_TITLE: str = Field(default="台股大師多頭選股監控表", description="若無 Sheet ID 則依名稱建立/讀取")
    GOOGLE_DRIVE_FOLDER_ID: Optional[str] = Field(default=None, description="Google Drive 歸檔資料夾 ID")

    # Gemini AI 盤後分析設定
    GEMINI_API_KEY: Optional[str] = Field(default=None, description="Google Gemini API Key (支援 AI Studio 免費金鑰)")
    GEMINI_MODEL: str = Field(default="gemini-3.1-flash-lite", description="Gemini 分析使用模型 (預設 gemini-3.1-flash-lite)")

    # 執行與日誌設定
    LOG_LEVEL: str = Field(default="INFO", description="日誌等級 (DEBUG, INFO, WARNING, ERROR)")
    CACHE_EXPIRY_HOURS: int = Field(default=8, description="本機行情快取有效小時數")

    def ensure_directories(self) -> None:
        """確保所有工作目錄均已建立。"""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
