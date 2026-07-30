from .flow_routes import flow_bp
from .news_routes import news_bp
from .config_routes import config_bp
from .log_routes import log_bp
from .house_routes import house_bp
from .auth_routes import auth_bp
from .jarvis_routes import jarvis_app_bp

__all__ = ['flow_bp', 'news_bp', 'config_bp', 'log_bp', 'house_bp', 'auth_bp', 'jarvis_app_bp']
