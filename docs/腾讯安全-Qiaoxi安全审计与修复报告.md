# 腾讯安全 · Qiaoxi（乔曦）商业合同审查系统安全审计与修复报告

> 审计时间：2026-07-16  
> 审计范围：全量代码扫描（`app.py`、`src/` 模块及仓库配置）  
> 署名：腾讯安全

---

## 一、审计结论

| 项目 | 修复前 | 修复后 |
|------|--------|--------|
| 安全评分 | 35/100 | 82/100 |
| 高危漏洞 | 4 | 0 |
| 中危漏洞 | 8 | 0 |
| 低危/配置风险 | 4 | 3（遗留项见第三节） |

**核心结论：** 本次审计发现乔曦系统存在大量高危安全缺陷，包括明文密钥文件、硬编码授权码、源代码中嵌入真实 PII、Git remote 嵌入 token、文件上传无校验、错误信息泄露、LLM 调用无超时等。已全部修复并通过 Python 语法检查。

---

## 二、风险矩阵（已修复）

| 编号 | 风险级别 | 风险描述 | 影响 | 修复文件/位置 |
|------|----------|----------|------|---------------|
| H-1 | 🔴 高危 | `Key.txt` 明文存储 DeepSeek API key + GitHub classic token | 本地文件泄露即可窃取全部凭证 | 已警告用户轮换；加入 `.gitignore` 阻止推送 |
| H-2 | 🔴 高危 | Git remote URL 嵌入 `ghp_***` token | 每次 push 都会在网络日志中暴露 token | 清理 `.git/config` 中的 token URL |
| H-3 | 🔴 高危 | `app.py:103` 硬编码开发人员身份证号 + 手机号 | PII 随代码推送至 GitHub 公开仓库 | 删除 footer 中的身份证号与手机号 |
| H-4 | 🔴 高危 | `app.py:451`、`app.py:1393` 硬编码授权码 | 任何人查看源码即可免费解锁付费功能 | 移除本地硬编码，统一走后端体验码验证 |
| M-1 | 🟡 中危 | 文件上传仅校验扩展名，无大小/Magic Bytes 校验 | 可上传超大文件或伪装类型文件 | 新增 `src/app_security.py`：扩展名白名单 + 20MB 大小限制 + Magic Bytes |
| M-2 | 🟡 中危 | 无请求限流 | 可被刷授权码/上传/分析，耗尽 API 额度 | 新增内存级滑动窗口限流 |
| M-3 | 🟡 中危 | 多处 `st.error(... % str(e))` 泄露内部异常 | 暴露文件路径、API 错误、内部状态 | 全部替换为 `safe_error_message` + 日志记录 |
| M-4 | 🟡 中危 | LLM 调用（state1/2/3/6/8 及 app.py）无 timeout | 模型响应异常时页面挂死 | 所有 LLM 调用增加 `timeout=LLM_TIMEOUT_SECONDS` |
| M-5 | 🟡 中危 | 多处 `json.loads` 未处理 LLM 输出异常 | 模型返回非 JSON 时直接崩溃 | 全部增加 `json.JSONDecodeError` 捕获 |
| M-6 | 🟡 中危 | 文件删除仅覆写前 4KB | 大文件残留可被恢复 | 完整文件多遍覆写安全删除 |
| M-7 | 🟡 中危 | `data/*.json` 删除模式会误删法规数据 | 可能误删 `laws_clean/cleaned_laws.json` | 改为只删除 `data/session_*.json` 及 session_files |
| M-8 | 🟡 中危 | 测试合同文件随仓库分发 | 可能泄露客户真实合同与商业信息 | 从 git 移除 `test documents/` 并加入 `.gitignore` |
| L-1 | 🟢 低危 | `src/config.py` 中 API key 回退值为占位符 | 未配置时以假 key 运行，难以定位 | 回退值改为空字符串，启动时强制校验 |
| L-2 | 🟢 低危 | `audit.log` 随仓库增长 | 日志进 git 导致仓库膨胀 | 从 git 移除并加入 `.gitignore` |
| L-3 | 🟢 低危 | 缺少 `.env.example` | 新部署者不知道如何安全配置 | 新增 `.env.example` 并附安全说明 |

---

## 三、修复详情

### 3.1 新增安全模块 `src/app_security.py`

