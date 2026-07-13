# Qiaoxi Contract-Analyzer · 霖信莯咨询 · 商业合同审查与决策重构系统

## 项目概述

Qiaoxi（乔曦）是霖信莯咨询为商业咨询顾问打造的一款 AI 驱动的商业合同审查与决策重构系统。区别于传统合同审查工具（律师视角，输出法律意见书），Qiaoxi 从商业咨询顾问视角出发，输出《商业决策报告》——直接告诉客户"能不能签、怎么改、谈不拢怎么退"。

### 核心方法论：商业咨询五步法
1. **客户画像与利益校准** → 2. **商业模式系统动力学解构** → 3. **核心风险识别（法律+商业+人性）** → 4. **后果推演与不对称性评估** → 5. **杠杆解重构**

### 数字团队：1+6+1
- **乔曦**（法务助理 + 系统主控）：唯一对外人格，State 2 法律初审（强制RAG），报告组装
- **六君子**（6个独立Agent）：State 4 并行独立审查，记忆隔离，一票否决权
- **李超逸**（AI决策者）：State 6 以L1+L2+L3三层蒸馏包注入，四选一决策

## 技术栈（MVP v0.1 · Phase 1 实际实现）

- **框架**：Python + Streamlit（前端/后端一体）
- **合同解析**：PyMuPDF（PDF文本提取）+ 自研条款树正则切分
- **法规RAG**：本地关键词匹配（55,088条款 / 1,132部法律，纯本地 JSON 检索，零外部 API）
- **法规数据**：Chinese-Dataset-Laws（清洗后 24.5MB，仅保留现行有效法律）
- **法律分析**：DeepSeek API（deepseek-chat）——仅做法律推理与自然语言生成，不检索法律
- **脱敏引擎**：正则+关键词匹配，覆盖公司名/人名/身份证/手机/银行卡/信用代码/地址/金额
- **数据存储**：JSON中间态（AES-256加密）+ 审计日志（WORM）
- **部署**：本地Streamlit（MVP阶段）

### 关于开源组件的实际使用情况

设计方案中计划使用 PAKTON（多Agent框架）和 PactGuard-ERNIE-PP（合同解析），在实际 Phase 1 开发中：

1. **PAKTON**（EMNLP 2025, MIT）——未直接改造代码，但提取了其核心设计思路：
   - Archivist 的文档结构化解析 → 对应 State 1 clause_tree
   - Researcher 的 Hybrid RAG 检索管线 → 对应 State 2 本地法规检索
   - Interrogator 的多步推理辩论 → 预留为 Phase 2 六君子串行机制的参考原型
   
2. **PactGuard-ERNIE-PP**（MIT）——未直接改造代码，采用自研替代：
   - PactGuard 的四阶段工作流（解析→分析→建议→渲染）启发了当前架构
   - PactGuard 的版面恢复（PP-StructureV3）因依赖 paddlepaddle ~2.5GB 而暂时不用
   - 当前使用 PyMuPDF（轻量级）+ 自研条款树正则切分替代

3. **claude-legal-skill**（MIT）——已提取 CUAD 41类风险分类 + Red Flags 清单
   - 注入到乔曦 State 2 的法律审查 System Prompt 中

4. **ai-legal-claude**（MIT）——已参考其 5-Agent 并行架构 + 10维风险评分
   - 预留为 Phase 2 六君子 Prompt 设计参考

## 架构（Pipeline 9-State 状态机）

```
State 0: 画像校准 → client_profile.json（零开放输入，封闭式点选）
State 1: 合同解析 → clause_tree.json（PactGuard改造 + 自研条款树）
State 2: 乔曦初审 → jo_legal_review.json（强制触发本地法规RAG）
State 3: 商业模式提取 → cld_report.md（资金流向+权力分配+时间轴）
State 4: 六君子并行审计 → private_board_audits.json（6实例记忆隔离）
State 5: 私董会辩论+推演 → simulation_snapshot.json（推演引擎+交叉比对）
State 6: 李超逸决策 → decision_order.json（L1+L2+L3三层蒸馏包）
State 7: 标准版报告 → final_report.md（8章结构）
State 8: 完整重构方案 → 新合同草案+附件（付费/高级版）
```

## 项目关键决策

