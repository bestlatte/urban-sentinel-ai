"""一次性建置工具：把 generate_sop_index_files.py 產生的 7 個 txt 檔上傳到 S3，
供建立 Bedrock Knowledge Base 使用。

參考 spec：`.kiro/specs/m3-bedrock-advisor/K3-sop-rag/design.md` 第三節、tasks.md Task 4。
需要 AWS 憑證已設定（見 `AWS服務選型建議.md` 0.2~0.3節）。如果 AWS 還沒通，
這個腳本可以先跳過，不影響 K3 的 Task 2/3（本機模式）開發。

環境變數 S3_DATA_BUCKET 見 `.env.example`。
"""

from __future__ import annotations

import os
from pathlib import Path

SOP_INDEX_DIR = Path(__file__).resolve().parents[1] / "data" / "sop-index"
S3_PREFIX = "sop-index/"


def main() -> None:
    """TODO(Kiro): boto3 s3 client，把 SOP_INDEX_DIR 底下全部 *.txt 上傳到
    s3://{S3_DATA_BUCKET}/{S3_PREFIX}，上傳後提醒回 KB 頁面按 Sync。
    """
    bucket = os.environ.get("S3_DATA_BUCKET")
    if not bucket:
        raise RuntimeError("S3_DATA_BUCKET 未設定，見 .env.example")
    raise NotImplementedError("見 K3-sop-rag/design.md 第三節、tasks.md Task 4")


if __name__ == "__main__":
    main()
