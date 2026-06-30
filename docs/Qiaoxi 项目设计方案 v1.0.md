# Qiaoxi Contract-Analyzer 项目设计方案

> **项目代号**：Qiaoxi（乔曦）  
> **全称**：程信霖咨询 · 商业合同审查与决策重构系统  
> **文档编号**：CHANGR-DESIGN-Qiaoxi-2026001  
> **版本**：v1.0  
> **日期**：2026-06-06  
> **编制**：Claude Code（基于 Kimi PRD v2.0 + 技术约束白皮书 + 数据安全铁律）  
> **状态**：待审核  

---

## 修订记录

| 日期 | 版本 | 修订内容 | 作者 |
|------|------|----------|------|
| 2026-06-06 | v1.0 | 初始版本，基于开源软件调研结果编制 | Claude Code |

---

## 目录

1. [项目定位与设计原则](#一项目定位与设计原则)
2. [技术方案](#二技术方案)
3. [工作流程与标准](#三工作流程与标准)
4. [可交付物](#四可交付物)
5. [数据安全与合规](#五数据安全与合规)
6. [异常处理与转人工](#六异常处理与转人工)
7. [开发路线图](#七开发路线图)
8. [附录](#八附录)

---

## 一、项目定位与设计原则

### 1.1 一句话定位

律师输出《法律意见书》（告诉你有什么风险）；Qiaoxi 输出《商业决策报告》（直接告诉你能不能签、怎么改、谈不拢怎么退）。

### 1.2 设计原则

| 原则 | 来源 | 说明 |
|------|------|------|
| **咨询视角优先** | 原始需求 V2.1 | 商业咨询五步法，非律师逐条审阅 |
| **1+6+1 团队架构** | PRD v2.0 §3 | 8 个独立 AI Agent，严格流水线+决策门 |
| **六君子物理隔离** | 技术约束 §1 | 6 个独立进程/线程，独立 LLM 上下文，禁止共享 |
| **李超逸常驻禁止** | PRD §3.3 | L1+L2+L3 仅在 State 6 注入 |
| **推演引擎非 Agent** | 技术约束 §4 | 纯 Python 确定性计算，禁止 LLM 生成推演结论 |
| **FSM 状态机** | 技术约束 §5 | State 0-8 显式实现，禁用 >3 层嵌套 if-else |
| **本地 RAG 强制** | 技术约束 §2 + PRD §7.2 | ChromaDB + bge-m3 + BM25，禁止外网向量服务 |
| **零开放输入** | PRD §5.1 | State 0 仅封闭式点选，textarea 禁止渲染 |
| **AES-256 加密** | 数据安全铁律 §1 | 绝密/敏感级中间态 JSON 加密存储 |
| **拿来主义** | 原始需求 §5 | 开源引擎 + 自建适配层，不重复造轮子 |

---

## 二、技术方案

### 2.1 总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     Streamlit Web 前端                           │
│  State 0 画像点选 → Pipeline 进度条 → State 7/8 报告展示+下载    │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                     FSM 状态机（State 0-8）                       │
│              transitions 穷举，HANDOFF 条件明确                   │
└──────────────────────────────┬──────────────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
┌───────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  乔曦 Agent   │    │ 六君子 ×6 Agent │    │ 李超逸 Agent    │
│  (主控+法务)  │    │  (State 4 并行) │    │ (State 6 注入)  │
│               │    │  记忆隔离       │    │ L1+L2+L3 蒸馏包 │
└───────┬───────┘    └────────┬────────┘    └────────┬────────┘
        │                     │                      │
        └─────────────────────┼──────────────────────┘
                              │
┌──────────────────────────────▼──────────────────────────────────┐
│                      共享基础设施层                               │
│  ┌──────────┐  ┌──────────────┐  ┌────────────┐  ┌───────────┐ │
│  │ 合同解析  │  │ 本地法规 RAG │  │ 推演引擎   │  │ 审计日志  │ │
│  │ PactGuard │  │ ChromaDB     │  │ 纯 Python  │  │ WORM 存储 │ │
│  │ 改造版    │  │ +bge-m3+BM25 │  │ 确定性计算 │  │           │ │
│  └──────────┘  └──────────────┘  └────────────┘  └───────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 技术栈总览

| 层级 | 选型 | 协议 | 说明 |
|------|------|:----:|------|
| **前端框架** | Streamlit 1.50+ | Apache 2.0 ✅ | Python 全栈，无需前后端分离 |
| **状态机** | Python `transitions` 库 或自建 FSM | MIT | State 0-8 显式实现 |
| **合同文档解析** | PactGuard-ERNIE-PP 改造版 | MIT ✅ | PDF/DOCX/图片解析 + 版面恢复 |
| **多Agent框架** | PAKTON 改造版 | MIT ✅ | Archivist/Researcher/Interrogator 三Agent流水线 |
| **LLM 调用** | OpenAI SDK → DeepSeek API | — | deepseek-chat，统一通过 OpenAI 兼容接口 |
| **向量数据库** | ChromaDB（本地文件型） | Apache 2.0 ✅ | 禁止外网向量服务 |
| **Embedding 模型** | BAAI/bge-m3（本地加载） | MIT ✅ | 禁止调用 OpenAI/Cohere 等外网 Embedding API |
| **精排** | BM25（本地实现） | — | Top-10 → BM25 精排 Top-3 |
| **法规数据源** | lawtext-laws + Chinese-Dataset-Laws | 公共领域 | 合计 6000+ 部中国法律法规 |
| **法规数据格式** | Markdown → txt 切分 → ChromaDB | — | 按条款级切分，标注来源法律+条款号 |
| **推演引擎** | 自建轻量 Python 模块 | — | 参考 MiroFish 逻辑，确定性计算，禁止 LLM |
| **加密** | AES-256（`cryptography` 库） | — | 密钥由环境变量注入 |
| **审计日志** | WORM 文件存储 | — | 不可篡改，不可删除 |

### 2.3 开源引擎选型与改造方案

#### 2.3.1 合同文档解析引擎 —— 基于 PactGuard-ERNIE-PP 改造

**选型理由**：
- MIT 协议，商用友好
- 四阶段工作流（解析→风险分析→建议生成→结果渲染）与 Qiaoxi State 1-2 天然对应
- PP-StructureV3 版面恢复能力对中文合同 PDF 支持好
- MCP Service 独立部署，松耦合

**改造方案**：

| 改造项 | 原实现 | 改造后 | 原因 |
|--------|--------|--------|------|
| **LLM 后端** | ERNIE 4.5（百度） | DeepSeek API（OpenAI 兼容） | 统一 LLM 栈，降低成本 |
| **Prompt 模板** | 通用合同风险识别 | 乔曦专属：中国法规RAG引用 + 法律/商业双维标定 | 适配 Qiaoxi PRD §3.1 |
| **输出 Schema** | 自有 JSON 格式 | `jo_legal_review.json`（PRD §6.4 定义） | 对接 State 2 标准输出 |
| **法规引用** | LLM 自由生成 | 强制触发本地 ChromaDB RAG，代码层正则校验 `《XXX法》第X条` | 技术约束 §2 + PRD §4.1 |
| **MCP Service** | 保留 | 保留，增加合同条款结构化提取 | 产出 `clause_tree.json`（PRD State 1） |
| **paddlepaddle 依赖** | 3.2.1（~2.5GB） | 保留，作为可选 OCR 降级通道 | 扫描件 OCR 置信度 <85% 时触发 |

**改造代码存放**：`D:\Ai RAG\Qiaoxi\modified code\PactGuard-Qiaoxi\`

**改造要点**：
1. `contract_workflow.py` 第 44 行 `default_model = "ernie-4.5-turbo-128k"` → `"deepseek-chat"`
2. `_analyze_risks()` 方法增加 RAG 调用钩子，读取 ChromaDB 检索结果后注入 Prompt
3. 风险 JSON 输出增加 `legal_basis` 字段（法条引用）和 `rag_confidence` 字段（检索置信度）
4. 新增合同条款树（`clause_tree`）结构化提取模块

#### 2.3.2 多 Agent 分析框架 —— 基于 PAKTON 改造

**选型理由**：
- MIT 协议，商用友好
- EMNLP 2025 论文发表，学术验证充分
- 三 Agent 流水线（Archivist/Researcher/Interrogator）与 Qiaoxi 的"文档处理→RAG检索→多步推理辩论"高度同构
- 基于 LangGraph StateGraph，天然支持 FSM 状态机
- Hybrid Dense-Sparse Retrieval + Graph-Aware Reranking 可直接复用到法规 RAG
- 模型无关，可接入任何 LLM

**三 Agent → Qiaoxi 映射**：

| PAKTON Agent | Qiaoxi 映射 | 改造方向 |
|--------------|------------|---------|
| **Archivist**（文档索引） | → State 1-2 合同结构化 + 法条索引 | 增加中文法规 RAG 索引器（ChromaDB + BM25） |
| **Researcher**（多源检索） | → State 2 乔曦初审 RAG 强制触发 | 替换 Wikipedia/Web 检索为本地法规 ChromaDB；增加法条引用校验 |
| **Interrogator**（多步推理辩论） | → State 4-5 六君子并行 + 辩论 | 改造为 6 实例并行 + 匿名化交叉比对；取消写最终报告（留给 State 7） |

**改造方案**：

| 改造项 | 原实现 | 改造后 | 原因 |
|--------|--------|--------|------|
| **LLM 后端** | 可配置（默认 OpenAI） | DeepSeek API | 统一 |
| **Researcher 检索源** | Web + Wikipedia + VectorDB + BM25 + LightRAG | **仅 ChromaDB + BM25**（本地法规 RAG） | 数据安全铁律：禁止外传数据 |
| **Interrogator 并行** | 单实例多步推理 | **6 实例并行**，每实例独立会话 ID | 技术约束 §1：六君子物理隔离 |
| **Interrogator 输出** | 最终法律结论报告 | **独立审计意见书**（每人一份 JSON） | PRD §6.4：六君子独立输出 Schema |
| **Archivist 索引器** | LightRAG + VectorDB | **仅 ChromaDB**（bge-m3 embedding） | 技术约束 §2 |
| **Supabase 认证** | 必需 | **移除**（MVP 无用户系统） | MVP 简化 |
| **Celery 任务队列** | 必需 | **改为线程池**（降低部署复杂度） | MVP 简化 |

**改造代码存放**：`D:\Ai RAG\Qiaoxi\modified code\PAKTON-Qiaoxi\`

#### 2.3.3 Prompt 参考 —— claude-legal-skill + ai-legal-claude

**不直接使用其代码**，而是提取高质量 Prompt 模板注入乔曦和六君子：

| 来源 | 提取内容 | 注入目标 |
|------|---------|---------|
| **claude-legal-skill** skill.md | CUAD 41 类风险分类体系 + Red Flags 12 项清单 + 市场基准对标表 + 文档类型检查清单（NDA/SaaS/M&A/Broker） | 乔曦 State 2 审查 Prompt |
| **ai-legal-claude** agents/legal-risks.md | 10 维风险评分体系（财务暴露/责任转移/限制性条款/模糊条款/缺失保护/单边条款/无限责任/广泛赔偿/自动续约陷阱/管辖权问题） | 六君子（特别是吴慧琼风险审查 + 李艾熹对手盘恶意推演） |
| **ai-legal-claude** agents/legal-clauses.md | 条款分类与结构化提取方法 | 乔曦 State 1 条款树构建 |

### 2.4 法规数据库 RAG 方案

#### 2.4.1 数据源

| 数据源 | 规模 | 格式 | 覆盖范围 | 用途 |
|--------|------|------|---------|------|
| **lawtext-laws** | 2477 部 | Markdown | 国家法律 723 件（有效 347）+ 行政法规 + 司法解释 + 监察法规 | 🥇 主库：RAG 嵌入 |
| **Chinese-Dataset-Laws** | 3531 部 | Markdown | 法律 + 行政法规 + 部门规章 + 司法解释 + 案例 | 🥈 补充库：案例检索 + 部门规章覆盖 |

#### 2.4.2 数据处理流程

```
[原始 Markdown 法规文件]
       ↓
按条款级切分（"第X条" 为分割标记）
       ↓
每条格式化为："《法律名称》第X条 [条款内容]"
       ↓
bge-m3 Embedding → ChromaDB 向量存储
       ↓
BM25 索引构建（用于精排）
```

#### 2.4.3 RAG 检索流程（State 2 强制触发）

```
[合同条款文本]
       ↓
bge-m3 向量检索 → ChromaDB Top-10 候选法条
       ↓
BM25 精排 → Top-3 最相关法条
       ↓
代码层正则校验："《XXX法》第X条" 格式
       ↓
注入乔曦 Prompt → LLM 生成审查意见
       ↓
未匹配成功的标注 "【法规待核】"
已废止的法条主动排除并告警
```

#### 2.4.4 法规数据库约束

- **范围**：中国现行民商法、税法、公司法及司法解释；项目所在省份地方性法规
- **禁用名单**：所有标注"已废止"的法条不得进入上下文；命中则主动排除并告警
- **引用格式**：`《法规名称》第X条第X款（生效状态：现行有效/已废止/待核）`
- **阻断机制**：RAG 服务未成功返回有效上下文 → Pipeline 主动阻断，不允许基于空法规库继续
- **更新方式**：离线脚本替换，不自动拉取，人工审核后替换

### 2.5 推演引擎方案

#### 2.5.1 设计原则

- **纯 Python 确定性函数**，禁止调用 LLM 生成推演结论（技术约束 §4）
- **参考 MiroFish 逻辑**但不使用其代码（AGPL 协议不兼容）
- **MVP 目标**：达到 70% 置信度（用户明确要求）

#### 2.5.2 推演逻辑

```
[State 3 CLD 报告]
       ↓
提取关键变量：
  - 资金变量：支付总额、支付节点、共管金额、对等担保金额
  - 权力变量：公章持有方、股权比例、董事会席位、法人代表
  - 时间变量：签约日、交割日、付款节点日期、合同到期日
       ↓
设定 4 个时间切片：T+3月 / T+6月 / T+12月 / T+36月
       ↓
每个切片运行：
  1. 资金流模拟：按支付节点推算各方累计投入/回收
  2. 权力转移模拟：确权节点 vs 付款节点的时间差分析
  3. 不对称性指标：甲方违约成本 / 乙方违约成本
  4. 压力测试：政策变化 ±20% / 价格波动 ±30%
       ↓
输出《推演快照》（simulation_snapshot.json）
  - 每个时间切片的关键指标变化
  - 风险热力值（1-5）
  - 不对称性拐点标记
```

#### 2.5.3 推演结果置信度评估

| 推演维度 | 确定性程度 | 说明 |
|---------|:--------:|------|
| 资金流向时间序列 | ~90% | 基于合同明确约定的支付节点，确定性高 |
| 权力转移分析 | ~85% | 基于股权/公章/治理结构条款，较为确定 |
| 违约不对称性 | ~75% | 部分依赖对违约概率的估算，有一定不确定性 |
| 政策风险压力测试 | ~50% | 置信度最低，仅作警示性参考 |
| **综合置信度** | **~75%** | 加权平均，超过 70% 目标 |

### 2.6 LLM 选型与配额

| 场景 | 模型 | Token 预算/次 | 说明 |
|------|------|:-----------:|------|
| **乔曦 State 0 交互** | deepseek-chat | ~2K | 清淡模态，引导用户点选 |
| **乔曦 State 2 初审** | deepseek-chat | ~8K-12K | 含 RAG 检索结果注入 |
| **乔曦 State 7/8 报告** | deepseek-chat | ~8K-15K | 报告组装 |
| **六君子 ×6 State 4** | deepseek-chat | 6 × ~8K-12K | 并行调用，独立上下文 |
| **李超逸 State 6** | deepseek-chat | ~4K-6K | L1+L2+L3 蒸馏包注入 |
| **推演引擎** | — | — | 不调用 LLM |

**单次审查预估总 Token**：约 70K-100K 输入（含六君子并行 ×6）

---

## 三、工作流程与标准

### 3.1 FSM 状态机（State 0-8）

> 严格遵循 PRD v2.0 §4 定义。以下仅标注与开源引擎改造相关的技术实现细节。

```
[State 0: 画像校准与接收]
 ├─ 技术实现：Streamlit 前端，封闭式点选组件（radio/selectbox），禁用 textarea
 ├─ 输出：client_profile.json（硬编码写入，不经 LLM 语义解读）
 ├─ 审计字段：system_flags.open_input_used 硬编码为 false
 └─ 退出路径：选择"以上均不符合"→ HANDOFF_TO_HUMAN

[State 1: 文档解析与结构化]
 ├─ 技术实现：PactGuard 改造版 MCP Service + 自研条款树提取
 ├─ PDF → PP-StructureV3 版面恢复 → 结构化文本
 ├─ 条款结构化：按"第X条"/"第X章"/"Section X" 分割 → clause_tree.json
 ├─ OCR 降级：扫描件置信度 <85% → 标红进入 HANDOFF_REVIEW
 └─ 输出：contract_raw.json + clause_tree.json

[State 2: 乔曦初审 + 法规RAG]
 ├─ 技术实现：乔曦 Agent + 本地 ChromaDB RAG（强制触发）
 ├─ RAG 检索：bge-m3 向量检索 Top-10 → BM25 精排 Top-3
 ├─ 引用校验：代码层正则匹配《XXX法》第X条；未匹配→【法规待核】
 ├─ 已废止法条主动排除并告警
 ├─ 输出：jo_legal_review.json（风险等级+法条依据+审查意见）
 └─ 阻断：RAG 服务不可用→ Pipeline 暂停，不基于空法规库继续

[State 3: 商业模式提取与系统动力学建模]
 ├─ 技术实现：LLM 驱动（DeepSeek），从 clause_tree 提取结构化信息
 ├─ 提取维度：资金流向节点、权力分配节点、时间约束节点
 ├─ 生成文本化 CLD（因果回路图描述），标注增强回路(R)/调节回路(B)
 └─ 输出：cld_report.md

[State 4: 私董会第一轮（六君子并行 · 记忆隔离）]
 ├─ 技术实现：PAKTON Interrogator 改造版 ×6 实例并行
 ├─ 每实例独立会话 ID，独立 LLM 上下文，禁止共享 KV Cache
 ├─ 输入（每人可见）：clause_tree + jo_legal_review + cld_report + PII脱敏
 ├─ 输入（彼此不可见）：其他君子的输出
 ├─ 输出格式（人均必填）：risk_score(1-5) + veto_triggered(bool) + audit_summary
 ├─ 覆盖规则：任一君子 veto_triggered==true → State 5 置顶呈报
 └─ 输出：private_board_audits.json（6 份独立审计意见书数组）

[State 5: 私董会第二轮（推演与辩论）]
 ├─ 技术实现：
 │   ├─ 推演引擎（纯 Python）：基于 CLD 运行 3/6/12/36 月时间轴模拟
 │   └─ 质询合成器（LLM）：六人意见匿名化后交叉比对
 ├─ 共识标记：≥4 人独立识别同一风险 → "高置信共识"
 ├─ Minority View：1-2 人识别 → 单独标注
 └─ 输出：simulation_snapshot.json + 《私董会研讨纪要》

[State 6: 李超逸决策]
 ├─ 技术实现：乔曦上下文注入 L1+L2+L3 三层蒸馏 Prompt 包
 ├─ L1（代码层硬编码）：六戒律触发器，if-then 逻辑
 ├─ L2（<800 tokens）：人格核，四选一决策风格
 ├─ L3（<1000 tokens）：合同并购专用规则
 ├─ 三条绝对禁区触发 → 直接输出"否决/重写"，跳过性价比计算
 ├─ 用户拒绝 VETO → 立即 HANDOFF_TO_HUMAN
 └─ 输出：decision_order.json（四选一标签 + ≤3句硬核依据）

[State 7: 报告生成（标准版）]
 ├─ 技术实现：乔曦整合 State 2-6 输出，渲染标准版 8 章
 ├─ 模态：锋锐模态（审查结论）+ 清淡模态（引言/结尾）
 └─ 输出：final_report.md + 用户交互 → Y/N 进入 State 8

[State 8: 完整重构（高级版）]
 ├─ 技术实现：方案重构引擎 + 合同模板库（积木化）
 ├─ 双轨交付：锋锐（条款重构+路线图）+ 清淡（风险提示叙事）
 └─ 输出：《重构解决方案包》（新合同草案+附件）
```

### 3.2 六君子并行实现标准

| 约束项 | 实现方式 |
|--------|---------|
| **进程隔离** | 6 个独立 LLM 会话，通过 `thread_id` / `session_id` 硬隔离 |
| **输入脱敏** | PII 正则规则库前置替换（自然人姓名→甲方/乙方，公司名→公司A/B，金额→金额X元，证件→[已脱敏]） |
| **超时阈值** | 统一 120 秒，超时重试 1 次，再超则触发 HANDOFF_TO_HUMAN |
| **输出校验** | JSON Schema 校验：`veto_triggered`（布尔）+ `risk_score`（1-5 整数）；缺字段→回退重新生成 |
| **禁止 Groupthink** | 第一轮六人输出彼此不可见，仅乔曦可读取全部 |

### 3.3 Pipeline 中间态数据管理

| 资产名 | 生成 State | Consumers | 加密级别 | 保留策略 |
|--------|------------|-----------|:------:|----------|
| `client_profile.json` | State 0 | 1-8 | 绝密 | 永久 |
| `contract_raw.json` | State 1 | 2-8 | 绝密 | 30天 |
| `clause_tree.json` | State 1 | 2-8 | 绝密 | 30天 |
| `jo_legal_review.json` | State 2 | 3-8 | 敏感 | 30天 |
| `cld_report.md` | State 3 | 4-8 | 敏感 | 30天 |
| `private_board_audits.json` | State 4 | 5-8 | 敏感 | 30天 |
| `simulation_snapshot.json` | State 5 | 6-8 | 敏感 | 30天 |
| `decision_order.json` | State 6 | 7-8 | 敏感 | 永久 |
| `final_report.md` | State 7/8 | 用户 | 敏感 | 永久 |
| 审计日志 | 全部 | — | 公开 | **永久（WORM）** |

### 3.4 协作规范（继承自 PRD + 协作规范 2.0）

- 唯一对外人格：**乔曦（Qiaoxi）**，禁止暴露内部子人格原始代号
- 李超逸非系统内部 Agent，是决策宪法来源；禁止物化表述（禁止"调用李超逸""李超逸接口"）
- 乔曦全链路统一采用结构化专业顾问风格（继承自协作规范 2.0 §6.1）
- 六君子之间上下文绝对隔离（继承自协作规范 2.0 §3.2）
- 推演引擎为系统级代码模块，非 Agent 角色（继承自协作规范 2.0 §3.4）

---

## 四、可交付物

### 4.1 标准版报告结构（State 7，8 章）

> 章节标题与内容规范已锁定，禁止 Agent 擅自增删章节或调换顺序（PRD §6.2）

**引言（乔曦 · 清淡模态）**
- 绑定用户画像中的 `anxiety_focus` 与 `trauma_tags`
- 专属情境叙事，结尾留白

**第 1 章：项目总览**
- 合同名称、版本号、交易类型、合同金额（人民币）、合同期限、关键时间节点、已披露附件清单

**第 2 章：利益相关方与核心诉求**
- 基于 `interest_weights` 绘制客户利益雷达图（文本描述）
- 交易对手方已知信息摘要

**第 3 章：商业模式解构（系统动力学 CLD）**
- 文本化因果回路图描述，标注增强回路（R）与调节回路（B）
- 资金流向主链路、权力分配节点、履约时间轴

**第 4 章：法律风险摘要（乔曦初审结果）**
- 按风险等级（高/中/低）降序排列
- 每项必须包含：`风险点简述`、`关联法条及生效状态`、`可能后果量化`、`乔曦建议动作`
- 法条引用格式强制：`《法规名称》第X条第X款（生效状态：现行有效/已废止/待核）`

**第 5 章：商业与人性风险透视（私董会研讨结论）**
- 高置信共识（≥4 人独立识别）优先呈报
- Minority View（1-2 人识别）单独标注
- 推演快照摘要：3/6/12/36 个月局势变化关键节点
- 李艾熹对手盘恶意推演结论（若触发）

**第 6 章：Top 3 重构建议与李超逸决策**
- ≤3 条杠杆解建议，每条指明：重构点、预期效果、实施难度、剩余风险
- 李超逸四选一决策标签：`**决策：接受 / 不接受 / 部分接受需修改 / 彻底推翻重写**`
- 决策依据 ≤3 句话，硬核无修饰

**第 7 章：风险提示与保留条款（系统免责声明）**
- 本报告为商业决策支持，不构成正式法律意见或投资建议
- 保留事项清单：未验证假设、待核法规、需客户补充的资料

**结尾（乔曦 · 清淡模态）**
- 专属细节回响 `trauma_tags` 与 `anxiety_focus`，形成情感闭环
- 留白结尾，不总结、不多言

### 4.2 高级版重构方案包结构（State 8，8 章）

**第 1-4 章**：同标准版

**第 5 章：商业模式问题深度诊断**
- 问题根因层定位

**第 6 章：重构方案决策**
- 杠杆解原则阐述（≤3 条）；李超逸指令：否决/重写/修改的具体原则

**第 7 章：新合同草案**
- 逐条修改处用**红色标注**
- 每处修改附注修改依据（引用戒律/私董会成员意见/推演快照编号）
- 新增条款标注新增原因+风险提示

**第 8 章：下一步行动路线图**
- Gantt 式文本描述：谈判节点、交割先决条件、资料补充清单、再次审查触发条件

**附录**
- 附录 A：术语对照表
- 附录 B：决策依据索引

### 4.3 结构化 JSON 输出（管线中间态）

#### client_profile.json（State 0）

完整 Schema 见 PRD v2.0 §5.2。关键字段：
- `basic_info`：`client_name`, `industry`（enum: mining/manufacturing/tech/energy/real_estate/other）, `counterparty_name`, `transaction_type`（enum: equity_acquisition/asset_acquisition/joint_venture/debt_restructuring/service_agreement/other）, `contract_value_cny`, `contract_duration_months`
- `strategic_layer`：`interest_weights`（control/cashflow/tax/time）, `trauma_tags`, `anxiety_focus`
- `tactical_layer`：`risk_appetite`, `max_loss_pct`, `position`, `batna_strength`, `compromise_dims`, `hard_lines`
- `system_flags`：`open_input_used`（硬编码 false）, `handoff_triggered`, `confidence_score`

#### jo_legal_review.json（State 2）

```json
{
  "contract_meta": { "title": "...", "type": "...", "value_cny": 0 },
  "clauses_analyzed": 0,
  "risks": [
    {
      "clause_id": "string",
      "risk_level": "high | medium | low",
      "risk_category": "string",
      "description": "string",
      "legal_basis": "《法规名称》第X条第X款（生效状态：现行有效）",
      "rag_confidence": 0.0,
      "consequence_quantified": "string",
      "suggested_action": "string"
    }
  ],
  "pending_verification": ["【法规待核】条款"],
  "rag_triggered": true,
  "rag_query_count": 0,
  "abolished_laws_blocked": 0
}
```

#### 六君子独立输出（State 4，人均一份）

```json
{
  "auditor_role": "value_investor | cfo_risk | industry_architect | deal_engineer | operations | risk_philosopher",
  "audit_summary": "string",
  "risk_score": { "type": "integer", "minimum": 1, "maximum": 5 },
  "veto_triggered": { "type": "boolean" },
  "veto_reason": "string (if veto_triggered=true)",
  "target_clauses": ["clause_id_1", "clause_id_2"],
  "recommendations": ["string"],
  "unique_tool_output": {
    "tool_name": "资金安全边际测算表 | 不对称性检测清单 | 行业尽调缺口分析 | 资金-权利映射表 | 运营控制权检查点 | 对手盘恶意推演 | 杠铃策略建议",
    "tool_data": {}
  }
}
```

#### decision_order.json（State 6）

```json
{
  "decision": "accept | reject | partial_accept | full_rewrite",
  "decision_basis": ["≤3 条硬核依据"],
  "veto_items": ["触发的戒律或禁区"],
  "reconstruction_principles": ["≤3 条重构原则（仅 partial_accept / full_rewrite 时）"],
  "handoff_recommended": false
}
```

### 4.4 前端用户可见交付物

| 交付物 | 格式 | 说明 |
|--------|------|------|
| **State 0 画像采集界面** | Streamlit Web | 6 道封闭式点选题，禁止 textarea |
| **Pipeline 进度条** | Streamlit 组件 | 9 步进度，实时显示当前 State |
| **标准版报告** | Web 内展示 + Markdown 下载 | 8 章完整结构 |
| **高级版重构方案** | Web 内展示 + DOCX 下载 | 8 章 + 新合同草案（红色标注修改处） |
| **推演快照可视化** | 文本化时间轴 + 风险热力描述 | 4 个时间切片 |
| **线下联系入口** | 页面底部固定 | 程信霖咨询联系方式 |

---

## 五、数据安全与合规

### 5.1 数据三级分类

完全继承《数据安全铁律（MVP 版）》§1 的分类标准。

| 级别 | 数据范围 | 处理规则 |
|------|----------|----------|
| **绝密** | 合同原文、client_profile、工商查询原始回包 | 永不离开本地运行环境，不上传任何第三方云 |
| **敏感** | 中间态 JSON、审计日志分析摘要、六君子输出 | AES-256 加密存储，最小权限访问 |
| **公开** | 报告模板、Prompt 模板、系统配置枚举值 | 明文存储，版本控制管理 |

### 5.2 六君子输入脱敏规则

完全继承《数据安全铁律（MVP 版）》§2。

| 实体类型 | 脱敏动作 | 示例 |
|----------|----------|------|
| 自然人姓名 | 替换为 `甲方`/`乙方`/`丙方` | `"张三"` → `"甲方代表"` |
| 公司/机构名 | 替换为 `公司A` / `公司B` | `"程信霖咨询"` → `"甲方"` |
| 金额数字 | 替换为 `金额X元`，保留量级 | `"5000万元"` → `"金额X元（千万级）"` |
| 证件/账号 | 正则匹配后替换为 `[已脱敏]` | 身份证、手机号、银行账号 |
| 地址/地块 | 替换为 `某省某市` | 精确地址模糊化 |

PII 正则规则库本地维护，匹配失败则**阻断进入 State 4**。

### 5.3 TTL 自动删除

完全继承《数据安全铁律（MVP 版）》§3。

| 数据类型 | 保留期限 | 动作 |
|----------|----------|------|
| 合同原文（PDF/DOCX/图片） | 任务完成/取消后 30 天 | `shred` 级物理删除，不可恢复 |
| 中间态 JSON（绝密/敏感） | 任务完成/取消后 30 天 | 同上 |
| `handoff_snapshot` | 人工恢复后即时删除，或 90 天无操作删除 | 同上 |
| 审计日志 | **永久** | 只读，不可改，不可删（WORM） |

### 5.4 审计日志（强制留痕）

完全继承《数据安全铁律（MVP 版）》§4。以下事件强制落盘 **WORM** 存储：

- State 转换（含时间戳与方向）
- 六君子 Agent 调用/返回/超时
- 李超逸 Veto 事件（含理由摘要）
- RAG 调用成功/失败/阻断
- HANDOFF_TO_HUMAN 触发与恢复
- 数据脱敏命中/失败记录

### 5.5 对外安全

- 传输层：本地 Streamlit 服务，MVP 阶段不对外暴露
- 静态数据：AES-256 加密，解密密钥由环境变量注入，不硬编码于仓库
- LLM 调用：仅向 DeepSeek API 发送脱敏后的条款文本（非完整合同原文）；六君子收到的材料已预先 PII 脱敏

---

## 六、异常处理与转人工

完全继承 PRD v2.0 §8 和协作规范 2.0 §8。

### 6.1 HANDOFF_TO_HUMAN 触发条件

| 场景 | 触发 State | 系统行为 |
|------|------------|----------|
| State 0 开放输入被拦截 | 0 | 拒绝写入，记录审计日志，提示用户点选 |
| 用户选择强制退出项 | 0 | 立即终止，不生成 profile |
| 澄清分支反复切换 ≥3 次或超时后仍不匹配 | 0 | 转人工，流程终止 |
| 用户明确拒绝接受李超逸 VETO | 6 | 转人工，流程暂停 |
| 法规 RAG 服务完全不可用 | 2 | 暂停 Pipeline，空法规库禁止继续 |
| LLM 调用连续失败 ≥3 次重试 | 任意 | 锁定中间态，转人工排查 |

### 6.2 中间态锁定

触发 HANDOFF 后：
- 当前 State 上下文冻结，生成 `handoff_snapshot`
- 人工顾问获得只读全景视图 + 可写干预通道
- 人工指令：`RESUME`（继续）/ `TERMINATE`（终止）/ `PATCH`（修复后指定下一 State）

---

## 七、开发路线图

### 7.1 MVP 阶段划分

```
Phase 1 ──── Phase 2 ──── Phase 3 ──── Phase 4
基础设施     核心管线      决策与报告     打磨交付
(3-5天)      (5-7天)       (3-4天)       (2-3天)
```

### Phase 1：基础设施（预计 3-5 天）

| 任务 | 说明 | 预估 |
|------|------|:--:|
| Streamlit 项目框架搭建 | 参考 F-Analyzer 的 app.py 结构 | 0.5天 |
| FSM 状态机实现 | State 0-8 枚举 + transitions + HANDOFF 条件 | 1天 |
| State 0 画像采集界面 | 6 道封闭式点选题 + 硬编码写入 client_profile.json | 1天 |
| PactGuard 改造 | LLM后端→DeepSeek，MCP Service 本地化部署 | 1天 |
| State 1 合同解析管线 | PDF→结构化文本 + clause_tree 提取 | 1天 |
| 法规数据库导入 ChromaDB | lawtext-laws + Chinese-Dataset-Laws → 条款级切分 → bge-m3 embedding | 0.5天 |

### Phase 2：核心管线（预计 5-7 天）

| 任务 | 说明 | 预估 |
|------|------|:--:|
| State 2 乔曦法律初审 | RAG 强制触发 + 风险标定 JSON + 法条引用校验 + 已废止过滤 | 1.5天 |
| State 3 商业模式提取 | 资金流向+权力分配+CLD 文本生成 | 1天 |
| PAKTON Interrogator 改造 | 6 实例并行改造 + 记忆隔离 + 六君子 Prompt 注入 | 1.5天 |
| State 4 六君子并行 | 6 独立会话 + 输出 JSON Schema 校验 + 脱敏前置 | 1天 |
| State 5 推演引擎 | 纯 Python CLD 模拟 + 4 时间切片 + 共识/分歧标记 | 1天 |

### Phase 3：决策与报告（预计 3-4 天）

| 任务 | 说明 | 预估 |
|------|------|:--:|
| State 6 李超逸决策 | L1+L2+L3 蒸馏包注入 + 四选一 + VETO 链路 | 1天 |
| State 7 标准版报告 | 8 章模板 + 乔曦双模态输出 | 1天 |
| State 8 重构方案包 | 合同模板库 + 新合同草案生成（MVP 可后延） | 1-2天 |
| 报告前端展示 | Web 内渲染 + Markdown 导出 + 页面底部联系入口 | 0.5天 |

### Phase 4：打磨交付（预计 2-3 天）

| 任务 | 说明 | 预估 |
|------|------|:--:|
| Pipeline 进度条可视化 | 9 步进度，实时 State 显示 | 0.5天 |
| HANDOFF_TO_HUMAN 链路 | 中间态锁定 + 人工指令接口 | 0.5天 |
| 审计日志 WORM 存储 | 强制留痕事件落盘 | 0.5天 |
| 数据安全加密 | AES-256 + 环境变量密钥 + TTL 删除 | 0.5天 |
| 煤矿并购案例端到端测试 | 用《合作意向协议-20260604》完整跑通 State 0-7 | 1天 |

**MVP 总预估**：13-19 天（对比 F-Analyzer 的 ~19 天工期，合理）

### 7.2 验证里程碑

| 里程碑 | 验证标准 |
|--------|---------|
| Phase 1 完成 | State 0-1 跑通：上传合同 PDF → 输出 clause_tree.json |
| Phase 2 完成 | State 2-5 跑通：clause_tree → 乔曦报告 + 六君子审计 + 推演快照 |
| Phase 3 完成 | State 6-7 跑通：完整《商业决策报告》生成 |
| Phase 4 完成 | 煤矿并购案例端到端测试通过，8 章报告质量达标 |

---

## 八、附录

### 附录 A：开源组件协议合规清单

| 组件 | 协议 | 商用风险 | 确认状态 |
|------|------|:--------:|:--------:|
| **PactGuard-ERNIE-PP**（改造） | MIT | 无风险 | ✅ |
| **PAKTON**（改造） | MIT | 无风险 | ✅ |
| **claude-legal-skill**（Prompt 参考） | MIT | 无风险 | ✅ |
| **ai-legal-claude**（Prompt 参考） | MIT | 无风险 | ✅ |
| **lawtext-laws**（法规数据） | 公共领域（法律法规） | 无风险 | ✅ |
| **Chinese-Dataset-Laws**（法规数据） | 公共领域（法律法规） | 无风险 | ✅ |
| **Streamlit** | Apache 2.0 | 无风险 | ✅ |
| **ChromaDB** | Apache 2.0 | 无风险 | ✅ |
| **bge-m3** | MIT | 无风险 | ✅ |
| **DeepSeek API** | 商用 API | 按量付费 | ✅ |
| **ChatLaw** | AGPL-3.0 | ⚠️ 仅作参考，不使用代码 | ⚠️ |
| **MiroFish-Offline** | AGPL-3.0 | ⚠️ 仅作思路参考，不使用代码 | ⚠️ |

### 附录 B：技术约束对照表

| 技术约束白皮书条款 | 设计方案对应 |
|-------------------|-------------|
| §1 六君子物理隔离 | §2.3.2 PAKTON Interrogator 改造为 6 实例并行，独立会话 ID |
| §2 本地 RAG 技术栈 | §2.4 ChromaDB + bge-m3 + BM25，禁止外网向量服务 |
| §3 中间态存储与加密 | §3.3 Pipeline 中间态 AES-256 加密 |
| §4 推演引擎非 Agent | §2.5 纯 Python 确定性函数 |
| §5 State 机实现 | §3.1 FSM 显式实现 |

### 附录 C：PRD 关键约束对照表

| PRD 约束 | 设计方案对应 |
|----------|-------------|
| §3.1 乔曦 Prompt 核心约束 | §2.3.1 PactGuard Prompt 模板改造：禁止引用已废止法律+RAG强制+禁止商业判断 |
| §3.2 六君子一票否决项 | §2.3.3 注入 ai-legal-claude 10 维风险评分 + 六君子专属工具 |
| §3.3 李超逸三层蒸馏包 | §3.1 State 6 技术实现 |
| §5.1 零开放输入 | §3.1 State 0 技术实现 |
| §8.1 HANDOFF 条件 | §6.1 六类触发场景 |

### 附录 D：与 F-Analyzer 开发模式对照

| F-Analyzer | Qiaoxi |
|------------|--------|
| MinerU → PDF 解析 | **PactGuard 改造版** → 合同 PDF 解析 |
| FinanceToolkit → 指标计算引擎 | **PAKTON 改造版** → 多 Agent 分析框架 |
| 自建 AccountingMapper（80+ 科目） | **自建法规 RAG Prompt 模板** + 乔曦审查规则 |
| 自建 QualityChecker（4 项检查） | **自建条款完整性校验**（空白字段/缺失附件/已废止法条过滤） |
| DeepSeek API → LLM 报告 | **DeepSeek API** → 乔曦 + 六君子 + 李超逸 |
| Streamlit → Web 前端 | **Streamlit** → Qiaoxi 前端 |
| 自研解析引擎（6 种报表格式） | **自研合同条款树提取器**（适应不同合同排版） |

---

> **文档结束**  
> 本文档待李超逸审核。审核通过后进入审计阶段，审计通过后启动 Phase 1 开发。
