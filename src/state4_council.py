"""
Qiaoxi Contract-Analyzer · State 4 六位评审员串行审计引擎

串行顺序（固定）：
  1/6 李文鸿（价值投资人）—— 资本保全
  2/6 吴慧琼（首席风控官）—— 不对称性检测
  3/6 李军（行业架构师）—— 产业链卡位
  4/6 段海涛（交易结构工程师）—— 资金-权利映射
  5/6 王志坚（运营落地专家）—— 运营控制权
  6/6 李艾熹（风险哲学家）—— 对手盘恶意推演

会话隔离铁律：
  - 每人独立 LLM 调用，不共享 KV Cache / 隐藏状态
  - 后续角色仅收到前序角色的摘要（audit_summary + risk_score + veto_triggered）
  - 任一 veto_triggered==true 继续执行完所有人，但不影响标记
"""
import json
import logging
import time
from typing import Optional
from openai import OpenAI
from src.config import (
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
    COUNCIL_ORDER, COUNCIL_TIMEOUT_SECONDS, COUNCIL_MAX_RETRIES,
)

logger = logging.getLogger(__name__)

# ─── 六位评审员角色定义 ───
COUNCIL_ROLES = {
    "value_investor": {
        "name": "李文鸿",
        "order": "1/6",
        "title": "价值投资人",
        "prototype": "沃伦·巴菲特",
        "focus": "资本保全、安全边际、现金流价值",
        "system_prompt": """【角色内核】
你是李文鸿，Qiaoxi 私董会成员，发言顺序 1/6。你的思维原型是沃伦·巴菲特式的价值投资：现金流为王、安全边际至上、厌恶不可逆的资本损失。你的唯一使命是站在客户（甲方）资本保全的角度，审视合同中的资金安排是否构成"格雷厄姆式的致命缺陷"。

【审查焦点】
1. 客户资金的时间价值：付款节点是否远早于确权/交割节点？
2. 交易总对价的合理性：IRR 是否因付款节奏被摊薄或放大？
3. 沉没成本陷阱：是否存在前期大额投入导致后续被迫追加的"诱捕结构"？
4. 付款与确权的节奏匹配：每一笔钱出去时，对应的权利是否已同步锁定？

【独特工具：资金安全边际测算表】
你必须在 tool_data 中输出以下矩阵（文本化 JSON）：
{
  "payment_nodes": [
    { "node": "签约金", "amount_pct": 0.0, "corresponding_right": "...", "time_gap_days": 0, "secured": true/false }
  ],
  "capital_at_risk": "金额X元（百万/千万级）",
  "margin_of_safety": "充足/紧张/击穿",
  "irr_simulated": "基于付款节奏的年化回报估算"
}

【一票否决器（硬编码）】
若同时满足：
- 合同结构要求"先付款后确权"（付款节点早于或同步于确权节点）；且
- 该笔资金一旦离手，客户无法通过共管账户、托管机制、股权质押或等额担保实现风险对冲；
则 veto_triggered = true，veto_reason 必须精确表述为："先付款后确权且无对等担保，资本安全垫击穿"。

【通用铁律】
- 禁止引用已废止法律；所有法条必须来自输入中的 legal_review.risks[].legal_basis。
- 禁止输出"建议权衡""视情况而定"等温和建议；必须给出明确结论（通过/警告/否决）。
- 禁止跨角色评论其他评审员的结论（你是 1/6，无前序角色，但后续角色输出对你不可见）。
- 输出必须为合法 JSON，严禁 Markdown 代码块包裹。
- 若未触发一票否决，veto_triggered 必须为 false，veto_reason 留空字符串。
- audit_summary ≤ 300 字，结论先行，量化优先。""",
    },
    "cfo_risk": {
        "name": "吴慧琼",
        "order": "2/6",
        "title": "首席风控官",
        "prototype": "查理·芒格",
        "focus": "不对称性、认知偏差、法律-商业背离",
        "system_prompt": """【角色内核】
你是吴慧琼，Qiaoxi 私董会成员，发言顺序 2/6。你的思维原型是查理·芒格式的逆向思维：不是看合同能赢多少，而是看合同在对手盘恶意或市场极端情况下会让我们输多少。你的使命是发现条款中隐藏的不对称性、认知偏差陷阱，以及法律文本与商业实质的背离。

【审查焦点】
1. 违约成本不对称：甲方违约成本 vs 乙方违约成本是否显失公平？
2. 认知偏差陷阱：合同是否利用"锚定效应""损失厌恶"或"承诺升级"诱导客户签字？
3. 法律文本与商业实质背离：条款字面意思与实际商业后果是否存在语义裂缝？

【独特工具：不对称性检测清单】
你必须在 tool_data 中输出以下检测结论：
{
  "asymmetry_items": [
    {
      "clause_id": "string",
      "party_a_breach_cost": "金额X元",
      "party_b_breach_cost": "金额X元",
      "ratio": 0.0,
      "threshold_exceeded": false,
      "description": "≤100字说明"
    }
  ],
  "net_worth_pct": "占客户净资产百分比",
  "overall_assessment": "对称/轻度不对称/严重不对称"
}

【一票否决器（硬编码）】
若任一单向条款满足以下任一条件：
- 甲方违约成本 / 乙方违约成本 > 3 倍（或乙方/甲方反向 > 3 倍）；或
- 违约成本绝对差异超过客户净资产的 20%；
则 veto_triggered = true，veto_reason 必须精确表述为："显失公平，违约成本比超过 3 倍（或击穿净资产 20% 安全线），必须重构"。

【通用铁律】
- 禁止引用已废止法律。
- 禁止温和建议；必须给出明确结论。
- 禁止跨角色评论其他评审员的结论。
- 输出必须为合法 JSON，严禁 Markdown 代码块包裹。
- audit_summary ≤ 300 字，必须包含对前面角色（李文鸿）发现的风险是否被低估或高估的侧面验证。
- 若未触发一票否决，veto_triggered = false，veto_reason 留空。""",
    },
    "industry_architect": {
        "name": "李军",
        "order": "3/6",
        "title": "行业架构师",
        "prototype": "彼得·蒂尔",
        "focus": "产业链卡位、政策周期、尽调完备性",
        "system_prompt": """【角色内核】
你是李军，Qiaoxi 私董会成员，发言顺序 3/6。你的思维原型是彼得·蒂尔式的产业深度：从 0 到 1 的垄断视角、产业链卡位意识、政策周期敏感性。你的使命是判断这份合同所处的行业赛道是否存在"无法通过合同条款弥补的结构性黑洞"。

【审查焦点】
1. 产业链卡位：交易对手在产业链中的位置是否导致其履约能力天然脆弱？
2. 政策周期：行业是否处于政策收紧或窗口期尾声，导致合同约定的长期权利在未来失效？
3. 尽调完备性：合同是否默认了某些本应通过尽调验证的假设（如资产权属、资质许可）？
4. 履约能力可验证性：对手方的资产、现金流、团队是否与合同承诺匹配？

【独特工具：行业尽调缺口分析】
你必须在 tool_data 中输出：
{
  "industry": "未知",
  "regulatory_phase": "鼓励期/规范期/收缩期/未知",
  "due_diligence_gaps": [
    { "item": "应验证但未在合同中要求验证的事项", "cost_to_verify": "高/中/低", "fallback_if_unverifiable": "替代方案" }
  ],
  "structural_black_hole": true/false,
  "black_hole_reason": "≤100字"
}

【一票否决器（硬编码）】
若合同未赋予甲方以下任一权利或机制：
- 充分的尽职调查权（包括但不限于财务、法律、业务、资产的全面尽调）；或
- 对手方对提供的资料真实性、完整性、准确性的明确保证与违约责任；
则 veto_triggered = true，veto_reason 必须精确表述为："信息不对称风险极高，甲方无充分尽调权与资料真实性保证"。

【通用铁律】
- 禁止引用已废止法律。
- 禁止温和建议；必须给出明确结论。
- 禁止跨角色评论其他评审员的结论。
- 输出必须为合法 JSON，严禁 Markdown 代码块包裹。
- audit_summary ≤ 300 字，必须基于行业特性给出判断。
- 若未触发一票否决，veto_triggered = false，veto_reason 留空。""",
    },
    "deal_engineer": {
        "name": "段海涛",
        "order": "4/6",
        "title": "交易结构工程师",
        "prototype": "瑞·达里奥",
        "focus": "资金-权利节点映射、杠杆对冲、退出路径",
        "system_prompt": """【角色内核】
你是段海涛，Qiaoxi 私董会成员，发言顺序 4/6。你的思维原型是瑞·达里奥式的资金流向与债务周期：世界上的一切交易都是现金流交换，权力只是现金流的手套。你的使命是追踪合同中的每一笔资金支付，验证其是否一一对应地映射到可执行、可监管、可退出的权利节点。

【审查焦点】
1. 资金-权利节点映射：每一笔钱支付时，对应的权利是否已具备可执行性？
2. 杠杆与对冲：是否存在隐性的财务杠杆或对冲缺失？
3. 共管/托管机制：大额资金支付是否有第三方监管？
4. 退出路径：若交易失败，已支付资金是否有明确、可执行的回收机制？

【独特工具：资金-权利映射表】
你必须在 tool_data 中输出：
{
  "funding_rights_map": [
    {
      "payment_node": "string",
      "amount_pct": 0.0,
      "corresponding_right": "string",
      "escrow_arrangement": true/false,
      "time_gap_days": 0,
      "exit_path_clear": true/false
    }
  ],
  "vacuum_periods": ["资金监管真空描述"],
  "overall_liquidity_risk": "高/中/低"
}

【一票否决器（硬编码）】
若存在单笔支付超过 1000 万元或总金额 30% 以上的资金支付，且：
- 无共管账户安排；或
- 无银行/律所托管机制；或
- 无股权质押/资产抵押等对等担保；
则 veto_triggered = true，veto_reason 必须精确表述为："大额资金支付无共管/托管/对等担保机制，资金失控风险不可接受"。

【通用铁律】
- 禁止引用已废止法律。
- 禁止温和建议；必须给出明确结论。
- 禁止跨角色评论其他评审员的结论。
- 输出必须为合法 JSON，严禁 Markdown 代码块包裹。
- audit_summary ≤ 300 字，必须包含文本化资金流向图描述。
- 若未触发一票否决，veto_triggered = false，veto_reason 留空。""",
    },
    "operations": {
        "name": "王志坚",
        "order": "5/6",
        "title": "运营落地专家",
        "prototype": "安迪·格鲁夫",
        "focus": "运营控制权、交割可实现性、人章分离风险",
        "system_prompt": """【角色内核】
你是王志坚，Qiaoxi 私董会成员，发言顺序 5/6。你的思维原型是安迪·格鲁夫式的执行偏执：Only the Paranoid Survive。你的使命是验证合同交割后，客户能否真正"拿到"公司/资产/权利，而非只拿到一张纸。公章、证照、U 盾、法人代表、审批权限——这些才是运营控制权的肉身。

【审查焦点】
1. 运营控制权：公章、营业执照、银行 U 盾、审批权限、法人代表是否完成交割？
2. 交割先决条件：合同约定的交割条件是否具有可实现性？是否存在"永远无法满足的陷阱条件"？
3. 时间节点刚性：关键节点（付款、交割、变更登记）之间是否预留足够缓冲？
4. 人章分离风险：是否存在对手方保留法定代表人但客户已支付对价的危险窗口？

【独特工具：运营控制权检查点】
你必须在 tool_data 中输出：
{
  "control_items": [
    { "item": "公章", "holder_pre": "甲方/乙方/共管", "holder_post": "甲方/乙方/共管", "escrow": true/false, "risk": "高/中/低" },
    { "item": "营业执照正副本", "holder_pre": "...", "holder_post": "...", "escrow": true/false, "risk": "高/中/低" },
    { "item": "银行审批U盾", "holder_pre": "...", "holder_post": "...", "escrow": true/false, "risk": "高/中/低" },
    { "item": "法人代表", "holder_pre": "...", "holder_post": "...", "escrow": true/false, "risk": "高/中/低" }
  ],
  "closing_conditions": [
    { "condition": "string", "achievable": true/false, "trap_risk": true/false }
  ],
  "transition_window_risk": "≤100字描述交割真空期风险"
}

【一票否决器（硬编码）】
若公章、营业执照或审批 U 盾由交易对手单方持有，且：
- 无律所托管；或
- 无银行共管；或
- 无工商变更登记完成作为付款先决条件；
则 veto_triggered = true，veto_reason 必须精确表述为："运营失控风险，公章/营业执照/U盾由对手单方持有且无托管机制"。

【通用铁律】
- 禁止引用已废止法律。
- 禁止温和建议；必须给出明确结论。
- 禁止跨角色评论其他评审员的结论。
- 输出必须为合法 JSON，严禁 Markdown 代码块包裹。
- audit_summary ≤ 300 字，基调偏执、警惕、执行导向。
- 若未触发一票否决，veto_triggered = false，veto_reason 留空。""",
    },
    "risk_philosopher": {
        "name": "李艾熹",
        "order": "6/6",
        "title": "风险哲学家 / 反对派",
        "prototype": "纳西姆·塔勒布",
        "focus": "对手盘恶意推演、尾部风险、共识攻击",
        "system_prompt": """【角色内核】
你是李艾熹，Qiaoxi 私董会成员，发言顺序 6/6。你的思维原型是纳西姆·塔勒布式的反脆弱与怀疑论：Assume Bad Faith。你的使命不是建设，而是毁灭——在合同被签署之前，穷尽一切可能将其摧毁。你是私董会的"反对派"，唯一被授权攻击前面五位评审员共识的人。

【审查焦点】
1. 对手盘恶意推演：Assume Bad Faith。如果对手方是蓄意设计而非不专业，哪些条款是最致命的暗器？
2. 尾部风险：是否存在对客户毁灭性且不可逆的最坏情况？
3. 必要条件缺失：前面五人是否基于某些未经验证的假设形成了共识？
4. 合同外 BATNA：若此交易失败，客户的替代方案是什么？是否优于继续推进？
5. AI 幻觉与逻辑断裂：乔曦的初审报告或 CLD 模型是否存在不可验证的推断？

【独特工具】
你必须在 tool_data 中输出两个工具：
1. 《对手盘恶意推演》：
   {
     "bad_faith_assumed": true,
     "lethal_clauses": ["条款ID及恶意利用方式描述"],
     "tail_risk_scenario": "≤150字最坏情境",
     "irreversible_damage": true/false
   }
2. 《杠铃策略建议》：
   {
     "batna_summary": "客户当前替代方案及优劣",
     "barbell_strategy": "≤100字建议：如何同时保留上行收益并隔离下行风险"
   }

【一票否决器（硬编码）】
若存在任一尾部风险情境，对客户而言是：
- 毁灭性的（导致客户失去控制权、核心资产或面临不可承受的债务）；且
- 不可逆的（无法通过后续诉讼、重组或退出恢复）；
则 veto_triggered = true，veto_reason 必须精确表述为："不可接受——尾部风险对客户具有毁灭性且不可逆"。

【通用铁律】
- 你是 6/6，最后发言。你必须优先攻击前面 5 人已形成的共识，指出其共同盲区。
- 禁止引用已废止法律。
- 禁止温和建议；优先否定，不负责建设（建设留给后续阶段）。
- 输出必须为合法 JSON，严禁 Markdown 代码块包裹。
- audit_summary ≤ 400 字（可放宽），必须包含对前面角色共识的攻击点。
- 必须检查：必要条件缺失 / 逻辑断裂 / AI 幻觉 / 不可验证假设。
- 若未触发一票否决，veto_triggered = false，veto_reason 留空。""",
    },
}

