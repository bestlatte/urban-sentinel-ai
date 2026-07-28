"""R1-R5：路網建圖、上下游判定、候選篩選、主/次路線、排除理由記錄（純確定性，零 LLM）。

參考 spec：`.kiro/specs/m2-incident-routing/` 全部五份文件，特別是
`模組2C_本機路網重規劃引擎_第一階段Spec.md`（R1-R5 演算法、九種排除原因碼、
飽和兩段式例外規則、TrafficSnapshotProvider/RoadNetworkProvider 介面）。

該資料夾其餘四份文件（M2-A/B/D + 總覽）是「Phase 1 獨立沙盒」規格，各自加註了
「整合收斂」補記——SQLite、專屬 REST 端點、專屬 WebSocket 都不是本檔案要接的介面，
本檔案只需要對外提供下面這兩個函式，由 orchestrator.py 呼叫。

`COUNT_INTERSECTIONS`（SOP-5 警力估算用，SPEC-00 §3.2）也定義在本檔，見該函式 docstring。
"""

from __future__ import annotations

from datetime import datetime

from src.models import NormalizedDataBundle, RoutePlan, RouteRequest


def plan_route(request: RouteRequest) -> RoutePlan:
    """R1-R5 主流程：建圖 → 上下游判定 → 候選篩選 → 主/次路線 → 排除理由記錄。

    簽章對齊 orchestrator.py 的 `ModuleGateway.plan_routes(request: RouteRequest)`
    ——[2026-07-28自查修正] 原本這裡寫成三個獨立參數 (incident, bundle, as_of)，
    跟 ModuleGateway Protocol 的單一物件簽章對不上，是搭鷹架時自己引入的不一致，已改正。

    TODO(Kiro): 依 `模組2C_本機路網重規劃引擎_第一階段Spec.md` 第4節 R1-R5 完整實作：
    - R3 候選篩選依序檢查：ID存在→非封閉→capacity_vph>=1000→直接相交→位於上游→
      流向符合→Saturation_Score<0.85。
    - R4 排序：飽和度升冪→容量降冪→segment_id升冪；唯一合格但已飽和時保留
      （SATURATED_BUT_RETAINED，記在 findings 不是 excluded）。
    - 九種 ReasonCode 用 SPEC-00 §3.3 的 UPPER_SNAKE_CASE 命名，不要用該 spec
      文件裡殘留的 lower_snake_case 舊寫法。
    - 60 秒 SLA：量測 duration_ms 並設定 within_60_second_sla。
    """
    raise NotImplementedError("見 m2-incident-routing/模組2C 第4-6節")


def count_affected_intersections(bundle: NormalizedDataBundle, affected_segment: str) -> int:
    """COUNT_INTERSECTIONS：算受影響路段沿線的路口數，供 SOP-5 警力估算（路口數 × 2）使用。

    純讀路網拓樸，不依賴車流或事件狀態。這個結果由呼叫端（orchestrator）算好後
    當成事實欄位注入 C3 prompt，LLM 不得自己計算或臆測（m4-decision-reporting/requirements.md §3.4）。

    TODO(Kiro): 見 m2-incident-routing/模組2C 檔頭補註「整合期新增函式」。
    """
    raise NotImplementedError("見 m2-incident-routing/模組2C 檔頭補註")