1. **开源引擎选型**：PAKTON（多Agent框架，MIT） + PactGuard-ERNIE-PP（合同PDF解析） → 改造适配
2. **合同审查复刻F-Analyzer模式**：国际开源做引擎 + 自建中国适配层
3. **六君子必须物理隔离**：6个独立LLM会话，禁止共享KV Cache/隐藏状态
4. **法规RAG强制触发**：State 2 未调用RAG则Pipeline阻断
5. **推演引擎非Agent**：纯Python确定性函数，禁止LLM生成推演结论
6. **李超逸常驻禁止**：L1+L2+L3仅在State 6注入，防止污染乔曦输出
7. **State 0 零开放输入**：textarea/自由文本框禁止渲染，仅封闭式点选
8. **所有中间态AES-256加密**：密钥由环境变量注入

## 开源组件清单

### 已下载到 source code/ 的核心引擎
| 仓库 | 大小 | 协议 | 用途 |
|------|------|------|------|
| **PAKTON** | 702MB | MIT ✅ | 🥇 核心：多Agent合同分析框架（Archivist/Researcher/Interrogator） |
| **PactGuard-ERNIE-PP** | 53MB | MIT ✅ | 🥈 核心：合同PDF解析+版面恢复+风险分析工作流 |
| **claude-legal-skill** | 1MB | MIT ✅ | 乔曦审查Prompt模板参考（CUAD 41类风险检测） |
| **ai-legal-claude** | 584KB | MIT ✅ | 六君子5并行Agent架构参考+Contract Safety Score |
| **MiroFish-Offline** | 18MB | AGPL ⚠️ | 推演引擎设计思路参考（不直接使用代码） |

### 法规数据库
| 仓库 | 大小 | 内容 | 用途 |
|------|------|------|------|
| **lawtext-laws** | 133MB | 2477部中国法律法规（Markdown） | RAG法规嵌入主库 |
| **Chinese-Dataset-Laws** | 89MB | 3531部（含案例、司法解释、部门规章） | RAG法规补充库+案例检索 |
| **legal_AI_assistant** | 850KB | RAG法律问答参考实现 | RAG管线设计参考 |

### 参考项目（不直接使用代码）
| 仓库 | 原因 |
|------|------|
| **ChatLaw** | AGPL协议，商用受限，仅参考其中文法律LLM思路 |

## 开发路线（MVP）

### Phase 1：基础设施（预计3-5天）
- Streamlit项目框架搭建
- State 0 封闭式画像采集界面（6道点选题 + 硬编码写入）
- State 1 合同解析管线（PactGuard MCP Service改造 + 自研条款树JSON）
- 法规数据库导入ChromaDB（bge-m3 embedding）

### Phase 2：核心管线（预计5-7天）
- State 2 乔曦法律初审（RAG强制触发 + 风险标定JSON输出）
- State 3 商业模式提取（资金流向+权力分配+CLD文本生成）
- State 4 六君子并行（6独立会话 + 记忆隔离 + JSON Schema校验）
- State 5 推演引擎（确定性CLD模拟 + 共识/分歧标记）

### Phase 3：决策与报告（预计3-4天）
- State 6 李超逸决策（L1+L2+L3注入 + 四选一输出 + VETO链路）
- State 7 标准版报告生成（8章模板）
- State 8 重构方案包（可选，MVP可后延）

### Phase 4：打磨交付（预计2-3天）
- 前端Pipeline进度条可视化
- 异常处理与HANDOFF_TO_HUMAN链路
- 审计日志WORM存储
- 数据安全加密 + TTL自动删除
- 煤矿并购案例端到端测试

## API 配置

- DeepSeek API Key 通过环境变量注入，不硬编码
- MVP阶段使用 deepseek-chat 模型
- 后续可切换为 deepseek-v3 或本地部署模型

## 协议合规

所有核心选型组件均为商用友好协议（MIT / Apache 2.0）：
- PAKTON → MIT ✅
- PactGuard-ERNIE-PP → MIT ✅
- claude-legal-skill → MIT ✅
- ai-legal-claude → MIT ✅
- Streamlit → Apache 2.0 ✅
- ChromaDB → Apache 2.0 ✅
- bge-m3 → MIT ✅

ChatLaw (AGPL) 和 MiroFish-Offline (AGPL) 仅作设计思路参考，不直接使用其代码。
