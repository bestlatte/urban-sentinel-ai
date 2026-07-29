"""一次性建置工具：把 emergency_traffic_sop.json 的 7 個 section 各自輸出成 .txt 檔，
供上傳 S3 建 Bedrock Knowledge Base 索引用。

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
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(DATA_FILE, encoding="utf-8") as f:
        raw = json.load(f)

    for section in raw["sections"]:
        num = section["section_number"]
        title = section["title"]
        content = section["content"]

        filename = f"SOP-{num}-{title}.txt"
        # 移除檔名不合法字元
        filename = filename.replace("/", "_").replace("\\", "_")

        filepath = OUTPUT_DIR / filename
        text = f"SOP 第 {num} 條：{title}\n\n{content}\n"
        filepath.write_text(text, encoding="utf-8")
        print(f"  ✓ {filepath.name}")

    print(f"\n完成：{len(raw['sections'])} 個 txt 檔已輸出到 {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
