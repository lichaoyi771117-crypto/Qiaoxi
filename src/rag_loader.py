"""
Qiaoxi · 法规数据库清洗与 ChromaDB 导入脚本

数据源：Chinese-Dataset-Laws（主）+ lawtext-laws（辅）
清洗规则：
  1. 仅保留现行有效的法律
  2. 删除已废止法律
  3. 按条款级切分（"第X条" 为分割标记）
  4. bge-m3 Embedding → ChromaDB
"""
import os
import re
import json
import logging
from pathlib import Path
from typing import Generator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 路径配置
CHINESE_DATASET_LAWS = Path("D:/Ai RAG/Qiaoxi/source code/Chinese-Dataset-Laws")
LAWTEXT_LAWS = Path("D:/Ai RAG/Qiaoxi/source code/lawtext-laws/content")
OUTPUT_DIR = Path("D:/Ai RAG/Qiaoxi/data/laws_clean")
CHROMA_DIR = Path("D:/Ai RAG/Qiaoxi/data/chroma_db")

# 核心法律类别优先级（合同审查相关）
PRIORITY_CATEGORIES = [
    "民法典", "民法商法", "经济法", "行政法",
    "司法解释", "行政法规", "部门规章",
]

# 条款切分正则
CLAUSE_PATTERN = re.compile(
    r'(第[一二三四五六七八九十百千\d]+条(?:之一|之二|之三)?)\s*'
    r'(.*?)(?=第[一二三四五六七八九十百千\d]+条(?:之一|之二|之三)?|$)',
    re.DOTALL
)

CHAPTER_PATTERN = re.compile(r'第[一二三四五六七八九十百千\d]+章')

# 已废止关键词
ABOLISHED_KEYWORDS = [
    '已废止', '已失效', '已被取代', '废止', '失效',
    '已被修改', '不再适用',
]

# 关键法律关键词（合同审查相关，至少包含这些）
CORE_LAW_KEYWORDS = [
    '民法典', '合同法', '公司法', '担保法', '物权法',
    '招投标法', '拍卖法', '破产法', '票据法', '保险法',
    '信托法', '证券法', '合伙企业法', '个人独资企业法',
    '消费者权益保护法', '商标法', '专利法', '著作权法',
    '税法', '税收征收管理法', '企业所得税法', '个人所得税法',
    '增值税', '劳动法', '劳动合同法', '安全生产法',
    '环境保护法', '数据安全法', '个人信息保护法',
]


def is_abolished(content: str) -> bool:
    """检测法律文件是否标注已废止"""
    head = content[:2000]  # 检查文件头部
    for keyword in ABOLISHED_KEYWORDS:
        if keyword in head:
            return True
    return False


def extract_law_name(filepath: Path) -> str:
    """从文件路径提取法律名称"""
    name = filepath.stem
    # 移除日期后缀，如 "公司法(2023-12-29)" → "公司法"
    name = re.sub(r'\(\d{4}-\d{2}-\d{2}\)$', '', name)
    return name


def split_clauses(text: str, law_name: str) -> list[dict]:
    """
    按条款切分法律文本

    Returns:
        [{ "law_name": "公司法", "article": "第一条", "content": "...", "chapter": "第一章 总则" }]
    """
    # 提取章节信息
    chapters = CHAPTER_PATTERN.findall(text)
    current_chapter = chapters[0] if chapters else ""

    clauses = []
    matches = CLAUSE_PATTERN.findall(text)
    for article, content in matches:
        content = content.strip()
        if len(content) < 5:  # 跳过过短的片段
            continue
        # 检查是否属于下一个章节
        for ch in chapters:
            if ch in content[:50]:
                current_chapter = ch
        clauses.append({
            "law_name": law_name,
            "article": article.strip(),
            "content": content[:2000],  # 截断超长条款
            "chapter": current_chapter,
        })

    return clauses


def process_chinese_dataset_laws() -> Generator[dict, None, None]:
    """处理 Chinese-Dataset-Laws"""
    logger.info("=== 处理 Chinese-Dataset-Laws ===")

    for category in PRIORITY_CATEGORIES:
        cat_dir = CHINESE_DATASET_LAWS / category
        if not cat_dir.exists():
            continue

        for md_file in cat_dir.glob("*.md"):
            if md_file.name.startswith("_"):  # 跳过索引文件
                continue
            try:
                content = md_file.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                try:
                    content = md_file.read_text(encoding='gbk')
                except Exception:
                    continue

            if is_abolished(content):
                logger.debug(f"跳过已废止: {md_file.name}")
                continue

            law_name = extract_law_name(md_file)
            for clause in split_clauses(content, law_name):
                yield clause

    logger.info("Chinese-Dataset-Laws 处理完成")


def process_lawtext_laws() -> Generator[dict, None, None]:
    """处理 lawtext-laws（补充库）"""
    logger.info("=== 处理 lawtext-laws ===")

    law_dir = LAWTEXT_LAWS / "法律"
    if not law_dir.exists():
        logger.warning("lawtext-laws 法律目录不存在")
        return

    for md_file in law_dir.glob("*.md"):
        if md_file.name.startswith("_"):
            continue
        try:
            content = md_file.read_text(encoding='utf-8')
        except Exception:
            continue

        if is_abolished(content):
            logger.debug(f"跳过已废止: {md_file.name}")
            continue

        # lawtext-laws 文件名是 hash，从内容提取法律名
        first_line = content.split('\n')[0] if content else ""
        law_name = first_line.replace('# ', '').strip()[:50]

        # 仅保留核心法律
        if not any(kw in law_name for kw in CORE_LAW_KEYWORDS):
            continue

        for clause in split_clauses(content, law_name):
            yield clause


def import_to_chromadb(clauses: list[dict]):
    """
    将条款数据导入 ChromaDB

    TODO: Phase 1.5 实现 ChromaDB 导入
    """
    logger.info(f"待导入 ChromaDB: {len(clauses)} 条法律条款")
    # 保存清洗后的 JSON 作为中间态
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / "cleaned_laws.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(clauses, f, ensure_ascii=False, indent=2)
    logger.info(f"清洗后的法律条款已保存至: {output_file}")


def main():
    """主清洗流程"""
    logger.info("开始法规数据库清洗...")

    all_clauses = []

    # 处理 Chinese-Dataset-Laws（主库）
    for clause in process_chinese_dataset_laws():
        all_clauses.append(clause)

    # 处理 lawtext-laws（补充）
    for clause in process_lawtext_laws():
        # 去重：同法律名+同条款号跳过
        key = (clause["law_name"], clause["article"])
        if key not in {(c["law_name"], c["article"]) for c in all_clauses}:
            all_clauses.append(clause)

    logger.info(f"清洗完成: 共 {len(all_clauses)} 条有效法律条款")

    # 统计
    law_names = set(c["law_name"] for c in all_clauses)
    logger.info(f"覆盖法律: {len(law_names)} 部")

    # 导入 ChromaDB
    import_to_chromadb(all_clauses)

    return all_clauses


if __name__ == "__main__":
    main()
