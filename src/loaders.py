"""D1-D4：五個 canonical 檔案載入與 raw→normalized 正規化。

參考 spec：`.kiro/specs/m1-data-ingestion/requirements.md`（完整函式契約、正規化規則、
真實 CSV 的 % 字串解析範例、10 項驗收測試）；資料來源與單位換算規則另見
`.kiro/steering/02-data-contract.md` §1-3。

本模組是唯一可以讀 `data/` 原始檔的地方（01-module-boundaries.md 規則2），
其他模組一律透過 `load_data()` 回傳的 `NormalizedDataBundle` 取用資料。
"""

from __future__ import annotations

from src.models import Incident, NormalizedDataBundle


def load_data() -> NormalizedDataBundle:
    """載入並正規化五個 canonical 檔案（D1-D3）。

    TODO(Kiro): 依 m1-data-ingestion/requirements.md 第三節「D1-D4 函式契約」實作：
    1. D1 讀取 data/ 五個檔案（city_traffic_flow.json、signaling_crowd_density.csv、
       road_network_topology.json、live_incidents.json、emergency_traffic_sop.json）。
    2. D2 欄位映射：Pascal/混合欄位 → snake_case（真實 CSV 的 BS_ID→station_id、
       Location_Name→station_name，見 02-data-contract.md §2）。
    3. D3 時間正規化為 ISO 8601 +08:00；Roaming_User_Pct 字串解析
       （"40%" → 移除 % 再除以100 → 0.40，不得假設為純數字型態，這是最容易漏測的一步，
       m1-data-ingestion/requirements.md 驗收測試 #1、#2 專門測這個）。
    4. Growth_Rate 已是小數率，禁止再除以 100。
    """
    raise NotImplementedError("見本函式 docstring 的 TODO 與 m1-data-ingestion/requirements.md")


def on_incident_injected(bundle: NormalizedDataBundle, incident: Incident) -> NormalizedDataBundle:
    """D4：事件注入監聽，把新事件併入 bundle（不重新載入整份資料）。

    TODO(Kiro): 依 m1-data-ingestion/requirements.md D4 章節實作；
    affected_road / affected_segment 缺漏時的驗證規則見同文件第四節。
    """
    raise NotImplementedError("見本函式 docstring 的 TODO 與 m1-data-ingestion/requirements.md")
