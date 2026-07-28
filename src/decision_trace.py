"""A4 決策留痕（記錄層，SPEC-M4A）+ 解釋生成層（SPEC-M4B）。

[2026-07-28總架構師補充：搭鷹架時的疏漏] `01-module-boundaries.md` 把 A4 歸在
`orchestrator.py` 底下，但 `open_trace`/`record_step`（SPEC-M4A）跟
`generate_report_explanation`/`answer_trace_query`/`resolve_segment_id`
（SPEC-M4B）這幾個函式一直沒有掛到任何檔案上。獨立成這個模組是業界通用做法——
單一職責分離，避免 `orchestrator.py` 變成什麼都塞的God Object（同一個理由，
K3/W1/W2 也都拆成獨立套件而不是塞進 agent.py）。`orchestrator.py` import 這裡的函式使用。

參考 spec：`.kiro/specs/m4-explanation-chain-and-orchestrator/SPEC-M4A_解釋鏈_記錄層.md`、
`SPEC-M4B_解釋鏈_生成層.md`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

ActorCode = Literal[
    "A1", "A2", "A3", "A4", "P5", "R1", "R2", "R3", "R4", "R5", "C1", "C2", "C3", "C4", "W1", "X1", "X2"
]
ToolName = Literal[
    "RAG_SEARCH",
    "GRAPH_BUILD",
    "UPSTREAM_JUDGE",
    "CANDIDATE_FILTER",
    "ROUTE_SELECT",
    "CALC_ETE",
    "COUNT_INTERSECTIONS",
    "CAPACITY_CHECK",
    "FORECAST_MODEL",
    "CASCADE_ANALYSIS",
    "FORMAT_REPORT",
    "TRANSLATE",
]


@dataclass
class TraceMeta:
    trace_id: str
    """格式 TR-YYYYMMDD-HHMM-serial，由 A2 生成（SPEC-00 §4）。"""
    triggered_by: list[str]
    opened_at: datetime


@dataclass
class ExcludedItem:
    segment_id: str
    reason_code: str
    """九值，SPEC-00 §3.3。"""
    reason_detail: str | None = None


@dataclass
class Finding:
    finding_code: str
    """五值，SPEC-00 §3.4。"""
    segment_ids: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    detail: str | None = None
    """禁止 LLM 生成（SPEC-M4A §3）。"""


@dataclass
class TraceStep:
    trace_id: str
    sequence_no: int
    """儲存層原子指派，從1遞增，呼叫端不可指定。"""
    agent: ActorCode
    action: str
    """保留值：SET_FLAG/PLAN/DISPATCH/AGENT_TIMEOUT/CYCLE_SUMMARY（SPEC-O1 §6）。"""
    input: dict
    output: dict
    parent_seq: int | None = None
    tool: ToolName | None = None
    sop_ref: str | None = None
    excluded: list[ExcludedItem] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    subject_segment_ids: list[str] = field(default_factory=list)
    duration_ms: int | None = None
    timestamp: datetime = field(default_factory=datetime.now)


_TRACES: dict[str, TraceMeta] = {}
_STEPS: dict[str, list[TraceStep]] = {}
"""行程內記憶體物件，單一行程假設（SPEC-M4A §2）。"""


def open_trace(trace_id: str, triggered_by: list[str]) -> None:
    """前置：trace_id 非空且未註冊；triggered_by >=1 且每項格式合法。
    違反或重複註冊拋 ValueError。
    """
    raise NotImplementedError("見 SPEC-M4A §4.1")


def record_step(
    trace_id: str,
    agent: ActorCode,
    action: str,
    input: dict,
    output: dict,
    parent_seq: int | None = None,
    tool: ToolName | None = None,
    sop_ref: str | None = None,
    excluded: list[ExcludedItem] | None = None,
    findings: list[Finding] | None = None,
    subject_segment_ids: list[str] | None = None,
    duration_ms: int | None = None,
) -> int:
    """驗證 → 取序號 → 指派 timestamp → 寫入 → 回傳序號。

    呼叫方是 orchestrator.py（A2），不是 R1-R5/A3/C1-C4 這些純函式模組自己呼叫
    ——那些模組完全不知道追蹤機制存在（SPEC-O1 §5 補註）。
    """
    raise NotImplementedError("見 SPEC-M4A §4.2，驗收測試表十條")


def resolve_segment_id(text: str) -> str | Literal["AMBIGUOUS", "NOT_FOUND"]:
    """子字串比對，最長匹配優先，僅處理路段代碼（不含站點，見 SPEC-M4B §2）。"""
    raise NotImplementedError("見 SPEC-M4B §2")


def generate_report_explanation(trace_id: str) -> str:
    """冪等：快取命中直接回傳。trace 底下無 TraceStep 時拋 ValueError。
    LLM 失敗時向呼叫端拋例外，不得回傳部分內容偽裝成功（SPEC-M4B §3）。
    """
    raise NotImplementedError("見 SPEC-M4B §3")


def answer_trace_query(trace_id: str, question: str) -> str:
    """回溯追問。resolve_segment_id 為 NOT_FOUND/AMBIGUOUS 時回固定文字、不呼叫LLM；
    命中為空時回「此路段未列入本次判斷」、不呼叫LLM；LLM失敗時降級顯示原始紀錄
    （永不沉默，見 SPEC-M4B §4）。
    """
    raise NotImplementedError("見 SPEC-M4B §4")
