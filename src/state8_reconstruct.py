"""
Qiaoxi Contract-Analyzer · State 8 合同重构引擎

三步串行生成：
  Step 1: 深度消化阶段 ── DeepSeek 精读审查报告，提炼"重构任务书"（内部中间态，不输出给用户）
  Step 2: 重构合同草案 ── 基于任务书 + 原条款树，输出新合同
  Step 3: 框架协议      ── 防御性框架协议（代尽调意向书），保障甲方付款前权利
  Step 4: 尽调清单      ── 分类详尽的文件核查清单

重构方向映射：
  "最大限度维护我方利益"  → aggressive：全面向甲方倾斜，违约对等或反向加重乙方
  "条款公平偏中性"        → neutral：市场惯例，双方对等
  "兼顾各方利益，便于尽快达成" → balanced：保护核心利益同时降低谈判摩擦
"""
import json
import logging
import time
from typing import Optional
from openai import OpenAI
from src.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

logger = logging.getLogger(__name__)

# ─── 重构方向 → Prompt 基调 ───
ANGLE_STYLE = {
    "最大限度维护我方利益": {
        "tone": "aggressive",
        "instruction": (
            "你代表甲方（委托客户）以最强势的姿态起草。"
            "每一条款都应最大化保护甲方利益：支付节点尽量后置、确权尽量前置、"
            "乙方违约成本不低于甲方违约成本的2倍、赋予甲方单方解除权和无理由退出权。"
            "不追求对方容易接受，追求甲方利益最大化。"
        ),
    },
    "条款公平偏中性": {
        "tone": "neutral",
        "instruction": (
            "参照市场商业惯例起草，追求双方权利义务对等。"
            "支付节点与确权节点同步、违约成本双向对等、信息义务双向透明。"
            "条款应能通过合理性审查，不偏袒任何一方。"
        ),
    },
    "兼顾各方利益，便于尽快达成": {
        "tone": "balanced",
        "instruction": (
            "在充分保护甲方核心利益（尽调权、资金安全、退出机制）的前提下，"
            "主动降低谈判摩擦：用弹性条款替代强硬单边条款、给乙方留出合理利益空间、"
            "优先确保交易能够推进至下一阶段。底线不让步，细节可妥协。"
        ),
    },
}

# ─── 关键风险类别 → 条款重构优先级 ───
VETO_PRIORITY_MAP = {
    "VETO_戒律1_资本安全垫击穿": "【最高优先级】重构付款-确权时序：所有付款节点必须后置于相应权利确认，或设立共管账户作为前置条件。",
    "VETO_戒律2_显失公平": "【最高优先级】重构违约条款：甲方违约成本不得超过乙方违约成本，补偿上限与保证金对等。",
    "VETO_戒律3_信息不对称": "【最高优先级】新增尽调权条款：乙方须在签约前提供完整资料，甲方享有60个工作日全面尽调权。",
    "VETO_戒律4_运营失控": "【最高优先级】新增交割先决条件：公章/营业执照/U盾须先进入律所托管，方可触发下一笔付款。",
    "VETO_戒律5_尾部风险不可逆": "【最高优先级】新增风险隔离机制：设置强制止损条款，当触发条件出现时甲方享有无责退出权。",
    "VETO_戒律6_资金失控": "【最高优先级】新增资金监管条款：所有超过100万元的单笔支付须通过第三方共管账户划转。",
}


