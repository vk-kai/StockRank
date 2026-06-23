from flask import Blueprint, jsonify, request
from datetime import datetime
import traceback
from news_processor import get_recent_news, search_news
from ai_analyzer import load_news_analysis_cache
from data_processor import error_logger
from logger import get_logger

news_bp = Blueprint('news', __name__, url_prefix='/api')
system_logger = get_logger('system')

@news_bp.route('/news', methods=['GET'])
def get_news():
    try:
        page = request.args.get('page', '1', type=int)
        page_size = request.args.get('page_size', '40', type=int)
        importance = request.args.get('importance', None, type=str)
        
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        
        if importance is not None:
            importance = importance.strip()
            if not importance:
                importance = None
        
        result = get_recent_news(page, page_size, importance)
        
        # 附加AI分析评分
        ai_cache = load_news_analysis_cache()
        for item in result['news']:
            cached = ai_cache.get(str(item.get('id')), {})
            item['ai_score'] = cached.get('score')
            item['ai_label'] = cached.get('label')
        
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
            'filter': {
                'importance': importance
            },
            'timestamp': datetime.now().astimezone().isoformat()
        })
    except Exception as e:
        error_logger.error(f"API /api/news 异常: {e}, 参数: page={page}, page_size={page_size}, importance={importance}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/news]: {str(e)}")
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
        importance = request.args.get('importance', None, type=str)
        
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        
        if importance is not None:
            importance = importance.strip()
            if not importance:
                importance = None
        
        if not keyword or not keyword.strip():
            return jsonify({
                'success': False,
                'message': '搜索关键词不能为空'
            }), 400
        
        result = search_news(keyword, page, page_size, importance)
        
        # 附加AI分析评分
        ai_cache = load_news_analysis_cache()
        for item in result['news']:
            cached = ai_cache.get(str(item.get('id')), {})
            item['ai_score'] = cached.get('score')
            item['ai_label'] = cached.get('label')
        
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
            'filter': {
                'keyword': keyword,
                'importance': importance
            },
            'timestamp': datetime.now().astimezone().isoformat()
        })
    except Exception as e:
        error_logger.error(f"API /api/news/search 异常: {e}, 参数: keyword={keyword}, page={page}, page_size={page_size}, importance={importance}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/news/search]: {str(e)}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500
