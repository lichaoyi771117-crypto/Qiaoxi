"""
Qiaoxi Contract-Analyzer · State 6 李超逸决策引擎

决策架构：
  L1（代码层硬编码）：六戒律触发器，if-then 逻辑，100% 确定性
  L2（<800 tokens 注入）：人格核，四选一决策风格
  L3（<1000 tokens 注入）：合同并购专用规则

输出：
  decision_order: 四选一标签（签/改/拖/退） + ≤3句硬核依据
  VETO 链路：三条绝对禁区触发 → 直接输出"否决/重写"
  用户拒绝 VETO → HANDOFF_TO_HUMAN
"""
import json
import logging
from openai import OpenAI
from src.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# L1: 六戒律硬编码触发器（确定性 if-then，禁止 AI 介入）
# ═══════════════════════════════════════════════════════════════

def _l1_hard_triggers(
    audits: list[dict],
    simulation: dict,
    legal_review: dict,
    profile: dict,
) -> dict:
    """
    L1 硬编码六戒律检查。
    返回 {"triggered": bool, "veto_type": str, "reason": str}
    """
    veto_count = sum(1 for a in audits if a.get("veto_triggered"))

    # 戒律1: 先付款后确权 + 无担保 → 否决
    for a in audits:
        if a.get("veto_triggered") and "先付款后确权" in a.get("veto_reason", ""):
            return {
                "triggered": True,
                "veto_type": "VETO_戒律1_资本安全垫击穿",
                "reason": "先付款后确权且无对等担保，资本安全垫击穿。不可签，必须重构付款与确权的时序对应关系。",
            }

    # 戒律2: 违约成本不对称超3倍 → 否决
    for a in audits:
        if a.get("veto_triggered") and ("显失公平" in a.get("veto_reason", "") or "3倍" in a.get("veto_reason", "")):
            return {
                "triggered": True,
                "veto_type": "VETO_戒律2_显失公平",
                "reason": "违约成本不对称超3倍或击穿净资产20%安全线。构成显失公平，必须重构违约条款。",
            }

    # 戒律3: 信息不对称 + 无充分尽调权 → 否决
    for a in audits:
        if a.get("veto_triggered") and "信息不对称" in a.get("veto_reason", ""):
            return {
                "triggered": True,
                "veto_type": "VETO_戒律3_信息不对称",
                "reason": "信息不对称风险极高，甲方无充分尽调权与资料真实性保证。不可签，必须先取得充分尽调权。",
            }

    # 戒律4: 运营失控（公章/执照/U盾由对手单方持有） → 否决
    for a in audits:
        if a.get("veto_triggered") and ("失控" in a.get("veto_reason", "") or "公章" in a.get("veto_reason", "")):
            return {
                "triggered": True,
                "veto_type": "VETO_戒律4_运营失控",
                "reason": "公章/营业执照/U盾由对手单方持有且无托管机制，运营失控风险不可接受。必须设置托管机制作为付款先决条件。",
            }

    # 戒律5: 尾部风险毁灭性且不可逆 → 否决
    for a in audits:
        if a.get("veto_triggered") and ("不可逆" in a.get("veto_reason", "") and "毁灭" in a.get("veto_reason", "")):
            return {
                "triggered": True,
                "veto_type": "VETO_戒律5_尾部风险不可逆",
                "reason": "尾部风险对客户具有毁灭性且不可逆。不可签，必须隔离下行风险或放弃交易。",
            }

    # 戒律6: 大额资金无托管/共管 → 否决
    for a in audits:
        if a.get("veto_triggered") and ("托管" in a.get("veto_reason", "") or "共管" in a.get("veto_reason", "")):
            return {
                "triggered": True,
                "veto_type": "VETO_戒律6_资金失控",
                "reason": "大额资金支付无共管/托管/对等担保机制，资金失控风险不可接受。必须建立第三方资金监管。",
            }

    # 无硬编码触发 — 交由 L2+L3 决策
    return {"triggered": False, "veto_type": "", "reason": ""}


