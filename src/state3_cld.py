"""
Qiaoxi Contract-Analyzer · State 3 商业模式提取与系统动力学建模

从 clause_tree 中提取:
- 资金流向节点
- 权力分配节点
- 时间约束节点
生成文本化因果回路图（CLD），标注增强回路（R）与调节回路（B）。
"""
import json
import logging
from openai import OpenAI
from src.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

logger = logging.getLogger(__name__)


class CLDBuilder:
    """
    State 3: 商业模式解构引擎

    从结构化合同 JSON 中提取商业模型，生成因果回路图描述。
    这是私董会（State 4）和推演引擎（State 5）的关键输入。
    """

    def __init__(self):
        self.llm_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    def build(self, clause_tree: dict, legal_review: dict | None = None) -> dict:
        """
        构建商业模型解构报告

        Args:
            clause_tree: State 1 输出的条款树（脱敏后）
            legal_review: State 2 乔曦初审报告（可选，用于交叉引用）

        Returns:
            cld_report: { "loops": [...], "key_variables": {...}, "summary": "..." }
        """
        clauses_text = json.dumps(clause_tree.get("clauses", [])[:40], ensure_ascii=False)

        # 风险点摘要（若有）
        risk_context = ""
        if legal_review and legal_review.get("risks"):
            high_risks = [r for r in legal_review["risks"] if r.get("risk_level") == "high"]
            risk_context = "\n".join([
                f"- {r.get('clause_id', '?')}: {r.get('description', '')[:100]}"
                for r in high_risks[:10]
            ])

        system_prompt = """你是商业模式系统动力学分析专家。你的任务是从商业合同中提取关键信息，构建因果回路图（Causal Loop Diagram）。

你需要识别：
1. 资金流向：谁付钱、付给谁、多少钱（量级）、何时付、什么条件下付
2. 权力分配：股权/控制权/公章/决策权/法人代表在谁手里、什么时候转移
3. 时间轴：签约→付款节点→交割节点→合同到期，各节点之间的顺序和间隔

输出严格的 JSON 结构。"""

        user_prompt = f"""请分析以下合同，提取商业模型的系统动力学结构。

【合同条款树】
{clauses_text}

【乔曦初审高风险项】
{risk_context if risk_context else "（无高风险项或初审未执行）"}

【输出格式（严格 JSON）】
{{
  "loops": [
    {{
      "id": "R1 或 B1",
      "type": "reinforcing（增强回路，描述正向循环放大效果） 或 balancing（调节回路，描述负反馈制约因素）",
      "description": "≤100字描述该回路的因果关系链",
      "variables_involved": ["变量A", "变量B"],
      "key_leverage_point": "该回路中哪个变量是潜在的杠杆点"
    }}
  ],
  "key_variables": {{
    "cashflow": ["描述所有资金流入流出节点及其触发条件"],
    "power": ["描述所有权力（股权/公章/决策/法人）的当前状态与转移条件"],
    "time": ["描述所有关键时间节点及其先后依赖关系"]
  }},
  "summary": "≤300字，用商业顾问的语言概述该合同的商业模式核心逻辑与结构性问题"
}}

注意事项：
- loops 至少输出 2 个回路（1个增强回路 R + 1个调节回路 B），至多 5 个
- 如果合同文本无法支撑某个维度的完整分析，在对应字段标注 "信息不足"
- 所有金额、公司名、人名为脱敏后的占位符，直接使用即可"""

        try:
            response = self.llm_client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.4,
                max_tokens=4096,
                response_format={"type": "json_object"},
            )
            result = json.loads(response.choices[0].message.content)
            logger.info(f"[CLD] 构建完成: 回路数={len(result.get('loops', []))}")
            return result
        except Exception as e:
            logger.error(f"[CLD] 构建失败: {e}")
            return {
                "loops": [],
                "key_variables": {"cashflow": ["分析失败"], "power": ["分析失败"], "time": ["分析失败"]},
                "summary": "商业模式解构失败: " + str(e),
                "error": str(e),
            }
