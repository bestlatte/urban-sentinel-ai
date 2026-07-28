"""W1 的 System Prompt。內容權威來源是 `prompts/advisor.txt`（00-tech-stack.md §3
固定結構要求 prompt 外部化成 .txt，方便非工程師調整、不用改程式碼重新部署）。

參考 spec：`.kiro/specs/m3-bedrock-advisor/W1-whatif-agent/design.md` 第三節。
"""

from pathlib import Path

SYSTEM_PROMPT = (Path(__file__).resolve().parents[2] / "prompts" / "advisor.txt").read_text(
    encoding="utf-8"
)

DEFAULT_QUESTIONS = [
    "目前系統是什麼應變等級？",
    "替代路線還有容量嗎？",
    "ETE 預計多久恢復？",
]
"""延伸問題解析失敗時的 fallback。"""
