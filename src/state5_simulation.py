"""
Qiaoxi Contract-Analyzer · State 5 推演引擎 + 私董会辩论

核心约束：
- 推演引擎：纯 Python 确定性函数，禁止 LLM 生成推演结论
- 质询合成器：LLM 驱动，交叉比对六位评审员意见，标记共识/分歧
- 4 时间切片：[3, 6, 12, 36] 月
- 共识标记：>=4 人独立识别同一风险 → 高置信共识
- Minority View：1-2 人识别 → 单独标注
"""
import json
import logging
from openai import OpenAI
from src.config import (
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
    SIMULATION_TIMESLICES,
)
from src.state4_council import COUNCIL_ROLES

logger = logging.getLogger(__name__)


class SimulationEngine:
    """
    确定性推演引擎（纯 Python，禁止 LLM）

    基于 CLD 的因果回路，在 4 个时间切片上模拟关键变量的演化。
    每条回路贡献一个方向性信号（增强 / 调节），叠加得到各切片的风险状态。
    """

    def run(self, cld_report: dict, audits: list[dict], timeslices: list[int] | None = None) -> dict:
        """
        执行确定性推演

        Args:
            cld_report: State 3 输出的因果回路图
            audits: State 4 六位评审员审计输出
            timeslices: 时间切片列表，默认 [3, 6, 12, 36]

        Returns:
            {
                "snapshots": [
                    { "month": 3, "cashflow_state": "...", "power_state": "...", "risk_signals": [...] },
                    ...
                ],
                "trajectory": "稳定向好 / 逐渐恶化 / 波动 / 拐点在前",
                "key_turning_points": [...]
            }
        """
        if timeslices is None:
            timeslices = SIMULATION_TIMESLICES

        loops = cld_report.get("loops", [])
        key_vars = cld_report.get("key_variables", {})

        # 解析回路方向性
        r_count = sum(1 for l in loops if l.get("type", "").startswith("reinforcing"))
        b_count = sum(1 for l in loops if l.get("type", "").startswith("balancing"))
        total_loops = max(r_count + b_count, 1)

        # 赋权：增强回路推风险上行，调节回路推风险下行
        r_weight = r_count / total_loops * 0.6 + 0.2  # 增强回路正向权（0.2~0.8）
        b_weight = b_count / total_loops * 0.6 + 0.2  # 调节回路负向权（0.2~0.8）

        # 风险基线来源：六位评审员平均评分
        avg_risk = sum(a.get("risk_score", 3) for a in audits) / max(len(audits), 1) if audits else 3.0
        veto_count = sum(1 for a in audits if a.get("veto_triggered"))

        snapshots = []
        for m in timeslices:
            # 增强回路：随时间放大风险
            r_signal = avg_risk + (r_weight * m / 12.0)
            # 调节回路：随时间抑制风险
            b_signal = avg_risk - (b_weight * m / 24.0)

            # 风险合成信号（越接近 m 月，r 越占主导，b 在早期更强）
            combined = (r_signal * m / 36.0 + b_signal * (1 - m / 36.0)) if m <= 36 else r_signal
            risk_level = "high" if combined >= 4 else "medium" if combined >= 2.5 else "low"

            # VETO 加权：任一人否决，所有切片 risk_level 上调一级
            if veto_count > 0:
                risk_level = "high" if risk_level == "medium" else "medium" if risk_level == "low" else "high"

            # 现金流状态推演
            cashflows = key_vars.get("cashflow", [])
            cash_state = self._simulate_cashflow(cashflows, m, combined)

            # 权力状态推演
            power_items = key_vars.get("power", [])
            power_state = self._simulate_power(power_items, m, combined)

            # 风险信号
            signals = []
            if combined >= 3.5:
                signals.append(f"M{m}: 综合风险信号强（{combined:.1f}/5），建议提前应对")
            if veto_count > 0:
                signals.append(f"M{m}: {veto_count}位董事否决，结构性问题需根本性改写")
            if r_count > b_count and m >= 12:
                signals.append(f"M{m}: 增强回路主导，风险随时间放大")
            if b_count > r_count:
                signals.append(f"M{m}: 调节回路主导，风险有自我修正趋势")
            if not signals:
                signals.append(f"M{m}: 无显著风险信号")

            snapshots.append({
                "month": m,
                "risk_level": risk_level,
                "combined_signal": round(combined, 2),
                "cashflow_state": cash_state,
                "power_state": power_state,
                "risk_signals": signals,
            })

        # 推演轨迹
        first = snapshots[0]["risk_level"] if snapshots else "low"
        last = snapshots[-1]["risk_level"] if snapshots else "low"
        if first == "low" and last == "high":
            trajectory = "逐渐恶化"
        elif first == "high" and last == "low":
            trajectory = "稳定向好"
        elif all(s["risk_level"] == snapshots[0]["risk_level"] for s in snapshots):
            trajectory = "风险稳定"
        else:
            trajectory = "波动，拐点在前"

        key_turning = []
        for i in range(1, len(snapshots)):
            if snapshots[i]["risk_level"] != snapshots[i - 1]["risk_level"]:
                key_turning.append(
                    f"M{snapshots[i-1]['month']}→M{snapshots[i]['month']}: "
                    f"{snapshots[i-1]['risk_level']}→{snapshots[i]['risk_level']}"
                )

        return {
            "snapshots": snapshots,
            "trajectory": trajectory,
            "key_turning_points": key_turning,
            "engine_version": "deterministic_python_v1.0",
        }

    def _simulate_cashflow(self, cash_vars: list, month: int, risk_signal: float) -> str:
        """现金流状态推演（确定性）"""
        if not cash_vars or all("信息不足" in c for c in cash_vars):
            return "数据不足，无法推演"

        node_count = len([c for c in cash_vars if "信息不足" not in c])

        if risk_signal >= 4:
            return f"M{month}: 资金流风险极高，建议立即设置共管账户或寻求对等担保。已识别 {node_count} 个资金节点。"
        elif risk_signal >= 2.5:
            return f"M{month}: 存在资金-权利时间差，建议关注 {node_count} 个节点的确权节奏。"
        else:
            return f"M{month}: 现金流结构相对健康，{node_count} 个节点暂无明显风险。"

    def _simulate_power(self, power_vars: list, month: int, risk_signal: float) -> str:
        """权力状态推演（确定性）"""
        if not power_vars or all("信息不足" in p for p in power_vars):
            return "数据不足，无法推演"

        node_count = len([p for p in power_vars if "信息不足" not in p])

        if risk_signal >= 4:
            return f"M{month}: 控制权真空风险极高，{node_count} 个权力节点需立即锁定交割安排。"
        elif risk_signal >= 2.5:
            return f"M{month}: 存在权力过渡期风险，建议尽快完成 {node_count} 个节点的权属确认。"
        else:
            return f"M{month}: 权力结构过渡平稳，{node_count} 个节点已规划明确。"