def _build_digest_prompt(
    final_report: str,
    clause_tree: dict,
    legal_review: dict,
    audits: list,
    decision: dict,
    profile: dict,
    reconstruct_angle: str,
) -> str:
    """Step 1：构建深度消化提示词，让模型精读报告并生成内部任务书。"""
    style = ANGLE_STYLE.get(reconstruct_angle, ANGLE_STYLE["条款公平偏中性"])

    # 提取 veto 信息
    veto_lines = []
    if decision:
        vt = decision.get("veto_type", "")
        if vt and vt in VETO_PRIORITY_MAP:
            veto_lines.append(VETO_PRIORITY_MAP[vt])
        for r in decision.get("decision_reasons", []):
            veto_lines.append(f"- {r}")

    # 提取六位评审员核心意见（每人不超过200字）
    council_brief = []
    for a in (audits or []):
        name = a.get("auditor_role", "?")
        summary = a.get("audit_summary", "")[:200]
        veto = "【已否决】" if a.get("veto_triggered") else ""
        recs = "; ".join(a.get("recommendations", [])[:3])
        council_brief.append(f"[{name}]{veto} {summary} | 建议：{recs}")

    # 客户核心诉求
    profile_brief = ""
    if profile:
        tl = profile.get("tactical_layer", {})
        profile_brief = (
            f"立场：{tl.get('position','未知')} | "
            f"风险偏好：{tl.get('risk_appetite','未知')} | "
            f"最大可承受损失：{tl.get('max_loss_pct',0)*100:.0f}% | "
            f"BATNA：{tl.get('batna_strength','未知')} | "
            f"底线：{', '.join(tl.get('hard_lines',[]) or ['未设置'])}"
        )

    # 原合同条款摘要（仅条款标题和核心内容摘要，控制长度）
    clauses_brief = []
    for c in (clause_tree.get("clauses", []) if clause_tree else [])[:20]:
        cid = c.get("clause_id", "")
        title = c.get("title", "")
        text = c.get("text", "")[:150]
        clauses_brief.append(f"{cid} {title}：{text}")

    prompt = f"""你是一名中国顶级商业并购律师，同时具备资深商业咨询顾问视角。
你现在接受了一项任务：基于下方完整的合同审查分析报告，为客户重构一套全新的合同解决方案。

═══════════════════════════════════════
【一、客户立场与重构方向】
客户选择方向：{reconstruct_angle}
重构原则：{style['instruction']}
客户画像：{profile_brief}

═══════════════════════════════════════
【二、李超逸最终决策（必须优先响应）】
{chr(10).join(veto_lines) if veto_lines else '无否决触发，决策为：' + (decision.get('decision_label','?') if decision else '未知')}
决策令全文：{(decision.get('detailed_order','') if decision else '')[:500]}

═══════════════════════════════════════
【三、六位评审员核心审查意见】
{chr(10).join(council_brief)}

═══════════════════════════════════════
【四、Qiaoxi 完整分析报告（请逐字精读）】
{final_report[:6000] if final_report else '报告未生成'}

═══════════════════════════════════════
【五、原合同主要条款结构】
{chr(10).join(clauses_brief) if clauses_brief else '条款树未提取'}

═══════════════════════════════════════
【任务】
在精读上述全部内容后，请输出一份"重构任务书"，格式为 JSON：
{{
  "contract_title": "建议的新合同名称",
  "party_a": "甲方简称",
  "party_b": "乙方简称",
  "deal_type": "交易类型（并购/合作/股权转让等）",
  "deal_complexity": "simple|medium|complex",
  "complexity_reason": "≤50字说明判断理由",
  "files_to_generate": {{
    "contract_draft": true,
    "framework_agreement": true/false,
    "dd_checklist": true/false
  }},
  "core_risks_to_fix": [
    {{"risk_id": "R1", "original_problem": "原合同问题描述", "fix_direction": "重构方向", "priority": "高/中/低"}}
  ],
  "new_clauses_required": [
    {{"clause_purpose": "条款目的", "key_content": "核心内容要点", "protection_target": "甲方/双方"}}
  ],
  "clauses_to_delete": ["应删除的原条款说明"],
  "payment_structure_redesign": "付款节点重设方案（文字描述）",
  "exit_mechanism": "退出/止损机制设计",
  "special_notes": "其他需要特别注意的事项"
}}

【files_to_generate 判定原则（强制遵守 —— 默认只生成新合同草案，附件按需才生成）】
- contract_draft 永远为 true（必须生成新合同）
- framework_agreement：默认 false。仅当合同涉及以下场景时才为 true：
  a) 并购/股权转让/采矿权/重大资产收购
  b) 标的金额在千万级以上，且原合同尽调条款完全缺失
  否则必须为 false。普通服务合同、外包合同、咨询合同、保密协议等，一律不需要框架协议。
- dd_checklist：默认 false。仅当且仅当合同涉及以下场景时才为 true：
  a) 并购（股权收购/资产收购/合并分立）
  b) 采矿权/探矿权转让
  仅此两类需要尽调清单。其他任何合同类型（包括股权合作、合资、外包、服务、咨询、保密协议等）一律为 false。
  基本判断逻辑：普通商业合同不需要客户去实施大规模尽职调查行为，尽调清单只在涉及资产/股权归属核查的重大交易场景下才有意义。
  若你在斟酌是否该设为 true —— 就设为 false。

严禁 Markdown 代码块包裹。输出纯 JSON。"""
    return prompt


