/**
 * SVG 拓樸圖，依 display_points 定位、依 payload 上色。不篩路線、不判級別。
 * 參考 spec：m5-api-orchestrator-dashboard/design.md 第六節；
 * 顏色規則 .kiro/steering/02-data-contract.md §8
 * （A級紅/B級橘/正常青綠；主路線亮綠實線/次路線黃色虛線/封閉路段紅色粗線）。
 * 資料無真實GIS座標，display_points只控制SVG位置、不參與任何決策判定。
 */
