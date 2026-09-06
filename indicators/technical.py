"""Vectorized Technical Indicators Computation for Quantitative Screening.

Computes Moving Averages, RSI, MACD, 52-Week Ranges, ATR, and Volume Statistics.
"""

from typing import Optional
import numpy as np
import pandas as pd


class TechnicalIndicators:
    """Calculates all essential technical indicators required by trend following strategies."""

    @staticmethod
    def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
        """對單一個股之 OHLCV DataFrame 計算所有技術指標。

        Args:
            df: 包含 ['Open', 'High', 'Low', 'Close', 'Volume'] 之 DataFrame (依日期由舊到新排序)

        Returns:
            pd.DataFrame: 包含所有新增指標之 DataFrame
        """
        if df.empty or len(df) < 50:
            return df.copy()

        res = df.copy()

        # 1. 移動平均線 (Moving Averages)
        res["SMA_20"] = res["Close"].rolling(window=20).mean()
        res["SMA_50"] = res["Close"].rolling(window=50).mean()
        res["SMA_150"] = res["Close"].rolling(window=150).mean()
        res["SMA_200"] = res["Close"].rolling(window=200).mean()

        # 200日均線斜率 / 趨勢 (過去 20 個交易日比較)
        res["SMA_200_20d_ago"] = res["SMA_200"].shift(20)
        res["SMA_200_trending_up"] = res["SMA_200"] > res["SMA_200_20d_ago"]

        # 2. 52 週 (約 250 交易日) 最高點與最低點
        lookback_52w = min(250, len(res))
        res["High_52W"] = res["High"].rolling(window=lookback_52w).max()
        res["Low_52W"] = res["Low"].rolling(window=lookback_52w).min()

        # 與 52 週高低點之百分比距離
        # 距離 52W 低點漲幅: (Close - Low_52W) / Low_52W * 100%
        res["Pct_Above_52W_Low"] = (res["Close"] - res["Low_52W"]) / res["Low_52W"] * 100.0
        # 距離 52W 高點折價: (High_52W - Close) / High_52W * 100% (越接近 0 代表越接近歷史新高)
        res["Pct_Below_52W_High"] = (res["High_52W"] - res["Close"]) / res["High_52W"] * 100.0

        # 3. 相對強弱指標 RSI (14) - Wilder's Smoothing
        res["RSI_14"] = TechnicalIndicators.compute_rsi(res["Close"], period=14)

        # 4. 指數平滑異同移動平均線 MACD (12, 26, 9)
        macd_line, macd_signal, macd_hist = TechnicalIndicators.compute_macd(res["Close"])
        res["MACD"] = macd_line
        res["MACD_Signal"] = macd_signal
        res["MACD_Hist"] = macd_hist

        # 5. 成交量指標
        res["Volume_MA_20"] = res["Volume"].rolling(window=20).mean()
        res["Volume_MA_5"] = res["Volume"].rolling(window=5).mean()
        res["Volume_Ratio"] = np.where(res["Volume_MA_20"] > 0, res["Volume"] / res["Volume_MA_20"], 1.0)
        # 台股單位：張 (1張 = 1000股)
        res["Volume_Lots"] = res["Volume"] / 1000.0
        res["Volume_MA_20_Lots"] = res["Volume_MA_20"] / 1000.0

        # 6. 當日漲跌幅 %
        res["Pct_Change"] = res["Close"].pct_change() * 100.0

        # 7. 平均真實波幅 ATR (14)
        res["ATR_14"] = TechnicalIndicators.compute_atr(res["High"], res["Low"], res["Close"], period=14)

        return res

    @staticmethod
    def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """計算相對強弱指標 RSI。"""
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -1 * delta.clip(upper=0)

        # 使用指數加權平滑 (EMA alpha = 1/period)
        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi.fillna(50.0)

    @staticmethod
    def compute_macd(
        series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """計算 MACD 指標。"""
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        macd_signal = macd_line.ewm(span=signal, adjust=False).mean()
        macd_hist = macd_line - macd_signal
        return macd_line, macd_signal, macd_hist

    @staticmethod
    def compute_atr(
        high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
    ) -> pd.Series:
        """計算平均真實波幅 ATR。"""
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr


indicators = TechnicalIndicators()
