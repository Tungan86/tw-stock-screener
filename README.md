# 📈 台股量化選股監控系統 (Taiwan Stock Master Bull Screener)

本專案是一個模組化、自動化的台股量化選股與資料同步系統，完整重現 TradingView 經典之「台股_大師多頭策略」（Minervini Trend Template 趨勢範本 + Stan Weinstein 第二階段突破動能）。

系統支援每日盤後自動抓取台股上市/上櫃（TWSE / TPEx）全市場行情、精準計算技術指標與趨勢濾網、將篩選出的多頭強勢股寫入 **Google Sheets**，並將歷史數據歸檔至 **Google Drive** 與本地 **Parquet** 壓縮檔案。

---

## 目錄結構

```text
tw_stock_screener/
├── config/
│   ├── __init__.py
│   └── settings.py          # 策略參數、API Token、路徑設定 (Pydantic Settings)
├── data/
│   ├── __init__.py
│   ├── fetcher.py           # 歷史 K 線與量能獲取 (yfinance 批次 + Parquet 快取)
│   └── tw_market.py         # 台股上市/上櫃代碼清單維護與 ISIN 爬蟲
├── indicators/
│   ├── __init__.py
│   └── technical.py         # 向量化指標計算 (均線、動量 RSI、MACD、52W 高低點)
├── strategy/
│   ├── __init__.py
│   └── master_bull.py       # 大師多頭策略核心篩選器 (8 大準則)
├── sync/
│   ├── __init__.py
│   ├── sheets_uploader.py   # Google Sheets 自動寫入 (gspread + 樣式格式化)
│   └── drive_archiver.py    # Google Drive 與本地 Parquet 歷史封存
├── tests/
│   ├── __init__.py
│   └── test_strategy.py     # 單元測試 (指標與策略邏輯)
├── main.py                  # CLI 主程式進入點 (支援排程呼叫)
├── requirements.txt         # 依賴套件清單
├── service_account.json     # Google Cloud 憑證 (由 .gitignore 排除)
├── service_account.json.example # 憑證格式範本
├── .env                     # 環境變數
├── .env.example             # 環境變數設定範本
└── .gitignore               # Git 忽略清單
```

---

## 策略核心邏輯：大師多頭策略 (Master Bull Strategy)

本策略融合超級績效大師 **Mark Minervini** 的「趨勢範本 (Trend Template)」與 **Stan Weinstein** 的「第二階段上升趨勢 (Stage 2 Breakout)」：

1. **股價高於長天期均線**：$Price > SMA_{150}$ 且 $Price > SMA_{200}$
2. **長天期均線多頭排列**：$SMA_{150} > SMA_{200}$
3. **200日均線上揚**：$SMA_{200}$ 當前值大於 20 個交易日前的值 (斜率為正)
4. **中短期均線多頭確認**：$SMA_{50} > SMA_{150}$ 且 $SMA_{50} > SMA_{200}$
5. **現價突破短期均線**：$Price > SMA_{50}$
6. **擺脫底部走勢**：$Price \ge 1.25 \times 52W\_Low$ (自 52 週低點反彈至少 25%)
7. **接近歷史/週期高點**：$Price \ge 0.75 \times 52W\_High$ (距離 52 週高點在 25% 範圍內)
8. **流動性與動能濾網**：
   - 20 日均量 $\ge 500$ 張 (500,000 股)，排除殭屍流動性
   - 最低股價 $\ge 10$ 元，排除水餃股
   - $RSI(14) \ge 50$，動能處於多頭強勢區

---

## 快速開始

### 1. 安裝環境與依賴

```bash
# 建立 Python 虛擬環境
python3 -m venv .venv
source .venv/bin/activate

# 安裝依賴
.venv/bin/pip install -r requirements.txt
```

### 2. 環境變數設定

複製 `.env.example` 為 `.env`：

```bash
cp .env.example .env
```

