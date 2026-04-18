from flask import Blueprint
from data_processor import error_logger

auth_bp = Blueprint('auth', __name__, url_prefix='/api')

PASSWORD = 'vk666'

def verify_password(password):
    return password == PASSWORD
