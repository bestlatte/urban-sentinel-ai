"""A4 決策留痕（記錄層，SPEC-M4A）+ 解釋生成層（SPEC-M4B）。

記錄層：純確定性、零 LLM、可單元測試。
生成層：需要 LLM（Phase 5.2 實作）。

參考 spec：`.kiro/specs/m4-explanation-chain-and-orchestrator/SPEC-M4A_解釋鏈_記錄層.md`、
`SPEC-M4B_解釋鏈_生成層.md`。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Literal, get_args

logger = logging.getLogger(__name__)

_TZ_TAIPEI = timezone(timedelta(hours=8))

ActorCode = Literal[
    "A1", "A2", "A3", "A4", "P5", "R1", "R2", "R3", "R4", "R5", "C1", "C2", "C3", "C4", "W1", "X1", "X2"
]
# ToolName 的唯一定義處是 `src/models.py`（01-module-boundaries.md：全專案型別只在
# models.py 定義一次）。本檔原本自己複製了一份同值的 Literal，兩處各自維護會漂移——
# SPEC-00 §3.2 若增修工具名，只改一邊就會讓 record_step 的驗證與規劃器的白名單不一致。
# 這裡改為從 models 的 Enum 推導出驗證集合。
from src.models import ToolName  # noqa: E402  （放在常數區之後，維持原檔案結構）

_VALID_ACTOR_CODES = set(get_args(ActorCode))
_VALID_TOOL_NAMES = {t.value for t in ToolName}
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


_ACTOR_LABELS: dict[str, str] = {
    "A1": "事件分類",
    "A2": "編排決策",
    "A3": "時程估算",
    "A4": "決策留痕",
    "R1": "路網建圖",
    "R2": "上游判定",
    "R3": "候選篩選",
    "R4": "路線選擇",
    "R5": "路線輸出",
    "C1": "建議書生成",
    "C2": "號誌建議",
    "C3": "聯動建議",
    "C4": "多語通報",
    "P1": "感知查詢",
    "K3": "SOP 檢索",
    "W1": "情境推演",
}
"""ActorCode → 人話。前端決策軌跡時間軸顯示用。

放後端的理由跟 `_TASK_LABELS` 一樣：ActorCode 的新增總是跟後端流程一起發生，
標籤跟著它走才不會出現「後端加了新角色、畫面顯示 R7」這種漂移。
未知代碼一律原樣回傳（不猜），前端顯示代碼本身。
"""

_ACTION_LABELS: dict[str, str] = {
    "PLAN": "規劃工具序列",
    "SET_FLAG": "設定旗標",
    "TOOL_CALL": "呼叫工具",
    "CYCLE_SUMMARY": "週期總結",
}


def get_trace_view(trace_id: str) -> dict | None:
    """把決策軌跡整理成前端可直接渲染的結構。

    [2026-08-01 新增] 決策軌跡在此之前**只有 M4B 生成層讀得到**——`get_steps()`
    回傳的是 `TraceStep` dataclass（含巢狀 dataclass 與 datetime），沒有任何
    端點對外暴露，前端拿不到。所以 chatbot 回答「這個決策怎麼來的」時，只能
    給一段 LLM 生成的散文，看不到實際的步驟。

    F7「決策依據」分頁看起來像是在顯示軌跡，其實是前端自己從 WebSocket 的
    `task_update` 事件拼的活動紀錄——那是「發生了什麼」，不是「依據什麼判斷」，
    而且事件斷線就永久缺一塊。真正的軌跡一直在後端記憶體裡沒人看。

    回傳 None 表示該 trace 不存在（例如伺服器重啟過、或 trace_id 打錯）。
    """
    meta = _TRACES.get(trace_id)
    steps = _STEPS.get(trace_id)
    if meta is None or steps is None:
        return None

    return {
        "trace_id": trace_id,
        "triggered_by": list(meta.triggered_by),
        "opened_at": meta.opened_at.isoformat(),
        "steps": [_step_to_view(s) for s in sorted(steps, key=lambda x: x.sequence_no)],
    }


def _step_to_view(step: TraceStep) -> dict:
    """單一步驟轉成 JSON 相容 dict（datetime → ISO 字串、dataclass → dict）。"""
    return {
        "sequence_no": step.sequence_no,
        "agent": step.agent,
        "agent_label": _ACTOR_LABELS.get(step.agent, step.agent),
        "action": step.action,
        "action_label": _ACTION_LABELS.get(step.action, step.action),
        "tool": step.tool,
        "sop_ref": step.sop_ref,
        "subject_segment_ids": list(step.subject_segment_ids),
        "excluded": [
            {
                "segment_id": e.segment_id,
                "reason_code": e.reason_code,
                "detail": e.reason_detail,
            }
            for e in step.excluded
        ],
        "findings": [
            {
                "finding_code": f.finding_code,
                "segment_ids": list(f.segment_ids),
                "evidence": dict(f.evidence or {}),
                "detail": f.detail,
            }
            for f in step.findings
        ],
        # `output` 原樣帶出：它是後端寫進去的純量 dict（工具算出的數字），
        # 前端可以選擇顯示哪些欄位。`input` 不帶——裡面常含整包 classification
        # 與 batch，對畫面沒有價值只會灌大 payload。
        "output": _json_safe_dict(step.output),
        "duration_ms": step.duration_ms,
        "timestamp": step.timestamp.isoformat(),
    }


def _json_safe_dict(value: dict | None) -> dict:
    """`output` 裡若混進 Enum／datetime，直接丟給 JSONResponse 會炸。

    只做淺層轉換——`record_step` 的呼叫端寫進去的都是純量與短清單，
    沒有深層巢狀結構需要處理。
    """
    if not isinstance(value, dict):
        return {}

    def _coerce(v):
        if isinstance(v, datetime):
            return v.isoformat()
        if hasattr(v, "value") and not isinstance(v, (str, int, float, bool)):
            return v.value  # Enum
        if isinstance(v, (list, tuple)):
            return [_coerce(x) for x in v]
        if isinstance(v, dict):
            return {k: _coerce(x) for k, x in v.items()}
        return v

    return {k: _coerce(v) for k, v in value.items()}


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


M4B_SYSTEM_PROMPT = """你是交通指揮系統的說明文字生成器。你會收到一組結構化的決策紀錄。
規則：
1. 只能使用提供的紀錄中出現的資訊，不得添加任何未出現的細節。
2. 每一項結論都必須附上對應的 sop_ref。
3. 若紀錄中的欄位不足以回答問題，明確說明「紀錄中未包含此資訊」，不得推測。
4. 使用繁體中文，語氣正式、簡潔。

