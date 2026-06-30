"""Qiaoxi Contract-Analyzer 路 椤圭洰甯搁噺涓庨厤缃?""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
DATA_DIR = PROJECT_ROOT / "data"
DOCS_DIR = PROJECT_ROOT / "docs"

# DeepSeek API 閰嶇疆
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-your-key-here")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# ChromaDB 閰嶇疆
CHROMA_PERSIST_DIR = str(DATA_DIR / "chroma_db")
CHROMA_COLLECTION_NAME = "chinese_laws_rag"
EMBEDDING_MODEL = "BAAI/bge-m3"

# RAG 閰嶇疆
RAG_TOP_K_VECTOR = 10   # 鍚戦噺妫€绱?Top-10
RAG_TOP_K_BM25 = 3      # BM25 绮炬帓 Top-3

# 鍏綅璇勫鍛橀厤缃?COUNCIL_ORDER = [
    "value_investor",    # 1/6 鏉庢枃楦?    "cfo_risk",          # 2/6 鍚存収鐞?    "industry_architect",# 3/6 鏉庡啗
    "deal_engineer",     # 4/6 娈垫捣娑?    "operations",        # 5/6 鐜嬪織鍧?    "risk_philosopher",  # 6/6 鏉庤壘鐔?]

# 鎺ㄦ紨寮曟搸閰嶇疆
SIMULATION_TIMESLICES = [3, 6, 12, 36]  # 鏈?
# 鏁版嵁淇濈暀
TTL_DAYS_CONTRACT = 30      # 鍚堝悓鍘熸枃淇濈暀澶╂暟
TTL_DAYS_INTERMEDIATE = 30  # 涓棿鎬丣SON淇濈暀澶╂暟
TTL_DAYS_HANDOFF = 90       # handoff_snapshot淇濈暀澶╂暟

# 鍏綅璇勫鍛樿秴鏃?COUNCIL_TIMEOUT_SECONDS = 120
COUNCIL_MAX_RETRIES = 1
