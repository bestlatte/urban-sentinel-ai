"""A3 ETE 計算 + C1-C4 建議書/號誌/聯動/簡訊生成。

參考 spec：`.kiro/specs/m4-decision-reporting/requirements.md`（唯一權威，含 ETE
公式、三筆黃金驗收值、C1-C4 提示詞契約、失敗降級規則）。**這不是**
`m4-explanation-chain-and-orchestrator/`（那是解釋鏈/Orchestrator 核心邏輯，
命名雖然都帶「模組四」但範圍不同，見該資料夾與本檔案的分工說明）。

C1~C4 一律由 A2 編排觸發，本模組不得被繞過直接呼叫（01-module-boundaries.md 規則9）。
"""

from __future__ import annotations

from src.models import (
    BedrockAdvisory,
    EteEstimate,
    Incident,
    Notification,
    NormalizedDataBundle,
    RoutePlan,
    SensingResult,
)


def calculate_ete(incident: Incident, bundle: NormalizedDataBundle) -> EteEstimate:
    """A3：確定性 ETE 計算，唯一公式來源，不得在其他模組重複實作或修改。

    公式（m4-decision-reporting/requirements.md 第二節）：
        ETE_minutes = base_clearance + max(0, (average_saturation - 0.5) * 60)
        base_clearance: Critical=60 / High=40 / Medium=20 / Low=20（沿用Medium，
        SOP原文未定義Low，取最保守但非零值——這是團隊補的假設，不是SOP原文）

    黃金驗收值（唯一依據，不得因程式改版而變動，已對真實資料驗算過）：
        ACC_001 (RD_TPE_002, Critical, sat=1.0)  → 90分 → 23:40
        EVT_002 (RD_TPE_001, High, sat=1.0)      → 70分
        EVT_003 (RD_TPE_007, Medium, sat=0.85)   → 41分

    TODO(Kiro): 取值順序——有 affected_road 用它，否則用 RD 類 affected_segment；
    多條才取平均。算出的數字與上表不符時，先檢查 as-of join，不要改公式。
    """
    raise NotImplementedError("見 m4-decision-reporting/requirements.md 第二節")


def generate_report(
    incident: Incident,
    sensing: SensingResult,
    route_plan: RoutePlan | None,
    ete: EteEstimate,
    advisory: BedrockAdvisory | None,
) -> tuple[str, Notification | None]:
    """C1-C4：LLM 生成，唯讀轉換——只能表達已經算好的事實，不得改寫任何數字/路段/條款編號。

    回傳 (交控建議書全文, 多語簡訊物件)。第二個回傳值是單一物件 {zh, en?, ja?, ko?}，
    不是清單；SOP-6 未觸發時只有 zh 有值。

    C1~C3（建議書/號誌/聯動）併入同一段全文，不拆成獨立結構化欄位——理由見
    `m4-explanation-chain-and-orchestrator/SPEC-O3` §3 補註：C2/C3 是 LLM 依 C1
    事實生成的文字建議，硬拆回結構化物件等於對自然語言重新做結構化解析，不可靠。

    輸入邊界鐵律（m4-decision-reporting/requirements.md §3.1，逐一以確定性方式注入 prompt，
    LLM 不得自行產生或變更）：
        event_id, location, type, status, severity, traffic_level
        primary_route/secondary_route/exclusion_reasons, ete.minutes/ete.recovery_at
        命中的 SOP 條款編號、affected_intersection_count（SOP-5用，含×2換算，
        由 routing.count_affected_intersections() 算好注入，不是這裡算）

    失敗處理：C1失敗→第一個回傳值為None，呼叫端於DecisionResult.degraded加入"C1_FAILED"；
    C4失敗→第二個回傳值為None，加入"C4_FAILED"。不得因單一生成項目失敗而拋出例外中斷
    （01-module-boundaries.md 第5節「永不沉默」）。

    TODO(Kiro): 依 m4-decision-reporting/requirements.md 第三節完整實作 C1-C4 的
    prompt 組裝與生成邏輯；系統提示詞讀 `prompts/report.txt`（C1-C3 共用）與
    `prompts/notification.txt`（C4 額外的多語簡訊限制），不得增減規則、不要把
    提示詞硬編在這個檔案裡。
    """
    raise NotImplementedError("見 m4-decision-reporting/requirements.md 第三節")
