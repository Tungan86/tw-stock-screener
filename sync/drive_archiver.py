"""Google Drive & Local Parquet Historical Archiving Module.

Saves daily screening results into compressed Parquet files locally and uploads to
Google Drive storage folder via Google Drive API v3.
"""

from datetime import datetime
import logging
from pathlib import Path
from typing import Optional, Tuple
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import pandas as pd

from config.settings import settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
]


class DriveArchiver:
    """Manages local Parquet preservation and Google Drive file uploads."""

    def __init__(
        self,
        service_account_file: Optional[str] = None,
        drive_folder_id: Optional[str] = None,
        archive_dir: Optional[Path] = None,
    ):
        self.service_account_file = service_account_file or settings.SERVICE_ACCOUNT_FILE
        self.drive_folder_id = drive_folder_id or settings.GOOGLE_DRIVE_FOLDER_ID
        self.archive_dir = archive_dir or settings.ARCHIVE_DIR
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._drive_service = None

    def archive_results(
        self,
        df: pd.DataFrame,
        as_of_date: Optional[str] = None,
        upload_to_drive: bool = True,
    ) -> Tuple[Path, Optional[str]]:
        """歸檔篩選結果至本地 Parquet 與 Google Drive。

        Args:
            df: 篩選結果 DataFrame
            as_of_date: 歸檔基準日 (YYYY-MM-DD)
            upload_to_drive: 是否上傳至 Google Drive

        Returns:
            Tuple[Path, Optional[str]]: (本地 Parquet 檔案路徑, Google Drive File ID 或 None)
        """
        date_str = as_of_date or datetime.now().strftime("%Y-%m-%d")
        file_basename = f"screener_master_bull_{date_str}"
        parquet_path = self.archive_dir / f"{file_basename}.parquet"

        # 1. 儲存本地 Parquet
        try:
            # 確保欄位皆可順利序列化
            save_df = df.copy()
            if "criteria_details" in save_df.columns:
                save_df["criteria_details"] = save_df["criteria_details"].astype(str)

            save_df.to_parquet(parquet_path, engine="pyarrow", compression="snappy")
            logger.info("已完成本地 Parquet 封存: %s", parquet_path)
        except Exception as e:
            logger.error("寫入本地 Parquet 失敗: %s", e)

        # 2. 上傳至 Google Drive (若配置有金鑰且指定了目標資料夾)
        drive_file_id = None
        if upload_to_drive and self.is_configured():
            if not self.drive_folder_id:
                logger.info("未指定 GOOGLE_DRIVE_FOLDER_ID，已略過 Drive 雲端備份，歷史數據已妥善封存於本機 Parquet。")
                return parquet_path, None
            try:
                drive_file_id = self._upload_file(parquet_path, mime_type="application/octet-stream")
                if drive_file_id:
                    logger.info("已上傳歸檔至 Google Drive (ID: %s)", drive_file_id)
            except Exception as e:
                logger.warning("上傳檔案至 Google Drive 失敗: %s", e)
        else:
            if upload_to_drive:
                logger.debug("未配置 Google 金鑰，略過雲端硬碟備份。")

        return parquet_path, drive_file_id

    def is_configured(self) -> bool:
        """檢查是否具備 Google Drive 憑證。"""
        return Path(self.service_account_file).exists()

    def _get_service(self):
        """取得授權之 Google Drive v3 Client。"""
        if self._drive_service:
            return self._drive_service
        if not self.is_configured():
            return None
        try:
            creds = Credentials.from_service_account_file(self.service_account_file, scopes=SCOPES)
            self._drive_service = build("drive", "v3", credentials=creds)
            return self._drive_service
        except Exception as e:
            logger.error("建立 Google Drive 服務連線失敗: %s", e)
            return None

    def _upload_file(self, file_path: Path, mime_type: str = "application/octet-stream") -> Optional[str]:
        """上傳檔案至指定 Google Drive 資料夾。"""
        service = self._get_service()
        if not service:
            return None

        file_metadata = {"name": file_path.name}
        if self.drive_folder_id:
            file_metadata["parents"] = [self.drive_folder_id]

        media = MediaFileUpload(str(file_path), mimetype=mime_type, resumable=True)
        file = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id")
            .execute()
        )
        return file.get("id")


drive_archiver = DriveArchiver()