class DebateSynthesizer:
    """
    私董会辩论质询合成器（LLM 驱动）

    功能：
    - 六人意见交叉比对
    - 共识标记（>=4人同一风险 → 高置信）
    - Minority View 标注
    - 生成《私董会研讨纪要》
    """

    def __init__(self):
        self.llm_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    def synthesize(self, audits: list[dict], simulation: dict, cld_report: dict) -> dict:
        """
        生成私董会研讨纪要

        Returns:
            {
                "consensus_items": [...],
                "disputed_items": [...],
                "minority_views": [...],
                "debate_minutes": "文本化会议纪要"
            }
        """
        # 确定性共识（已在 State 4 计算，此处复用并增强）
        from collections import Counter
        all_targets = []
        for a in audits:
            all_targets.extend(a.get("target_clauses", []))
        counter = Counter(all_targets)

        high_conf = [clause for clause, count in counter.most_common() if count >= 4]
        minority_clauses = [clause for clause, count in counter.items() if 1 <= count <= 2]

        # 将少数意见转为字典列表，与 app.py State 7 报告生成期望的结构一致
        minority_views = []
        for clause in minority_clauses:
            who = [
                COUNCIL_ROLES.get(a.get("auditor_role", ""), {}).get("name", "?")
                for a in audits if clause in a.get("target_clauses", [])
            ]
            minority_views.append({"clause_id": clause, "identified_by": who, "count": len(who)})

        # LLM 质询合成：生成纪要
        try:
            summary_text = self._llm_synthesize(audits, simulation, cld_report, high_conf, minority_clauses)
        except Exception as e:
            logger.warning(f"[辩论合成] LLM 生成失败，使用回退文本: {e}")
            summary_text = self._fallback_debate_text(audits, simulation, high_conf, minority_clauses)

        return {
            "consensus_items": high_conf,
            "minority_views": minority_views,
            "simulation_trajectory": simulation.get("trajectory", "未知"),
            "debate_minutes": summary_text,
            "consensus_level": "高置信" if len(high_conf) >= 3 else "中等共识" if len(high_conf) >= 1 else "分散",
        }

    def _llm_synthesize(
        self,
        audits: list,
        simulation: dict,
        cld_report: dict,
        high_conf: list,
        minority_list: list,
    ) -> str:
        """调用 LLM 生成辩论纪要"""
        # 精简输入
        audit_briefs = []
        for a in audits:
            audit_briefs.append({
                "role": a.get("auditor_role", "?"),
                "summary": a.get("audit_summary", "")[:200],
                "score": a.get("risk_score", 3),
                "veto": a.get("veto_triggered", False),
            })

        prompt = f"""你是私董会主持人。以下是一次合同审查私董会的会议记录。

【六位评审员审查摘要】
{json.dumps(audit_briefs, ensure_ascii=False, indent=2)}

【推演结果】
时间轨迹: {simulation.get('trajectory', '未知')}
快照摘要: {json.dumps([{{'month':s['month'], 'risk':s['risk_level']}} for s in simulation.get('snapshots', [])], ensure_ascii=False)}

【共识风险（>=4人识别）】
{high_conf if high_conf else '无'}
【少数观点（1-2人识别）】
{minority_list if minority_list else '无'}

请生成一段 ≤500 字的《私董会研讨纪要》，包括：
1. 整体风险评估（一句话结论）
2. 核心共识（高置信风险）
3. 主要分歧（少数观点）
4. 推演结论（4 时间切片趋势）
5. 建议行动方向

语言锋锐、结论先行、商业顾问口吻。"""

        resp = self.llm_client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是私董会主持人，输出格式为结构化中文纪要，≤500字。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            max_tokens=1024,
        )
        return resp.choices[0].message.content or ""

    def _fallback_debate_text(
        self,
        audits: list,
        simulation: dict,
        high_conf: list,
        minority_list: list,
    ) -> str:
        """LLM 不可用时的确定性回退纪要"""
        veto_count = sum(1 for a in audits if a.get("veto_triggered"))
        avg_score = sum(a.get("risk_score", 3) for a in audits) / max(len(audits), 1)

        lines = [
            "=== 私董会研讨纪要（自动生成） ===",
            f"整体风险评分: {avg_score:.1f}/5",
            f"否决数: {veto_count}/6",
            f"推演轨迹: {simulation.get('trajectory', '未知')}",
        ]
        if veto_count > 0:
            veto_names = [a.get("auditor_role", "?") for a in audits if a.get("veto_triggered")]
            lines.append(f"⚠️ 否决触发成员: {', '.join(veto_names)}")
        if high_conf:
            lines.append(f"高置信共识风险: {', '.join(high_conf)}")
        if minority_list:
            lines.append(f"少数观点标记: {', '.join(minority_list)}")
        return "\n".join(lines)
