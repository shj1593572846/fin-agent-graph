"""
用户认证与图形验证码安全服务模块
提供：
1. 纯 Python 轻量级高防 SVG 图形验证码生成与单次消费校验
2. 基于 HMAC-SHA256 的防篡改安全令牌 (Token) 签发与过期验签
3. 用户身份鉴权与安全密钥管理
"""

import os
import time
import uuid
import hmac
import hashlib
import base64
import json
import random
import urllib.parse
from typing import Optional, Tuple, Dict, Any

# 内存中暂存验证码: {captcha_id: {"code": "ABCD", "expires_at": float}}
_CAPTCHA_STORE: Dict[str, Dict[str, Any]] = {}

# 秘钥与默认凭证配置
DEFAULT_SECRET_KEY = "fin-agent-graph-secret-key-2026-safe-secure"
TOKEN_EXPIRE_SECONDS = 86400 * 7  # Token 有效期 7 天
CAPTCHA_EXPIRE_SECONDS = 300      # 验证码有效期 5 分钟


def get_secret_key() -> str:
    """获取服务端全局加盐秘钥"""
    return os.getenv("AUTH_SECRET_KEY", DEFAULT_SECRET_KEY)


def get_configured_credentials() -> Tuple[str, str]:
    """获取配置的管理员账号密码"""
    username = os.getenv("AUTH_USERNAME", "shj").strip()
    password = os.getenv("AUTH_PASSWORD", "1qaz@WSX").strip()
    return username, password


def cleanup_expired_captchas():
    """定期清理过期验证码"""
    now = time.time()
    expired_keys = [k for k, v in _CAPTCHA_STORE.items() if v["expires_at"] < now]
    for k in expired_keys:
        _CAPTCHA_STORE.pop(k, None)


def generate_svg_captcha() -> Dict[str, Any]:
    """
    生成纯 SVG 图形验证码 (无外部 C 扩展依赖，跨平台稳定，高分屏清晰矢量渲染)
    """
    cleanup_expired_captchas()

    # 剔除易混淆字符 0, O, 1, I
    charset = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    code = "".join(random.choices(charset, k=4))
    captcha_id = str(uuid.uuid4())

    width = 120
    height = 40

    # 优雅高对比度配色
    palette = ["#38bdf8", "#818cf8", "#34d399", "#f472b6", "#fbbf24", "#a78bfa"]

    elements = []
    # 1. 背景底板 (深色磨砂微质感)
    elements.append(f'<rect width="{width}" height="{height}" fill="#0f172a" rx="6" />')

    # 2. 贝塞尔干扰曲线
    for _ in range(3):
        color = random.choice(palette)
        x1 = random.randint(0, width // 3)
        y1 = random.randint(5, height - 5)
        x2 = random.randint(2 * width // 3, width)
        y2 = random.randint(5, height - 5)
        cx = random.randint(width // 4, 3 * width // 4)
        cy = random.randint(0, height)
        elements.append(
            f'<path d="M {x1} {y1} Q {cx} {cy} {x2} {y2}" stroke="{color}" stroke-width="1.6" fill="none" opacity="0.65"/>'
        )

    # 3. 散列噪点
    for _ in range(25):
        color = random.choice(palette)
        cx = random.randint(2, width - 2)
        cy = random.randint(2, height - 2)
        r = round(random.uniform(0.8, 1.8), 1)
        elements.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}" opacity="0.45"/>')

    # 4. 旋转、缩放与扭曲文字
    step = (width - 20) / 4
    for i, ch in enumerate(code):
        x = int(14 + i * step + random.randint(-2, 3))
        y = int(28 + random.randint(-3, 3))
        rot = random.randint(-18, 18)
        color = random.choice(palette)
        font_size = random.randint(22, 25)
        elements.append(
            f'<text x="{x}" y="{y}" fill="{color}" font-size="{font_size}" '
            f'font-family="system-ui, -apple-system, Arial, sans-serif" font-weight="900" '
            f'transform="rotate({rot}, {x}, {y})">{ch}</text>'
        )

    svg_content = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">{"".join(elements)}</svg>'
    data_uri = f"data:image/svg+xml;utf8,{urllib.parse.quote(svg_content)}"

    # 暂存入库（大小写不敏感存储）
    _CAPTCHA_STORE[captcha_id] = {
        "code": code.lower(),
        "expires_at": time.time() + CAPTCHA_EXPIRE_SECONDS,
    }

    return {
        "captcha_id": captcha_id,
        "image": data_uri,
        "expires_in": CAPTCHA_EXPIRE_SECONDS,
    }


def verify_captcha(captcha_id: str, input_code: str) -> bool:
    """校验验证码有效性并立刻单次消费作废，防止重放攻击"""
    cleanup_expired_captchas()

    if not captcha_id or not input_code:
        return False

    item = _CAPTCHA_STORE.pop(captcha_id, None)
    if not item:
        return False

    if time.time() > item["expires_at"]:
        return False

    return item["code"] == input_code.strip().lower()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = 4 - (len(s) % 4)
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s.encode("ascii"))


def create_token(username: str, expires_in: int = TOKEN_EXPIRE_SECONDS) -> str:
    """签发标准 HMAC-SHA256 安全令牌"""
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + expires_in,
    }

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")

    secret = get_secret_key().encode("utf-8")
    signature = hmac.new(secret, signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """验证令牌签名及有效期，返回解析出的 payload，无效或过期返回 None"""
    if not token or not isinstance(token, str):
        return None

    parts = token.strip().split(".")
    if len(parts) != 3:
        return None

    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    secret = get_secret_key().encode("utf-8")

    expected_sig = hmac.new(secret, signing_input, hashlib.sha256).digest()
    actual_sig = _b64url_decode(sig_b64)

    if not hmac.compare_digest(expected_sig, actual_sig):
        return None

    try:
        payload_json = _b64url_decode(payload_b64).decode("utf-8")
        payload = json.loads(payload_json)
        now = int(time.time())
        if payload.get("exp", 0) < now:
            return None
        return payload
    except Exception:
        return None


def authenticate_user(username: str, password: str) -> bool:
    """常量时间比较校验管理员账号密码，防范时序侧信道攻击"""
    cfg_user, cfg_pwd = get_configured_credentials()
    user_ok = hmac.compare_digest(username.strip(), cfg_user)
    pwd_ok = hmac.compare_digest(password.strip(), cfg_pwd)
    return user_ok and pwd_ok
