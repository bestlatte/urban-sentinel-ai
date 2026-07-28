"""P1-P5：感知計算與 SOP 規則引擎（純確定性，零 LLM）。

參考 spec：`.kiro/specs/m1-data-ingestion/requirements.md` 第五節「P1-P5 函式契約」
（含 SOP-1 城市應變觸發限定路段 vs 全15路段分級的區分，見該文件測試 #6b）；
門檻值權威來源 `.kiro/steering/02-data-contract.md` §4；SOP 原文
`data/emergency_traffic_sop.json`。
"""

from __future__ import annotations

from datetime import datetime

from src.models import Incident, NormalizedDataBundle, RuleHit, SensingResult, TrafficLevel


def get_saturation(bundle: NormalizedDataBundle, segment_id: str, as_of: datetime) -> float | None:
    """P1：as-of 飽和度查詢。

    TODO(Kiro): 依 02-data-contract.md §3「時間 Join 固定 as-of」實作——
    取 timestamp <= as_of 的最近一筆，不做插值；查無資料回傳 None（不是 0）。
    """
    raise NotImplementedError("見 m1-data-ingestion/requirements.md P1")


def get_growth_rate(bundle: NormalizedDataBundle, station_id: str, as_of: datetime) -> float | None:
    """P2：人流成長率查詢（SOP-3/4 用）。"""
    raise NotImplementedError("見 m1-data-ingestion/requirements.md P2")


def get_roaming_ratio(bundle: NormalizedDataBundle, station_id: str, as_of: datetime) -> float | None:
    """P3：漫遊比率查詢（SOP-6 用，門檻 >= 0.30）。"""
    raise NotImplementedError("見 m1-data-ingestion/requirements.md P3")


def determine_level(rule_hits: list[RuleHit], saturation_score: float | None) -> TrafficLevel:
    """P5：交通等級判定。

    門檻（02-data-contract.md §4，SOP-1 原文：適用全 15 路段，不得誤植為只限定
    RD_TPE_001/002——那兩段限定的是「城市應變觸發」動作，不是分級本身）：
        Saturation_Score >= 0.95 → A
        0.85 <= score < 0.95     → B
        其他                      → normal
    """
    raise NotImplementedError("見 m1-data-ingestion/requirements.md P5，注意測試 #6 與 #6b 的區別")


def evaluate_rules(bundle: NormalizedDataBundle, incident: Incident | None = None) -> SensingResult:
    """P4：SOP 規則引擎，門檻→條款→動作。彙整 P1-P3 的查詢結果與 P5 的等級判定。

    TODO(Kiro): 依 m1-data-ingestion/requirements.md 第五節完整實作 SOP-1~7 的命中判斷，
    十項驗收測試（含真實資料黃金值）逐條轉成 tests/test_rules.py 的斷言。
    """
    raise NotImplementedError("見 m1-data-ingestion/requirements.md 第五、六節")
