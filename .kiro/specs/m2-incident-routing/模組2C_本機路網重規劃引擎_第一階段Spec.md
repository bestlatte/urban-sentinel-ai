# M2-C：本機路網重規劃引擎——第一階段 Spec

版本：v1.1 Phase 1  
資料來源：本地 `road_network_topology.json`、`city_traffic_flow.json`  
不依賴：模組 1 API、SOP RAG、LLM

> **[2026-07-28 總架構師補註] 整合期新增函式：`COUNT_INTERSECTIONS`**（不在 Phase 1 範圍內，供後續整合參考）
> `SPEC-O2`（orchestrator 分派表）SOP-5 號誌故障流程需要「受影響路口數」這個確定性數字，交給 `decision_reporting`（C3）算警力估算（路口數 × 2）。這個小工具歸屬 `routing.py`（需要路網拓樸 `intersections` 欄位），對齊 `SPEC-00` §3.2 新增的 `ToolName.COUNT_INTERSECTIONS`：
> ```python
> def count_affected_intersections(affected_segment: str) -> int:
>     """算受影響路段沿線的路口數，供 SOP-5 警力估算（路口數 × 2）使用；純讀路網拓樸，不依賴車流或事件狀態。"""
> ```
> R1-R5 的邏輯不受影響，這是額外的獨立函式，不影響 Phase 1 的驗收條件。

## 1. 目標

使用本地路網與車流資料完成 R1～R5，在 60 秒內產生主要／次要替代道路及每個候選的理由。

## 2. 資料提供介面

演算法不得把檔案讀取寫死在 R1～R5，應透過介面：

```python
class TrafficSnapshotProvider:
    def get_snapshot(self, segment_ids, as_of): ...

class RoadNetworkProvider:
    def get_network(self): ...
```

第一階段實作：

```text
JsonTrafficSnapshotProvider
JsonRoadNetworkProvider
```

未來可替換為 API Provider，不修改演算法。

## 3. 輸入

```json
{
  "event_id": "TPE_2026_ACC_001",
  "analysis_version": 1,
  "affected_road": "RD_TPE_002",
  "event_timestamp": "2026-05-20T22:10:00+08:00",
  "status": "Closed",
  "severity": "Critical"
}
```

## 4. R1～R5

### R1 路網載入

- 載入 15 條道路。
- 以 `segment_id` 建索引。
- 驗證 `alternatives` ID 存在。
- 驗證容量、路口順序及必要欄位。
- 記錄路網版本或檔案雜湊。

### R2 上下游判定

- `intersections` 順序視為上游至下游。
- 依事故位置和交會點判定 `upstream/downstream/unknown`。
- 資料不足回傳 `unknown`，不可猜測。

### R3 候選篩選

依序檢查：

1. ID 存在。
2. 非事故或封閉道路。
3. `capacity_vph >= 1000`。
4. 與事故道路直接相交。
5. 位於上游。
6. 流向符合。
7. `Saturation_Score < 0.85`。

### R4 主次排序

```text
飽和度升冪 → 容量降冪 → segment_id 升冪
```

- 第一名為主道路。
- 其他合格道路為次要道路。
- 下游道路只能列備援。
- 唯一合格但已飽和時保留，標記 `saturated_but_retained`，附綠燈延長 25% 建議。
- 沒有道路時回傳 `NO_FEASIBLE_ROUTE`。

### R5 原因記錄

原因碼（[2026-07-28更正] 統一改用 `m4-explanation-chain-and-orchestrator/SPEC-00` §3.3 `ReasonCode` 的正式命名，SPEC-00 是列舉唯一來源；`SATURATED_BUT_RETAINED` 屬於 `FindingCode`，不是 `ReasonCode`，原因是該候選未被排除，語意上不能放進排除清單）：

- `CLOSED`（原寫 `closed_or_affected`）
- `CAPACITY_INSUFFICIENT`（原寫 `capacity_below_1000`）
- `NOT_DIRECTLY_INTERSECTING`（原寫 `not_directly_intersecting`）
- `DOWNSTREAM_ONLY`（原寫 `downstream_only`）
- `FLOW_DIRECTION_MISMATCH`（原寫 `direction_mismatch`）
- `SATURATED`（原寫 `saturated`）
- `MISSING_TRAFFIC_SNAPSHOT`（原寫 `missing_traffic_snapshot`；SPEC-00 已補齊此值）
- `UNKNOWN_SEGMENT`（原寫 `unknown_segment`；SPEC-00 已補齊此值）

`saturated_but_retained` 這個情境改記錄成 `Finding { finding_code: "SATURATED_BUT_RETAINED", ... }`，不放進 excluded 清單。

每個候選須保留全部通過／失敗結果。

## 5. As-of 車流快照

- 選擇 `Timestamp <= event_timestamp` 的最近一筆。
- 不得使用事件後的資料。
- 每個候選保存 `snapshot_at`。
- `Avg_Speed=null` 代表缺資料，不等於 0。
- 找不到飽和度時預設排除並記 `missing_traffic_snapshot`。

## 6. 輸出

```json
{
  "event_id": "TPE_2026_ACC_001",
  "analysis_version": 1,
  "status": "SUCCESS",
  "affected_segment": "RD_TPE_002",
  "road_network_version": "sha256:...",
  "traffic_snapshot_at": "2026-05-20T22:00:00+08:00",
  "primary_route": {
    "segment_id": "RD_TPE_004",
    "road_name": "仁愛路四段"
  },
  "secondary_routes": [],
  "candidate_evaluations": [],
  "warnings": [],
  "elapsed_ms": 235,
  "data_source": "LOCAL_JSON"
}
```

這是替代道路推薦，不是 GPS 導航路徑。

## 7. 第一階段不做

- 不呼叫模組 1取得即時快照。
- 不依 SOP RAG 動態改規則。
- 不計算 ETE。
- 不產生 LLM 解釋。
- 不使用 Redis；15 條道路使用記憶體即可。

## 8. 驗收條件

- AC-C01：容量不足道路正確排除。
- AC-C02：非直接相交道路正確排除。
- AC-C03：下游道路不成為主道路。
- AC-C04：飽和道路在有其他候選時被排除。
- AC-C05：唯一飽和候選正確保留並警告。
- AC-C06：無候選時回傳 `NO_FEASIBLE_ROUTE`。
- AC-C07：只使用事件時間以前的快照。
- AC-C08：相同輸入產生相同結果。
- AC-C09：缺值不被當成零。
- AC-C10：計算低於 2 秒，端到端低於 60 秒。

## 9. Definition of Done

- [ ] JSON Providers 完成。
- [ ] R1～R5 完成並有單元測試。
- [ ] as-of 快照完成。
- [ ] 主次排序、原因碼與例外完成。
- [ ] 無路可走可正確處理。
- [ ] 不依賴外部 API、LLM 或雲端服務。

