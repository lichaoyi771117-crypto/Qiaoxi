"""
Qiaoxi Contract-Analyzer · 安全与合规模块

数据脱敏、AES-256加密、审计日志WORM存储
"""
import re
import json
import copy
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from cryptography.fernet import Fernet
import os

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# PII 脱敏规则库（增强版 — 基于 chengxiaorong 打码器 + 合同场景扩展）
# ═══════════════════════════════════════════════════════════════

# ─── 精确格式脱敏（保留可辨识量级）───

def mask_id_card(id_str: Optional[str]) -> str:
    """身份证: 440301********1234 (保留前6后4)"""
    if not id_str or not isinstance(id_str, str):
        return "" if id_str is None else str(id_str)
    cleaned = id_str.strip()
    if not re.match(r'^\d{17}[\dXx]$', cleaned):
        return id_str
    return cleaned[:6] + "********" + cleaned[-4:]


def mask_phone(phone: Optional[str]) -> str:
    """手机号: 138****5678 (保留前3后4)"""
    if not phone or not isinstance(phone, str):
        return "" if phone is None else str(phone)
    cleaned = phone.strip()
    if not re.match(r'^\d{11}$', cleaned):
        return phone
    return cleaned[:3] + "****" + cleaned[-4:]


def mask_name(name: Optional[str]) -> str:
    """中文姓名: 张* / 张*三 / 张**"""
    if not name or not isinstance(name, str):
        return "" if name is None else str(name)
    cleaned = name.strip()
    if not cleaned:
        return name
    length = len(cleaned)
    if length == 1:
        return "*"
    elif length == 2:
        return cleaned[0] + "*"
    elif length == 3:
        return cleaned[0] + "*" + cleaned[2]
    else:
        return cleaned[0] + "*" * (length - 1)


def mask_bank_card(card: Optional[str]) -> str:
    """银行卡: 6222 **** **** 1234 (保留前4后4)"""
    if not card or not isinstance(card, str):
        return "" if card is None else str(card)
    cleaned = re.sub(r'\s+', '', card.strip())
    if not cleaned.isdigit() or len(cleaned) < 13:
        return card
    return cleaned[:4] + " **** **** " + cleaned[-4:]


def mask_company_name(text: str) -> str:
    """公司名称脱敏: 保留地域前缀，其余打码。如 '昆明霖信莯科技有限公司' -> '云南***有限公司'"""
    # 匹配已知公司名后缀
    suffixes = [
        '有限公司', '有限责任公司', '股份有限公司', '集团有限公司',
        '合伙企业', '事务所', '中心', '厂', '集团',
    ]
    for suffix in sorted(suffixes, key=len, reverse=True):
        if suffix in text:
            idx = text.index(suffix)
            prefix_len = min(2, idx)  # 保留前2字作为地域提示
            prefix = text[:prefix_len] if prefix_len > 0 else text[0]
            return prefix + "***" + suffix
    # 通用：保留前2字
    if len(text) > 4:
        return text[:2] + "***" + text[-2:]
    return text[:1] + "***"


def mask_address(text: str) -> str:
    """地址脱敏: 保留省级，其余打码"""
    provinces = ['北京', '天津', '上海', '重庆', '河北', '山西', '辽宁', '吉林', '黑龙江',
                 '江苏', '浙江', '安徽', '福建', '江西', '山东', '河南', '湖北', '湖南',
                 '广东', '广西', '海南', '四川', '贵州', '云南', '西藏', '陕西', '甘肃',
                 '青海', '宁夏', '新疆', '内蒙古', '香港', '澳门', '台湾']
    for prov in provinces:
        if text.startswith(prov):
            return prov + "***（详情已脱敏）"
    return "某省某市（详情已脱敏）"


# ─── 粗粒度正则批量脱敏 ───

