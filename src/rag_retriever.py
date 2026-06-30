"""
Qiaoxi Contract-Analyzer · 本地 RAG 检索引擎

纯本地关键词匹配，不依赖 ChromaDB Embedding（bge-m3 作为后续优化方案预留）
"""
import json
import os
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 清洗后的法律条款
LAWS_FILE = "data/laws_clean/cleaned_laws.json"
_laws_cache: Optional[list[dict]] = None


def _load_laws() -> list[dict]:
    """加载清洗后的法律条款到内存"""
    global _laws_cache
    if _laws_cache is not None:
        return _laws_cache
    if not os.path.exists(LAWS_FILE):
        logger.warning("法律条款文件不存在: %s", LAWS_FILE)
        _laws_cache = []
        return _laws_cache
    with open(LAWS_FILE, "r", encoding="utf-8") as f:
        _laws_cache = json.load(f)
    logger.info("已加载 %d 条法律条款到内存", len(_laws_cache))
    return _laws_cache


def _extract_keywords_from_clause(clause_text: str) -> list[str]:
    """从合同条款中提取法律检索关键词"""
    keywords = []

    # 核心法律关键词库
    keyword_map = {
        "违约": ["民法典 合同编 违约责任", "民法典 第577条"],
        "赔偿": ["民法典 第584条 损害赔偿"],
        "解除": ["民法典 合同编 合同解除", "民法典 第563条"],
        "转让": ["民法典 合同编 债权转让", "公司法 股权转让"],
        "股权": ["公司法 股权转让", "公司法 第71条"],
        "采矿": ["矿产资源法 采矿权", "探矿权采矿权转让管理办法"],
        "矿": ["矿产资源法", "探矿权采矿权转让管理办法"],
        "价款": ["民法典 合同编 价款", "民法典 第626条"],
        "支付": ["民法典 合同编 履行", "民法典 第509条"],
        "担保": ["民法典 担保制度", "民法典 第386条"],
        "保证": ["民法典 保证合同", "民法典 第681条"],
        "抵押": ["民法典 抵押权", "民法典 第394条"],
        "质押": ["民法典 质权", "民法典 第425条"],
        "公章": ["公司法 公司印章管理", "民法典 第170条"],
        "法人": ["公司法 法定代表人", "民法典 第61条"],
        "董事会": ["公司法 董事会", "公司法 第67条"],
        "股东会": ["公司法 股东会", "公司法 第66条"],
        "工商": ["公司法 公司登记", "市场主体登记管理条例"],
        "税务": ["税收征收管理法", "企业所得税法"],
        "税": ["税收征收管理法", "企业所得税法"],
        "发票": ["发票管理办法", "税收征收管理法"],
        "知识": ["民法典 知识产权", "专利法", "商标法", "著作权法"],
        "保密": ["反不正当竞争法 商业秘密", "民法典 第501条"],
        "竞业": ["劳动合同法 竞业限制", "反不正当竞争法"],
        "劳动": ["劳动合同法", "劳动法"],
        "仲裁": ["仲裁法", "民事诉讼法 仲裁"],
        "管辖": ["民事诉讼法 管辖", "民事诉讼法 第34条"],
        "不可抗力": ["民法典 第180条 不可抗力", "民法典 第590条"],
        "生效": ["民法典 合同编 合同生效", "民法典 第502条"],
        "终止": ["民法典 合同编 权利义务终止", "民法典 第557条"],
    }

    for kw, laws in keyword_map.items():
        if kw in clause_text:
            keywords.extend(laws)

    return list(set(keywords))  # 去重


def search_laws(query_text: str, top_k: int = 5) -> list[dict]:
    """
    检索与合同条款相关的法律法规。

    策略：
    1. 关键词精确匹配（核心法律词汇 -> 法条映射）
    2. 如果关键词库没有覆盖，用法律名称做模糊匹配

    返回:
        [{ "law_name": "...", "article": "...", "content": "...", "relevance": 0.0 }]
    """
    laws = _load_laws()
    if not laws:
        return []

    keywords = _extract_keywords_from_clause(query_text)

    results = []
    seen = set()

    # 1. 关键词匹配
    for kw in keywords:
        for law in laws:
            law_name = law.get("law_name", "")
            article = law.get("article", "")
            content = law.get("content", "")
            key = (law_name, article)
            if key in seen:
                continue
            # 法条名或内容包含关键词
            if kw in law_name or kw in content:
                seen.add(key)
                results.append({
                    "law_name": law_name,
                    "article": article,
                    "content": content[:500],
                    "status": "现行有效",
                    "relevance": 0.85,
                })

    # 2. 如果关键词没命中，用法律名称模糊搜索
    if not results:
        for law in laws:
            law_name = law.get("law_name", "")
            key = (law_name, law.get("article", ""))
            if key in seen:
                continue
            # 核心法律优先匹配
            core_laws = ["民法典", "公司法", "合同法", "矿产资源法", "担保法", "税收征收管理法"]
            for core in core_laws:
                if core in law_name and len(results) < top_k:
                    seen.add(key)
                    results.append({
                        "law_name": law_name,
                        "article": law.get("article", ""),
                        "content": law.get("content", "")[:500],
                        "status": "现行有效",
                        "relevance": 0.6,
                    })
                    break

    # 按相关性排序，取 top_k
    results.sort(key=lambda x: x["relevance"], reverse=True)
    return results[:top_k]


def search_relevant_laws(contract_text: str, top_k: int = 5) -> list[dict]:
    """
    对完整合同文本进行多段检索，
    从合同中提取关键段落，逐段检索，合并去重
    """
    # 按条款分段
    segments = re.split(r'(?:第[一二三四五六七八九十百千\d]+条|\n\n)', contract_text)
    segments = [s.strip() for s in segments if len(s.strip()) > 20]

    all_results = []
    seen = set()

    for seg in segments[:20]:  # 最多检索20个段落
        results = search_laws(seg, top_k=3)
        for r in results:
            key = (r["law_name"], r["article"])
            if key not in seen:
                seen.add(key)
                all_results.append(r)
        if len(all_results) >= top_k:
            break

    all_results.sort(key=lambda x: x["relevance"], reverse=True)
    return all_results[:top_k]
