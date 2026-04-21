from flask import Blueprint, jsonify, request
from datetime import datetime
from news_processor import get_recent_news, search_news
from data_processor import error_logger

news_bp = Blueprint('news', __name__, url_prefix='/api')

@news_bp.route('/news', methods=['GET'])
def get_news():
    try:
        limit = request.args.get('limit', '50', type=int)
        limit = min(limit, 200)
        
        news_data = get_recent_news(limit)
        
        return jsonify({
            'success': True,
            'data': news_data,
            'count': len(news_data),
            'timestamp': datetime.now().astimezone().isoformat()
        })
    except Exception as e:
        error_logger.error(f"API /api/news 异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@news_bp.route('/news/search', methods=['GET'])
def search_news_api():
    try:
        keyword = request.args.get('keyword', '', type=str)
        limit = request.args.get('limit', '200', type=int)
        limit = min(limit, 200)
        
        if not keyword or not keyword.strip():
            return jsonify({
                'success': False,
                'message': '搜索关键词不能为空'
            }), 400
        
        search_results = search_news(keyword, limit)
        
        return jsonify({
            'success': True,
            'data': search_results,
            'count': len(search_results),
            'keyword': keyword,
            'timestamp': datetime.now().astimezone().isoformat()
        })
    except Exception as e:
        error_logger.error(f"API /api/news/search 异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500
