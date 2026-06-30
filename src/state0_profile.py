"""
Qiaoxi Contract-Analyzer · State 0 画像采集

零开放输入：仅封闭式点选，textarea 禁止渲染。
2轮选择题：战略层 Q1-Q3 → 战术层 Q4-Q6，统一锋锐模态。
"""
from typing import Optional
import json
from datetime import datetime


# ─── State 0-B：战略层画像（Q1-Q3）───

STRATEGIC_QUESTIONS = [
    {
        "id": "Q1",
        "header": "核心利益权重",
        "question": "在本次交易中，以下哪个维度是您最看重的？",
        "field": "interest_weights",
        "type": "weight_allocation",
        "options": [
            {"label": "控制权（股权/公章/决策权）", "value": "control"},
            {"label": "现金流（回款速度/利润率）", "value": "cashflow"},
            {"label": "税务优化", "value": "tax"},
            {"label": "时间效率（快速交割/退出）", "value": "time"},
        ],
        "instruction": "请为以下 4 个维度分配权重（总和为 1.0）",
    },
    {
        "id": "Q2",
        "header": "历史创伤标签",
        "question": "您过去在商业合作中遭遇过哪些问题？（最多选3项）",
        "field": "trauma_tags",
        "type": "multi_select",
        "max_items": 3,
        "options": [
            {"label": "先付款后无法确权", "value": "payment_no_title"},
            {"label": "隐藏负债/或有债务", "value": "hidden_liability"},
            {"label": "公章/证照被劫持", "value": "seal_hijack"},
            {"label": "对方违约成本极低", "value": "asymmetric_default"},
            {"label": "税务炸弹（历史欠税/偷税）", "value": "tax_bomb"},
        ],
    },
    {
        "id": "Q3",
        "header": "核心焦虑点",
        "question": "当前这笔交易，您最大的担忧是什么？",
        "field": "anxiety_focus",
        "type": "single_select",
        "options": [
            {"label": "标的真实性存疑", "value": "authenticity"},
            {"label": "资金出去回不来", "value": "funds"},
            {"label": "税务合规风险", "value": "tax"},
            {"label": "交割后失控", "value": "control"},
            {"label": "退出路径不清晰", "value": "exit"},
            {"label": "对方合规/资质存疑", "value": "compliance"},
        ],
    },
]

# ─── State 0-C：战术层画像（Q4-Q6）───

TACTICAL_QUESTIONS = [
    {
        "id": "Q4",
        "header": "风险偏好",
        "question": "您对本次交易的风险承受能力是？",
        "field": "risk_appetite",
        "type": "single_select",
        "options": [
            {"label": "保守——宁愿不赚，不能亏", "value": "conservative"},
            {"label": "适中——接受可控风险换取合理回报", "value": "moderate"},
            {"label": "激进——高回报优先，愿承担显著风险", "value": "aggressive"},
        ],
    },
    {
        "id": "Q5",
        "header": "最大损失容忍度 + 谈判地位 + 替代方案",
        "question": "请选择最符合您当前处境的描述：",
        "field": "multi_field",
        "type": "compound",
        "sub_fields": [
            {
                "id": "max_loss_pct",
                "header": "最大可接受损失",
                "question": "您能承受的最大损失占净资产的比例？",
                "type": "single_select",
                "options": [
                    {"label": "不超过 5%", "value": 0.05},
                    {"label": "不超过 15%", "value": 0.15},
                    {"label": "不超过 30%", "value": 0.30},
                ],
            },
            {
                "id": "position",
                "header": "谈判地位",
                "question": "您在本交易中的谈判地位？",
                "type": "single_select",
                "options": [
                    {"label": "买家强势（有多个替代标的）", "value": "buyer_strong"},
                    {"label": "买家弱势（标的稀缺/急需）", "value": "buyer_weak"},
                    {"label": "双方均势", "value": "equal"},
                    {"label": "我是卖方", "value": "seller"},
                    {"label": "合作方/共建方", "value": "cooperator"},
                ],
            },
            {
                "id": "batna_strength",
                "header": "替代方案(BATNA)",
                "question": "如果此交易失败，您的替代方案？",
                "type": "single_select",
                "options": [
                    {"label": "有明确的替代标的/方案", "value": "strong"},
                    {"label": "有但不理想", "value": "weak"},
                    {"label": "没有替代方案", "value": "none"},
                ],
            },
        ],
    },
    {
        "id": "Q6",
        "header": "可妥协维度 + 绝对底线",
        "question": "请选择可妥协维度与绝对不可退让的底线：",
        "field": "multi_field",
        "type": "compound",
        "sub_fields": [
            {
                "id": "compromise_dims",
                "header": "可妥协维度（最多3项）",
                "question": "在哪些方面您可以做出让步？",
                "type": "multi_select",
                "max_items": 3,
                "options": [
                    {"label": "价格/对价金额", "value": "price"},
                    {"label": "付款节奏/时间表", "value": "schedule"},
                    {"label": "治理结构（董事会/表决权）", "value": "governance"},
                    {"label": "交易范围（缩减标的）", "value": "scope"},
                ],
            },
            {
                "id": "hard_lines",
                "header": "绝对底线（最多3项）",
                "question": "哪些条件是您绝不让步的？",
                "type": "multi_select",
                "max_items": 3,
                "options": [
                    {"label": "禁止先付款后确权", "value": "no_prepayment_without_guarantee"},
                    {"label": "财务/税务控制权不可转让", "value": "fiscal_control_untransferable"},
                    {"label": "不接受单方核弹级违约责任", "value": "no_unilateral_nuke"},
                ],
            },
        ],
    },
]

# 退出选项（每道题的最后一个选项，固定不变）
EXIT_OPTION = "以上情况均不符合，我需要人工协助"


def build_client_profile(
    basic_info: dict,
    strategic_answers: dict,
    tactical_answers: dict,
) -> dict:
    """
    将 State 0-B 和 0-C 的封闭式点选结果硬编码写入 client_profile.json。
    不经 LLM 语义二次解读。
    """
    return {
        "client_id": f"QIAOXI-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "upload_timestamp": datetime.now().isoformat(),
        "basic_info": basic_info,
        "strategic_layer": {
            "interest_weights": strategic_answers.get("interest_weights", {
                "control": 0.4, "cashflow": 0.3, "tax": 0.15, "time": 0.15
            }),
            "trauma_tags": strategic_answers.get("trauma_tags", []),
            "anxiety_focus": strategic_answers.get("anxiety_focus", ""),
        },
        "tactical_layer": {
            "risk_appetite": tactical_answers.get("risk_appetite", "moderate"),
            "max_loss_pct": tactical_answers.get("max_loss_pct", 0.15),
            "position": tactical_answers.get("position", "equal"),
            "batna_strength": tactical_answers.get("batna_strength", "weak"),
            "compromise_dims": tactical_answers.get("compromise_dims", []),
            "hard_lines": tactical_answers.get("hard_lines", []),
        },
        "system_flags": {
            "open_input_used": False,  # 硬编码 false
            "handoff_triggered": False,
            "confidence_score": 1.0,   # 初始满分，后续 State 可下调
        },
    }
