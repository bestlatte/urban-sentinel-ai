"""一次性建置工具：把 `data/` 底下五個 canonical 原始檔上傳到 S3。

參考：`.kiro/specs/architecture-reference/2026-07-28_架構圖合規性複查與待辦.md` §2.4/§2.5
——AWS 部署分層圖把「Amazon S3 資料檔+SOP原文」畫成紅色核心節點。跟
`upload_sop_to_s3.py` 用途不同：那支是把 SOP 切段成 txt 供 Bedrock KB 建索引用，
這支是把五個原始 JSON/CSV 檔案本身備份到 S3，供正式版 `LiveGateway.load_data()`
未來若改成讀 S3 而非本機 `data/` 目錄時使用。

目前 `src/loaders.py` 讀的都是本機檔案路徑，這支腳本跑完**不會**自動改變
`LiveGateway` 的讀取行為——上傳到 S3 只是先把資料備份過去，要不要真的切換讀取
來源是另一個獨立的決定（涉及 `loaders.py` 的改動，不在這支腳本的範圍內）。

需要 AWS 憑證已設定（見 `AWS服務選型建議.md` 0.2~0.3節）。如果 AWS 還沒通，
這個腳本可以先跳過，不影響任何本機開發或demo流程。

環境變數 S3_DATA_BUCKET 見 `.env.example`（跟 `upload_sop_to_s3.py` 共用同一個桶，
只是 prefix 不同）。
"""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
S3_PREFIX = "raw-data/"

DATA_FILES = [
    "city_traffic_flow.json",
    "signaling_crowd_density.csv",
    "road_network_topology.json",
    "live_incidents.json",
    "emergency_traffic_sop.json",
]
"""五個 canonical 檔案，見 `.kiro/steering/02-data-contract.md` 一、資料現況提醒。"""


def main() -> None:
    """把 DATA_FILES 逐一上傳到 s3://{S3_DATA_BUCKET}/{S3_PREFIX}{filename}。"""
    bucket = os.environ.get("S3_DATA_BUCKET")
    if not bucket:
        raise RuntimeError("S3_DATA_BUCKET 未設定，見 .env.example")

    missing = [f for f in DATA_FILES if not (DATA_DIR / f).exists()]
    if missing:
        raise FileNotFoundError(f"以下檔案在 {DATA_DIR} 找不到：{missing}")

    import boto3

    region = os.environ.get("AWS_REGION", "us-west-2")
    s3 = boto3.client("s3", region_name=region)

    for filename in DATA_FILES:
        filepath = DATA_DIR / filename
        key = S3_PREFIX + filename
        s3.upload_file(str(filepath), bucket, key)
        print(f"  ✓ 上傳 s3://{bucket}/{key}")

    print(f"\n完成：{len(DATA_FILES)} 個檔案已上傳到 s3://{bucket}/{S3_PREFIX}")


if __name__ == "__main__":
    main()