def _build_contract_prompt(task_book: dict, reconstruct_angle: str, profile: dict) -> str:
    """Step 2：基于任务书起草新合同。"""
    style = ANGLE_STYLE.get(reconstruct_angle, ANGLE_STYLE["条款公平偏中性"])
    party_a = task_book.get("party_a", "甲方")
    party_b = task_book.get("party_b", "乙方")
    title = task_book.get("contract_title", "重构合同草案")

    risks_text = "\n".join(
        f"- [{r['priority']}] {r['original_problem']} → {r['fix_direction']}"
        for r in task_book.get("core_risks_to_fix", [])
    )
    new_clauses_text = "\n".join(
        f"- {c['clause_purpose']}：{c['key_content']} （保护：{c['protection_target']}）"
        for c in task_book.get("new_clauses_required", [])
    )

    return f"""你是一名中国顶级商业并购律师。请根据以下重构任务书，起草一份完整的新合同文本。

【重构任务书摘要】
合同名称：{title}
甲方：{party_a} | 乙方：{party_b}
交易类型：{task_book.get('deal_type','未知')}
重构原则：{style['instruction']}

需修复的核心风险：
{risks_text}

需新增的条款：
{new_clauses_text}

需删除的条款：{'; '.join(task_book.get('clauses_to_delete', ['无']))}
付款结构重设：{task_book.get('payment_structure_redesign', '待定')}
退出机制：{task_book.get('exit_mechanism', '待定')}
特别注意事项：{task_book.get('special_notes', '无')}

【起草要求】
1. 使用标准中国商事合同格式（第一条、第二条……结构）
2. 每条款必须具体可执行，禁止空泛表述
3. 重点条款后附【重构说明】注释，说明与原合同的差异和保护逻辑（用括号标注）
4. 包含完整的：协议目的条款、权利义务条款、付款条款、尽调权条款、违约责任条款、解除条款、争议解决条款
5. 全文约2000-3500字
6. 直接输出合同正文（Markdown格式，用 # ## 标题层级），不要加前言说明"""


def _build_framework_prompt(task_book: dict, reconstruct_angle: str) -> str:
    """Step 3：起草防御性框架协议（代尽调意向书）。"""
    style = ANGLE_STYLE.get(reconstruct_angle, ANGLE_STYLE["条款公平偏中性"])
    party_a = task_book.get("party_a", "甲方")
    party_b = task_book.get("party_b", "乙方")
    deal_type = task_book.get("deal_type", "合作")

    return f"""你是一名中国顶级商业并购律师。请起草一份防御性框架协议，用作尽调意向书。

【背景】
甲方：{party_a} | 乙方：{party_b}
交易类型：{deal_type}
框架协议目标：在签署正式合同前，保障甲方的尽调权、信息权和退出权，同时不承担任何付款义务。
重构原则：{style['instruction']}

【特别注意的风险点】
- 付款结构：{task_book.get('payment_structure_redesign','待定')}
- 退出机制：{task_book.get('exit_mechanism','待定')}
- 特别事项：{task_book.get('special_notes','无')}

【框架协议核心要素（必须全部覆盖）】
1. 合作意向声明（非约束性）
2. 尽职调查权（全面：法律/财务/税务/技术/资产/合规）
3. 资料提供义务（乙方须在15个工作日内提供，真实性保证条款）
4. 零预付款原则（框架协议期间甲方不支付任何款项）
5. 非排他性条款（双方均可同步接触其他合作方）
6. 终止权（甲方可无理由终止，书面通知即生效）
7. 保密义务（双向，尽调材料不得外传）
8. 有效期（建议6个月，不自动续期）

【起草要求】
1. 用正式法律合同格式（第一条、第二条……）
2. 明确标注"本协议不构成具有法律约束力的交易承诺"
3. 全文约1200-1800字
4. Markdown格式输出，不要加前言说明"""