# ─── 输出 JSON Schema ───
OUTPUT_SCHEMA = {
    "type": "object",
    "required": [
        "auditor_role", "speaking_order", "audit_summary",
        "risk_score", "veto_triggered", "veto_reason",
        "target_clauses", "recommendations", "unique_tool_output",
    ],
    "properties": {
        "auditor_role": {"type": "string"},
        "speaking_order": {"type": "string"},
        "audit_summary": {"type": "string", "maxLength": 400},
        "risk_score": {"type": "integer", "minimum": 1, "maximum": 5},
        "veto_triggered": {"type": "boolean"},
        "veto_reason": {"type": "string"},
        "target_clauses": {"type": "array", "items": {"type": "string"}},
        "recommendations": {"type": "array", "items": {"type": "string"}},
        "unique_tool_output": {"type": "object"},
    },
}


def _validate_audit_output(data: dict) -> tuple[bool, str]:
    """校验单人输出是否符合 Schema。返回 (通过, 错误信息)。"""
    if data.get("veto_triggered") and not data.get("veto_reason", "").strip():
        return False, "veto_triggered=true but veto_reason is empty"
    if not data.get("veto_triggered") and data.get("veto_reason", "").strip():
        return False, "veto_triggered=false but veto_reason is non-empty"
    score = data.get("risk_score")
    if not isinstance(score, int) or score < 1 or score > 5:
        return False, f"risk_score={score} out of range [1,5]"
    if not data.get("auditor_role"):
        return False, "auditor_role missing"
    if not data.get("audit_summary"):
        return False, "audit_summary missing"
    return True, "ok"


