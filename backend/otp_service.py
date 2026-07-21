"""OTP 动态口令（TOTP）服务。

提供密钥生成、二维码（otpauth URI + PNG data URL）生成、口令校验，
以及 otp_config.json 的加载/保存。

TOTP 参数遵循 Google Authenticator / 微软/阿里云 Authenticator 默认：
  - 算法 SHA1，6 位数字，30 秒步长。pyotp.TOTP 默认即如此，无需额外配置。
"""
import os
import json
import io
import base64

from config import OTP_CONFIG_FILE, CONFIG_DIR

# 兜底导入 qrcode/pyotp：若运行环境未安装依赖，仍保证后端可启动（仅 OTP 接口报错）
try:
    import pyotp  # type: ignore
except Exception:  # pragma: no cover - 依赖缺失时的优雅降级
    pyotp = None

try:
    import qrcode  # type: ignore
except Exception:  # pragma: no cover
    qrcode = None

# otpauth URI 中的发行方/账号名
ISSUER = 'StockRank'
ACCOUNT = 'vk'


def load_otp_config():
    """读取 OTP 配置，结构：{enabled: bool, secret: str, enrolled_at: str}。"""
    default = {'enabled': False, 'secret': '', 'enrolled_at': ''}
    if not os.path.exists(OTP_CONFIG_FILE):
        return default
    try:
        with open(OTP_CONFIG_FILE, 'r', encoding='utf-8') as f:
            default.update(json.load(f) or {})
    except Exception:
        pass
    return default


def save_otp_config(cfg):
    """写入 OTP 配置。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(OTP_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def is_otp_enabled():
    """OTP 是否已开启且密钥就绪。"""
    cfg = load_otp_config()
    return bool(cfg.get('enabled') and cfg.get('secret'))


def _require_pyotp():
    if pyotp is None:
        raise RuntimeError('未安装 pyotp 依赖，请在 backend 目录执行 pip install pyotp')


def generate_secret():
    """生成一个新的 base32 密钥（仅用于 setup，不落库）。"""
    _require_pyotp()
    return pyotp.random_base32()


def build_provisioning_uri(secret):
    """构造 otpauth://totp/... URI，供二维码扫描录入。"""
    _require_pyotp()
    return pyotp.totp.TOTP(secret).provisioning_uri(name=ACCOUNT, issuer_name=ISSUER)


def build_qr_data_url(uri):
    """把 otpauth URI 渲染成 PNG 二维码的 data URL（前端 <img> 直接用）。"""
    if qrcode is None:
        raise RuntimeError('未安装 qrcode 依赖，请在 backend 目录执行 pip install "qrcode[pil]"')
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    return 'data:image/png;base64,' + b64


def verify_code(secret, code):
    """校验动态口令是否匹配（允许 ±1 个 30s 时间窗，兼容手机时间轻微漂移）。"""
    if not secret or not code:
        return False
    try:
        _require_pyotp()
        totp = pyotp.TOTP(secret)
        # valid_window=1 表示前后各容忍一个 30s 窗口
        return bool(totp.verify(str(code).strip(), valid_window=1))
    except Exception:
        return False
