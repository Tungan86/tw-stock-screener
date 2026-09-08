"""Taiwan Stock Quantitative Screener - Main Execution Pipeline.

Executes the Master Bull Strategy (TradingView Minervini Trend Template replica)
for Taiwan equities, syncs outputs to Google Sheets, and archives Parquet data.
"""

import argparse
from datetime import datetime
import logging
import sys
from pathlib import Path
import pandas as pd
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from config.settings import settings
from data.fetcher import data_fetcher
from data.tw_market import market_registry
from strategy.master_bull import master_bull_strategy
from sync.drive_archiver import drive_archiver
from sync.html_generator import html_generator
from sync.sheets_uploader import sheets_uploader

console = Console()


def setup_logging(debug: bool = False) -> None:
    """設定豐富色彩與詳細度的日誌紀錄器。"""
    log_level = logging.DEBUG if debug else getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )


def print_banner() -> None:
    """印出終端機啟動橫幅。"""
    console.print(
        "\n[bold cyan]================================================================[/bold cyan]"
    )
    console.print(
        "[bold green]   📈 台股量化選股監控系統 - 大師多頭策略 (Master Bull) 自動化平台[/bold green]"
    )
    console.print(
        "[dim]   Trend Template (Minervini) | Stage 2 Momentum | Google Sheets Sync[/dim]"
    )
    console.print(
        "[bold cyan]================================================================[/bold cyan]\n"
    )


def display_results_table(df: pd.DataFrame) -> None:
    """在終端機中以 Rich Table 精美展示篩選結果。"""
    if df.empty:
        console.print("[bold yellow]⚠️  本日篩選未發現完全符合「大師多頭策略」之標的。[/bold yellow]\n")
        return

    table = Table(
        title="🏆 台股大師多頭策略精選清單 (Master Bull Candidates)",
        header_style="bold magenta",
        show_lines=True,
    )
    table.add_column("代碼", justify="center", style="bold cyan")
    table.add_column("名稱", justify="center", style="bold white")
    table.add_column("市場", justify="center")
    table.add_column("產業", justify="left")
    table.add_column("收盤價", justify="right", style="bold yellow")
    table.add_column("漲跌幅(%)", justify="right")
    table.add_column("量能(張)", justify="right")
    table.add_column("20MA均量", justify="right")
    table.add_column("距52W高點", justify="right")
    table.add_column("RSI(14)", justify="right")
    table.add_column("全過", justify="center")

    for _, row in df.iterrows():
        pct_chg = row["pct_change"]
        chg_style = "bold red" if pct_chg > 0 else ("bold green" if pct_chg < 0 else "white")
        chg_str = f"[{chg_style}]{pct_chg:+.2f}%[/{chg_style}]"

        passed_all_str = "✅ 是" if row["passed_all"] else f"🟡 {row['passed_count']}/8"

        table.add_row(
            str(row["code"]),
            str(row["name"]),
            str(row["market"]),
            str(row["industry"]),
            f"{row['close']:.2f}",
            chg_str,
            f"{int(row['volume_lots']):,}",
            f"{int(row['vol_ma20_lots']):,}",
            f"{row['pct_below_52w_high']:.1f}%",
            f"{row['rsi_14']:.1f}",
            passed_all_str,
        )

    console.print(table)
    console.print(f"[dim]共篩選出 {len(df)} 檔多頭強勢股[/dim]\n")


def parse_args() -> argparse.Namespace:
    """解析命令列參數。"""
    parser = argparse.ArgumentParser(description="台股大師多頭量化選股與同步系統")
    parser.add_argument(
        "--date",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="計算基準日期 (YYYY-MM-DD，預設為今日)",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="指定掃描個股代號，以逗號分隔 (例: 2330,2454,2317,6488)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="限制掃描股票數量 (除錯與快速測試用)",
    )
    parser.add_argument(
        "--market",
        choices=["ALL", "TWSE", "TPEx"],
        default="ALL",
        help="篩選市場 (ALL: 上市櫃全部, TWSE: 僅上市, TPEx: 僅上櫃)",
    )
    parser.add_argument(
        "--all-candidates",
        action="store_true",
        help="納入接近多頭標準之候選名單 (滿足 7/8 條件者)",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="不執行 Google Sheets 上傳 (乾跑模式)",
    )
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="不執行 Google Drive / Parquet 歷史封存",
    )
    parser.add_argument(
        "--export-csv",
        action="store_true",
        default=True,
        help="同時匯出本地 CSV 報表至 output/ 目錄 (預設啟用)",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="強制重新抓取清單與行情數據，忽略快取",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="啟用 DEBUG 詳細除錯日誌",
    )
    return parser.parse_args()


