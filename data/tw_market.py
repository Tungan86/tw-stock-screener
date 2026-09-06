"""Taiwan Stock Market Ticker Registry and Metadata Provider.

Fetches and caches listed (TWSE - 上市) and OTC (TPEx - 上櫃) equities from official ISIN sources.
Filters for ordinary common stocks and maps them to yfinance compatible symbols (.TW / .TWO).
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
import requests

from config.settings import settings

logger = logging.getLogger(__name__)

CACHE_FILE = settings.DATA_DIR / "tw_stocks_registry.json"


class TWMarketRegistry:
    """Manages Taiwan stock symbols, industry categorization, and market mappings."""

    TWSE_URL = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
    TPEX_URL = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"

    def __init__(self, cache_file: Optional[Path] = None, cache_expiry_days: int = 7):
        self.cache_file = cache_file or CACHE_FILE
        self.cache_expiry_days = cache_expiry_days
        self._stocks: Optional[pd.DataFrame] = None

    def get_stock_list(self, force_refresh: bool = False) -> pd.DataFrame:
        """獲取台股上市與上櫃股票完整清單。

        Returns:
            pd.DataFrame: 包含 columns:
                - code: 股票代碼 (e.g. "2330")
                - name: 股票名稱 (e.g. "台積電")
                - yf_symbol: yfinance 標的代碼 (e.g. "2330.TW" 或 "6488.TWO")
                - market: "TWSE" 或 "TPEx"
                - industry: 產業分類 (e.g. "半導體業")
        """
        if not force_refresh and self._is_cache_valid():
            logger.info("載入本機台股清單快取: %s", self.cache_file)
            try:
                self._stocks = pd.read_json(self.cache_file, dtype={"code": str})
                if not self._stocks.empty:
                    self._stocks["code"] = self._stocks["code"].astype(str)
                    return self._stocks
            except Exception as e:
                logger.warning("讀取股票清單快取失敗，重新抓取: %s", e)

        logger.info("向台灣證交所 / 櫃買中心同步最新股票清單...")
        twse_df = self._fetch_isin_table(self.TWSE_URL, market="TWSE", suffix=".TW")
        tpex_df = self._fetch_isin_table(self.TPEX_URL, market="TPEx", suffix=".TWO")

        combined = pd.concat([twse_df, tpex_df], ignore_index=True)

        if combined.empty:
            logger.warning("官方 ISIN 網頁同步失敗（可能受海外 IP 限制），嘗試透過 TWSE/TPEx OpenAPI 開放資料接口獲取...")
            combined = self._fetch_from_openapi()

        # 若成功透過網路獲取到清單，與既有本機快取進行增量合併 (Smart Upsert)
        if not combined.empty:
            if self.cache_file.exists():
                try:
                    cached_df = pd.read_json(self.cache_file, dtype={"code": str})
                    if not cached_df.empty:
                        cached_df["code"] = cached_df["code"].astype(str)
                        # 保留快取中的詳細產業分類，並增量納入最新掛牌股票 (New IPOs)
                        existing_codes = set(cached_df["code"])
                        new_stocks = combined[~combined["code"].isin(existing_codes)]
                        if not new_stocks.empty:
                            logger.info("偵測到新上市/櫃掛牌標的 %d 檔，自動增量納入: %s", len(new_stocks), new_stocks["code"].tolist())
                            combined = pd.concat([cached_df, new_stocks], ignore_index=True)
                        else:
                            # 無新股票時，以保有詳細產業別的既有清單為主力
                            combined = cached_df
                except Exception as e:
                    logger.warning("增量比對快取失敗，直接採用新抓取清單: %s", e)

            # 寫入快取
            try:
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                combined.to_json(self.cache_file, orient="records", force_ascii=False, indent=2)
                logger.info("已更新並儲存台股清單快取: 共 %d 檔標的", len(combined))
            except Exception as e:
                logger.warning("寫入股票清單快取失敗: %s", e)

            self._stocks = combined
            return self._stocks

        # 網路兩大管道皆不可用時，降級載入既有快取或備援
        if self.cache_file.exists():
            try:
                logger.warning("網路同步失敗，降級載入已存在之本機股票清單快取: %s", self.cache_file)
                cached_df = pd.read_json(self.cache_file, dtype={"code": str})
                if not cached_df.empty:
                    cached_df["code"] = cached_df["code"].astype(str)
                    self._stocks = cached_df
                    return self._stocks
            except Exception as e:
                logger.error("讀取歷史快取失敗: %s", e)

        logger.warning("無法自網路取得最新清單且無快取，載入預設主流股備援清單...")
        self._stocks = self._fallback_stock_list()
        return self._stocks

    def _is_cache_valid(self) -> bool:
        """檢查快取是否存在且未過期。"""
        if not self.cache_file.exists():
            return False
        mtime = self.cache_file.stat().st_mtime
        age_days = (time.time() - mtime) / 86400
        return age_days < self.cache_expiry_days

    def _fetch_isin_table(self, url: str, market: str, suffix: str) -> pd.DataFrame:
        """解析證交所 ISIN 網頁表格，篩選出普通股 (4 碼數字)。"""
        from io import StringIO

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            resp.encoding = "cp950"  # ISIN 頁面使用 CP950/Big5 編碼
            dfs = pd.read_html(StringIO(resp.text))
            if not dfs:
                return pd.DataFrame()

            raw_df = dfs[0]
            raw_df.columns = raw_df.iloc[0]
            raw_df = raw_df.iloc[1:].copy()

            # 尋找「有價證券代號及名稱」與「產業別」欄位
            target_col = None
            industry_col = None
            for col in raw_df.columns:
                col_str = str(col)
                if "有價證券代號及名稱" in col_str or "代號" in col_str:
                    target_col = col
                if "產業別" in col_str:
                    industry_col = col

            if not target_col:
                return pd.DataFrame()

            records = []
            pattern = re.compile(r"^(\d{4})[\s\u3000]+(.+)$")

            for _, row in raw_df.iterrows():
                val = str(row.get(target_col, "")).strip()
                match = pattern.match(val)
                if match:
                    code = match.group(1)
                    name = match.group(2).strip()
                    industry = str(row.get(industry_col, "其他")).strip() if industry_col else "其他"
                    records.append({
                        "code": code,
                        "name": name,
                        "yf_symbol": f"{code}{suffix}",
                        "market": market,
                        "industry": industry if industry and industry != "nan" else "其他"
                    })

            res_df = pd.DataFrame(records)
            logger.info("自 %s 成功解析 %d 檔普通股股票", market, len(res_df))
            return res_df
        except Exception as e:
            logger.error("抓取 %s (%s) 失敗: %s", market, url, e)
            return pd.DataFrame()

    def _fetch_from_openapi(self) -> pd.DataFrame:
        """透過台灣證交所與櫃買中心之官方 OpenAPI 取得最新上市上櫃股票清單。

        OpenAPI 為政府開放資料平台，全球機房 (含海外雲端 runner) 存取穩定無連線阻擋，
        可作為海外執行或新股掛牌 (IPO) 的第二重自動探索管道。
        """
        records = []
        pattern = re.compile(r"^\d{4}$")

        # 1. 抓取 TWSE 上市股票 (當日全部成交行情包含全市場最新上市代碼)
        try:
            twse_url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
            resp = requests.get(twse_url, timeout=15)
            if resp.status_code == 200:
                for item in resp.json():
                    code = str(item.get("Code", "")).strip()
                    if pattern.match(code):
                        records.append({
                            "code": code,
                            "name": str(item.get("Name", "")).strip(),
                            "yf_symbol": f"{code}.TW",
                            "market": "TWSE",
                            "industry": "其他",
                        })
                logger.info("透過 TWSE OpenAPI 成功獲取 %d 檔上市普通股", len([r for r in records if r["market"] == "TWSE"]))
        except Exception as e:
            logger.warning("TWSE OpenAPI 抓取失敗: %s", e)

        # 2. 抓取 TPEx 上櫃股票
        try:
            tpex_url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
            resp = requests.get(tpex_url, timeout=15)
            if resp.status_code == 200:
                for item in resp.json():
                    code = str(item.get("SecuritiesCompanyCode", "")).strip()
                    if pattern.match(code):
                        records.append({
                            "code": code,
                            "name": str(item.get("CompanyName", "")).strip(),
                            "yf_symbol": f"{code}.TWO",
                            "market": "TPEx",
                            "industry": "其他",
                        })
                logger.info("透過 TPEx OpenAPI 成功獲取 %d 檔上櫃普通股", len([r for r in records if r["market"] == "TPEx"]))
        except Exception as e:
            logger.warning("TPEx OpenAPI 抓取失敗: %s", e)

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        df.drop_duplicates(subset=["code"], keep="first", inplace=True)
        logger.info("OpenAPI 合計取得 %d 檔台股上市/上櫃普通股", len(df))
        return df

    def _fallback_stock_list(self) -> pd.DataFrame:
        """當完全無法連外時的基準主流台股清單。"""
        fallback_data = [
            {"code": "2330", "name": "台積電", "yf_symbol": "2330.TW", "market": "TWSE", "industry": "半導體業"},
            {"code": "2454", "name": "聯發科", "yf_symbol": "2454.TW", "market": "TWSE", "industry": "半導體業"},
            {"code": "2317", "name": "鴻海", "yf_symbol": "2317.TW", "market": "TWSE", "industry": "其他電子業"},
            {"code": "2382", "name": "廣達", "yf_symbol": "2382.TW", "market": "TWSE", "industry": "電腦及週邊設備業"},
            {"code": "3231", "name": "緯創", "yf_symbol": "3231.TW", "market": "TWSE", "industry": "電腦及週邊設備業"},
            {"code": "2308", "name": "台達電", "yf_symbol": "2308.TW", "market": "TWSE", "industry": "電子零組件業"},
            {"code": "2379", "name": "瑞昱", "yf_symbol": "2379.TW", "market": "TWSE", "industry": "半導體業"},
            {"code": "3034", "name": "聯詠", "yf_symbol": "3034.TW", "market": "TWSE", "industry": "半導體業"},
            {"code": "3008", "name": "大立光", "yf_symbol": "3008.TW", "market": "TWSE", "industry": "光電業"},
            {"code": "2603", "name": "長榮", "yf_symbol": "2603.TW", "market": "TWSE", "industry": "航運業"},
            {"code": "2609", "name": "陽明", "yf_symbol": "2609.TW", "market": "TWSE", "industry": "航運業"},
            {"code": "6488", "name": "環球晶", "yf_symbol": "6488.TWO", "market": "TPEx", "industry": "半導體業"},
            {"code": "8069", "name": "元太", "yf_symbol": "8069.TWO", "market": "TPEx", "industry": "光電業"},
            {"code": "3293", "name": "鈊象", "yf_symbol": "3293.TWO", "market": "TPEx", "industry": "文化創意業"},
            {"code": "6510", "name": "精測", "yf_symbol": "6510.TWO", "market": "TPEx", "industry": "半導體業"},
            {"code": "5274", "name": "信驊", "yf_symbol": "5274.TWO", "market": "TPEx", "industry": "半導體業"},
        ]
        return pd.DataFrame(fallback_data)


market_registry = TWMarketRegistry()
