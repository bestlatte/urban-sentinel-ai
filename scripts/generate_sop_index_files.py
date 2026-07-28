"""一次性建置工具：把 emergency_traffic_sop.json 的 7 個 section 各自輸出成 .txt 檔，
供上傳 S3 建 Bedrock Knowledge Base 索引用。

參考 spec：`.kiro/specs/m3-bedrock-advisor/K3-sop-rag/design.md` 第三節「前置設定」、
`K3-sop-rag/tasks.md` Task 4。

不是應用程式讀取路徑的一部分（見 `.kiro/steering/00-tech-stack.md` §3 `scripts/`
的定位說明）——這是 K1 離線索引建置的手動/半自動工具，跑完 Task 4/5 之後，
正式流程只透過 Bedrock KB ID 查詢，不會再讀這裡產生的 txt 檔。

檔名格式：SOP-{section_number}-{title}.txt
內容格式：
    SOP 第 {section_number} 條：{title}

    {content}
"""

from __future__ import annotations

import json
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "emergency_traffic_sop.json"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "sop-index"


def main() -> None:
    """TODO(Kiro): 讀 DATA_FILE，對每個 section 依上述格式輸出到 OUTPUT_DIR，
    建立目錄（若不存在）。跑完後應該有 7 個 txt 檔。
    """
    raise NotImplementedError("見 K3-sop-rag/design.md 第三節、tasks.md Task 4")


if __name__ == "__main__":
    main()