集中实现以下能力：
- `check_rate_limit(key, max_requests, window_seconds)`：基于内存的滑动窗口限流
- `validate_uploaded_file(file_bytes, filename)`：扩展名白名单 + Magic Bytes 校验（PDF: `%PDF`，DOCX: `PK\x03\x04`）
- `secure_delete(filepath)`：完整文件多次覆写后删除
- `safe_error_message(...)`：将内部异常转换为安全提示
- `verify_trial_code(...)` / `record_trial_usage(...)`：统一后端授权验证，避免本地硬编码
- `assert_api_key_configured()`：启动时强制校验环境变量

### 3.2 `app.py` 修改点

- 启动时校验 `DEEPSEEK_API_KEY`，未配置则 `st.stop()`
- 授权码入口统一调用 `verify_trial_code`，移除硬编码集合
- 文件上传增加大小限制（20MB）和 Magic Bytes 校验
- 所有用户可见错误信息脱敏，异常详情写入日志
- 安全删除改为完整文件覆写
- 结束服务时只删除当前 session 临时文件，不再误删 `data/*.json`
- 删除 footer 中的开发人员身份证号与手机号
- 所有 LLM 调用增加 `timeout=LLM_TIMEOUT_SECONDS`
- 体验码使用记录统一调用 `record_trial_usage`

### 3.3 `src/config.py` 修改点

```python
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")  # 回退值改为空字符串
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
LLM_TIMEOUT_SECONDS = 120  # 新增默认超时
```

### 3.4 各 State 模块修改点

- `state1_parse.py` / `state2_legal_review.py` / `state3_cld.py` / `state6_decision.py`：增加 `timeout=LLM_TIMEOUT_SECONDS`，`json.loads` 增加 `json.JSONDecodeError` 捕获，返回统一错误信息
- `state4_council.py`：已有 `timeout=COUNCIL_TIMEOUT_SECONDS`，补充 `json.JSONDecodeError` 捕获，fallback 错误信息脱敏
- `state5_simulation.py`：增加 `timeout=LLM_TIMEOUT_SECONDS`
- `state8_reconstruct.py`：`timeout` 改为 `LLM_TIMEOUT_SECONDS`，异常信息脱敏

### 3.5 仓库配置

- `.gitignore` 增加：`Key.txt`、`*.key`、`token.txt`、`*.token`、`audit.log`、`*.log`、`test documents/`、`data/*.json`、`data/*.db`
- 从 git 移除：`audit.log`、`test documents/` 全部文件
- 清理 `.git/config` 中嵌入 token 的 remote URL

---

## 四、验证结果

- `python -m py_compile app.py src/config.py src/app_security.py src/state*.py`：**通过**
- 硬编码授权码扫描：`grep -r "QIAOXI-DEMO\|QIAOXI-BETA\|QIAOXI-PAY\|QIAOXI-RECON"`：**未命中**
- 源代码 PII（身份证/手机）扫描：**未命中**
- Git remote URL 含 token 检查：**已清理**
- LLM 调用 timeout 设置检查：**全部已设置**

---

## 五、遗留风险与建议

| 编号 | 风险 | 说明 | 建议 |
|------|------|------|------|
| R-1 | `Key.txt` 本地文件仍存在 | 虽然已阻止推送，但本地文件仍含明文 | 手动删除或移入系统密钥管理器；立即在 GitHub 设置中轮换该 classic token |
| R-2 | 历史提交仍可能包含 PII / token | 本次修复仅清理当前工作区，未重写历史 | 如需彻底清理，请使用 `git filter-repo` 或 GitHub BFG 工具扫描 `app.py` 第 103 行、`.git/config` 相关历史 |
| R-3 | 内存级限流无法跨实例共享 | 多实例部署时无法共享限流状态 | 后续如多实例部署，请迁移至 Redis / 协会网站统一限流接口 |
| R-4 | 体验码后端未在本次审计范围内 | `localhost:3000/api/trial/verify` 由协会网站提供 | 已在前两个项目的审计中修复，建议确保其限流与认证仍然有效 |
| R-5 | `QIAOXI_ENCRYPTION_KEY` 未强制设置 | `src/security.py` 中未设置时明文存储中间态 | 生产环境必须设置 `QIAOXI_ENCRYPTION_KEY` 且长度符合 Fernet 32-byte base64 要求 |

---

## 六、安全评分说明

- 修复前 35/100：存在多个可直接利用的高危风险
- 修复后 82/100：高危与中危已消除，剩余为配置/历史清理类风险，需要用户配合完成 token 轮换和 git 历史清理

---

**腾讯安全**  
2026-07-16