def _build_dd_checklist_prompt(task_book: dict) -> str:
    """Step 4：生成分类详尽的尽调清单。"""
    deal_type = task_book.get("deal_type", "并购/合作")
    risks = task_book.get("core_risks_to_fix", [])
    risk_text = "\n".join(f"- {r.get('original_problem','')}" for r in risks)

    return f"""你是一名中国顶级商业并购律师兼财务顾问。请生成一份详尽的尽职调查清单。

【背景】
交易类型：{deal_type}
本次审查发现的核心风险点：
{risk_text}

【清单要求】
请按以下六大类别生成尽调清单，每类不少于6项具体核查事项：

**第一类：法律尽调**
- 主体资格与权属文件
- 诉讼/仲裁/执行记录
- 标的资产的完整权利链条
- 重大合同审查

**第二类：财务与税务尽调**
- 财务报表及审计报告
- 税务合规与欠税核查
- 关联交易与资金占用

**第三类：标的资产/业务尽调**
- 核心资产的技术状态
- 许可证与资质有效性
- 经营数据与客户合同

**第四类：政策与合规尽调**
- 行业政策合规性
- 环保/安全/资质许可
- 政府关系与审批事项

**第五类：对方履约能力核查**
- 主体资信与实控人背景
- 近期经营状况与现金流
- 已有债务与担保情况

**第六类：其他专项核查**
- 针对本次交易特定风险的专项调查事项

【格式要求】
1. 每项核查事项必须明确：核查内容 + 所需文件/证据 + 风险提示
2. 全文约2000-3500字
3. Markdown格式，用 ## 分类标题，用有序列表编号每项
4. 结尾附"尽调优先级说明"，标注哪3项最关键"""


