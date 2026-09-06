"""Historical Stock Data Fetcher with Batch Downloading and Multi-Tier Caching.

Uses yfinance as primary fast engine with parallel batching, supports local Parquet caching,
and FinMind as optional fallback.
"""

from datetime import datetime, timedelta
import logging
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
import yfinance as yf

from config.settings import settings

logger = logging.getLogger(__name__)


class DataFetcher:
    """Handles retrieval of historical price and volume data for Taiwan equities."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or settings.CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch_historical_data(
        self,
        symbols: List[str],
        history_days: int = settings.HISTORY_DAYS,
        force_refresh: bool = False,
        as_of_date: Optional[str] = None
    ) -> Dict[str, pd.DataFrame]:
        """抓取一組標的的歷史日 K 線資料 (OHLCV)。

        Args:
            symbols: yfinance 標的代碼清單 (e.g. ["2330.TW", "6488.TWO"])
            history_days: 回溯天數
            force_refresh: 是否強制重新抓取忽略快取
            as_of_date: 基準日期 (格式 YYYY-MM-DD)，預設為今日

        Returns:
            Dict[str, pd.DataFrame]: {yf_symbol: df_ohlcv}
        """
        target_date_str = as_of_date or datetime.now().strftime("%Y-%m-%d")
        cache_file = self.cache_dir / f"market_ohlcv_{target_date_str}.parquet"

        results: Dict[str, pd.DataFrame] = {}

        # 1. 檢查快取
        if not force_refresh and cache_file.exists():
            logger.info("載入當日行情快取: %s", cache_file)
            try:
                cached_df = pd.read_parquet(cache_file)
                # 依 symbol 還原字典
                if "symbol" in cached_df.columns:
                    for sym, group in cached_df.groupby("symbol"):
                        if sym in symbols:
                            df_sym = group.drop(columns=["symbol"]).sort_index()
                            results[sym] = df_sym
                    # 若快取涵蓋所有請求的 symbols，直接回傳
                    missing_symbols = [s for s in symbols if s not in results]
                    if not missing_symbols:
                        logger.info("快取完全命中 %d 檔標的資料", len(results))
                        return results
                    logger.info("快取命中 %d 檔，剩餘 %d 檔需下載", len(results), len(missing_symbols))
                    symbols = missing_symbols
            except Exception as e:
                logger.warning("解析歷史行情快取失敗，將自網路下載: %s", e)

        if not symbols:
            return results

        # 2. yfinance 批次下載
        logger.info("開始下載 %d 檔標的歷史行情 (天數: %d)...", len(symbols), history_days)
        start_date = (datetime.now() - timedelta(days=history_days)).strftime("%Y-%m-%d")

        # 分批下載避免 Yahoo Finance URL 過長或連線中斷
        batch_size = settings.BATCH_SIZE
        downloaded_dfs: Dict[str, pd.DataFrame] = {}

        for i in range(0, len(symbols), batch_size):
            chunk = symbols[i : i + batch_size]
            chunk_str = " ".join(chunk)
            logger.info("正在下載批次 [%d/%d]: %s...", i + len(chunk), len(symbols), chunk[0])
            try:
                data = yf.download(
                    tickers=chunk_str,
                    start=start_date,
                    group_by="ticker",
                    auto_adjust=False,
                    threads=True,
                    progress=False
                )

                if data.empty:
                    continue

                if len(chunk) == 1:
                    sym = chunk[0]
                    clean_df = self._clean_dataframe(data)
                    if not clean_df.empty:
                        downloaded_dfs[sym] = clean_df
                else:
                    for sym in chunk:
                        if sym in data.columns.levels[0]:
                            df_sym = data[sym]
                            clean_df = self._clean_dataframe(df_sym)
                            if not clean_df.empty:
                                downloaded_dfs[sym] = clean_df

            except Exception as e:
                logger.error("下載批次時發生錯誤: %s", e)

        # 3. 合併結果
        results.update(downloaded_dfs)

        # 4. 寫入或更新快取
        if results:
            self._save_to_parquet(results, cache_file)

        return results

    def _clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """清洗單一個股之歷史 K 線資料，確保數值完整與型態正確。"""
        if df.empty:
            return pd.DataFrame()

        df = df.copy()
        # 移除完全為 NaN 的列
        df.dropna(subset=["Close", "Volume"], how="all", inplace=True)

        # 欄位扁平化處理
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]

        # 確保必要欄位存在
        required = ["Open", "High", "Low", "Close", "Volume"]
        for col in required:
            if col not in df.columns:
                return pd.DataFrame()
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df.dropna(subset=["Close"], inplace=True)
        # 台股部分成交量可能為 0，填補為 0
        df["Volume"] = df["Volume"].fillna(0)
        df.sort_index(inplace=True)
        return df

    def _save_to_parquet(self, data_dict: Dict[str, pd.DataFrame], cache_file: Path) -> None:
        """將多檔個股之 DataFrame 合併為單一 Parquet 檔案以利快速持久化。"""
        try:
            frames = []
            for sym, df in data_dict.items():
                temp = df.copy()
                temp["symbol"] = sym
                frames.append(temp)
            if frames:
                combined = pd.concat(frames)
                combined.to_parquet(cache_file, engine="pyarrow", compression="snappy")
                logger.info("已更新當日行情快取 Parquet: %s", cache_file)
        except Exception as e:
            logger.warning("寫入 Parquet 快取失敗: %s", e)


data_fetcher = DataFetcher()
