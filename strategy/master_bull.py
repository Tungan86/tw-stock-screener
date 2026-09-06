"""Master Bull Strategy Screener (台股_大師多頭策略).

Recreates the classic Trend Template & Stage 2 Momentum Bull Strategy popularized by
Mark Minervini and Stan Weinstein, tailored for the Taiwan Stock Market (TWSE / TPEx).
"""

import logging
from typing import Dict, List, Optional
import pandas as pd

from config.settings import settings
from indicators.technical import indicators

logger = logging.getLogger(__name__)


class MasterBullStrategy:
    """Implements the complete Minervini Trend Template & Stage 2 Bull Screener."""

    def __init__(
        self,
        min_price: float = settings.MIN_PRICE,
        min_volume_shares: int = settings.MIN_VOLUME_SHARES,
        min_rsi: float = settings.MIN_RSI,
        min_dist_52w_low_pct: float = settings.MIN_DIST_52W_LOW_PCT,
        max_dist_52w_high_pct: float = settings.MAX_DIST_52W_HIGH_PCT,
        ma200_lookback_days: int = settings.MA200_TREND_LOOKBACK_DAYS,
    ):
        self.min_price = min_price
        self.min_volume_shares = min_volume_shares
        self.min_rsi = min_rsi
        self.min_dist_52w_low_pct = min_dist_52w_low_pct
        self.max_dist_52w_high_pct = max_dist_52w_high_pct
        self.ma200_lookback_days = ma200_lookback_days

    def evaluate_stock(
        self,
        df_raw: pd.DataFrame,
        meta: Optional[Dict[str, str]] = None
    ) -> Optional[Dict]:
        """評估單一個股是否符合大師多頭策略。

        Args:
            df_raw: 該個股歷史 OHLCV (至少包含 200 交易日以上)
            meta: 個股基本資訊 (code, name, market, industry 等)

        Returns:
            Optional[Dict]: 若符合基本篩選評估回傳詳細指標與評判結果字典，資料不足則回傳 None。
        """
        if df_raw.empty or len(df_raw) < 200:
            return None

        # 計算技術指標
        df = indicators.calculate_all(df_raw)
        latest = df.iloc[-1]

        close = float(latest["Close"])
        volume = float(latest["Volume"])
        vol_ma20 = float(latest["Volume_MA_20"]) if not pd.isna(latest["Volume_MA_20"]) else 0.0

        # 流動性與最低價格門檻
        if close < self.min_price:
            return None
        if vol_ma20 < self.min_volume_shares:
            return None

        sma_50 = float(latest["SMA_50"])
        sma_150 = float(latest["SMA_150"])
        sma_200 = float(latest["SMA_200"])
        high_52w = float(latest["High_52W"])
        low_52w = float(latest["Low_52W"])
        rsi = float(latest["RSI_14"])
        pct_above_low = float(latest["Pct_Above_52W_Low"])
        pct_below_high = float(latest["Pct_Below_52W_High"])
        sma_200_up = bool(latest["SMA_200_trending_up"])

        # 檢驗八大多頭核心條件 (Minervini Trend Template + Momentum)
        c1_price_above_ma150_200 = close > sma_150 and close > sma_200
        c2_ma150_above_ma200 = sma_150 > sma_200
        c3_ma200_trending_up = sma_200_up
        c4_ma50_above_long_ma = sma_50 > sma_150 and sma_50 > sma_200
        c5_price_above_ma50 = close > sma_50
        c6_above_52w_low = pct_above_low >= (self.min_dist_52w_low_pct * 100.0)
        c7_near_52w_high = pct_below_high <= (self.max_dist_52w_high_pct * 100.0)
        c8_rsi_bullish = rsi >= self.min_rsi

        conditions = [
            c1_price_above_ma150_200,
            c2_ma150_above_ma200,
            c3_ma200_trending_up,
            c4_ma50_above_long_ma,
            c5_price_above_ma50,
            c6_above_52w_low,
            c7_near_52w_high,
            c8_rsi_bullish,
        ]

        passed_count = sum(conditions)
        is_all_passed = (passed_count == len(conditions))

        meta = meta or {}
        code = meta.get("code", "")
        name = meta.get("name", "")
        market = meta.get("market", "")
        industry = meta.get("industry", "")

        return {
            "code": code,
            "name": name,
            "market": market,
            "industry": industry,
            "close": round(close, 2),
            "pct_change": round(float(latest["Pct_Change"]), 2),
            "volume_lots": round(float(latest["Volume_Lots"]), 0),
            "vol_ma20_lots": round(float(latest["Volume_MA_20_Lots"]), 0),
            "vol_ratio": round(float(latest["Volume_Ratio"]), 2),
            "sma_20": round(float(latest["SMA_20"]), 2),
            "sma_50": round(sma_50, 2),
            "sma_150": round(sma_150, 2),
            "sma_200": round(sma_200, 2),
            "high_52w": round(high_52w, 2),
            "low_52w": round(low_52w, 2),
            "pct_above_52w_low": round(pct_above_low, 1),
            "pct_below_52w_high": round(pct_below_high, 1),
            "rsi_14": round(rsi, 1),
            "macd_hist": round(float(latest["MACD_Hist"]), 3),
            "atr_14": round(float(latest["ATR_14"]), 2),
            "passed_all": is_all_passed,
            "passed_count": passed_count,
            "criteria_details": {
                "c1_price_above_ma150_200": c1_price_above_ma150_200,
                "c2_ma150_above_ma200": c2_ma150_above_ma200,
                "c3_ma200_trending_up": c3_ma200_trending_up,
                "c4_ma50_above_long_ma": c4_ma50_above_long_ma,
                "c5_price_above_ma50": c5_price_above_ma50,
                "c6_above_52w_low": c6_above_52w_low,
                "c7_near_52w_high": c7_near_52w_high,
                "c8_rsi_bullish": c8_rsi_bullish,
            }
        }

    def run_screening(
        self,
        market_data: Dict[str, pd.DataFrame],
        stock_meta: pd.DataFrame,
        only_perfect: bool = True
    ) -> pd.DataFrame:
        """對全市場或指定股票集體進行大師多頭策略掃描。

        Args:
            market_data: {yf_symbol: ohlcv_df}
            stock_meta: 股票基本資料 (code, name, yf_symbol, market, industry)
            only_perfect: 是否僅篩選 100% 滿足 8 大條件者 (False 則納入 7/8 觀察名單)

        Returns:
            pd.DataFrame: 排序後的篩選結果清單
        """
        meta_dict = stock_meta.set_index("yf_symbol").to_dict(orient="index") if not stock_meta.empty else {}

        results = []
        for symbol, df in market_data.items():
            meta = meta_dict.get(symbol, {
                "code": symbol.split(".")[0],
                "name": symbol,
                "market": "TWSE" if symbol.endswith(".TW") else "TPEx",
                "industry": "其他"
            })
            eval_res = self.evaluate_stock(df, meta=meta)
            if not eval_res:
                continue

            if only_perfect and not eval_res["passed_all"]:
                continue

            results.append(eval_res)

        if not results:
            logger.info("本輪篩選無符合條件之標的。")
            return pd.DataFrame()

        df_res = pd.DataFrame(results)

        # 欄位依實用重要性排序
        sort_cols = ["passed_all", "pct_below_52w_high", "pct_change"]
        df_res.sort_values(by=sort_cols, ascending=[False, True, False], inplace=True)
        df_res.reset_index(drop=True, inplace=True)

        logger.info(
            "大師多頭策略掃描完成: 檢驗 %d 檔，精選出 %d 檔 (全數達標: %d 檔)",
            len(market_data),
            len(df_res),
            df_res["passed_all"].sum()
        )
        return df_res


master_bull_strategy = MasterBullStrategy()
