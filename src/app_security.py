"""
Qiaoxi Streamlit 应用安全加固模块
"""
import hashlib
import os
import time
from typing import Optional
import requests as _requests


# ─── 请求限流（内存级，适合单实例 Streamlit） ───
_rate_limit_store = {}


def check_rate_limit(
    key: str,
    max_requests: int = 10,
    window_seconds: int = 60,
) -> bool:
    """
    基于 key 的滑动窗口限流。
    返回 True 表示允许，False 表示被限流。
    """
    now = time.time()
    window = _rate_limit_store.setdefault(key, [])
    # 清理过期记录
    cutoff = now - window_seconds
    while window and window[0] < cutoff:
        window.pop(0)
    if len(window) >= max_requests:
        return False
    window.append(now)
    return True


# ─── 文件上传 Magic Bytes 校验 ───
_ALLOWED_EXTENSIONS = {".pdf", ".docx"}
_MAGIC_BYTES = {
    ".pdf": [(b"%PDF", 0)],
    ".docx": [(b"PK\x03\x04", 0)],  # DOCX/XLSX/PPTX 等 Office Open XML 都是 ZIP/PK 开头
}


def validate_uploaded_file(file_bytes: bytes, filename: str) -> tuple[bool, Optional[str]]:
    """
    校验上传文件：扩展名白名单 + Magic Bytes。
    返回 (is_valid, error_message)。
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext not in _ALLOWED_EXTENSIONS:
        return False, f"不支持的文件格式：{ext}，仅支持 PDF 或 DOCX"

    magic_list = _MAGIC_BYTES.get(ext, [])
    if not magic_list:
        return False, f"未配置 Magic Bytes 校验：{ext}"

    for magic, offset in magic_list:
        if len(file_bytes) >= offset + len(magic) and file_bytes[offset:offset + len(magic)] == magic:
            return True, None

    return False, "文件内容与实际扩展名不符，请上传真实的 PDF/DOCX 文件"


# ─── 安全擦除 ───
def secure_delete(filepath: str, passes: int = 3) -> None:
    """
    安全删除文件：多次覆写完整文件内容后删除。
    """
    if not os.path.exists(filepath):
        return
    try:
        size = os.path.getsize(filepath)
        if size > 0:
            with open(filepath, "r+b") as f:
                for _ in range(passes):
                    f.seek(0)
                    f.write(os.urandom(size))
                    f.flush()
                    os.fsync(f.fileno())
        os.unlink(filepath)
    except Exception:
        # 即使覆写失败也尝试删除，避免文件残留
        try:
            os.unlink(filepath)
        except Exception:
            pass


# ─── 错误信息脱敏 ───
def safe_error_message(_error: Exception, public_msg: str = "操作失败，请稍后重试或联系客服") -> str:
    """
    将内部异常转换为对前端用户安全的提示。
    """
    return public_msg


# ─── 授权码验证（统一走后端 API，不再本地硬编码） ───

def verify_trial_code(code: str, product: str = "qiaoxi") -> dict:
    """
    向本地协会网站验证体验码。返回后端原始响应，调用方处理 UI 提示。
    失败时返回统一错误结构，不泄露内部异常。
    """
    try:
        resp = _requests.post(
            "http://localhost:3000/api/trial/verify",
            json={"code": code},
            timeout=5,
        )
        data = resp.json()
        if data.get("valid") and data.get("remaining", {}).get(product, 0) > 0:
            return {"valid": True, "remaining": data.get("remaining", {})}
        return {"valid": False, "error": data.get("error", "体验码无效或额度已用完")}
    except Exception:
        return {"valid": False, "error": "授权验证服务暂不可用，请稍后重试或联系客服"}


def record_trial_usage(code: str, product: str = "qiaoxi") -> dict:
    """
    记录体验码使用。失败时返回统一错误结构。
    """
    try:
        resp = _requests.post(
            "http://localhost:3000/api/trial/use",
            json={"code": code, "product": product},
            timeout=5,
        )
        data = resp.json()
        if data.get("success"):
            return {"success": True, "remaining": data.get("remaining", {})}
        return {"success": False, "error": data.get("error", "使用记录失败")}
    except Exception:
        return {"success": False, "error": "使用记录服务暂不可用"}


# ─── 环境变量/启动校验 ───
def assert_api_key_configured() -> None:
    """
    如果 DEEPSEEK_API_KEY 未设置，抛出可感知的异常。
    由 app.py 在启动时捕获并展示友好提示。
    """
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise RuntimeError("DEEPSEEK_API_KEY 未配置。请在环境变量中设置后重启服务。")


# ─── 输入安全：限制上传文件大小 ───
MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB


def check_file_size(file_bytes: bytes) -> tuple[bool, Optional[str]]:
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        return False, f"文件过大，请上传不超过 20MB 的合同文件"
    return True, None