PII_PATTERNS = [
    (re.compile(r'\d{17}[\dXx]|\d{15}'), '[已脱敏-身份证号]'),
    (re.compile(r'1[3-9]\d{9}'), '[已脱敏-手机号]'),
    (re.compile(r'\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4,7}'), '[已脱敏-银行卡]'),
    (re.compile(r'[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}'), '[已脱敏-统一社会信用代码]'),
    (re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'), '[已脱敏-邮箱]'),
]


def sanitize_pii(text: str) -> str:
    """对文本执行粗粒度 PII 正则替换"""
    sanitized = text
    for pattern, replacement in PII_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def deep_sanitize_contract_text(text: str) -> str:
    """
    对合同全文执行深度脱敏:
    1. 粗粒度正则替换（身份证/手机/银行卡/信用代码/邮箱）
    2. 公司名识别与打码
    3. 人名识别与打码
    4. 地址识别与打码
    5. 金额保留量级

    返回：脱敏后的文本，AI 可直接阅读而不会泄露 PII
    """
    if not text:
        return text

    # Step 1: 粗粒度替换
    sanitized = sanitize_pii(text)

    # Step 2: 公司名打码（匹配 "XXX公司" / "XXX有限公司" 等模式）
    company_pattern = re.compile(
        r'[一-鿿()（）•·]{3,30}?(?:有限公司|有限责任公司|股份有限公司|集团有限公司|合伙企业|事务所|集团|厂)'
    )
    seen_companies = {}
    company_counter = [0]

    def replace_company(m):
        original = m.group(0)
        if original not in seen_companies:
            company_counter[0] += 1
            seen_companies[original] = f"【公司{chr(64 + company_counter[0])}】"
        return seen_companies[original]

    sanitized = company_pattern.sub(replace_company, sanitized)

    # Step 3: 中文姓名打码（2-4字中文名，前有/后跟职务词或标点）
    name_pattern = re.compile(
        r'(?:(?:甲方代表|乙方代表|法定代表人|联系人|负责人|授权代表|签字人)[：:]\s*)?'
        r'([一-鿿]{2,4})'
        r'(?=\s*(?:先生|女士|经理|董事|总经理|法人|联系电话|电话|身份证|住址|地址|\n|，|。|$))'
    )
    seen_names = {}
    name_counter = [0]

    def replace_name(m):
        original = m.group(1)
        # 跳过公司名已处理过的文本段
        if original in seen_companies or any(kw in original for kw in ['有限', '责任', '股份', '合伙', '公司']):
            return m.group(0)
        if original not in seen_names:
            name_counter[0] += 1
            seen_names[original] = mask_name(original)
        return m.group(0).replace(original, seen_names[original])

    sanitized = name_pattern.sub(replace_name, sanitized)

    # Step 4: 精确地址打码
    address_pattern = re.compile(
        r'(?:地址|住址|住所|注册地址|办公地址|经营场所)[：:]\s*'
        r'([一-鿿0-9\-号路街巷栋座楼层室]+)'
    )
    sanitized = address_pattern.sub(
        lambda m: m.group(0).replace(m.group(1), mask_address(m.group(1))),
        sanitized,
    )

    # Step 5: 金额保留量级
    def mask_amount(m):
        num = float(m.group(1))
        if num >= 1e8:
            return f'金额X元（亿级）'
        elif num >= 1e7:
            return f'金额X元（千万级）'
        elif num >= 1e6:
            return f'金额X元（百万级）'
        elif num >= 1e4:
            return f'金额X元（万级）'
        return f'金额X元'

    sanitized = re.sub(r'(\d+(?:\.\d+)?)\s*(?:万|亿)?元', mask_amount, sanitized)

    return sanitized


# ─── AES-256 加密层 ───

def get_cipher() -> Optional[Fernet]:
    key = os.environ.get("QIAOXI_ENCRYPTION_KEY", "")
    if not key:
        logger.warning("QIAOXI_ENCRYPTION_KEY 未设置，中间态数据将明文存储")
        return None
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_json(data: dict, cipher: Optional[Fernet] = None) -> bytes:
    if cipher is None:
        cipher = get_cipher()
    plaintext = json.dumps(data, ensure_ascii=False).encode('utf-8')
    if cipher is None:
        return plaintext
    return cipher.encrypt(plaintext)


def decrypt_json(encrypted: bytes, cipher: Optional[Fernet] = None) -> dict:
    if cipher is None:
        cipher = get_cipher()
    if cipher is None:
        return json.loads(encrypted.decode('utf-8'))
    plaintext = cipher.decrypt(encrypted)
    return json.loads(plaintext.decode('utf-8'))


# ─── 审计日志 WORM 存储 ───

class AuditLogger:
    """WORM（一次写入多次读取）审计日志"""

    def __init__(self, log_path: str = "audit.log"):
        self.log_path = Path(log_path)

    def _write(self, entry: dict):
        entry["timestamp"] = datetime.now().isoformat()
        entry["hash"] = hashlib.sha256(
            json.dumps(entry, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def log_state_transition(self, from_state: str, to_state: str):
        self._write({"event": "state_transition", "from": from_state, "to": to_state})

    def log_rag_call(self, success: bool, query_count: int, blocked_abolished: int = 0):
        self._write({"event": "rag_call", "success": success, "query_count": query_count,
                     "abolished_laws_blocked": blocked_abolished})

    def log_council_auditor(self, role: str, success: bool, risk_score: Optional[int] = None,
                            veto: bool = False, timeout: bool = False):
        self._write({"event": "council_auditor", "role": role, "success": success,
                     "risk_score": risk_score, "veto_triggered": veto, "timeout": timeout})

    def log_veto(self, reason: str):
        self._write({"event": "li_chaoyi_veto", "reason": reason[:200]})

    def log_handoff(self, reason: str):
        self._write({"event": "handoff_to_human", "reason": reason[:200]})

    def log_pii_block(self, entity_type: str):
        self._write({"event": "pii_blocked", "entity_type": entity_type})

    def log_user_consent(self, consent_granted: bool):
        self._write({"event": "user_consent", "granted": consent_granted})

    def log_file_deletion(self, filename: str, reason: str = "service_end"):
        self._write({"event": "file_deletion", "filename": filename, "reason": reason})


# ─── 用户授权声明记录 ───

USER_CONSENT_TEMPLATE = """<div style='font-family:"Microsoft YaHei","宋体",SimSun,serif; font-size:14px; line-height:2.0; color:#222; max-width:900px; margin:0 auto;'>

<h2 style='text-align:center; font-size:20px; font-weight:bold; margin-bottom:8px;'>霖信莯咨询 · 合审通·AI商务合同审查<br/>用户授权与服务协议</h2>

<p style='text-align:center; font-size:12px; color:#888; margin-bottom:24px;'>
版本：v1.0 &nbsp;|&nbsp; 更新日期：2026年6月6日 &nbsp;|&nbsp; 生效日期：2026年6月6日<br/>
运营主体：昆明霖信莯科技有限公司（以下简称"霖信莯"或"本公司"） ｜ 开发团队：李超逸、李屹泉
</p>

<div style='background:#fff3e0; border-left:4px solid #e65100; padding:16px; margin:16px 0; border-radius:4px;'>
<p style='font-weight:bold; color:#e65100; margin:0 0 8px 0;'>⚠️ 重要提示</p>
<p style='margin:0;'><b>尊敬的用户</b>：</p>
<p style='margin:4px 0;'>感谢您选择霖信莯咨询开发的合审通·AI商务合同审查系统（以下简称"本系统"或"合审通"）。本系统是一款基于人工智能技术的商业合同审查与决策辅助工具。</p>
<p style='margin:4px 0;'><b style='color:#d32f2f;'>请您在使用本系统之前，仔细阅读并充分理解本协议的全部条款，特别是以加粗、标红、高亮等方式显著标注的条款。您通过网络页面点击勾选或以其他方式确认本协议，即表示您已阅读、理解并同意接受本协议所有条款的约束。如果您不同意本协议的任何条款，请勿使用本系统。</b></p>
<p style='margin:4px 0;'><b style='color:#d32f2f;'>本系统输出的分析报告仅供商业决策参考，不构成正式的法律意见、财务建议或投资建议。如果您需要具有法律效力的专业意见，请咨询持有相应资质的执业律师、会计师或其他专业人士。</b></p>
<p style='margin:4px 0;'><b>本协议适用中华人民共和国法律。</b></p>
</div>

<h3 style='font-size:16px; margin-top:28px; border-bottom:1px solid #ddd; padding-bottom:4px;'>第一条 定义与解释</h3>

<p><b>1.1 本系统</b>：指霖信莯开发并运营的"合审通·AI商务合同审查系统"，包括其全部功能模块、算法模型、用户界面及相关文档。</p>
<p><b>1.2 用户</b>：指通过霖信莯提供的访问途径使用本系统的自然人、法人或非法人组织。本协议中,"用户"与"您"具有相同含义。</p>
<p><b>1.3 合同文件</b>：指用户上传至本系统的 PDF、DOCX 或图片格式的合同文本、协议文件及相关附件。</p>
<p><b>1.4 输出报告</b>：指本系统基于用户上传的合同文件，通过人工智能算法处理后生成的《商业决策报告》及其他分析输出物。</p>
<p><b>1.5 脱敏处理</b>：指本系统在将合同内容发送给人工智能模型（包括但不限于 DeepSeek API）进行分析之前，自动对合同中包含的自然人姓名、公司全称、身份证号、手机号码、银行卡号、统一社会信用代码、精确地址、精确金额数字等个人身份信息（PII）和商业秘密信息进行不可逆的匿名化、模糊化或替代化处理的技术措施。</p>
<p><b>1.6 中间态数据</b>：指本系统在处理合同文件的过程中生成的、介于原始文件与最终输出报告之间的所有临时性结构化数据（包括但不限于 JSON 格式的条款树、审查中间结果等）。</p>
<p><b>1.7 人工智能模型/AI模型</b>：指本系统调用的第三方大语言模型（包括但不限于 DeepSeek API），用于执行合同文本分析、法律风险识别、商业逻辑推理等任务。<b style='color:#c62828;'>AI 模型仅接收经过脱敏处理后的合同内容</b>。</p>
<p><b>1.8 不可抗力</b>：指不能预见、不能避免并不能克服的客观情况，包括但不限于自然灾害（地震、洪水、火灾、台风等）、战争、恐怖袭击、政府行为、法律法规或政策变化、电力中断、电信网络故障、黑客攻击、计算机病毒、AI模型服务中断等超出霖信莯合理控制范围的事件。</p>

<h3 style='font-size:16px; margin-top:28px; border-bottom:1px solid #ddd; padding-bottom:4px;'>第二条 服务内容与范围</h3>

<p><b>2.1 服务内容</b></p>
<p>本系统为用户提供以下商业决策辅助服务：</p>
<ul>
<li>（1）合同文件的自动解析与条款结构提取；</li>
<li>（2）基于中国法律法规数据库（本地 RAG）的法律风险初步标定；</li>
<li>（3）基于商业咨询方法论（系统动力学解构、多角色私董会分析、后果推演）的商业风险识别与杠杆解重构建议；</li>
<li>（4）结构化《商业决策报告》的自动生成。</li>
</ul>

<p><b>2.2 服务范围与限制</b></p>
<p><b>2.2.1</b> 本系统的分析范围限定于用户上传的合同文件的<b>文本层面</b>。本系统不进行事实核查、不验证合同签署方的真实身份或资质、不对合同标的物进行实地勘查或评估。</p>
<p><b>2.2.2</b> 本系统的法律风险识别基于本地存储的中国法律法规数据库。该数据库可能存在更新延迟、覆盖不全或个别条文解读偏差的情况。标注为<b>"【法规待核】"</b>的风险项，表示本系统未能在本地法律法规数据库中检索到充分的法律依据，用户应另行核实。</p>
<p><b>2.2.3 <span style='color:#d32f2f;'>本系统不提供任何形式的正式法律意见、诉讼策略建议、仲裁建议或具有法律约束力的文书。本系统的输出报告在任何情况下均不应被解释为构成律师-客户关系、会计师-客户关系或任何其他专业咨询关系。</span></b></p>
<p><b>2.2.4</b> 本系统当前版本（v0.1 MVP）为最小可行产品（Minimum Viable Product），其中商业模式解构（State 3）、私董会审计（State 4-5）、李超逸最终决策（State 6）等功能模块仍在开发中，以报告中的 "Phase 2 实现" 标注为准。</p>

<p><b>2.3 服务可用性</b></p>
<p>霖信莯将尽商业上合理的努力保障本系统的正常运行，但<b>不对服务的持续性、及时性、无错误或无中断做出任何明示或默示的保证</b>。本系统可能因系统维护、升级、故障、网络问题或第三方服务中断等原因暂时无法使用。</p>

<h3 style='font-size:16px; margin-top:28px; border-bottom:1px solid #ddd; padding-bottom:4px;'>第三条 数据安全与隐私保护</h3>

<p><b>3.1 数据本地化存储</b></p>
<p style='background:#e8f5e9; padding:12px; border-radius:4px;'><b>用户上传的合同文件及所有处理过程中产生的中间态数据，均存储于昆明霖信莯科技有限公司的本地服务器上。霖信莯承诺，未经用户另行书面授权，不会将用户的原始合同文件上传、传输、备份、复制或以任何形式提供至任何第三方云服务平台、外部存储设备或境外服务器。</b></p>

<p><b>3.2 脱敏处理机制（AI 看不见您的真实信息）</b></p>
<p style='background:#fff3e0; padding:12px; border-radius:4px;'><b>这是本系统最核心的安全措施，请用户特别关注：</b></p>
<p>在将合同内容发送给 AI 模型（DeepSeek API）进行分析之前，本系统自动执行以下脱敏处理，且该脱敏为<b>不可逆</b>操作：</p>

<table style='width:100%; border-collapse:collapse; margin:12px 0;'>
<tr style='background:#f5f5f5;'><th style='border:1px solid #ddd; padding:8px; text-align:left;'>信息类型</th><th style='border:1px solid #ddd; padding:8px; text-align:left;'>脱敏方式</th><th style='border:1px solid #ddd; padding:8px; text-align:left;'>示例</th></tr>
<tr><td style='border:1px solid #ddd; padding:8px;'>自然人姓名</td><td style='border:1px solid #ddd; padding:8px;'>部分打码</td><td style='border:1px solid #ddd; padding:8px;'>"张三" → "张*"、"李四明" → "李*明"</td></tr>
<tr><td style='border:1px solid #ddd; padding:8px;'>公司/机构全称</td><td style='border:1px solid #ddd; padding:8px;'>匿名化替换</td><td style='border:1px solid #ddd; padding:8px;'>"昆明霖信莯科技有限公司" → "【公司A】"</td></tr>
<tr><td style='border:1px solid #ddd; padding:8px;'>身份证号</td><td style='border:1px solid #ddd; padding:8px;'>部分打码</td><td style='border:1px solid #ddd; padding:8px;'>"440301199001011234" → "440301********1234"</td></tr>
<tr><td style='border:1px solid #ddd; padding:8px;'>手机号码</td><td style='border:1px solid #ddd; padding:8px;'>部分打码</td><td style='border:1px solid #ddd; padding:8px;'>"13812345678" → "138****5678"</td></tr>
<tr><td style='border:1px solid #ddd; padding:8px;'>银行卡号</td><td style='border:1px solid #ddd; padding:8px;'>部分打码</td><td style='border:1px solid #ddd; padding:8px;'>"6222021234567890" → "6222 **** **** 7890"</td></tr>
<tr><td style='border:1px solid #ddd; padding:8px;'>统一社会信用代码</td><td style='border:1px solid #ddd; padding:8px;'>完全替换</td><td style='border:1px solid #ddd; padding:8px;'>"91530100MA6XXXXXX" → "[已脱敏-统一社会信用代码]"</td></tr>
<tr><td style='border:1px solid #ddd; padding:8px;'>精确地址</td><td style='border:1px solid #ddd; padding:8px;'>模糊化</td><td style='border:1px solid #ddd; padding:8px;'>"云南省昆明市五华区XX路XX号" → "云南省***（详情已脱敏）"</td></tr>
<tr><td style='border:1px solid #ddd; padding:8px;'>精确金额</td><td style='border:1px solid #ddd; padding:8px;'>量级保留</td><td style='border:1px solid #ddd; padding:8px;'>"5000万元" → "金额X元（千万级）"</td></tr>
<tr><td style='border:1px solid #ddd; padding:8px;'>电子邮箱</td><td style='border:1px solid #ddd; padding:8px;'>完全替换</td><td style='border:1px solid #ddd; padding:8px;'>"example@company.com" → "[已脱敏-邮箱]"</td></tr>
</table>

<p style='background:#c62828; color:#fff; padding:12px; border-radius:4px;'><b>霖信莯特别声明：AI 模型（DeepSeek API）在整个分析过程中，仅能接触到上述脱敏后的文本内容。AI 模型无法获知原始合同中包含的任何自然人姓名、公司全称、证件号码、联系方式、精确地址或精确金额。</b></p>

<p><b>3.3 文件自动删除机制</b></p>
<ul>
<li><b>3.3.1</b> 用户每次使用本系统完成一轮合同审查后，可点击"结束服务"按钮。</li>
<li><b>3.3.2</b> 点击"结束服务"按钮后，系统将自动启动<b style='color:#c62828;'>15 秒倒计时</b>。倒计时结束后，系统将执行<b style='color:#c62828;'>shred 级物理删除</b>——即对文件存储区域进行覆写后删除，确保文件内容不可通过数据恢复工具恢复。</li>
<li><b>3.3.3</b> 删除范围包括：用户上传的合同原始文件（PDF/DOCX/图片）、所有中间态 JSON 数据、及本次会话中生成的全部临时文件。</li>
<li><b>3.3.4</b> 即使系统发生意外崩溃或用户未主动点击"结束服务"，系统亦将在<b>合同上传之日起 30 天后</b>自动触发物理删除程序。</li>
<li><b>3.3.5 不删除的内容</b>：系统审计日志（仅记录操作时间、操作类型、是否成功等元数据，<b>不包含合同原文或脱敏后的合同内容</b>）。审计日志采用 WORM（一次写入多次读取）存储，不可篡改，用于系统安全审计和异常追溯。</li>
</ul>

<p><b>3.4 加密存储</b></p>
<p>所有在本地服务器上存储的中间态分析数据（JSON 格式）均使用 <b>AES-256</b> 加密算法进行加密存储。解密密钥通过环境变量注入，不硬编码于系统源代码中，不随源代码一起进行版本管理。</p>

<p><b>3.5 数据传输安全</b></p>
<p>本系统与 AI 模型（DeepSeek API）之间的数据传输采用 <b>TLS 1.3</b> 加密协议。霖信莯仅向 DeepSeek API 发送<b>已经过脱敏处理的合同文本片段</b>，不发送原始合同全文。每次 API 调用完成后，发送的上下文立即释放，不在 DeepSeek 服务器端持久化存储。</p>

<p><b>3.6 无人工查阅</b></p>
<p>在系统自动处理流程中，霖信莯的任何员工、顾问或关联方<b>均不会主动查阅、复制、截取或转发用户上传的原始合同文件</b>。仅在以下例外情形下，经用户明确书面授权，霖信莯授权技术人员可临时访问已脱敏的数据以排查系统故障：</p>
<ul>
<li>（1）用户主动报告系统错误，并书面请求人工介入排查；</li>
<li>（2）系统触发 HANDOFF_TO_HUMAN 机制，且用户选择同意人工顾问介入。</li>
</ul>
<p>上述访问将在问题解决后 24 小时内终止，访问记录将写入审计日志。</p>

<p><b>3.7 用户数据权利</b></p>
<p>用户有权在任何时候：</p>
<ul>
<li>（1）在使用过程中查看本系统正在处理的数据的阶段状态；</li>
<li>（2）点击"结束服务"按钮立即触发数据删除；</li>
<li>（3）通过本协议第十三条列明的联系方式，向霖信莯提交数据查阅、更正或删除的书面请求。</li>
</ul>
<p>霖信莯将在收到书面请求后 <b>15 个工作日内</b>予以响应。</p>

<h3 style='font-size:16px; margin-top:28px; border-bottom:1px solid #ddd; padding-bottom:4px;'>第四条 AI 使用条款</h3>

<p><b>4.1 AI 模型的局限性</b></p>
<p>用户理解并确认，本系统所使用的人工智能技术存在固有的局限性，包括但不限于：</p>
<ul>
<li><b>（1）"幻觉"风险</b>：AI 模型可能生成与事实不符、与法律条文不符或逻辑不一致的内容。尽管本系统已采取本地法规 RAG 检索、正则校验、已废止法律过滤等多重措施来减少幻觉，但仍无法完全消除该风险。</li>
<li><b>（2）训练数据偏差</b>：AI 模型基于特定时间点之前的训练数据，可能无法反映最新的法律法规变化、司法实践动态或行业惯例。</li>
<li><b>（3）非确定性输出</b>：相同的输入可能在不同时间产生不同的输出。AI 模型的输出具有非确定性，霖信莯不对输出的可复现性做出保证。</li>
</ul>

<p><b>4.2 用户自行判断的义务</b></p>
<p style='background:#fff3e0; padding:12px; border-radius:4px;'><b>用户在使用本系统输出的《商业决策报告》时，必须结合自身的商业经验、专业判断和实际情况进行独立评估。本系统的输出在任何情况下均不应被视为对用户决策的替代或免除用户在决策前进行独立尽职调查的义务。</b></p>

<p><b>4.3 禁止的用途</b></p>
<p>用户不得将本系统用于以下目的或场景：</p>
<ul>
<li>（1）生成、传播或协助传播违法、侵权、诽谤、淫秽、歧视性、煽动性或其他违反公序良俗的内容；</li>
<li>（2）自动化决策导致对个人权益产生法律上的重大影响或类似显著影响（根据《中华人民共和国个人信息保护法》第二十四条）；</li>
<li>（3）提供医疗诊断、处方开具、治疗方案选择等可能直接影响人身安全或健康的决策；</li>
<li>（4）任何违反中华人民共和国法律、行政法规、部门规章或地方性法规的活动；</li>
<li>（5）绕过、移除或试图绕过本系统的安全措施（包括但不限于脱敏机制、访问控制、审计日志）。</li>
</ul>
<p>如用户违反上述禁止条款，霖信莯有权立即终止向该用户提供服务，并保留追究其法律责任的权利。</p>

<h3 style='font-size:16px; margin-top:28px; border-bottom:1px solid #ddd; padding-bottom:4px;'>第五条 知识产权</h3>

<p><b>5.1 本系统的知识产权</b></p>
<p>本系统（包括但不限于其源代码、算法设计、架构设计、用户界面设计、Prompt 模板、报告模板、商标、标识、文档等）的全部知识产权及相关权益归属霖信莯所有，受《中华人民共和国著作权法》《中华人民共和国商标法》《中华人民共和国专利法》及相关国际知识产权条约的保护。</p>

<p><b>5.2 用户上传内容</b></p>
<p>用户对其上传的合同文件保留全部原始权利。用户授予霖信莯一项<b>有限的、不可转让的、免许可费的许可</b>，仅用于：</p>
<ul>
<li>（1）在本系统的自动化处理流程中解析、脱敏、分析用户上传的合同文件；</li>
<li>（2）生成并向用户展示分析结果；</li>
<li>（3）在用户点击"结束服务"后按本协议 3.3 条的约定删除数据。</li>
</ul>
<p>本节所述的许可在用户点击"结束服务"或数据自动过期删除后自动终止。</p>

<p><b>5.3 输出报告的权利</b></p>
<p>本系统生成的《商业决策报告》及相关输出物的知识产权归属霖信莯所有。用户有权为了自身的商业决策目的查看、下载、打印、存档该等输出报告，但<b>不得</b>：</p>
<ul>
<li>（1）将输出报告转售、再许可或提供给与本次交易无关的第三方用于商业目的；</li>
<li>（2）声称输出报告构成正式法律意见或专业咨询意见；</li>
<li>（3）将输出报告中的风险评估结果作为向任何第三方主张权利或抗辩的唯一依据。</li>
</ul>

<h3 style='font-size:16px; margin-top:28px; border-bottom:1px solid #ddd; padding-bottom:4px;'>第六条 用户义务与承诺</h3>

<p><b>6.1</b> 用户承诺其为上传的合同文件的合法持有人或已获得合法授权，有权将合同文件提交至本系统进行分析处理。用户上传合同文件的行为不违反其对任何第三方负有的保密义务或合同义务。</p>
<p><b>6.2</b> 用户承诺其上传的合同文件不包含：</p>
<ul>
<li>（1）违反中华人民共和国法律、行政法规、部门规章的内容；</li>
<li>（2）侵犯任何第三方合法权益（包括但不限于知识产权、商业秘密、个人隐私）的内容；</li>
<li>（3）病毒、木马、蠕虫、恶意代码或任何可能干扰、破坏、限制本系统或其他计算机系统功能的程序。</li>
</ul>
<p><b>6.3</b> 用户不得对本系统进行反向工程、反编译、反汇编或试图提取本系统的源代码或算法，不得绕过或试图绕过本系统的安全保护机制（包括但不限于脱敏机制、访问控制、速率限制）。</p>
<p><b>6.4</b> 用户承诺不将本系统用于任何可能违反《中华人民共和国网络安全法》《中华人民共和国数据安全法》《中华人民共和国个人信息保护法》及相关法律法规的用途。</p>

<h3 style='font-size:16px; margin-top:28px; border-bottom:1px solid #ddd; padding-bottom:4px;'>第七条 免责声明</h3>

<p><b>7.1 "按现状"提供</b></p>
<p style='background:#fff3e0; padding:12px; border-radius:4px;'><b>本系统按"现状"（AS IS）和"可提供"（AS AVAILABLE）的基础提供，不作任何形式的明示或默示保证，包括但不限于对适销性、特定用途适用性、不侵权性、准确性、完整性、可靠性、及时性的默示保证。</b></p>

<p><b>7.2 不构成专业意见</b></p>
<p style='background:#ffebee; padding:12px; border-radius:4px;'><b>本系统输出的《商业决策报告》及相关分析内容在任何情况下均不应被解释为：</b></p>
<ul style='background:#ffebee; padding:12px 12px 12px 32px; border-radius:4px; margin-top:-12px;'>
<li><b>（1）正式的法律意见、法律建议或法律文书；</b></li>
<li><b>（2）财务建议、税务建议或投资建议；</b></li>
<li><b>（3）对合同签署、交易执行或不执行的建议或指令。</b></li>
</ul>
<p><b>用户如需获得具有法律约束力的专业意见，应咨询持有相应执业资质的执业律师。用户如需获得专业的财务或税务意见，应咨询持有相应资质的注册会计师或税务师。</b></p>

<p><b>7.3 第三方 AI 模型的免责</b></p>
<p>本系统依赖第三方 AI 模型（DeepSeek API）执行核心分析任务。霖信莯不对 DeepSeek API 的可用性、响应质量、生成内容的准确性或合规性做出任何保证。若因 DeepSeek API 服务中断、降级、变更或停止而导致本系统无法正常提供服务，霖信莯不承担由此产生的任何责任。</p>

<p><b>7.4 责任限制</b></p>
<p style='background:#ffebee; padding:12px; border-radius:4px;'><b>在适用法律允许的最大范围内，霖信莯在任何情况下均不对因使用或无法使用本系统而产生的任何间接损失、附带损失、特殊损失、惩罚性损失或结果性损失承担责任，包括但不限于：</b></p>
<ul style='background:#ffebee; padding:12px 12px 12px 32px; border-radius:4px; margin-top:-12px;'>
<li><b>（1）商业机会损失、利润损失、收入损失、商誉损失；</b></li>
<li><b>（2）数据丢失或损坏（但本协议另有约定或霖信莯故意或重大过失造成的除外）；</b></li>
<li><b>（3）因用户依赖本系统输出而做出的任何商业决策所造成的损失或不利后果；</b></li>
<li><b>（4）任何第三方索赔。</b></li>
</ul>
<p><b>在适用法律允许的最大范围内，霖信莯就本协议项下所有索赔的累计赔偿责任总额，以人民币壹仟元（¥1,000.00）或用户在前十二（12）个月内向霖信莯实际支付的服务费用总额（以较高者为准）为上限。</b></p>

<p><b>7.5 不可抗力</b></p>
<p>因不可抗力导致本系统无法正常提供服务的，霖信莯将在不可抗力影响范围内免于承担违约责任。</p>

<h3 style='font-size:16px; margin-top:28px; border-bottom:1px solid #ddd; padding-bottom:4px;'>第八条 违约责任</h3>

<p><b>8.1</b> 如用户违反本协议第六条的义务与承诺，霖信莯有权：（1）发出书面警告；（2）暂停或终止服务；（3）要求赔偿直接损失（含合理律师费、诉讼费）。</p>
<p><b>8.2</b> 用户同意，因其上传内容违法或侵权导致霖信莯遭受第三方索赔的，用户应赔偿霖信莯全部损失。</p>

<h3 style='font-size:16px; margin-top:28px; border-bottom:1px solid #ddd; padding-bottom:4px;'>第九条 协议的变更与终止</h3>

<p><b>9.1</b> 霖信莯有权根据法律法规变化或业务需要修订本协议。修订版本将在系统界面公示。用户不同意修订的应停止使用；继续使用视为接受。</p>
<p><b>9.2</b> 用户可随时点击"结束服务"终止本协议。霖信莯可在用户严重违约、从事违法活动或决定永久停止服务时（提前30日公告）终止本协议。</p>
<p><b>9.3</b> 本协议终止后，第四条（AI使用条款）、第五条（知识产权）、第七条（免责声明）、第十条（法律适用与争议解决）继续有效。</p>

<h3 style='font-size:16px; margin-top:28px; border-bottom:1px solid #ddd; padding-bottom:4px;'>第十条 法律适用与争议解决</h3>

<p><b>10.1</b> 本协议适用<b>中华人民共和国法律</b>（不包括香港、澳门、台湾地区法律）。</p>
<p><b>10.2</b> 争议应首先友好协商。协商不成的，任何一方有权向<b>昆明霖信莯科技有限公司所在地有管辖权的人民法院</b>提起诉讼。</p>

<h3 style='font-size:16px; margin-top:28px; border-bottom:1px solid #ddd; padding-bottom:4px;'>第十一条 通知与送达</h3>

<p>霖信莯向用户发出的通知可通过系统界面公告或电子邮件发送，发布/发送之日视为送达。用户向霖信莯发出的通知应通过第十三条列明的联系方式送达。</p>

<h3 style='font-size:16px; margin-top:28px; border-bottom:1px solid #ddd; padding-bottom:4px;'>第十二条 其他条款</h3>

<p><b>12.1</b> 本协议构成双方就本协议主题事项达成的完整协议，取代此前所有口头或书面的约定和声明。</p>
<p><b>12.2</b> 霖信莯未行使任何权利不应被视为放弃该等权利。</p>
<p><b>12.3</b> 用户不得未经霖信莯书面同意转让本协议项下权利义务。霖信莯可将本协议转让给其关联公司或业务继承者。</p>
<p><b>12.4</b> 本协议任何条款被认定无效的，不影响其他条款效力。双方应诚信协商以合法有效的替代条款取代原条款。</p>

<h3 style='font-size:16px; margin-top:28px; border-bottom:1px solid #ddd; padding-bottom:4px;'>第十三条 联系方式</h3>

<table style='width:100%; border-collapse:collapse; margin:12px 0;'>
<tr><td style='border:1px solid #ddd; padding:8px; font-weight:bold; width:120px;'>运营主体</td><td style='border:1px solid #ddd; padding:8px;'>昆明霖信莯科技有限公司</td></tr>
<tr><td style='border:1px solid #ddd; padding:8px; font-weight:bold;'>联系人</td><td style='border:1px solid #ddd; padding:8px;'>余磊</td></tr>
<tr><td style='border:1px solid #ddd; padding:8px; font-weight:bold;'>联系电话</td><td style='border:1px solid #ddd; padding:8px;'>13987671259</td></tr>
<tr><td style='border:1px solid #ddd; padding:8px; font-weight:bold;'>电子邮箱</td><td style='border:1px solid #ddd; padding:8px;'>425448719@qq.com</td></tr>
</table>

<hr style='margin:24px 0;'/>

<p style='text-align:center; font-size:12px; color:#888;'>
<b>本协议更新日期：2026年6月6日 &nbsp;|&nbsp; 本协议生效日期：2026年6月6日</b><br/>
&copy; 2026 昆明霖信莯科技有限公司 保留一切权利
</p>

</div>"""
