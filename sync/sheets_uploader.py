"""Google Sheets Auto-Sync and Uploader.

Uploads quantitative screening results to Google Sheets via gspread, applying
professional styling, frozen headers, and historical tab archiving.
"""

from datetime import datetime
import logging
from pathlib import Path
from typing import Optional, Tuple
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd

from config.settings import settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# 繁體中文友善欄位映射表
COLUMN_MAPPING = {
    "code": "股票代碼",
    "name": "股票名稱",
    "market": "市場",
    "industry": "產業別",
    "close": "收盤價",
    "pct_change": "漲跌幅(%)",
    "volume_lots": "成交量(張)",
    "vol_ma20_lots": "20日均量(張)",
    "vol_ratio": "量能倍數",
    "sma_20": "20MA",
    "sma_50": "50MA",
    "sma_150": "150MA",
    "sma_200": "200MA",
    "high_52w": "52W最高",
    "low_52w": "52W最低",
    "pct_below_52w_high": "距52W高點(%)",
    "pct_above_52w_low": "距52W低點(%)",
    "rsi_14": "RSI(14)",
    "macd_hist": "MACD柱狀",
    "atr_14": "ATR(14)",
    "passed_count": "達成條件(8項)",
}


class GoogleSheetsUploader:
    """Synchronizes screening dataframes to Google Sheets with format styling."""

    def __init__(
        self,
        service_account_file: Optional[str] = None,
        sheet_id: Optional[str] = None,
        sheet_title: Optional[str] = None,
    ):
        self.service_account_file = service_account_file or settings.SERVICE_ACCOUNT_FILE
        self.sheet_id = sheet_id or settings.GOOGLE_SHEET_ID
        self.sheet_title = sheet_title or settings.GOOGLE_SHEET_TITLE
        self._client: Optional[gspread.Client] = None

    def is_configured(self) -> bool:
        """檢查 Service Account 金鑰檔案是否存在。"""
        return Path(self.service_account_file).exists()

    def _get_client(self) -> Optional[gspread.Client]:
        """建立並快取 gspread 用戶端。"""
        if self._client:
            return self._client
        if not self.is_configured():
            logger.warning(
                "未偵測到 Google Service Account 金鑰檔 [%s]，將略過 Google Sheets 上傳。",
                self.service_account_file,
            )
            return None
        try:
            creds = Credentials.from_service_account_file(self.service_account_file, scopes=SCOPES)
            self._client = gspread.authorize(creds)
            return self._client
        except Exception as e:
            logger.error("建立 Google Sheets 用戶端授權失敗: %s", e)
            return None

    def upload_results(
        self,
        df: pd.DataFrame,
        as_of_date: Optional[str] = None,
        archive_date_tab: bool = True,
    ) -> Tuple[bool, str]:
        """將篩選結果寫入 Google Sheets。

        Args:
            df: 篩選結果 DataFrame
            as_of_date: 運算日期字串 (YYYY-MM-DD)
            archive_date_tab: 是否同步建立以日期命名之歷史分頁

        Returns:
            Tuple[bool, str]: (是否成功, 狀態訊息)
        """
        if df.empty:
            logger.info("無篩選資料可供上傳至 Google Sheets。")
            return False, "Data is empty"

        client = self._get_client()
        if not client:
            return False, "Google credentials not configured"

        date_str = as_of_date or datetime.now().strftime("%Y-%m-%d")

        try:
            # 1. 開啟試算表
            spreadsheet = self._open_spreadsheet(client)
            if not spreadsheet:
                return False, "Failed to open or create spreadsheet"

            # 2. 準備乾淨格式化資料
            display_df = self._prepare_display_df(df)
            header = list(display_df.columns)
            # 替換 NaN 為空字串
            values = display_df.fillna("").astype(str).values.tolist()
            rows_data = [header] + values

            # 3. 更新 "Latest" (最新即時) 工作表
            latest_ws = self._get_or_create_worksheet(spreadsheet, title="Latest")
            latest_ws.clear()
            latest_ws.update(rows_data, value_input_option="USER_ENTERED")
            self._style_worksheet(latest_ws, num_rows=len(rows_data), num_cols=len(header))
            logger.info("已成功同步最新選股清單至 Google Sheet 分頁 [Latest]")

            # 4. 歷史歸檔分頁 (e.g. "2026-09-06")
            if archive_date_tab:
                date_ws = self._get_or_create_worksheet(spreadsheet, title=date_str)
                date_ws.clear()
                date_ws.update(rows_data, value_input_option="USER_ENTERED")
                self._style_worksheet(date_ws, num_rows=len(rows_data), num_cols=len(header))
                logger.info("已成功歸檔選股清單至歷史分頁 [%s]", date_str)

            # 5. 清理新試算表預設產生的空白分頁 (工作表1 / Sheet1)，確保首頁即為 Latest
            try:
                for ws in spreadsheet.worksheets():
                    if ws.title in ["工作表1", "Sheet1"] and ws.row_count > 0:
                        vals = ws.get_all_values()
                        if not vals or len(vals) <= 1:
                            spreadsheet.del_worksheet(ws)
                            logger.info("已自動移除預設空白分頁 [%s]", ws.title)
            except Exception:
                pass

            return True, f"Successfully uploaded to sheet: {spreadsheet.title}"

        except Exception as e:
            logger.error("同步至 Google Sheets 時發生錯誤: %s", e)
            return False, str(e)

    def _open_spreadsheet(self, client: gspread.Client) -> Optional[gspread.Spreadsheet]:
        """依 ID 或名稱開啟試算表，若不存在則主動建立。"""
        if self.sheet_id:
            try:
                return client.open_by_key(self.sheet_id)
            except Exception as e:
                logger.warning("無法依 ID [%s] 開啟試算表，嘗試依名稱開啟: %s", self.sheet_id, e)

        try:
            return client.open(self.sheet_title)
        except gspread.SpreadsheetNotFound:
            logger.info("Google Sheets [%s] 不存在，自動建立新試算表...", self.sheet_title)
            new_sheet = client.create(self.sheet_title)
            return new_sheet

    def _get_or_create_worksheet(
        self, spreadsheet: gspread.Spreadsheet, title: str
    ) -> gspread.Worksheet:
        """取得特定分頁，若無則建立。"""
        try:
            return spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            return spreadsheet.add_worksheet(title=title, rows=100, cols=30)

    def _prepare_display_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """挑選最關鍵欄位並重命名為中文標題。"""
        cols = [col for col in COLUMN_MAPPING.keys() if col in df.columns]
        display_df = df[cols].copy()
        display_df.rename(columns=COLUMN_MAPPING, inplace=True)
        return display_df

    def _style_worksheet(self, worksheet: gspread.Worksheet, num_rows: int, num_cols: int) -> None:
        """設定標題列深色高質感樣式與凍結首列。"""
        try:
            # 凍結第一列
            worksheet.freeze(rows=1)
            # 設定標題列背景深藍灰色 (#1E293B) 與白字粗體
            worksheet.format(
                "A1:Z1",
                {
                    "backgroundColor": {"red": 0.12, "green": 0.16, "blue": 0.23},
                    "textFormat": {"bold": True, "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}},
                    "horizontalAlignment": "CENTER",
                },
            )
        except Exception as e:
            # 樣式設定非致命，僅記錄日誌
            logger.debug("Google Sheets 樣式格式化略過或不受支援: %s", e)


sheets_uploader = GoogleSheetsUploader()
