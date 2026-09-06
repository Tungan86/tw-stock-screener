"""AI Market Analyst Powered by Google Gemini.

Generates executive-level daily quantitative market reviews, capital flow interpretations,
and trader risk guidelines for Taiwan Stock Screener.
"""

import json
import logging
from typing import Any, Dict, List, Optional
import requests

from config.settings import settings

logger = logging.getLogger(__name__)


class GeminiMarketAnalyst:
    """Generates hedge-fund style market executive summaries using Google Gemini API."""

    CANDIDATE_MODELS = [
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash",
    ]

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL

    def generate_executive_briefing(self, insight_data: Dict[str, Any]) -> Dict[str, Any]:
        """產生每日盤後 AI 深度複盤與交易員行動綱領。

        Returns:
            Dict 包含:
                - status: 'success' 或 'fallback'
                - model_used: 使用的模型
                - market_sentiment: '攻勢多頭' / '輪動震盪' / '防守拉回'
                - sections:
                    - regime_and_flow: 市場多空位階與資金結構
                    - breakout_highlights: 帶量突破焦點與族群亮點
                    - risk_and_execution: 部位管理與風控行動綱領
                - raw_markdown: 完整 Markdown 報告
        """
        if not self.api_key:
            logger.warning("未偵測到 GEMINI_API_KEY，採用內建量化規則產出盤後速報")
            return self._generate_fallback_briefing(insight_data)

        # 整理要餵給 Gemini 的高密度結構化量化數據
        payload_summary = self._prepare_data_payload(insight_data)
        prompt = self._build_prompt(payload_summary)

        # 依序嘗試可用模型
        models_to_try = [self.model] + [m for m in self.CANDIDATE_MODELS if m != self.model]

        for target_model in models_to_try:
            try:
                logger.info("向 Gemini (%s) 請求每日量化複盤觀點...", target_model)
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent?key={self.api_key}"
                
                req_body = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.4,
                        "maxOutputTokens": 8192,
                    }
                }

                resp = requests.post(url, json=req_body, timeout=35)
                if resp.status_code == 200:
                    res_json = resp.json()
                    candidates = res_json.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        raw_text = candidates[0]["content"]["parts"][0]["text"].strip()
                        parsed = self._parse_ai_response(raw_text, insight_data)
                        parsed["model_used"] = target_model
                        parsed["status"] = "success"
                        logger.info("Gemini 盤後觀點產出成功！使用模型: %s", target_model)
                        return parsed
                else:
                    logger.warning("Gemini 模型 %s 回應失敗 (狀態碼 %d): %s", target_model, resp.status_code, resp.text[:150])
            except Exception as e:
                logger.warning("連線 Gemini (%s) 異常: %s", target_model, e)

        logger.warning("所有 Gemini 請求均未成功，降級至規則引擎產出速報")
        return self._generate_fallback_briefing(insight_data)

    def _prepare_data_payload(self, insight_data: Dict[str, Any]) -> Dict[str, Any]:
        """將龐大的數據壓縮為關鍵量化指標。"""
        summary = insight_data.get("summary", {})
        capital_flow = insight_data.get("capital_flow", [])[:5]  # Top 5 產業
        breakouts = insight_data.get("breakout_momentum", [])[:6]  # Top 6 突破股
        trend_core = insight_data.get("trend_core", [])[:6]  # Top 6 趨勢股

        return {
            "market_date": summary.get("trade_date", "今日"),
            "total_screened_stocks": summary.get("total_screened", 0),
            "perfect_score_count": summary.get("perfect_count", 0),
            "top_industries": [
                {
                    "industry": row.get("industry"),
                    "est_amount_billion": round(row.get("est_amount_billion", 0), 1),
                    "amount_share_pct": round(row.get("amount_share_pct", 0), 1),
                    "stock_count": row.get("stock_count", 0),
                    "avg_change_pct": round(row.get("avg_change_pct", 0), 2),
                }
                for row in capital_flow
            ],
            "breakout_stocks": [
                {
                    "code": row.get("code"),
                    "name": row.get("name"),
                    "industry": row.get("industry"),
                    "close": row.get("close"),
                    "change_pct": round(row.get("change_pct", 0), 2),
                    "vol_ratio": round(row.get("vol_ratio", 0), 2),
                    "rsi": round(row.get("rsi", 0), 1),
                    "dist_52w_high_pct": round(row.get("dist_52w_high_pct", 0) * 100, 1),
                }
                for row in breakouts
            ],
            "trend_core_sample": [
                f"{row.get('code')} {row.get('name')} ({row.get('industry')})"
                for row in trend_core
            ],
        }

    def _build_prompt(self, payload: Dict[str, Any]) -> str:
        return f"""# Role & Task
你是一名頂尖量化避險基金投資總監 (Chief Investment Officer, CIO) 與資深台股操盤手。
請依據今日「大師多頭策略 (Minervini Trend Template & Stage 2)」的盤後量化數據，撰寫一份精準、專業、言之有物的每日盤後量化深度複盤與交易員行動綱領。

## 今日量化結構數據 (JSON)
```json
{json.dumps(payload, ensure_ascii=False, indent=2)}
```

## 撰寫規範
1. 嚴禁廢話與客套，以機構法人晨會操盤手觀點出發，語氣冷靜、客觀、具備高勝率交易執行力。
2. 輸出結構必須嚴格劃分為以下 3 個主題區塊（請精確包含標題字眼）：

### 1. 資金結構與多空溫度計
- 評估今日台股多頭健康度與廣度（達標家數與資金聚焦程度）。
- 解析資金主要流向的 Top 板塊特徵與強弱背離。

### 2. 帶量突破亮點與族群焦點
- 針對今日出現「量能激增 (Volume Expansion) + 逼近 52 週新高」的突破個股進行結構性點評。
- 指出具備最強相對強度 (RS) 的核心族群。

### 3. 風控方針與部位管理行動綱領
- 根據當前盤勢給出建議的多頭部位暴露比例 (Exposure: 如積極 80~100%、中性 50~70%、防守 30% 以下)。
- 強調 1% 資本風險敞口與 2x ATR 動態停損的防守執行心法。

請直接輸出繁體中文 Markdown 報告。"""

    def _parse_ai_response(self, raw_text: str, insight_data: Dict[str, Any]) -> Dict[str, Any]:
        """解析 AI 回傳的 Markdown 結構，嚴格以 ## 或 ### 標題切割。"""
        import re

        sections = {
            "regime_and_flow": "",
            "breakout_highlights": "",
            "risk_and_execution": "",
        }

        # 匹配獨立行 Markdown 標題: ## 或 ###
        pattern = re.compile(r"(?:^|\n)#{2,3}\s*([^\n]+)\n")
        matches = list(pattern.finditer(raw_text))

        if matches:
            for i, match in enumerate(matches):
                title = match.group(1).strip()
                start_idx = match.end()
                end_idx = matches[i + 1].start() if i + 1 < len(matches) else len(raw_text)
                content = raw_text[start_idx:end_idx].strip()
                # 移除結尾的 --- 分隔線
                content = re.sub(r"\n\s*---\s*$", "", content).strip()

                if "資金結構" in title or "多空溫度" in title:
                    sections["regime_and_flow"] = content
                elif "帶量突破" in title or "族群焦點" in title or "突破亮點" in title:
                    sections["breakout_highlights"] = content
                elif "風控" in title or "部位管理" in title or "行動綱領" in title:
                    sections["risk_and_execution"] = content

        # 若未完整切出，直接以 raw_text 填補第一段
        if not sections["regime_and_flow"] and not sections["breakout_highlights"]:
            sections["regime_and_flow"] = raw_text

        # 判定市場溫度
        perfect_count = insight_data.get("summary", {}).get("perfect_count", 0)
        if perfect_count >= 100:
            sentiment = "強攻多頭・主動進攻"
        elif perfect_count >= 30:
            sentiment = "族群輪動・去弱留強"
        else:
            sentiment = "分歧防守・嚴控部位"

        return {
            "market_sentiment": sentiment,
            "sections": sections,
            "raw_markdown": raw_text,
        }

    def _generate_fallback_briefing(self, insight_data: Dict[str, Any]) -> Dict[str, Any]:
        """規則引擎備援盤後速報（無 API 金鑰或網路中斷時保證網頁不空白）。"""
        summary = insight_data.get("summary", {})
        capital_flow = insight_data.get("capital_flow", [])
        breakouts = insight_data.get("breakout_momentum", [])
        perfect_count = summary.get("perfect_count", 0)

        top_ind = capital_flow[0]["industry"] if capital_flow else "電子科技"
        top_share = capital_flow[0]["amount_share_pct"] if capital_flow else 0.0

        if perfect_count >= 100:
            sentiment = "強攻多頭・主動進攻"
            regime = f"全市場共有 {perfect_count} 檔標的符合大師多頭 8 項指標，多頭趨勢結構紮實。主流資金高度聚焦於「{top_ind}」，佔今日總成交金額約 {top_share:.1f}%，盤面具備良好續航力。"
            risk = "建議總倉位維持積極水位 (70% ~ 90%)。每筆新進場標的嚴格落實 1% 資本損失上限，隨行情推升將停損點移動至進場成本或 20MA。"
        elif perfect_count >= 30:
            sentiment = "族群輪動・去弱留強"
            regime = f"市場處於健康階梯式輪動，達標 8 項多頭標的共 {perfect_count} 檔。資金由「{top_ind}」板塊引領，族群間分化明顯，切忌追高破線轉弱股。"
            risk = "建議維持中性偏多倉位 (50% ~ 70%)。嚴格遵守 2x ATR 動態停損，回調至重要均線有支撐時再行介入。"
        else:
            sentiment = "分歧防守・嚴控部位"
            regime = f"大盤多頭廣度收斂，達標 8 項個股僅 {perfect_count} 檔，多數個股陷入均線糾結或修正。資金防守意識濃厚，需警惕流動性不足與量價背離風險。"
            risk = "建議降低多頭總曝險至防守水位 (30% 以下)。保留充裕現金儲備，靜待市場重現量能突破訊號。"

        breakout_text = f"今日帶量突破攻擊組共篩出 {len(breakouts)} 檔標的。"
        if breakouts:
            sample_names = ", ".join([f"{s['code']} {s['name']}" for s in breakouts[:3]])
            breakout_text += f" 重點關注具備量能倍數放大且逼近 52 週新高之領先股：{sample_names}。"

        return {
            "status": "fallback",
            "model_used": "Rule-Based Engine",
            "market_sentiment": sentiment,
            "sections": {
                "regime_and_flow": regime,
                "breakout_highlights": breakout_text,
                "risk_and_execution": risk,
            },
            "raw_markdown": f"### 1. 資金結構與多空溫度計\n{regime}\n\n### 2. 帶量突破亮點與族群焦點\n{breakout_text}\n\n### 3. 風控方針與部位管理行動綱領\n{risk}",
        }


market_analyst = GeminiMarketAnalyst()
