"""
Qiaoxi Contract-Analyzer · FSM 状态机核心模块

State 0 → State 1 → State 2 → State 3 → State 4 → State 5 → State 6 → State 7 → State 8
每个状态 transitions 穷举，HANDOFF 条件明确。
"""
from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class State(str, Enum):
    """Qiaoxi Pipeline 九大状态"""
    S0_PROFILE = "0_profile"                    # 画像校准与接收
    S1_PARSE = "1_parse"                        # 文档解析与结构化
    S2_LEGAL_REVIEW = "2_legal_review"          # 乔曦初审 + 法规RAG
    S3_CLD = "3_cld"                            # 商业模式提取与系统动力学建模
    S4_COUNCIL_ROUND1 = "4_council_r1"          # 私董会第一轮（六位评审员串行）
    S5_COUNCIL_ROUND2 = "5_council_r2"          # 私董会第二轮（推演与辩论）
    S6_DECISION = "6_decision"                  # 李超逸决策
    S7_REPORT_STANDARD = "7_report_standard"    # 报告生成（标准版）
    S8_REPORT_ADVANCED = "8_report_advanced"    # 完整重构（高级版）
    TERMINATED = "terminated"                   # 流程终止
    HANDOFF = "handoff"                         # 转人工


# State 转换规则
TRANSITIONS: Dict[State, list[State]] = {
    State.S0_PROFILE:        [State.S1_PARSE, State.TERMINATED, State.HANDOFF],
    State.S1_PARSE:          [State.S2_LEGAL_REVIEW, State.HANDOFF],
    State.S2_LEGAL_REVIEW:   [State.S3_CLD, State.HANDOFF],
    State.S3_CLD:            [State.S4_COUNCIL_ROUND1, State.HANDOFF],
    State.S4_COUNCIL_ROUND1: [State.S5_COUNCIL_ROUND2, State.HANDOFF],
    State.S5_COUNCIL_ROUND2: [State.S6_DECISION, State.HANDOFF],
    State.S6_DECISION:       [State.S7_REPORT_STANDARD, State.HANDOFF],
    State.S7_REPORT_STANDARD:[State.S8_REPORT_ADVANCED, State.TERMINATED, State.HANDOFF],
    State.S8_REPORT_ADVANCED:[State.TERMINATED, State.HANDOFF],
    State.TERMINATED:        [],
    State.HANDOFF:           [State.S0_PROFILE, State.TERMINATED],  # RESUME 或 ABORT
}


@dataclass
class PipelineContext:
    """贯穿 State 0-8 的上下文载体"""
    state: State = State.S0_PROFILE
    client_profile: Optional[Dict[str, Any]] = field(default=None)
    contract_raw: Optional[str] = field(default=None)
    clause_tree: Optional[Dict[str, Any]] = field(default=None)
    jo_legal_review: Optional[Dict[str, Any]] = field(default=None)
    cld_report: Optional[str] = field(default=None)
    private_board_audits: Optional[list[Dict[str, Any]]] = field(default=None)
    simulation_snapshot: Optional[Dict[str, Any]] = field(default=None)
    decision_order: Optional[Dict[str, Any]] = field(default=None)
    final_report: Optional[str] = field(default=None)
    error: Optional[str] = field(default=None)
    handoff_reason: Optional[str] = field(default=None)

    def transition_to(self, target: State) -> bool:
        """执行状态转换。返回 False 表示非法转换。"""
        if target not in TRANSITIONS.get(self.state, []):
            logger.error(f"非法转换: {self.state} → {target}")
            return False
        logger.info(f"状态转换: {self.state} → {target}")
        self.state = target
        return True

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "has_profile": self.client_profile is not None,
            "has_contract": self.contract_raw is not None,
            "has_clause_tree": self.clause_tree is not None,
            "has_legal_review": self.jo_legal_review is not None,
            "has_cld": self.cld_report is not None,
            "has_audits": self.private_board_audits is not None,
            "has_simulation": self.simulation_snapshot is not None,
            "has_decision": self.decision_order is not None,
            "has_report": self.final_report is not None,
            "error": self.error,
            "handoff_reason": self.handoff_reason,
        }


class FSM:
    """有限状态机，驱动 Pipeline 流转"""

    def __init__(self):
        self.ctx = PipelineContext()

    @property
    def current_state(self) -> State:
        return self.ctx.state

    def next(self) -> bool:
        """自动推进到下一个合法 State。返回 False 表示需要人工干预。"""
        allowed = TRANSITIONS.get(self.ctx.state, [])
        if not allowed:
            logger.info(f"状态 {self.ctx.state} 无可用转换，Pipeline 结束")
            return False
        # 优先取第一个非 HANDOFF/Terminated 的 state
        for target in allowed:
            if target not in (State.HANDOFF, State.TERMINATED):
                return self.ctx.transition_to(target)
        return False

    def handoff(self, reason: str) -> bool:
        """触发转人工"""
        self.ctx.handoff_reason = reason
        return self.ctx.transition_to(State.HANDOFF)

    def terminate(self) -> bool:
        """正常终止"""
        return self.ctx.transition_to(State.TERMINATED)

    def reset(self):
        """重置 Pipeline"""
        self.ctx = PipelineContext()