可在 `.env` 中修改策略參數（例如均量門檻、RSI 限制、Google Sheet ID 等）。

---

## Google Cloud (Sheets & Drive) 設定指南

如需啟用 Google Sheets 與 Google Drive 自動同步，請依以下步驟操作：

1. 前往 [Google Cloud Console](https://console.cloud.google.com/)。
2. 建立新專案，並進入「API 與服務」>「程式庫」，啟用以下兩個 API：
   - **Google Sheets API**
   - **Google Drive API**
3. 進入「憑證 (Credentials)」，建立 **服務帳號 (Service Account)**。
4. 點選該服務帳號，進入「金鑰 (Keys)」頁籤，新增金鑰並選擇 **JSON** 格式下載。
5. 將下載的 JSON 檔案重新命名為 `service_account.json`，放置於專案根目錄（`.gitignore` 已自動保護此檔案）。
6. 開啟您的 Google Sheet 試算表（或 Google Drive 資料夾），點擊右上角 **共用 (Share)**，將服務帳號中的 `client_email`（如 `xxx@your-project.iam.gserviceaccount.com`）加入共用並設為 **編輯者**。
7. 在 `.env` 中設定 `GOOGLE_SHEET_ID`（即試算表網址中 `/d/` 與 `/edit` 之間的那串英數字）。

> 💡 **無憑證降級機制**：若尚未設定 `service_account.json`，系統將自動跳過雲端上傳，直接將結果匯出為本地 CSV 與 Parquet，不中斷選股運算。

---

## 常用指令範例

### 1. 快速測試特定個股 (例如台積電、聯發科、鴻海、環球晶)
```bash
.venv/bin/python main.py --tickers 2330,2454,2317,6488
```

### 2. 快速除錯模式 (僅掃描前 30 檔股票)
```bash
.venv/bin/python main.py --limit 30
```

### 3. 掃描全市場並同步至 Google Sheets
```bash
.venv/bin/python main.py
```

### 4. 僅掃描上市股票且納入 7/8 符合之潛在觀察名單
```bash
.venv/bin/python main.py --market TWSE --all-candidates
```

### 5. 乾跑模式 (不寫入 Google Sheets / Drive)
```bash
.venv/bin/python main.py --no-upload --no-archive
```

### 6. 強制清除快取並重新抓取最新數據
```bash
.venv/bin/python main.py --force-refresh
```

### 7. 執行單元測試
```bash
.venv/bin/pytest tests/ -v
```

---

## 定時自動化排程 (每日盤後 15:30 執行)

### 使用 Linux / macOS Crontab
編輯排程表：
```bash
crontab -e
```
新增如下排程（週一至週五下午 15:30 執行）：
```cron
30 15 * * 1-5 cd /Users/tongan/股市監控平台 && .venv/bin/python main.py >> logs/cron.log 2>&1
```

### 使用 GitHub Actions 雲端自動排程
本專案已包含 `.github/workflows/daily_screener.yml`，每個交易日（週一至週五）15:30 自動於 GitHub 雲端執行選股並同步。

如需讓 GitHub Actions 具備同步 Google Sheets 與 Gemini AI 功能，請至 GitHub 儲存庫設定：
1. 前往 GitHub 倉庫頁面 -> **Settings** -> **Secrets and variables** -> **Actions**
2. 點擊 **New repository secret**，新增以下 Secrets：
   - `GCP_SERVICE_ACCOUNT_JSON`：將本地 `service_account.json` 的全部文字內容完整複製貼入。
   - `GOOGLE_SHEET_ID`：Google 試算表 ID（例如 `1uiH3EGecCFxbbZeDa1PCpfg3SUL6POTT0b-rMoQsOWg`）。
   - `GEMINI_API_KEY`：Google Gemini API 金鑰。
3. 設定完成後，GitHub Actions 每日定時執行即可自動同步至 Google Sheets 與 GitHub Pages 戰情看板。

