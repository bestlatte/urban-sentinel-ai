"""A4 決策留痕（記錄層，SPEC-M4A）+ 解釋生成層（SPEC-M4B）。

記錄層：純確定性、零 LLM、可單元測試。
生成層：需要 LLM（Phase 5.2 實作）。

參考 spec：`.kiro/specs/m4-explanation-chain-and-orchestrator/SPEC-M4A_解釋鏈_記錄層.md`、
`SPEC-M4B_解釋鏈_生成層.md`。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Literal, get_args

_TZ_TAIPEI = timezone(timedelta(hours=8))

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

_VALID_ACTOR_CODES = set(get_args(ActorCode))
_VALID_TOOL_NAMES = set(get_args(ToolName))
_VALID_REASON_CODES = {
    "CLOSED", "CAPACITY_INSUFFICIENT", "NOT_IN_ALTERNATIVES",
    "NOT_DIRECTLY_INTERSECTING", "DOWNSTREAM_ONLY", "FLOW_DIRECTION_MISMATCH",
    "SATURATED", "UNKNOWN_SEGMENT", "MISSING_TRAFFIC_SNAPSHOT",
}
_VALID_FINDING_CODES = {
    "SATURATED_BUT_RETAINED", "CAPACITY_OVERLOAD", "PREDICTED_COLLAPSE",
    "CASCADE_RISK", "SCENARIO_COMPARED",
}

# 合法路段代碼（從 road_network_topology.json 的 15 條路段）
_VALID_SEGMENT_IDS: set[str] = {f"RD_TPE_{i:03d}" for i in range(1, 16)}

_TRIGGERED_BY_PATTERN = re.compile(r"^§\d+(-[A-Za-z])?$")


@dataclass
class TraceMeta:
    trace_id: str
    triggered_by: list[str]
    opened_at: datetime
    _seq_counter: int = field(default=0, repr=False)


@dataclass
class ExcludedItem:
    segment_id: str
    reason_code: str
    reason_detail: str | None = None


@dataclass
class Finding:
    finding_code: str
    segment_ids: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    detail: str | None = None


@dataclass
class TraceStep:
    trace_id: str
    sequence_no: int
    agent: str
    action: str
    input: dict
    output: dict
    parent_seq: int | None = None
    tool: str | None = None
    sop_ref: str | None = None
    excluded: list[ExcludedItem] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    subject_segment_ids: list[str] = field(default_factory=list)
    duration_ms: int | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=_TZ_TAIPEI))


_TRACES: dict[str, TraceMeta] = {}
_STEPS: dict[str, list[TraceStep]] = {}


def _validate_segment_id(seg_id: str) -> None:
    if seg_id not in _VALID_SEGMENT_IDS:
        raise ValueError(f"非法路段代碼: {seg_id}")


def open_trace(trace_id: str, triggered_by: list[str]) -> None:
    """前置：trace_id 非空且未註冊；triggered_by >=1 且每項格式合法。
    違反或重複註冊拋 ValueError。
    """
    if not trace_id:
        raise ValueError("trace_id 不得為空")
    if trace_id in _TRACES:
        raise ValueError(f"trace_id 已註冊: {trace_id}")
    if not triggered_by or len(triggered_by) == 0:
        raise ValueError("triggered_by 至少需一項")
    for item in triggered_by:
        if not _TRIGGERED_BY_PATTERN.match(item):
            raise ValueError(f"triggered_by 項目格式不合法: {item}")

    _TRACES[trace_id] = TraceMeta(
        trace_id=trace_id,
        triggered_by=triggered_by,
        opened_at=datetime.now(tz=_TZ_TAIPEI),
    )
    _STEPS[trace_id] = []


def record_step(
    trace_id: str,
    agent: str,
    action: str,
    input: dict,
    output: dict,
    parent_seq: int | None = None,
    tool: str | None = None,
    sop_ref: str | None = None,
    excluded: list[ExcludedItem] | None = None,
    findings: list[Finding] | None = None,
    subject_segment_ids: list[str] | None = None,
    duration_ms: int | None = None,
) -> int:
    """驗證 → 取序號 → 指派 timestamp → 寫入 → 回傳序號。"""
    excluded = excluded or []
    findings = findings or []
    subject_segment_ids = subject_segment_ids or []

    # 驗證 trace 已註冊
    if trace_id not in _TRACES:
        raise ValueError(f"trace_id 未註冊: {trace_id}")

    # 驗證 agent
    if agent not in _VALID_ACTOR_CODES:
        raise ValueError(f"agent 不在 ActorCode: {agent}")

    # 驗證 tool
    if tool is not None and tool not in _VALID_TOOL_NAMES:
        raise ValueError(f"tool 不在 ToolName: {tool}")

    # 驗證 action 非空
    if not action:
        raise ValueError("action 不得為空")

    # 驗證 parent_seq
    if parent_seq is not None:
        existing_seqs = {s.sequence_no for s in _STEPS[trace_id]}
        if parent_seq not in existing_seqs:
            raise ValueError(f"parent_seq {parent_seq} 不存在於 trace {trace_id}")

    # 驗證 sop_ref 格式
    if sop_ref is not None:
        if not re.match(r"^§\d+(-[a-z])?$", sop_ref):
            raise ValueError(f"sop_ref 格式不合法: {sop_ref}")

    # 驗證 excluded 的路段代碼和 reason_code
    for exc in excluded:
        _validate_segment_id(exc.segment_id)
        if exc.reason_code not in _VALID_REASON_CODES:
            raise ValueError(f"reason_code 不在九值列舉: {exc.reason_code}")

    # 驗證 findings 的 segment_ids 和 finding_code
    for f in findings:
        if f.finding_code not in _VALID_FINDING_CODES:
            raise ValueError(f"finding_code 不在五值列舉: {f.finding_code}")
        for seg_id in f.segment_ids:
            _validate_segment_id(seg_id)

    # 驗證 subject_segment_ids
    for seg_id in subject_segment_ids:
        _validate_segment_id(seg_id)

    # 驗證 duration_ms
    if duration_ms is not None and duration_ms < 0:
        raise ValueError(f"duration_ms 不得為負: {duration_ms}")

    # 取序號（原子遞增）
    meta = _TRACES[trace_id]
    meta._seq_counter += 1
    seq_no = meta._seq_counter

    step = TraceStep(
        trace_id=trace_id,
        sequence_no=seq_no,
        agent=agent,
        action=action,
        input=input,
        output=output,
        parent_seq=parent_seq,
        tool=tool,
        sop_ref=sop_ref,
        excluded=excluded,
        findings=findings,
        subject_segment_ids=subject_segment_ids,
        duration_ms=duration_ms,
    )
    _STEPS[trace_id].append(step)
    return seq_no


def get_steps(trace_id: str) -> list[TraceStep]:
    """取得 trace 的所有步驟（供 M4B 生成層使用）。"""
    return _STEPS.get(trace_id, [])


def get_trace_meta(trace_id: str) -> TraceMeta | None:
    """取得 trace 的 meta 資訊。"""
    return _TRACES.get(trace_id)


# ---------------------------------------------------------------------------
# M4B 解釋生成層
# ---------------------------------------------------------------------------

# 路段名稱映射（啟動時從 road_network_topology.json 建立）
_SEGMENT_NAME_MAP: dict[str, str] = {}  # name → segment_id


def _ensure_segment_name_map() -> None:
    """延遲載入路段名稱映射。"""
    if _SEGMENT_NAME_MAP:
        return
    from src.loaders import load_data
    bundle = load_data()
    for seg in bundle.road_network:
        _SEGMENT_NAME_MAP[seg.name] = seg.segment_id


def resolve_segment_id(text: str) -> str | Literal["AMBIGUOUS", "NOT_FOUND"]:
    """子字串比對，最長匹配優先，僅處理路段代碼。

    演算法：取全部路段 name → 子字串比對 → 恰一命中回 segment_id；
    零命中回 NOT_FOUND；多命中採最長匹配優先，最長仍並列回 AMBIGUOUS。
    """
    _ensure_segment_name_map()

    matches: list[tuple[str, str]] = []  # (name, segment_id)
    for name, seg_id in _SEGMENT_NAME_MAP.items():
        if name in text:
            matches.append((name, seg_id))

    if not matches:
        return "NOT_FOUND"

    # 最長匹配優先
    max_len = max(len(name) for name, _ in matches)
    longest_matches = [(name, seg_id) for name, seg_id in matches if len(name) == max_len]

    if len(longest_matches) == 1:
        return longest_matches[0][1]

    return "AMBIGUOUS"


# 報告生成快取（冪等）
_EXPLANATION_CACHE: dict[str, str] = {}


def generate_report_explanation(trace_id: str) -> str:
    """冪等：快取命中直接回傳。trace 底下無 TraceStep 時拋 ValueError。
    LLM 失敗時向呼叫端拋例外，不得回傳部分內容偽裝成功。
    """
    if trace_id in _EXPLANATION_CACHE:
        return _EXPLANATION_CACHE[trace_id]

    steps = get_steps(trace_id)
    if not steps:
        raise ValueError(f"trace {trace_id} 底下無 TraceStep，無法生成說明")

    meta = get_trace_meta(trace_id)

    # 組裝給 LLM 的結構化輸入
    import json
    import os

    steps_data = []
    for s in sorted(steps, key=lambda x: x.sequence_no):
        step_dict = {
            "sequence_no": s.sequence_no,
            "agent": s.agent,
            "action": s.action,
            "tool": s.tool,
            "sop_ref": s.sop_ref,
            "subject_segment_ids": s.subject_segment_ids,
            "excluded": [{"segment_id": e.segment_id, "reason_code": e.reason_code, "detail": e.reason_detail} for e in s.excluded],
            "findings": [{"finding_code": f.finding_code, "segment_ids": f.segment_ids} for f in s.findings],
        }
        steps_data.append(step_dict)

    use_bedrock = os.getenv("USE_BEDROCK", "true").lower() == "true"

    if not use_bedrock:
        # 保底模式：不呼叫 LLM，拋例外讓呼叫端降級
        raise RuntimeError("USE_BEDROCK=false，無法生成報告說明（LLM 不可用）")

    # TODO(Kiro): Phase 7 完成 Agent 後接入 Bedrock LLM 呼叫
    # 目前暫時拋例外（等同 LLM 不可用）
    raise RuntimeError("LLM 呼叫尚未實作，請等待 Phase 7 完成")


def answer_trace_query(trace_id: str, question: str) -> str:
    """回溯追問。resolve_segment_id 為 NOT_FOUND/AMBIGUOUS 時回固定文字、不呼叫LLM；
    命中為空時回「此路段未列入本次判斷」、不呼叫LLM；LLM失敗時降級顯示原始紀錄
    （永不沉默）。
    """
    import json
    import os

    # Step 1: 解析路段
    resolved = resolve_segment_id(question)

    if resolved == "NOT_FOUND":
        return "無法識別問題中提及的路段，請確認路段名稱"
    if resolved == "AMBIGUOUS":
        return "提及的路段名稱有多種可能，請提供更明確的路段全名"

    target_segment_id = resolved

    # Step 2: 篩選同 trace 紀錄
    steps = get_steps(trace_id)
    matched_steps: list[TraceStep] = []
    for step in steps:
        if target_segment_id in step.subject_segment_ids:
            matched_steps.append(step)
            continue
        if any(e.segment_id == target_segment_id for e in step.excluded):
            matched_steps.append(step)
            continue
        if any(target_segment_id in f.segment_ids for f in step.findings):
            matched_steps.append(step)
            continue

    # Step 3: 命中為空
    if not matched_steps:
        return "此路段未列入本次判斷"

    # Step 4: 命中非空 → 呼叫 LLM（或降級）
    use_bedrock = os.getenv("USE_BEDROCK", "true").lower() == "true"

    # 組裝原始紀錄
    records_data = []
    for s in matched_steps:
        records_data.append({
            "sequence_no": s.sequence_no,
            "agent": s.agent,
            "action": s.action,
            "tool": s.tool,
            "sop_ref": s.sop_ref,
            "excluded": [{"segment_id": e.segment_id, "reason_code": e.reason_code, "detail": e.reason_detail} for e in s.excluded],
            "findings": [{"finding_code": f.finding_code, "segment_ids": f.segment_ids} for f in s.findings],
        })

    if not use_bedrock:
        # 降級：顯示原始紀錄
        return f"系統暫時無法生成說明，相關原始紀錄如下：\n{json.dumps(records_data, ensure_ascii=False, indent=2)}"

    try:
        # TODO(Kiro): Phase 7 接入真正的 LLM 呼叫
        # 目前退化到降級行為
        return f"系統暫時無法生成說明，相關原始紀錄如下：\n{json.dumps(records_data, ensure_ascii=False, indent=2)}"
    except Exception:
        return f"系統暫時無法生成說明，相關原始紀錄如下：\n{json.dumps(records_data, ensure_ascii=False, indent=2)}"


def reset_traces() -> None:
    """測試輔助：清空所有 trace 和快取。"""
    _TRACES.clear()
    _STEPS.clear()
    _EXPLANATION_CACHE.clear()