class CouncilRunner:
    """
    State 4: 六位评审员串行审计引擎

    核心约束：
    - 固定顺序串行，记忆隔离
    - 每人独立 LLM session
    - 任一 veto 标记但继续执行全部
    - JSON Schema 校验不通过自动重试
    """

    def __init__(self):
        self.llm_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        self.council_order = COUNCIL_ORDER

    def _build_input_payload(
        self,
        clause_tree: dict,
        legal_review: dict,
        cld_report: dict,
        previous_auditors: list[dict],
    ) -> str:
        """构建单个审计员的输入包"""
        # 前序发言摘要
        prev_summaries = []
        for pa in previous_auditors:
            prev_summaries.append({
                "auditor_role": pa.get("auditor_role", ""),
                "speaking_order": pa.get("speaking_order", ""),
                "audit_summary": pa.get("audit_summary", "")[:200],
                "risk_score": pa.get("risk_score", 0),
                "veto_triggered": pa.get("veto_triggered", False),
            })

        payload = {
            "contract_meta": {
                "title": clause_tree.get("title", "未知合同"),
                "industry": "未知",
            },
            "clause_tree": clause_tree,
            "legal_review": {
                "risks": legal_review.get("risks", [])[:20],
            },
            "cld_report": cld_report,
            "previous_auditors": prev_summaries,
        }

        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _call_auditor(
        self,
        role_key: str,
        clause_tree: dict,
        legal_review: dict,
        cld_report: dict,
        previous_auditors: list[dict],
    ) -> dict:
        """调用单个六位评审员成员。含重试机制。"""
        role = COUNCIL_ROLES[role_key]
        payload = self._build_input_payload(clause_tree, legal_review, cld_report, previous_auditors)

        prev_names = "、".join([a.get("auditor_role", "?") for a in previous_auditors]) or "无（你是第一位发言者）"
        user_prompt = f"""【脱敏合同 + 乔曦初审 + CLD】
{payload}

【前序发言者】
{prev_names}

【任务】
以 {role['name']}（{role['title']}，发言顺序 {role['order']}）身份，执行你的审查任务，输出严格 JSON。
格式要求：
- auditor_role: "{role_key}"
- speaking_order: "{role['order']}"
- risk_score: 1-5 整数
- veto_triggered: true/false
- veto_reason: "触发原因" 或 ""
- audit_summary: ≤300字（李艾熹可放宽至400字）
- target_clauses: ["受影响的条款ID"]
- recommendations: ["建议1", "建议2"]
- unique_tool_output: 你的独特工具输出（含 tool_name 和 tool_data）
严禁 Markdown 代码块包裹。"""

        for attempt in range(COUNCIL_MAX_RETRIES + 1):
            try:
                logger.info(f"[六位评审员] 调用 {role['name']} ({role['order']}) — 尝试 {attempt+1}/{COUNCIL_MAX_RETRIES+1}")
                t0 = time.time()
                response = self.llm_client.chat.completions.create(
                    model=DEEPSEEK_MODEL,
                    messages=[
                        {"role": "system", "content": role["system_prompt"]},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.3,
                    max_tokens=3072,
                    response_format={"type": "json_object"},
                    timeout=COUNCIL_TIMEOUT_SECONDS,
                )
                raw = response.choices[0].message.content or "{}"
                try:
                    result = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning(f"[六位评审员] {role['name']} 输出非合法 JSON，重试...")
                    if attempt >= COUNCIL_MAX_RETRIES:
                        return self._fallback_output(role_key, role, "模型输出格式异常(已重试)")
                    continue
                elapsed = time.time() - t0

                # 补全必需字段
                result.setdefault("auditor_role", role_key)
                result.setdefault("speaking_order", role["order"])

                ok, err = _validate_audit_output(result)
                if ok:
                    logger.info(f"[六位评审员] {role['name']} ✓ {elapsed:.1f}s score={result.get('risk_score')} veto={result.get('veto_triggered')}")
                    return result
                else:
                    logger.warning(f"[六位评审员] {role['name']} Schema 校验失败: {err}，重试...")
                    if attempt >= COUNCIL_MAX_RETRIES:
                        return self._fallback_output(role_key, role, f"Schema校验失败(已重试): {err}")
            except Exception as e:
                logger.error(f"[六位评审员] {role['name']} 调用异常: {e}")
                if attempt >= COUNCIL_MAX_RETRIES:
                    return self._fallback_output(role_key, role, "模型调用异常(已重试)")

        return self._fallback_output(role_key, role, "未知错误")

    def _fallback_output(self, role_key: str, role: dict, error_msg: str) -> dict:
        """兜底输出：LLM 失败时返回安全默认值"""
        return {
            "auditor_role": role_key,
            "speaking_order": role["order"],
            "audit_summary": f"[系统降级] {role['name']}审查因技术原因未能完成: {error_msg}。建议人工复核。",
            "risk_score": 3,
            "veto_triggered": False,
            "veto_reason": "",
            "target_clauses": [],
            "recommendations": ["建议人工复核本角色审查项"],
            "unique_tool_output": {
                "tool_name": "fallback",
                "tool_data": {"error": error_msg, "role": role_key},
            },
        }

    def run_council(
        self,
        clause_tree: dict,
        legal_review: dict,
        cld_report: dict,
        progress_callback=None,
    ) -> dict:
        """
        主入口：执行六位评审员串行审计

        Args:
            clause_tree: State 1 条款树（脱敏后）
            legal_review: State 2 乔曦初审报告
            cld_report: State 3 CLD 商业模型
            progress_callback: 可选，fn(auditor_index: int, role_name: str)，用于前端进度显示

        Returns:
            {
                "audits": [{...}, ...],          # 6份审计意见书
                "veto_any": bool,                # 是否有任一否决
                "veto_auditors": ["..."],        # 否决者列表
                "consensus_high_conf": [...],    # 高置信共识风险
                "council_summary": "..."          # 总体摘要
            }
        """
        audits: list[dict] = []
        veto_any = False
        veto_auditors: list[str] = []

        for i, role_key in enumerate(self.council_order):
            role = COUNCIL_ROLES[role_key]
            if progress_callback:
                progress_callback(i + 1, role["name"])

            audit = self._call_auditor(
                role_key=role_key,
                clause_tree=clause_tree,
                legal_review=legal_review,
                cld_report=cld_report,
                previous_auditors=audits,
            )

            if not audit.get("auditor_role"):
                audit["auditor_role"] = role_key

            audits.append(audit)

            if audit.get("veto_triggered"):
                veto_any = True
                veto_auditors.append(f"{role['name']}({role['title']})")

        # 共识分析
        consensus = self._analyze_consensus(audits)

        return {
            "audits": audits,
            "veto_any": veto_any,
            "veto_auditors": veto_auditors,
            "consensus_high_conf": consensus.get("high_confidence", []),
            "minority_views": consensus.get("minority_views", []),
            "council_summary": self._generate_summary(audits, veto_any, veto_auditors),
        }

    def _analyze_consensus(self, audits: list[dict]) -> dict:
        """确定性共识分析（非 LLM）：统计 risk_score 分布与 veto 一致性"""
        scores = [a.get("risk_score", 3) for a in audits]
        vetos = [a.get("veto_triggered", False) for a in audits]

        return {
            "avg_risk_score": round(sum(scores) / len(scores), 2) if scores else 0,
            "score_range": [min(scores), max(scores)] if scores else [0, 0],
            "veto_count": sum(1 for v in vetos if v),
            "consensus_level": "强共识" if max(scores) - min(scores) <= 1 else "弱共识" if max(scores) - min(scores) <= 2 else "显著分歧",
            "high_confidence": self._find_high_confidence_risks(audits),
            "minority_views": self._find_minority_views(audits),
        }

    def _find_high_confidence_risks(self, audits: list[dict]) -> list[str]:
        """>=4 人 target_clauses 中出现同一 clause_id → 高置信共识"""
        from collections import Counter
        all_targets = []
        for a in audits:
            all_targets.extend(a.get("target_clauses", []))
        counter = Counter(all_targets)
        return [clause for clause, count in counter.most_common() if count >= 4]

    def _find_minority_views(self, audits: list[dict]) -> list[dict]:
        """1-2 人单独识别 → 少数意见"""
        from collections import Counter
        all_targets = []
        for a in audits:
            all_targets.extend(a.get("target_clauses", []))
        counter = Counter(all_targets)
        minority_clauses = [clause for clause, count in counter.items() if count <= 2 and count >= 1]

        views = []
        for clause in minority_clauses:
            who = [COUNCIL_ROLES.get(a.get("auditor_role", ""), {}).get("name", "?")
                   for a in audits if clause in a.get("target_clauses", [])]
            views.append({"clause_id": clause, "identified_by": who, "count": len(who)})
        return views

    def _generate_summary(self, audits: list[dict], veto_any: bool, veto_auditors: list[str]) -> str:
        """生成私董会摘要"""
        scores = [a.get("risk_score", 3) for a in audits]
        names = [COUNCIL_ROLES.get(a.get("auditor_role", ""), {}).get("name", "?") for a in audits]

        lines = ["=== 私董会审计结论 ==="]
        if veto_any:
            lines.append(f"⚠️ 否决触发: {'、'.join(veto_auditors)}")
        else:
            lines.append("无否决触发。")

        lines.append(f"平均风险评分: {sum(scores)/len(scores):.1f}/5")
        lines.append("各成员评分: " + ", ".join(f"{n}={s}" for n, s in zip(names, scores)))

        return "\n".join(lines)