def run_pipeline(args: argparse.Namespace) -> int:
    """執行完整選股與資料同步管線。"""
    setup_logging(args.debug)
    print_banner()

    target_date = args.date
    console.print(f"[bold blue]📅 執行基準日期:[/bold blue] {target_date}")

    # 1. 取得股票代碼清單
    console.print("\n[bold]1. 獲取台股上市/上櫃代碼清單...[/bold]")
    stock_df = market_registry.get_stock_list(force_refresh=args.force_refresh)

    if args.market != "ALL":
        stock_df = stock_df[stock_df["market"] == args.market].copy()

    # 處理指定標的
    stock_df["code"] = stock_df["code"].astype(str)
    if args.tickers:
        specified = [c.strip() for c in args.tickers.split(",")]
        # 支援純代碼 (2330) 或 yfinance 標記 (2330.TW)
        matched = stock_df[
            stock_df["code"].isin(specified) | stock_df["yf_symbol"].isin(specified)
        ].copy()

        if not matched.empty:
            stock_df = matched
        else:
            # 若手動輸入不在現有清單中，動態建立 DataFrame
            custom_rows = []
            for code in specified:
                clean_code = code.replace(".TW", "").replace(".TWO", "")
                suffix = ".TWO" if len(clean_code) == 4 and clean_code.startswith(("5", "6", "8")) else ".TW"
                custom_rows.append({
                    "code": clean_code,
                    "name": clean_code,
                    "yf_symbol": f"{clean_code}{suffix}" if not ("." in code) else code,
                    "market": "TPEx" if suffix == ".TWO" else "TWSE",
                    "industry": "指定標的",
                })
            stock_df = pd.DataFrame(custom_rows)

    if args.limit and args.limit > 0:
        stock_df = stock_df.head(args.limit)

    console.print(f"✅ 目標掃描標的數: [bold green]{len(stock_df)}[/bold green] 檔")

    # 2. 批量下載歷史 K 線
    console.print("\n[bold]2. 下載與同步歷史日 K 線行情 (OHLCV)...[/bold]")
    symbols = stock_df["yf_symbol"].tolist()
    market_data = data_fetcher.fetch_historical_data(
        symbols=symbols,
        force_refresh=args.force_refresh,
        as_of_date=target_date,
    )
    console.print(f"✅ 成功載入歷史行情: [bold green]{len(market_data)}[/bold green] 檔")

    # 3. 執行大師多頭策略評估
    console.print("\n[bold]3. 運算大師多頭策略 (Trend Template & Stage 2)...[/bold]")
    only_perfect = not args.all_candidates
    results_df = master_bull_strategy.run_screening(
        market_data=market_data,
        stock_meta=stock_df,
        only_perfect=only_perfect,
    )

    # 4. 終端機展示結果
    console.print("\n[bold]4. 篩選結果總覽:[/bold]")
    display_results_table(results_df)

    # 5. 本地 CSV 匯出
    if args.export_csv and not results_df.empty:
        csv_filename = settings.OUTPUT_DIR / f"master_bull_{target_date}.csv"
        results_df.to_csv(csv_filename, index=False, encoding="utf-8-sig")
        console.print(f"📁 已匯出本地 CSV 報表: [cyan]{csv_filename}[/cyan]")

    # 6. Google Sheets 同步
    if not args.no_upload:
        console.print("\n[bold]5. 同步至 Google Sheets...[/bold]")
        if sheets_uploader.is_configured():
            success, msg = sheets_uploader.upload_results(results_df, as_of_date=target_date)
            if success:
                console.print(f"✅ [bold green]Google Sheets 同步成功:[/bold green] {msg}")
            else:
                console.print(f"⚠️ [bold yellow]Google Sheets 同步略過或失敗:[/bold yellow] {msg}")
                if os.environ.get("GITHUB_ACTIONS"):
                    print(f"::warning title=Google Sheets Sync Incomplete::{msg}")
        else:
            console.print(
                "[dim]💡 提示: 未配置 service_account.json，已略過 Google Sheets 上傳。"
                "欲啟用雲端同步請參考 README.md 配置服務帳號金鑰。[/dim]"
            )
            if os.environ.get("GITHUB_ACTIONS"):
                print("::warning title=Google Sheets Not Configured::GitHub Secrets 未配置 GCP_SERVICE_ACCOUNT_JSON，已略過 Google Sheets 同步。")

    # 7. 本地 Parquet 與 Google Drive 封存
    if not args.no_archive and not results_df.empty:
        console.print("\n[bold]6. 執行歷史數據歸檔 (Parquet / Drive)...[/bold]")
        parquet_file, drive_id = drive_archiver.archive_results(
            results_df,
            as_of_date=target_date,
            upload_to_drive=not args.no_upload,
        )
        console.print(f"💾 本地 Parquet 封存完成: [cyan]{parquet_file}[/cyan]")
        if drive_id:
            console.print(f"☁️ Google Drive 歸檔完成，檔案 ID: [green]{drive_id}[/green]")

    # 8. 交易員決策分析與 HTML 戰情看板產出
    if not results_df.empty:
        console.print("\n[bold]7. 運算交易員決策分析並產出視覺化戰情看板...[/bold]")
        html_file = html_generator.generate(results_df, as_of_date=target_date)
        console.print(f"📊 已生成交易員視覺化戰情看板: [cyan]{html_file}[/cyan]")
        console.print(f"🌐 GitHub Pages 部署檔就緒: [cyan]{settings.PROJECT_DIR / 'docs' / 'index.html'}[/cyan]")

    console.print("\n[bold green]🎉 全流程執行完畢！[/bold green]\n")
    return 0


def main() -> None:
    """主程式進入點。"""
    args = parse_args()
    sys.exit(run_pipeline(args))


if __name__ == "__main__":
    main()
