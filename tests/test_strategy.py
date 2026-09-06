"""Unit tests for technical indicators and Master Bull screening strategy."""

import numpy as np
import pandas as pd
import pytest

from indicators.technical import indicators
from strategy.master_bull import MasterBullStrategy


def generate_synthetic_ohlcv(
    trend: str = "bull",
    days: int = 300,
    base_price: float = 100.0,
    volume: float = 1_000_000.0,
) -> pd.DataFrame:
    """產生測試用合成 OHLCV 歷史數據。

    Args:
        trend: 'bull' (穩定多頭上升趨勢) 或 'bear' (空頭破底走勢)
        days: 交易天數
        base_price: 起始股價
        volume: 平均成交量
    """
    np.random.seed(42)
    dates = pd.date_range(end=pd.Timestamp.today(), periods=days, freq="B")

    if trend == "bull":
        # 穩定上升曲線，確保各期均線呈完美多頭排列
        step = np.linspace(0, 50, days)
        noise = np.random.normal(0, 0.5, days)
        close = base_price + step + noise
    else:
        # 下跌走勢
        step = np.linspace(50, 0, days)
        noise = np.random.normal(0, 0.5, days)
        close = base_price + step + noise

    high = close + np.random.uniform(0.5, 2.0, days)
    low = close - np.random.uniform(0.5, 2.0, days)
    open_p = (high + low) / 2.0
    vol = np.random.normal(volume, volume * 0.1, days).clip(min=10_000)

    df = pd.DataFrame(
        {
            "Open": open_p,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": vol,
        },
        index=dates,
    )
    return df


class TestIndicators:
    """測試技術指標計算正確性。"""

    def test_indicator_calculations(self):
        df = generate_synthetic_ohlcv("bull", days=260)
        res = indicators.calculate_all(df)

        assert "SMA_20" in res.columns
        assert "SMA_50" in res.columns
        assert "SMA_150" in res.columns
        assert "SMA_200" in res.columns
        assert "RSI_14" in res.columns
        assert "MACD" in res.columns
        assert "High_52W" in res.columns
        assert "Low_52W" in res.columns

        # 檢驗最後一筆數值在合理範圍
        latest = res.iloc[-1]
        assert latest["SMA_200"] > 0
        assert 0 <= latest["RSI_14"] <= 100
        assert latest["High_52W"] >= latest["Close"]
        assert latest["Low_52W"] <= latest["Close"]


class TestMasterBullStrategy:
    """測試大師多頭策略評估與篩選。"""

    def test_perfect_bull_pass(self):
        strategy = MasterBullStrategy(min_price=10.0, min_volume_shares=100_000)
        bull_df = generate_synthetic_ohlcv("bull", days=300, base_price=100.0, volume=500_000.0)

        eval_res = strategy.evaluate_stock(
            bull_df, meta={"code": "9999", "name": "測試多頭", "market": "TWSE", "industry": "電子業"}
        )

        assert eval_res is not None
        assert eval_res["code"] == "9999"
        # 多頭資料應符合大部分或全部 8 大指標
        assert eval_res["passed_count"] >= 7
        assert eval_res["criteria_details"]["c1_price_above_ma150_200"] is True
        assert eval_res["criteria_details"]["c2_ma150_above_ma200"] is True

    def test_bear_stock_filtered_out(self):
        strategy = MasterBullStrategy(min_price=10.0, min_volume_shares=100_000)
        bear_df = generate_synthetic_ohlcv("bear", days=300, base_price=100.0, volume=500_000.0)

        eval_res = strategy.evaluate_stock(
            bear_df, meta={"code": "8888", "name": "測試空頭", "market": "TWSE", "industry": "傳產業"}
        )

        assert eval_res is not None
        assert eval_res["passed_all"] is False
        # 空頭均線不應排列向上
        assert eval_res["criteria_details"]["c1_price_above_ma150_200"] is False

    def test_low_volume_stock_rejected(self):
        # 設定高量能門檻
        strategy = MasterBullStrategy(min_volume_shares=1_000_000)
        low_vol_df = generate_synthetic_ohlcv("bull", days=300, volume=10_000.0)

        eval_res = strategy.evaluate_stock(low_vol_df)
        assert eval_res is None  # 量能不足直接排除
