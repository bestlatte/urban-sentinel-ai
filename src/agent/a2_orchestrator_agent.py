"""A2 LLM 規劃器：事件注入時由 LLM 決定「呼叫哪些工具、什麼順序」。

SPEC-O2 §3（折衷制）：規則觸發走靜態分派表（零 LLM），事件注入走本模組的
LLM 規劃器，失敗時降級為靜態分派鏈。

**本模組只規劃、不執行**（SPEC-O2 §3.1）：LLM 產出 `ToolPlan` 工具序列，
實際計算全部由 orchestrator 的 EXECUTE 階段呼叫 `GATEWAY` 的決定性模組完成。
這是 SPEC-00 鐵律①「LLM 只表達、不改寫」在編排層的落實——LLM 不得產生任何
數值結果，也不得決定 event_id／路段代碼等事實欄位。

三層護欄（SPEC-O2 §3.2），任一層失敗都降級為靜態鏈：
  ① 白名單驗證   ToolPlan 出現 `ToolName` 以外的工具名 → 整份計畫作廢
  ② 必要步驟檢查 依 A1 命中條款做確定性後驗（§2 必含 R 鏈 + CALC_ETE；
                  §5 必含 COUNT_INTERSECTIONS）
  ③ 逾時         超過 8 秒未回（SPEC-O2 §4.3 逾時預算）
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field

from src.models import (
    R_CHAIN_TOOLS,
    ToolName,
    ToolPlan,
    ToolPlanStep,
)

logger = logging.getLogger(__name__)

PLANNER_TIMEOUT_S = 8.0
"""SPEC-O2 §4.3 逾時預算：LLM 規劃器 8s。"""

_VALID_TOOL_NAMES = {t.value for t in ToolName}


# ---------------------------------------------------------------------------
# 規劃結果
# ---------------------------------------------------------------------------


@dataclass
class PlanResult:
    """規劃器輸出。`plan is None` 代表降級，呼叫端須改走靜態分派鏈。

    `reason` 記錄降級原因（哪一層護欄擋下的），由 orchestrator 寫進
    `record_step(A2, "PLAN", input={"degraded": True, "reason": ...})`（SPEC-O2 §3.2）。
    """

    plan: ToolPlan | None
    degraded: bool
    reason: str | None = None
    raw_output: str | None = None
    tool_sequence: list[str] = field(default_factory=list)


def _degraded(reason: str, raw: str | None = None) -> PlanResult:
    logger.warning(f"A2 規劃器降級：{reason}")
    return PlanResult(plan=None, degraded=True, reason=reason, raw_output=raw)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def _build_a2_system_prompt() -> str:
    """A2 規劃器的 system prompt。

    工具呼叫條件必須跟 `orchestrator.classify_incident()` 的對照表一致，否則
    護欄②會把 LLM 的計畫全部擋掉、等於白呼叫一次 LLM。
    """
    tool_list = "\n".join(f"- {t.value}" for t in ToolName)
    return f"""你是交通指揮系統的 A2 編排規劃器。

你的唯一任務是「規劃」：決定要依什麼順序呼叫哪些工具來處理一筆交通事件。

## 絕對禁止
1. 你不執行工具，也拿不到工具結果。
2. 你不產生任何數值（路線、恢復時間、飽和度、警力人數都不准寫）。
3. 你不改寫事件 ID、路段代碼、SOP 條款編號。

## 可用工具白名單（只能從這裡選，寫出清單以外的名稱整份計畫會作廢）
{tool_list}

## 規劃規則
1. 所有事件都必須包含 RAG_SEARCH（查 SOP 依據）與 CALC_ETE（預計恢復時間）。
2. Road_Collapse_Accident（SOP-2）必須包含完整 R 鏈四步，順序固定：
   GRAPH_BUILD → UPSTREAM_JUDGE → CANDIDATE_FILTER → ROUTE_SELECT，
   且必須包含 CALC_ETE。缺任何一步整份計畫會被判定不合格。
3. Power_Failure（SOP-5）必須包含 COUNT_INTERSECTIONS（警力估算依路口數）。
4. Crowd_Surge_Injury（SOP-3）不需要路網重規劃，不要放 R 鏈工具。
5. 最後固定以 FORMAT_REPORT 收尾；需要多語通報時才追加 TRANSLATE。
6. CAPACITY_CHECK / FORECAST_MODEL / CASCADE_ANALYSIS 是延伸功能，除非題目明確
   要求壓力測試或預測，否則不要放。

