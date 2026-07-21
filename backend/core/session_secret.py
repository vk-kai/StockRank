"""Flask 会话签名密钥（secret_key）管理。

StockRank 的登录态完全由 Flask 签名 Cookie 承载（无服务端 session 存储、无 DB、
无 JWT）。因此"让所有已登录账号失效、强制重新登录"只需旋转 app.secret_key：
旧 Cookie 用旧密钥签名，换密钥后验签失败 → 全部视为未登录。

为了让"旋转一次"的效果在进程重启后仍然保持（不会回退到默认/环境变量密钥导致
旧会话复活），旋转时把新密钥持久化到 config/session_secret.json，启动时优先读取它。

优先级：持久化文件 > 环境变量 STOCKRANK_SECRET_KEY > 代码默认值。
"""
import os
import json
import secrets

from core.config import SESSION_SECRET_FILE, CONFIG_DIR


def load_session_secret(default):
    """启动时获取会话密钥。优先持久化文件，其次环境变量，最后 default。"""
    if os.path.exists(SESSION_SECRET_FILE):
        try:
            with open(SESSION_SECRET_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f) or {}
            persisted = data.get('secret')
            if persisted:
                return persisted
        except Exception:
            pass
    return os.environ.get('STOCKRANK_SECRET_KEY', default)


def rotate_session_secret(app):
    """生成新随机密钥，持久化并立即应用到 app。

    返回新密钥。调用后所有用旧密钥签名的会话 Cookie 立即失效（强制重新登录）。
    """
    new_secret = secrets.token_hex(32)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(SESSION_SECRET_FILE, 'w', encoding='utf-8') as f:
        json.dump({'secret': new_secret}, f, ensure_ascii=False, indent=2)
    # Flask 在每次请求签名/验签时实时读取 app.secret_key，赋值后即刻生效。
    app.secret_key = new_secret
    return new_secret