輸出格式（不影響上述四條規則的判斷，只規範呈現）：
- 全文不得超過 150 字。這段文字顯示在指揮中心側邊的對話框，寬度只有幾百像素。
- 直接回答，不要加標題。**不要**使用 `#` 標題、表格、水平線、emoji。
- 只使用 `**粗體**` 與 `-` 項目符號兩種語法，項目最多 3 條。
- 不要複述問題，不要寫「答案：」這類引導詞。"""
"""SPEC-M4B §5 提示詞契約，兩個生成函式共用。

規則一到四逐字對應規格，**不得增減**——這是 SPEC-00 鐵律①「LLM 只表達、不改寫」
在解釋鏈的落實：加規則可能讓 LLM 開始推論、減規則會讓它憑空補細節。

[2026-08-01] 底下另外加了「輸出格式」段落。它**不是第五條規則**，刻意與四條規則
分開列並註明「只規範呈現」——加的是版面約束，不碰「能不能推論、資料不足時怎麼辦」
這些語意規則，所以不牴觸上面那條「不得增減」。

加的原因是實測輸出長這樣：

    # 交通指揮決策說明

    **問題：** 延吉街為什麼不能走

    **答案：**
    ...

在 340px 寬的對話框裡，一個 H1 標題加上複述一次問題，已經佔掉整個可視範圍，
真正的答案要捲動才看得到。`prompts/advisor.txt` 與 `prompts/report.txt` 早就
各自有長度與格式約束，只有 M4B 這條路徑沒有——它是最後一個會吐出公文體長文的
生成點。
"""


def _invoke_m4b_llm(user_message: str) -> str:
    """M4B 的 LLM 呼叫。失敗時拋例外，由各函式依 SPEC-M4B 的失敗處理決定降級。

    共用 `reporting._invoke_bedrock_converse()`，不另外建一套 Bedrock 呼叫——
    region／model_id 的讀取方式必須跟 C1-C4 一致，否則同一次決策的報告與說明
    可能跑在不同模型上。
    """
    from src.reporting import _invoke_bedrock_converse

    return _invoke_bedrock_converse(M4B_SYSTEM_PROMPT, user_message)


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
    from src.llm import bedrock_enabled

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

    use_bedrock = bedrock_enabled()

    if not use_bedrock:
        # 保底模式：不呼叫 LLM，拋例外讓呼叫端降級
        raise RuntimeError("USE_BEDROCK=false，無法生成報告說明（LLM 不可用）")

    user_message = json.dumps(
        {
            "trace_id": trace_id,
            "triggered_by": meta.triggered_by if meta else [],
            "steps": steps_data,
        },
        ensure_ascii=False,
        indent=2,
    )

    # SPEC-M4B §3 失敗處理：LLM 失敗一律往上拋，不得回傳部分內容或以樣板偽裝成功。
    # 降級由呼叫端（A2 的 EXPLAIN 階段）決定，見 SPEC-O2 §5。
    text = _invoke_m4b_llm(user_message)

    _EXPLANATION_CACHE[trace_id] = text
    return text


def answer_trace_query(trace_id: str, question: str) -> str:
    """回溯追問。resolve_segment_id 為 NOT_FOUND/AMBIGUOUS 時回固定文字、不呼叫LLM；
    命中為空時回「此路段未列入本次判斷」、不呼叫LLM；LLM失敗時降級顯示原始紀錄
    （永不沉默）。
    """
    import json
    from src.llm import bedrock_enabled

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
    use_bedrock = bedrock_enabled()

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

    fallback = (
        "系統暫時無法生成說明，相關原始紀錄如下：\n"
        f"{json.dumps(records_data, ensure_ascii=False, indent=2)}"
    )

    if not use_bedrock:
        return fallback

    meta = get_trace_meta(trace_id)
    user_message = json.dumps(
        {
            "trace_id": trace_id,
            "triggered_by": meta.triggered_by if meta else [],
            "question": question,
            "target_segment_id": target_segment_id,
            "steps": records_data,
        },
        ensure_ascii=False,
        indent=2,
    )

    # SPEC-M4B §4 失敗處理：降級為顯示原始資料，永不沉默、永不偽裝（不拋出）。
    try:
        return _invoke_m4b_llm(user_message)
    except Exception as e:
        logger.warning(f"answer_trace_query LLM 呼叫失敗，降級顯示原始紀錄: {e}")
        return fallback


def reset_traces() -> None:
    """測試輔助：清空所有 trace 和快取。"""
    _TRACES.clear()
    _STEPS.clear()
    _EXPLANATION_CACHE.clear()