## 輸出格式
只輸出 JSON，不要有任何說明文字、不要用 markdown 程式碼區塊包起來：

{{"steps": [{{"tool": "RAG_SEARCH", "args_hint": {{}}}}, {{"tool": "CALC_ETE", "args_hint": {{}}}}]}}

`args_hint` 可留空物件；系統不會採用你寫的參數值，實際參數一律由系統自事件資料取得。
"""


def _build_user_prompt(
    event_id: str,
    event_type: str,
    classification: dict,
    traffic_level: str | None = None,
) -> str:
    """組規劃輸入（SPEC-O2 §3.1：A1 分類結果 + P5 當前級別 + GlobalState 快照）。"""
    parts = [
        f"事件 ID：{event_id}",
        f"事件類型：{event_type}",
        f"A1 分類：主因條款={classification.get('primary_sop')}、"
        f"需要路網重規劃={classification.get('requires_rerouting')}",
    ]
    if traffic_level:
        parts.append(f"P5 當前交通等級：{traffic_level}")
    parts.append("請依規劃規則輸出 JSON 工具序列。")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Agent 實例（延遲初始化，無 AWS 憑證時回 None 走降級）
# ---------------------------------------------------------------------------


_A2_AGENT = None


def create_a2_agent():
    """建立 A2 Agent 實例。

    `tools=[]` 是刻意的：SPEC-O2 §3.1 要求規劃器「不執行工具」，所以不註冊任何
    Strands `@tool`。LLM 只透過 system prompt 認識工具白名單，產出 JSON 序列。

    [2026-08-01] `callback_handler=None`：Strands 預設會把串流輸出 print 到
    stdout，Windows cp950 主控台遇到 emoji 會拋 `UnicodeEncodeError`，整次規劃
    直接失敗降級。規劃器的輸出是要拿去 parse 的 JSON，本來就不需要串流列印。

    model 改用 `llm.get_strands_model()` 共用快取實例，順帶拿到 boto3 層的
    read/connect timeout——原本只有護欄③的 thread 逾時，底層 socket 沒有上限。
    """
    from strands import Agent

    from src.llm import get_strands_model

    return Agent(
        model=get_strands_model(),
        tools=[],
        system_prompt=_build_a2_system_prompt(),
        callback_handler=None,
    )


def _get_a2_agent():
    """取得或建立 A2 Agent。建立失敗（缺套件／缺憑證）時回 None，呼叫端降級。"""
    global _A2_AGENT
    if _A2_AGENT is None:
        try:
            _A2_AGENT = create_a2_agent()
        except Exception as e:
            logger.warning(f"無法建立 A2 Agent: {e}，將使用靜態分派降級")
            return None
    return _A2_AGENT


def reset_agent_cache() -> None:
    """測試輔助：清掉快取的 Agent 實例，讓下次呼叫重新建立。"""
    global _A2_AGENT
    _A2_AGENT = None


# ---------------------------------------------------------------------------
# 護欄①：白名單驗證
# ---------------------------------------------------------------------------


_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def _extract_json_object(text: str) -> str:
    """從 LLM 回應抽出 JSON 物件字串。

    容忍兩種常見雜訊：markdown 程式碼圍籬，以及 JSON 前後的說明文字。
    只做「找出最外層大括號區間」這種確定性處理，不做語意修補。
    """
    cleaned = _JSON_FENCE.sub("", text.strip())
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("回應中找不到 JSON 物件")
    return cleaned[start : end + 1]


def parse_tool_plan(text: str) -> ToolPlan:
    """把 LLM 原始回應解析成 `ToolPlan`，並執行護欄①白名單驗證。

    任何格式錯誤或非法工具名一律拋 `ValueError`——SPEC-O2 §3.2「整份計畫作廢」，
    不做「丟掉壞的那一步、留下好的」這種部分採用，避免產出殘缺的工具序列。
    """
    payload = json.loads(_extract_json_object(text))
    if not isinstance(payload, dict):
        raise ValueError("JSON 根節點不是物件")

    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("steps 缺漏或不是非空陣列")

    steps: list[ToolPlanStep] = []
    for i, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            raise ValueError(f"steps[{i}] 不是物件")
        name = raw.get("tool")
        if name not in _VALID_TOOL_NAMES:
            # 護欄①：非法工具名 → 整份作廢
            raise ValueError(f"steps[{i}] 工具名不在白名單: {name!r}")
        args_hint = raw.get("args_hint") or {}
        if not isinstance(args_hint, dict):
            args_hint = {}
        steps.append(ToolPlanStep(tool=ToolName(name), args_hint=args_hint))

    return ToolPlan(steps=steps)


# ---------------------------------------------------------------------------
# 護欄②：必要步驟檢查（確定性後驗）
# ---------------------------------------------------------------------------


def check_required_steps(plan: ToolPlan, primary_sop: str | None) -> str | None:
    """依 A1 命中條款檢查計畫完整性（SPEC-O2 §3.2 護欄②）。

    回傳 None 代表通過；回傳字串代表缺漏原因（供降級留痕）。

    對照 SPEC-O2 §2 靜態分派表：
      SOP-2（§2）→ R 鏈四步 + CALC_ETE
      SOP-5（§5）→ COUNT_INTERSECTIONS
    其餘條款 spec 未規定必要步驟，不強制。
    """
    present = set(plan.tool_names())

    if primary_sop == "SOP-2":
        missing_r = sorted(t.value for t in (R_CHAIN_TOOLS - present))
        if missing_r:
            return f"§2 事件缺 R 鏈工具: {', '.join(missing_r)}"
        if ToolName.CALC_ETE not in present:
            return "§2 事件缺 CALC_ETE"

    if primary_sop == "SOP-5" and ToolName.COUNT_INTERSECTIONS not in present:
        return "§5 事件缺 COUNT_INTERSECTIONS"

    return None


# ---------------------------------------------------------------------------
# 對外入口
# ---------------------------------------------------------------------------


def plan_tools(
    event_id: str,
    event_type: str,
    classification: dict,
    traffic_level: str | None = None,
    timeout_s: float = PLANNER_TIMEOUT_S,
) -> PlanResult:
    """讓 A2 LLM 規劃器產出工具序列（SPEC-O2 §3）。

    永不拋例外：任何失敗都回傳 `PlanResult(plan=None, degraded=True, reason=...)`，
    呼叫端據此走靜態分派鏈。這是 SPEC-O2 §5「降級規則：永不沉默」的要求。

    Args:
        event_id: 事件 ID
        event_type: 事件類型（如 Road_Collapse_Accident）
        classification: `orchestrator.classify_incident()` 的回傳值
        traffic_level: P5 當前級別（A/B/normal），僅作為規劃參考
        timeout_s: 護欄③逾時秒數，預設 8s
    """
    # 00-tech-stack.md §6 保底模式：USE_BEDROCK=false 時「Agent 工具選擇改用
    # 依事件類型查表的固定流程」——這裡直接降級，不得真的送出 Bedrock 請求。
    # 只靠下面的 except 接住連線錯誤是不夠的：離線或憑證過期時每個決策週期都要
    # 先等一次 ConverseStream 逾時，旗標等於沒作用。
    from src.llm import bedrock_enabled

    if not bedrock_enabled():
        return _degraded("USE_BEDROCK=false（保底模式，改用靜態分派）")

    agent = _get_a2_agent()
    if agent is None:
        return _degraded("A2 Agent 不可用（缺套件或缺 AWS 憑證）")

    prompt = _build_user_prompt(event_id, event_type, classification, traffic_level)

    # 護欄③：逾時。Strands Agent 呼叫是同步阻塞，丟到工作執行緒才能設 deadline。
    # 逾時後該執行緒仍會跑完，但結果被丟棄——不會影響已降級的決策路徑。
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            raw_response = pool.submit(agent, prompt).result(timeout=timeout_s)
    except FuturesTimeout:
        return _degraded(f"規劃器逾時（>{timeout_s:g}s）")
    except Exception as e:
        return _degraded(f"規劃器呼叫失敗: {e}")

    raw_text = str(raw_response)

    # 護欄①：白名單驗證
    try:
        plan = parse_tool_plan(raw_text)
    except Exception as e:
        return _degraded(f"計畫解析／白名單驗證失敗: {e}", raw=raw_text)

    # 護欄②：必要步驟檢查
    missing = check_required_steps(plan, classification.get("primary_sop"))
    if missing:
        result = _degraded(f"必要步驟檢查未通過: {missing}", raw=raw_text)
        result.tool_sequence = [t.value for t in plan.tool_names()]
        return result

    sequence = [t.value for t in plan.tool_names()]
    logger.info(f"A2 規劃完成（{event_id}）: {' → '.join(sequence)}")
    return PlanResult(
        plan=plan,
        degraded=False,
        reason=None,
        raw_output=raw_text,
        tool_sequence=sequence,
    )
