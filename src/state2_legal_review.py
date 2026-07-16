"""
Qiaoxi Contract-Analyzer · State 2 乔曦法律初审

强制触发本地法规 RAG，输出 jo_legal_review.json
审查时必须代入客户画像（立场、风险偏好、底线约束），从客户利益角度分析每一条款。
"""
import json
import logging
from openai import OpenAI
from typing import Optional
from src.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, LLM_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

# 立场翻译表
POSITION_LABELS = {
    "buyer_strong": "买方，谈判强势，有多个替代标的",
    "buyer_weak": "买方，谈判弱势，标的稀缺或急需",
    "equal": "双方均势",
    "seller": "卖方/转让方",
    "cooperator": "合作方/共建方",
}


class QiaoxiLegalReviewer:
    """
    乔曦法律初审引擎

    State 2: 接收 clause_tree + RAG检索结果 + 客户画像
    从客户立场出发逐条审查，标注"对客户有利/不利/中性"。
    """

    def __init__(self):
        self.llm_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    def _build_client_context(self, profile: dict) -> str:
        """把 client_profile 转成自然语言上下文"""
        if not profile:
            return "（未提供客户画像，无法确定立场）"

        sl = profile.get("strategic_layer", {})
        tl = profile.get("tactical_layer", {})
        bi = profile.get("basic_info", {})

        parts = []
        # 1. 立场——最核心
        pos = tl.get("position", "")
        pos_label = POSITION_LABELS.get(pos, pos)
        parts.append(f"【客户立场】{pos_label}")

        # 2. 核心焦虑
        anxiety = sl.get("anxiety_focus", "")
        anxiety_map = {
            "authenticity": "标的真实性存疑——特别关注对手资质、资产权属、证照真实性",
            "funds": "资金安全——特别关注付款后无法确权、资金监管缺失、退出路径不清晰",
            "tax": "税务合规风险——特别关注历史欠税、税负承担、税务保证条款",
            "control": "交割后失控——特别关注公章/证照/U盾/法人代表的交割安排",
            "exit": "退出路径不清晰——特别关注合同终止条件、违约责任上限、回购/退出机制",
            "compliance": "对方合规/资质存疑——特别关注尽调权、资料真实性保证、资质许可条款",
        }
        parts.append(f"【核心焦虑】{anxiety_map.get(anxiety, anxiety)}")

        # 3. 风险偏好
        risk = tl.get("risk_appetite", "moderate")
        risk_map = {
            "conservative": "保守——宁愿不赚也不能亏，倾向否决含任何显著风险的条款",
            "moderate": "适中——接受可控风险换取合理回报",
            "aggressive": "激进——高回报优先，愿承担显著风险",
        }
        parts.append(f"【风险偏好】{risk_map.get(risk, risk)}")

        # 4. 最大容忍损失
        loss_pct = tl.get("max_loss_pct", 0.15)
        parts.append(f"【最大可接受损失】不超过净资产的 {loss_pct*100:.0f}%")

        # 5. BATNA
        batna = tl.get("batna_strength", "weak")
        batna_map = {
            "strong": "有明确的替代方案，不怕谈崩",
            "weak": "有但不理想，需要尽力促成但保留底线",
            "none": "没有替代方案，但绝不接受毁灭性条款",
        }
        parts.append(f"【替代方案(BATNA)】{batna_map.get(batna, batna)}")

        # 6. 绝对底线
        hard_lines = tl.get("hard_lines", [])
        if hard_lines:
            hl_map = {
                "no_prepayment_without_guarantee": "禁止先付款后确权",
                "fiscal_control_untransferable": "财税控制权不可转让",
                "no_unilateral_nuke": "不接受单方核弹级违约责任",
            }
            hl_text = [hl_map.get(h, h) for h in hard_lines]
            parts.append(f"【绝对不可退让的底线】{'; '.join(hl_text)}")

        # 7. 可妥协维度
        compromise = tl.get("compromise_dims", [])
        if compromise:
            c_map = {"price": "价格/对价", "schedule": "付款节奏", "governance": "治理结构", "scope": "交易范围"}
            parts.append(f"【可妥协维度】{'; '.join(c_map.get(c, c) for c in compromise)}")

        return "\n".join(parts)

    def _build_system_prompt(self, client_context: str, rag_context: str) -> str:
        return f"""你是乔曦（Qiaoxi），霖信莯咨询公司的法务助理。
身份档案：女，26岁，中国政法大学硕士，通过司法考试，执业方向商事争议解决。
输出模态：锋锐模态——结构化、结论先行、标注依据、量化风险。

【最核心原则——客户立场】
你必须代入以下客户画像，所有条款分析必须从客户角度出发：
{client_context}

对于每一条款，你必须首先判断：这个条款对客户是有利、不利、还是中性？
- 如果客户是买方/收购方，卖方/转让方提出的单方面保护条款 → "对客户不利"
- 如果客户是卖方/转让方，收购方提出的过分要求 → "对客户不利"
- 凡是与客户底线冲突的条款 → 直接标为高风险

【硬性约束】
1. 禁止引用已废止法律
2. 所有法条必须来自 RAG 检索结果，不能自行编造
3. 若本地库未命中相关法条，标注"【法规待核】"
4. 禁止对商业模式合理性做主观判断（留给私董会）
5. 仅做法律标定，不输出商业判断
6. 法条引用格式强制：《法规名称》第X条第X款（生效状态：现行有效/已废止/待核）

【RAG 检索结果】
{rag_context}

【风险等级定义】
- high: 涉嫌违法、触碰客户绝对底线、或可能造成不可逆的法律后果
- medium: 对客户不利但可通过谈判修改，或存在法律瑕疵
- low: 轻微的措辞问题或对客户影响不大
"""

    def review(self, clause_tree: dict, profile: dict, rag_results: Optional[list[dict]] = None) -> dict:
        """
        执行法律初审，代入客户画像

        Args:
            clause_tree: State 1 输出的条款树（脱敏后）
            profile: client_profile（含用户立场、偏好、底线）
            rag_results: ChromaDB RAG 检索结果

        Returns:
            jo_legal_review.json 结构
        """
        # 客户画像上下文
        client_context = self._build_client_context(profile)

        # RAG 上下文
        if rag_results:
            rag_items = []
            for i, r in enumerate(rag_results[:3]):
                rag_items.append(
                    f"【法规{i+1}】{r.get('law_name', '未知')} "
                    f"第{r.get('article', '?')}条（生效状态：{r.get('status', '现行有效')}）\n"
                    f"内容：{r.get('content', '')[:500]}"
                )
            rag_context = "\n\n".join(rag_items)
        else:
            rag_context = "⚠️ RAG 检索未返回结果。以下分析将基于法律常识进行，无法条引用的项目标注【法规待核】。"
            logger.warning("RAG 未提供检索结果")

        clauses_json = json.dumps(clause_tree.get("clauses", [])[:30], ensure_ascii=False)

        user_prompt = f"""请审查以下合同条款，从客户立场出发逐条分析。

【客户画像】
{client_context}

【条款清单】
{clauses_json}

【输出格式（严格 JSON）】
{{
  "client_position_summary": "≤100字：基于客户立场，概述本次审查的角度和关注重点",
  "contract_meta": {{ "title": "string", "type": "string", "value_cny": 0 }},
  "clauses_analyzed": {clause_tree.get("total_clauses", 0)},
  "risks": [
    {{
      "clause_id": "CLS-XXXX",
      "risk_level": "high | medium | low",
      "risk_category": "string（如：违约责任不对称/支付条款风险/股权确权瑕疵/税务合规/管辖争议）",
      "client_impact": "对客户有利 | 对客户不利 | 中性",
      "description": "≤150字风险描述，从客户立场指出问题",
      "legal_basis": "《法规名称》第X条第X款（生效状态：现行有效）",
      "rag_confidence": 0.0,
      "consequence_quantified": "如果触发，对客户可能的经济后果量化",
      "suggested_action": "从客户利益出发的修改建议"
    }}
  ],
  "bottom_line_violations": ["触碰客户绝对底线的条款ID及说明"],
  "overall_client_assessment": "≤150字：综合评估这份合同对客户的总风险水平",
  "pending_verification": ["标注为【法规待核】的条款ID"],
  "rag_triggered": true,
  "rag_query_count": {len(rag_results) if rag_results else 0},
  "abolished_laws_blocked": 0
}}

核心要求：
- 每条 risk 必须有 client_impact 字段："对客户有利" / "对客户不利" / "中性"
- 与客户绝对底线冲突的条款 → risk_level 必须是 high
- 按客户利益大小排序：最不利的排最前面
"""

        try:
            response = self.llm_client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": self._build_system_prompt(client_context, rag_context)},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=4096,
                response_format={"type": "json_object"},
                timeout=LLM_TIMEOUT_SECONDS,
            )
            content = response.choices[0].message.content or "{}"
            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                logger.error("[乔曦初审] LLM 输出非合法 JSON")
                return {"error": "模型输出格式异常", "risks": []}
            logger.info(f"[乔曦初审] 完成，风险项: {len(result.get('risks', []))}")
            return result
        except Exception as e:
            logger.error(f"[乔曦初审] 失败: {e}")
            return {"error": "模型调用失败，请稍后重试", "risks": []}
