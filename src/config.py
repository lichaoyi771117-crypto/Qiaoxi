"""Qiaoxi Contract-Analyzer · 项目常量与配置"""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
DATA_DIR = PROJECT_ROOT / "data"
DOCS_DIR = PROJECT_ROOT / "docs"

# DeepSeek API 配置（必须从环境变量读取，禁止硬编码）
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

# LLM 调用默认超时（秒）
LLM_TIMEOUT_SECONDS = 120

# ChromaDB 配置（预留，当前使用纯本地关键词检索）
CHROMA_PERSIST_DIR = str(DATA_DIR / "chroma_db")
CHROMA_COLLECTION_NAME = "chinese_laws_rag"
EMBEDDING_MODEL = "BAAI/bge-m3"

# RAG 配置
RAG_TOP_K_VECTOR = 10
RAG_TOP_K_BM25 = 3

# 六位评审员配置
COUNCIL_ORDER = [
    "value_investor",      # 1/6
    "cfo_risk",            # 2/6
    "industry_architect",  # 3/6
    "deal_engineer",       # 4/6
    "operations",          # 5/6
    "risk_philosopher",    # 6/6
]

# 推演引擎配置
SIMULATION_TIMESLICES = [3, 6, 12, 36]  # 月

# 数据保留
TTL_DAYS_CONTRACT = 30
TTL_DAYS_INTERMEDIATE = 30
TTL_DAYS_HANDOFF = 90

# 六位评审员超时
COUNCIL_TIMEOUT_SECONDS = 120
COUNCIL_MAX_RETRIES = 1