class ReconstructionEngine:
    """
    State 8: Qiaoxi 合同重构引擎

    四步串行：
      1. 深度消化 → 生成内部任务书（JSON）
      2. 新合同草案
      3. 框架协议
      4. 尽调清单
    """

    def __init__(self):
        self.llm_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    def _call_llm(self, prompt: str, step_name: str, use_json: bool = False, max_tokens: int = 4096) -> str:
        """通用 LLM 调用，含错误处理和重试。"""
        for attempt in range(2):
            try:
                logger.info(f"[重构] {step_name} — 尝试 {attempt+1}/2")
                t0 = time.time()
                kwargs = {
                    "model": DEEPSEEK_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.4,
                    "max_tokens": max_tokens,
                    "timeout": 180,
                }
                if use_json:
                    kwargs["response_format"] = {"type": "json_object"}
                response = self.llm_client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content or ""
                logger.info(f"[重构] {step_name} ✓ {time.time()-t0:.1f}s ({len(content)} chars)")
                return content
            except Exception as e:
                logger.error(f"[重构] {step_name} 异常: {e}")
                if attempt >= 1:
                    raise RuntimeError(f"{step_name} 调用失败: {e}")
                time.sleep(3)
        return ""

    def run(
        self,
        final_report: str,
        clause_tree: dict,
        legal_review: dict,
        audits: list,
        decision: dict,
        profile: dict,
        reconstruct_angle: str,
        progress_callback=None,
    ) -> dict:
        """
        主入口：执行四步重构生成

        progress_callback: fn(step: int, total: int, label: str)

        Returns:
            {
                "task_book": dict,          # 内部任务书（调试用）
                "contract_draft": str,      # 新合同草案 Markdown
                "framework_agreement": str, # 框架协议 Markdown
                "dd_checklist": str,        # 尽调清单 Markdown
                "reconstruct_angle": str,
            }
        """
        results = {}

        # ── Step 1: 深度消化，生成任务书 ──
        if progress_callback:
            progress_callback(1, 4, "精读审查报告，提炼重构任务书…")

        digest_prompt = _build_digest_prompt(
            final_report, clause_tree, legal_review,
            audits, decision, profile, reconstruct_angle
        )
        task_book_raw = self._call_llm(digest_prompt, "Step1-消化任务书", use_json=True, max_tokens=2048)
        try:
            task_book = json.loads(task_book_raw)
        except Exception:
            logger.warning("[重构] 任务书 JSON 解析失败，使用空模板")
            task_book = {
                "contract_title": "重构合同草案",
                "party_a": "甲方", "party_b": "乙方",
                "deal_type": "合作",
                "deal_complexity": "simple",
                "complexity_reason": "JSON解析失败，使用简单兜底",
                "files_to_generate": {"contract_draft": True, "framework_agreement": False, "dd_checklist": False},
                "core_risks_to_fix": [],
                "new_clauses_required": [],
                "clauses_to_delete": [],
                "payment_structure_redesign": "分阶段付款，确权先于付款",
                "exit_mechanism": "甲方享有无理由退出权",
                "special_notes": "",
            }
        results["task_book"] = task_book

        # ── 读取判定：哪些文件需要生成 ──
        files = task_book.get("files_to_generate", {"contract_draft": True, "framework_agreement": True, "dd_checklist": True})
        gen_contract = files.get("contract_draft", True)
        gen_framework = files.get("framework_agreement", False)
        gen_dd = files.get("dd_checklist", False)

        total_steps = 1 + (1 if gen_contract else 0) + (1 if gen_framework else 0) + (1 if gen_dd else 0)
        step_n = 1  # Step 1 已完成

        # ── Step 2: 新合同草案（始终生成）──
        if gen_contract:
            step_n += 1
            if progress_callback:
                progress_callback(step_n, total_steps, "起草新合同文本…")

            contract_prompt = _build_contract_prompt(task_book, reconstruct_angle, profile)
            results["contract_draft"] = self._call_llm(
                contract_prompt, "Step2-新合同草案", max_tokens=6000
            )
        else:
            results["contract_draft"] = ""

        # ── Step 3: 框架协议（条件生成）──
        if gen_framework:
            step_n += 1
            if progress_callback:
                progress_callback(step_n, total_steps, "起草防御性框架协议（代尽调意向书）…")

            framework_prompt = _build_framework_prompt(task_book, reconstruct_angle)
            results["framework_agreement"] = self._call_llm(
                framework_prompt, "Step3-框架协议", max_tokens=4096
            )
        else:
            results["framework_agreement"] = ""
            logger.info("[重构] DeepSeek 判定：本合同不需要框架协议")

        # ── Step 4: 尽调清单（条件生成）──
        if gen_dd:
            step_n += 1
            if progress_callback:
                progress_callback(step_n, total_steps, "生成尽职调查清单…")

            dd_prompt = _build_dd_checklist_prompt(task_book)
            results["dd_checklist"] = self._call_llm(
                dd_prompt, "Step4-尽调清单", max_tokens=6000
            )
        else:
            results["dd_checklist"] = ""
            logger.info("[重构] DeepSeek 判定：本合同不需要尽调清单")

        results["reconstruct_angle"] = reconstruct_angle
        results["files_generated"] = files
        logger.info(f"[重构] 全部完成 (合同={gen_contract}, 框架={gen_framework}, 尽调={gen_dd})")
        return results
