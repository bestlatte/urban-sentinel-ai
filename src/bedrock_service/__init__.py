"""K3 SOP RAG 檢索服務，對外只曝露 query_sop()。

參考 spec：`.kiro/specs/m3-bedrock-advisor/K3-sop-rag/`（design.md 已修正版：
欄位名 retrieval_source 不是 source；本機保底邏輯要真的寫 try/except，不能只在
文件裡描述）。
"""

from src.bedrock_service.sop_retriever import query_sop

__all__ = ["query_sop"]
