"""Trader Decision Insight and Portfolio Risk Management Engine.

Implements Top-Down Industry Capital Flow Analysis, Actionable Dual-Bucket Categorization
(Breakout Momentum vs. Trend Core & Defensive), and Wall Street 1% Risk Position Sizing.
"""

from dataclasses import dataclass
import logging
from math import floor
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class RiskSizingResult:
    """財務風控與部位試算結果。"""

    code: str
    name: str
    close: float
    atr_14: float
    stop_price: float
    stop_pct: float
    max_risk_amount: float
    max_shares_lots: int
    est_allocated_capital: float
    est_capital_ratio_pct: float


class TraderInsightEngine:
    """專業交易員決策分析與財務風控模組。"""

    def __init__(self, default_capital: float = 10_000_000.0, default_risk_pct: float = 0.01):
        self.default_capital = default_capital
        self.default_risk_pct = default_risk_pct

    def analyze(self, df_screener: pd.DataFrame, total_capital: Optional[float] = None) -> Dict[str, Any]:
        """執行由上而下 (Top-Down) 的全方位交易員決策分析。

        Args:
            df_screener: 選股母體或達標 DataFrame (來自 master_bull_strategy.run_screening)
            total_capital: 總管理資本 (預設 1,000 萬 TWD)

        Returns:
            Dict[str, Any]: 包含市場水溫、產業資金流向、兩大戰術籃子及風控試算的完整資料集。
        """
        capital = total_capital or self.default_capital

        if df_screener.empty:
            return self._empty_response(capital)

        df = df_screener.copy()

        # 1. 預估成交金額 (億元) = 收盤價 * 成交量(張) * 1,000 / 100,000,000
        # 即收盤價 * 成交量(張) / 100,000
        if "turnover_yi" not in df.columns:
            vol_lots = df["volume_lots"] if "volume_lots" in df.columns else df["Volume"] / 1000.0
            df["turnover_yi"] = (df["close"] * vol_lots) / 100_000.0
            df["turnover_yi"] = df["turnover_yi"].round(2)

        # 2. 產業板塊真實資金流向與熱力聚合
        industry_summary = self._analyze_industry_capital_flow(df)

        # 3. 執行端標的智慧分類 (帶量突破組 vs. 波段核心組)
        bucket_a, bucket_b = self._categorize_actionable_buckets(df, capital)

        # 4. 市場多頭水溫儀表 (Top-Down Climate)
        total_stocks_scanned = len(df)
        passed_8_stocks = df[df["passed_all"] == True]
        passed_8_count = len(passed_8_stocks)

        total_turnover = df["turnover_yi"].sum()
        passed_8_turnover = passed_8_stocks["turnover_yi"].sum() if not passed_8_stocks.empty else 0.0
        passed_8_turnover_ratio = (
            round((passed_8_turnover / total_turnover * 100.0), 1) if total_turnover > 0 else 0.0
        )

        # 市場水溫燈號與戰術建議
        if passed_8_count >= 100 and passed_8_turnover_ratio >= 35.0:
            market_climate = "🔥 主流多頭主升段，全力順勢做多"
            market_climate_badge = "bull_hyper"
            market_action_guide = "市場資金全面擁抱多頭主流，可放大風險預算至 1.0%~1.5%，積極進攻帶量突破組。"
        elif passed_8_count >= 40:
            market_climate = "⚡️ 族群分化輪動，聚焦突破龍頭"
            market_climate_badge = "bull_moderate"
            market_action_guide = "個股行情強於大盤，嚴守突破關鍵價買點，避開乖離過大標的，維持標準 1.0% 風控。"
        else:
            market_climate = "🛡️ 震盪防禦期，縮小部位嚴控停損"
            market_climate_badge = "defensive"
            market_action_guide = "多頭標的較為收斂，建議配置以低波動波段核心組為主，單筆風險降至 0.5%~0.7%。"

        return {
            "summary": {
                "total_scanned": total_stocks_scanned,
                "passed_8_count": passed_8_count,
                "total_turnover_yi": round(float(total_turnover), 1),
                "passed_8_turnover_yi": round(float(passed_8_turnover), 1),
                "passed_8_turnover_ratio_pct": passed_8_turnover_ratio,
                "market_climate": market_climate,
                "market_climate_badge": market_climate_badge,
                "market_action_guide": market_action_guide,
                "total_capital": capital,
            },
            "industry_capital_flow": industry_summary,
            "bucket_a_breakout": bucket_a,
            "bucket_b_core": bucket_b,
        }

    def _analyze_industry_capital_flow(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """計算產業板塊真實資金流向、佔比與角色判定。"""
        total_market_turnover = df["turnover_yi"].sum()
        industries = []

        for industry_name, group in df.groupby("industry"):
            turnover_sum = group["turnover_yi"].sum()
            turnover_ratio = (
                round((turnover_sum / total_market_turnover * 100.0), 2)
                if total_market_turnover > 0
                else 0.0
            )

            passed_8_cnt = int(group["passed_all"].sum())
            avg_pct_chg = round(float(group["pct_change"].mean()), 2)
            avg_vol_ratio = round(float(group["vol_ratio"].mean()), 2)
            avg_dist_52w_high = round(float(group["pct_below_52w_high"].mean()), 1)
            avg_atr = round(float(group["atr_14"].mean()), 2) if "atr_14" in group.columns else 0.0

            industries.append({
                "industry": industry_name,
                "turnover_yi": round(float(turnover_sum), 1),
                "turnover_ratio_pct": turnover_ratio,
                "total_stocks": len(group),
                "passed_8_count": passed_8_cnt,
                "avg_pct_change": avg_pct_chg,
                "avg_vol_ratio": avg_vol_ratio,
                "avg_dist_52w_high": avg_dist_52w_high,
                "avg_atr": avg_atr,
            })

        # 依總成交金額降冪排序
        industries.sort(key=lambda x: x["turnover_yi"], reverse=True)

        # 標註市場角色 (主力攻擊矛 vs. 底層防禦盾 vs. 中游擴散部隊)
        for idx, item in enumerate(industries):
            turnover_rank = idx + 1
            if turnover_rank <= 3 and item["avg_pct_change"] >= 2.0:
                item["role"] = "主力攻擊矛"
                item["role_desc"] = "吸金主流且漲勢凌厲，資金核心進攻方向"
                item["role_color"] = "red"
            elif item["industry"] == "金融保險業" or (
                item["passed_8_count"] >= 2 and item["avg_dist_52w_high"] <= 5.0 and item["avg_atr"] <= 2.5
            ):
                item["role"] = "底層防禦盾"
                item["role_desc"] = "貼近新高但波動度低，走勢平穩的防禦性資金避風港"
                item["role_color"] = "blue"
            else:
                item["role"] = "中游擴散部隊"
                item["role_desc"] = "中小型跟進族群，注意個股分化"
                item["role_color"] = "gray"

        return industries

    def _categorize_actionable_buckets(
        self, df: pd.DataFrame, total_capital: float
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """智慧分流：【帶量突破攻擊組】與【波段趨勢核心組】，並附帶風控部位試算。"""
        # 以 8/8 完美達標為優先基準，若 8/8 標的充足則取 8/8；否則納入 7/8 以上候選
        passed_pool = df[df["passed_all"] == True].copy()
        if len(passed_pool) < 15:
            passed_pool = df[df["passed_count"] >= 7].copy()

        bucket_a_records = []
        bucket_b_records = []

        for _, row in passed_pool.iterrows():
            row_dict = row.to_dict()

            # 計算 1% 資本風險試算
            risk_res = self.calculate_position_size(
                close=float(row_dict.get("close", 0.0)),
                atr_14=float(row_dict.get("atr_14", 1.0)),
                total_capital=total_capital,
                risk_pct=self.default_risk_pct,
            )

            row_dict.update({
                "stop_price": risk_res.stop_price,
                "stop_pct": risk_res.stop_pct,
                "max_shares_lots": risk_res.max_shares_lots,
                "est_allocated_capital": risk_res.est_allocated_capital,
                "est_capital_ratio_pct": risk_res.est_capital_ratio_pct,
            })

            dist_high = float(row_dict.get("pct_below_52w_high", 99.0))
            vol_ratio = float(row_dict.get("vol_ratio", 1.0))
            turnover_yi = float(row_dict.get("turnover_yi", 0.0))
            industry = str(row_dict.get("industry", ""))
            rsi = float(row_dict.get("rsi_14", 50.0))

            # ----------------------------------------------------
            # 籃子 A：帶量突破攻擊組 (Breakout Momentum)
            # 條件：距 52W 高點 <= 5.0% 且 量能倍數 >= 1.2
            # ----------------------------------------------------
            if dist_high <= 5.0 and vol_ratio >= 1.2:
                if rsi >= 80.0:
                    note = "⚠️ 短線過熱 (RSI>80)，禁止市價追高，宜逢量縮拉回再低接"
                    tag = "過熱警戒"
                elif dist_high <= 0.5:
                    note = "🚀 創波段新高突破買點，主力強勢表態"
                    tag = "新高突破"
                else:
                    note = "🔥 帶量蓄勢突破，動能充沛"
                    tag = "量能放大"

                row_dict["trader_note"] = note
                row_dict["action_tag"] = tag
                bucket_a_records.append(row_dict)

            # ----------------------------------------------------
            # 籃子 B：波段趨勢核心組 (Trend Core & Defensive)
            # 條件：成交金額 >= 10 億元之權值標的，或距 52W 高點 <= 5% 之優質金融/低波動標的
            # ----------------------------------------------------
            is_large_cap = turnover_yi >= 10.0
            is_financial_defense = (industry == "金融保險業") and (dist_high <= 6.0)
            is_steady_trend = (dist_high <= 4.0) and (float(row_dict.get("atr_14", 99.0)) <= 3.0)

            if is_large_cap or is_financial_defense or is_steady_trend:
                if is_large_cap and is_financial_defense:
                    note = "🛡️ 兆元權值防禦盾，長線生命線支撐穩固"
                    tag = "金融權值"
                elif is_large_cap:
                    note = "🏛️ 巨量權值領頭羊，外資主力持股重心"
                    tag = "權值核心"
                else:
                    note = "💎 低波動趨勢壓艙石，回檔支撐強勁"
                    tag = "波段核心"

                row_dict["trader_note"] = note
                row_dict["action_tag"] = tag
                bucket_b_records.append(row_dict)

        # 排序：攻擊組依量能倍數與距高點排序；核心組依成交金額排序
        bucket_a_records.sort(
            key=lambda x: (x.get("pct_below_52w_high", 99), -x.get("vol_ratio", 0))
        )
        bucket_b_records.sort(
            key=lambda x: -x.get("turnover_yi", 0)
        )

        return bucket_a_records, bucket_b_records

    def calculate_position_size(
        self,
        close: float,
        atr_14: float,
        total_capital: float = 10_000_000.0,
        risk_pct: float = 0.01,
        multiplier: float = 2.0,
    ) -> RiskSizingResult:
        """依據 1% 資本風險紀律與 2x ATR 動態停損點計算部位大小。

        公式：
          動態停損價 = 收盤價 - 2.0 * ATR
          每股風險金額 = 2.0 * ATR
          每張風險金額 = 每股風險金額 * 1,000
          最大可承擔虧損 = 總資本 * 1%
          建議買進張數 = floor(最大可承擔虧損 / 每張風險金額)
        """
        atr = max(0.05, atr_14)
        stop_dist = multiplier * atr
        stop_price = max(0.1, round(close - stop_dist, 2))
        stop_pct = round((close - stop_price) / close * 100.0, 2) if close > 0 else 0.0

        max_risk_amount = total_capital * risk_pct
        risk_per_lot = (close - stop_price) * 1000.0

        if risk_per_lot > 0:
            max_shares_lots = int(floor(max_risk_amount / risk_per_lot))
        else:
            max_shares_lots = 0

        # 防呆：至少 0 張
        max_shares_lots = max(0, max_shares_lots)
        est_allocated_capital = round(max_shares_lots * 1000.0 * close, 0)
        est_capital_ratio_pct = (
            round(est_allocated_capital / total_capital * 100.0, 2)
            if total_capital > 0
            else 0.0
        )

        return RiskSizingResult(
            code="",
            name="",
            close=close,
            atr_14=atr,
            stop_price=stop_price,
            stop_pct=stop_pct,
            max_risk_amount=round(max_risk_amount, 0),
            max_shares_lots=max_shares_lots,
            est_allocated_capital=est_allocated_capital,
            est_capital_ratio_pct=est_capital_ratio_pct,
        )

    def _empty_response(self, capital: float) -> Dict[str, Any]:
        """無資料時的回傳骨架。"""
        return {
            "summary": {
                "total_scanned": 0,
                "passed_8_count": 0,
                "total_turnover_yi": 0.0,
                "passed_8_turnover_yi": 0.0,
                "passed_8_turnover_ratio_pct": 0.0,
                "market_climate": "無交易數據",
                "market_climate_badge": "neutral",
                "market_action_guide": "無資料可供分析。",
                "total_capital": capital,
            },
            "industry_capital_flow": [],
            "bucket_a_breakout": [],
            "bucket_b_core": [],
        }


trader_engine = TraderInsightEngine()
