from flask import Blueprint, jsonify, request
from datetime import datetime
from news_processor import get_recent_news, search_news
from data_processor import error_logger

news_bp = Blueprint('news', __name__, url_prefix='/api')

@news_bp.route('/news', methods=['GET'])
def get_news():
    try:
        page = request.args.get('page', '1', type=int)
        page_size = request.args.get('page_size', '40', type=int)
        
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        
        result = get_recent_news(page, page_size)
        
        return jsonify({
            'success': True,
            'data': result['news'],
            'pagination': {
                'total': result['total'],
                'page': result['page'],
                'page_size': result['page_size'],
                'total_pages': result['total_pages'],
                'has_more': result['page'] < result['total_pages']
            },
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
        page = request.args.get('page', '1', type=int)
        page_size = request.args.get('page_size', '40', type=int)
        
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        
        if not keyword or not keyword.strip():
            return jsonify({
                'success': False,
                'message': '搜索关键词不能为空'
            }), 400
        
        result = search_news(keyword, page, page_size)
        
        return jsonify({
            'success': True,
            'data': result['news'],
            'pagination': {
                'total': result['total'],
                'page': result['page'],
                'page_size': result['page_size'],
                'total_pages': result['total_pages'],
                'has_more': result['page'] < result['total_pages']
            },
            'keyword': keyword,
            'timestamp': datetime.now().astimezone().isoformat()
        })
    except Exception as e:
        error_logger.error(f"API /api/news/search 异常: {e}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500