# ═══════════════════════════════════════════════════════════════
# L2: 人格核（<800 tokens）—— 四选一决策风格
# ═══════════════════════════════════════════════════════════════

L2_PERSONA = """【角色内核】
你是李超逸，霖信莯咨询的首席决策者。你的决策风格基于以下四类范式：

【四选一决策标签】
1. ✅ 签（SIGN）：合同框架可行，风险可控，建议签署。若有具体条款修改建议则附注。
2. 🔧 改（AMEND）：合同可签，但以下条款必须修改（列出 ≤3 条具体条款及修改方向）。
3. ⏸️ 拖（PAUSE）：当前不宜签署，应由对方先满足以下先决条件（列出 ≤3 条），满足后再议。
4. 🚫 退（WALK）：不可签，不可改，建议放弃此交易并启动 BATNA 替代方案。

【决策铁律】
- 结论先行。不能先说"按照分析"再给结论。
- 最多 3 句硬核依据。不能冗长论证。
- 绝对不能使用"建议权衡""视情况而定"等温和措辞。
- 若六位评审员中任一人 veto_triggered==true，必须先讨论该否决是否成立，不能无视。
- 若六戒律触发器（L1）已触发，必须采纳 VETO 结论，不准有"但是"。
- 你做出的决策是最终决策，不是建议。客户可以不接受，但你不能不给明确结论。"""


# ═══════════════════════════════════════════════════════════════
# L3: 合同并购专用规则（<1000 tokens）
# ═══════════════════════════════════════════════════════════════

L3_RULES = """【合同并购专用决策规则】

1. **付款-确权顺序**：中国的合同并购交易，付款必须先于确权，或两者同步。但若对方为民营企业且无上市公司审计，付款必须先于确权时，必须要求共管账户 + 工商变更提交回执作为前置条件。
2. **公章与U盾**：公章与U盾交割完成是交割完成的唯一最终标志。在公章未进入共管或未变更前，不得视为交割完成。
3. **税务敞口**：若目标公司存在历史税务不合规，买方必须要求卖方在交割前以现金或等额保证金覆盖全部潜在税款，否则不考虑签署。
4. **法人变更**：法人代表变更的工商登记完成之前，收购方不得支付超过交易总对价 60% 以上的资金。
5. **竞业禁止**：交易中若涉及原股东/创始人的后续服务，必须附带不低于交易金额 20% 的竞业禁止保证金，锁定期不少于 3 年。
6. **退出机制**：合同必须包含明确的股东退出条款（强制回购、随售权、拖售权），否则不建议签署。
"""


# ═══════════════════════════════════════════════════════════════
# 决策引擎主类
# ═══════════════════════════════════════════════════════════════

