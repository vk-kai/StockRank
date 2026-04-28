"""
Jarvis 配置文件
"""

DEFAULT_CONFIG = {
    'enabled': True,
    'enabled_checks': [
        'sql_injection',
        'xss',
        'command_injection',
        'path_traversal',
        'ldap_injection',
        'xxe',
        'ssrf',
    ],
    'sensitivity': 'medium',
    'ban_duration': 3600,
    'max_attempts': 5,
    'attempt_window': 300,
    'whitelist': ['127.0.0.1', '::1'],
    'exempt_routes': ['/api/health', '/api/ping', '/favicon.ico'],
    'data_dir': 'data/jarvis',
}

def get_config(overrides=None):
    config = DEFAULT_CONFIG.copy()
    if overrides:
        config.update(overrides)
    return config
