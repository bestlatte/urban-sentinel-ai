# 資料清單（Definition of Done 項目，m1-data-ingestion/requirements.md）

五個 canonical 檔案，全部真實資料，欄位/單位換算規則權威來源
`.kiro/steering/02-data-contract.md` §1-3。

| logical_type | 檔案 | 筆數 | classification |
|---|---|---:|---|
| `traffic` | `data/city_traffic_flow.json` | 112 | `provided` |
| `crowd` | `data/signaling_crowd_density.csv` | 36 | `provided`（2026-07-28主辦方補齊真實資料，取代原模擬版；筆數已修正 37→36，`wc -l` 誤把標題列算入） |
| `road_network` | `data/road_network_topology.json` | 15 | `provided` |
| `incident` | `data/live_incidents.json` | 3 | `provided` |
| `sop` | `data/emergency_traffic_sop.json` | 7 sections | `provided` |

不得新增、改名或複製其他資料檔（`data/display_geometry.json` 為唯一例外，M2 產出，僅供 SVG 顯示）。

TODO(Kiro): 此檔隨 `src/loaders.py` 完成後更新——記錄實際載入時的雜湊/版本號，
供 `RoadSegment` 的 `road_network_version` 欄位使用（見 K3-sop-rag、M2-C 相關 spec）。