class DecisionEngine:
    """
    State 6: 李超逸决策引擎

    L1 硬编码 → L1 触发则直接 VETO，不调 LLM
    L1 未触发 → 组装 L1+L2+L3，调 LLM 输出四选一决策
    """

    def __init__(self):
        self.llm_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    def decide(
        self,
        audits: list[dict],
        simulation: dict,
        cld_report: dict,
        profile: dict,
        legal_review: dict,
    ) -> dict:
        """
        主入口：输出最终决策

        Returns:
            {
                "decision_label": "签/改/拖/退",
                "decision_reasons": ["≤3条"],
                "veto_type": "VETO_xxx" 或 "",
                "veto_triggered": bool,
                "handoff_required": bool,
                "detailed_order": "文本化决策令"
            }
        """
        # ─── L1 硬编码检查 ───
        l1 = _l1_hard_triggers(audits, simulation, legal_review, profile)

        if l1["triggered"]:
            logger.info(f"[决策] L1 硬编码触发: {l1['veto_type']}")
            return {
                "decision_label": "VETO",
                "decision_reasons": [l1["reason"]],
                "veto_type": l1["veto_type"],
                "veto_triggered": True,
                "handoff_required": True,
                "detailed_order": f"## 李超逸最终决策：否决\n\n**依据**: {l1['veto_type']}\n\n**理由**: {l1['reason']}\n\n**⚠️ 客户如需推翻此否决，将触发人工顾问介入（HANDOFF_TO_HUMAN）。**",
            }

        # ─── L1 未触发 → LLM 综合决策（L1+L2+L3）───
        # 构建六位评审员摘要
        council_brief = self._build_council_brief(audits)
        sim_brief = self._build_simulation_brief(simulation)
        profile_brief = self._build_profile_brief(profile)

        system_prompt = f"""{L2_PERSONA}

【L3 合同并购专用规则】
{L3_RULES}

【L1 六戒律硬编码状态】
本轮 L1 硬编码未触发。六戒律已全部通过确定性检查。

【当前客户画像】
{profile_brief}"""

        user_prompt = f"""【私董会审计摘要】
{council_brief}

【推演引擎结果】
{sim_brief}

【乔曦法律初审摘要】
风险总数: {len(legal_review.get("risks", []))}
高风险数: {len([r for r in legal_review.get("risks", []) if r.get("risk_level")=="high"])}

【任务】
以李超逸身份做出最终决策。输出严格 JSON：
{{
  "decision_label": "签/改/拖/退",
  "decision_reasons": ["核心理由1 ≤100字", "核心理由2 ≤100字", "核心理由3 ≤100字"],
  "veto_override": false,
  "handoff_recommended": false,
  "detailed_order": "≤300字决策令正文"
}}

若决策为"退"或"拖"，handoff_recommended 应为 true。
若六位评审员中有任何人 veto_triggered==true 但你选择不采纳，veto_override 应为 true 并必须在 reasons 中说明理由。
严禁 Markdown 代码块包裹。"""

        try:
            response = self.llm_client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=2048,
                response_format={"type": "json_object"},
            )
            result = json.loads(response.choices[0].message.content)
            logger.info(f"[决策] 李超逸输出: {result.get('decision_label', '?')}")

            # 如果 LLM 输出 veto_override，也触发 handoff
            if result.get("veto_override"):
                result["handoff_required"] = True

            result.setdefault("veto_triggered", False)
            result.setdefault("veto_type", "")
            return result

        except Exception as e:
            logger.error(f"[决策] LLM 调用失败: {e}")
            return self._fallback_decision(str(e))

    def _build_council_brief(self, audits: list[dict]) -> str:
        lines = []
        for a in audits:
            lines.append(
                f"- {a.get('auditor_role', '?')} "
                f"(评分 {a.get('risk_score', 3)}/5, "
                f"veto={'是' if a.get('veto_triggered') else '否'}): "
                f"{a.get('audit_summary', '')[:150]}"
            )
        return "\n".join(lines)

    def _build_simulation_brief(self, sim: dict) -> str:
        snapshots = sim.get("snapshots", [])
        lines = [f"推演轨迹: {sim.get('trajectory', '未知')}"]
        for s in snapshots[:4]:
            lines.append(f"  M{s.get('month', '?')}: {s.get('risk_level', '?')} (信号 {s.get('combined_signal', 0)})")
        return "\n".join(lines)

    def _build_profile_brief(self, profile: dict) -> str:
        if not profile:
            return "客户画像未完成"
        sl = profile.get("strategic_layer", {})
        tl = profile.get("tactical_layer", {})
        return (
            f"立场: {tl.get('position', '?')} | "
            f"风险偏好: {tl.get('risk_appetite', '?')} | "
            f"最大损失: {tl.get('max_loss_pct', 0)*100:.0f}% | "
            f"BATNA: {tl.get('batna_strength', '?')} | "
            f"底线: {', '.join(tl.get('hard_lines', [])) or '未设置'}"
        )

    def _fallback_decision(self, error: str) -> dict:
        return {
            "decision_label": "拖",
            "decision_reasons": [
                f"AI决策引擎因技术原因未能完成分析: {error}",
                "建议等待系统恢复后重新生成决策，或启动人工顾问介入。",
            ],
            "veto_type": "",
            "veto_triggered": False,
            "handoff_required": True,
            "detailed_order": f"## 李超逸决策（降级回退）\n\n系统故障，无法生成决策。建议人工介入。错误: {error}",
        }
