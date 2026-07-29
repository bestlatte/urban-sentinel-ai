"""一次性建置工具：把 generate_sop_index_files.py 產生的 7 個 txt 檔上傳到 S3，
供建立 Bedrock Knowledge Base 使用。

環境變數 S3_DATA_BUCKET 見 `.env.example`。
需要 AWS 憑證已設定。
"""

from __future__ import annotations

import os
from pathlib import Path

import boto3

SOP_INDEX_DIR = Path(__file__).resolve().parents[1] / "data" / "sop-index"
S3_PREFIX = "sop-index/"


def main() -> None:
    bucket = os.environ.get("S3_DATA_BUCKET")
    if not bucket:
        raise RuntimeError("S3_DATA_BUCKET 未設定，見 .env.example")

    region = os.environ.get("AWS_REGION", "us-west-2")
    s3 = boto3.client("s3", region_name=region)

    txt_files = sorted(SOP_INDEX_DIR.glob("*.txt"))
    if not txt_files:
        print("⚠️  找不到 txt 檔案，請先跑 generate_sop_index_files.py")
        return

    for filepath in txt_files:
        key = S3_PREFIX + filepath.name
        s3.upload_file(str(filepath), bucket, key)
        print(f"  ✓ 上傳 s3://{bucket}/{key}")

    print(f"\n完成：{len(txt_files)} 個檔案已上傳")
    print(f"請至 Bedrock Knowledge Base 頁面按 Sync 觸發索引建立")


if __name__ == "__main__":
    main()
