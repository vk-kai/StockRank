from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
import traceback
from news_processor import get_recent_news, search_news, NEWS_DIR
from ai_analyzer import load_news_analysis_cache
from data_processor import error_logger
from logger import get_logger
import os
import json

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

@news_bp.route('/news/score-summary', methods=['GET'])
def get_news_score_summary():
    """获取每天的AI评分统计（利好/利空/中性数量）"""
    try:
        # 加载所有新闻数据
        all_news = []
        if os.path.exists(NEWS_DIR):
            for filename in os.listdir(NEWS_DIR):
                if filename.endswith('.json'):
                    file_path = os.path.join(NEWS_DIR, filename)
                    try:
                        if os.path.getsize(file_path) == 0:
                            continue
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            if isinstance(data, list):
                                all_news.extend(data)
                    except (json.JSONDecodeError, Exception):
                        continue
        
        # 加载AI分析缓存
        ai_cache = load_news_analysis_cache()
        
        # 按日期分组统计
        date_stats = {}
        for item in all_news:
            news_id = str(item.get('id', ''))
            time_str = item.get('time', '')
            
            if not time_str:
                continue
            
            # 解析日期
            try:
                if isinstance(time_str, (int, float)):
                    dt = datetime.fromtimestamp(float(time_str))
                elif isinstance(time_str, str):
                    if time_str.isdigit():
                        dt = datetime.fromtimestamp(int(time_str))
                    else:
                        dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                else:
                    continue
                
                date_key = dt.strftime('%Y-%m-%d')
            except (ValueError, TypeError, OSError):
                continue
            
            # 初始化日期统计
            if date_key not in date_stats:
                date_stats[date_key] = {
                    'positive': 0,
                    'negative': 0,
                    'neutral': 0,
                    'total_analyzed': 0,
                    'total_news': 0
                }
            
            date_stats[date_key]['total_news'] += 1
            
            # 检查是否有AI分析
            cached = ai_cache.get(news_id, {})
            score = cached.get('score')
            
            if score is not None:
                date_stats[date_key]['total_analyzed'] += 1
                if score > 50:
                    date_stats[date_key]['positive'] += 1
                elif score < 50:
                    date_stats[date_key]['negative'] += 1
                else:
                    date_stats[date_key]['neutral'] += 1
        
        # 转换为前端需要的格式
        summary = {}
        for date_key, stats in date_stats.items():
            if stats['total_analyzed'] > 0:
                summary[date_key] = {
                    'positive': stats['positive'],
                    'negative': stats['negative'],
                    'neutral': stats['neutral'],
                    'total_analyzed': stats['total_analyzed'],
                    'total_news': stats['total_news'],
                    'text': f"利好{stats['positive']} 利空{stats['negative']} 中性{stats['neutral']}（共分析{stats['total_analyzed']}条）"
                }
        
        return jsonify({
            'success': True,
            'data': summary,
            'timestamp': datetime.now().astimezone().isoformat()
        })
    except Exception as e:
        error_logger.error(f"API /api/news/score-summary 异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/news/score-summary]: {str(e)}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500

@news_bp.route('/news/score-trend', methods=['GET'])
def get_news_score_trend():
    """获取今日按小时分组的利好/利空/中性趋势数据"""
    try:
        # 加载所有新闻数据
        all_news = []
        if os.path.exists(NEWS_DIR):
            for filename in os.listdir(NEWS_DIR):
                if filename.endswith('.json'):
                    file_path = os.path.join(NEWS_DIR, filename)
                    try:
                        if os.path.getsize(file_path) == 0:
                            continue
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            if isinstance(data, list):
                                all_news.extend(data)
                    except (json.JSONDecodeError, Exception):
                        continue
        
        # 加载AI分析缓存
        ai_cache = load_news_analysis_cache()
        
        # 获取今日日期
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 按小时分组统计（只统计今天）
        hour_stats = {}  # {hour: {'positive': n, 'negative': n, 'neutral': n}}
        for item in all_news:
            news_id = str(item.get('id', ''))
            time_str = item.get('time', '')
            
            if not time_str:
                continue
            
            # 解析时间
            try:
                if isinstance(time_str, (int, float)):
                    dt = datetime.fromtimestamp(float(time_str))
                elif isinstance(time_str, str):
                    if time_str.isdigit():
                        dt = datetime.fromtimestamp(int(time_str))
                    else:
                        dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                        # 处理时区：转换为本地时间
                        if dt.tzinfo is not None:
                            dt = dt.astimezone().replace(tzinfo=None)
                else:
                    continue
            except (ValueError, TypeError, OSError):
                continue
            
            # 只统计今天
            if dt.strftime('%Y-%m-%d') != today:
                continue
            
            hour = dt.hour
            
            # 初始化小时统计
            if hour not in hour_stats:
                hour_stats[hour] = {'positive': 0, 'negative': 0, 'neutral': 0}
            
            # 检查是否有AI分析
            cached = ai_cache.get(news_id, {})
            score = cached.get('score')
            
            if score is not None:
                if score > 50:
                    hour_stats[hour]['positive'] += 1
                elif score < 50:
                    hour_stats[hour]['negative'] += 1
                else:
                    hour_stats[hour]['neutral'] += 1
        
        # 生成从0点到当前小时的完整小时序列
        current_hour = datetime.now().hour
        hours = list(range(0, current_hour + 1))
        
        # 构建图表数据
        x_axis = [f"{h:02d}:00" for h in hours]
        positive_data = [hour_stats.get(h, {}).get('positive', 0) for h in hours]
        negative_data = [hour_stats.get(h, {}).get('negative', 0) for h in hours]
        neutral_data = [hour_stats.get(h, {}).get('neutral', 0) for h in hours]
        
        # 计算累计值
        cum_positive = []
        cum_negative = []
        cum_neutral = []
        sum_p, sum_n, sum_neu = 0, 0, 0
        for h in hours:
            sum_p += hour_stats.get(h, {}).get('positive', 0)
            sum_n += hour_stats.get(h, {}).get('negative', 0)
            sum_neu += hour_stats.get(h, {}).get('neutral', 0)
            cum_positive.append(sum_p)
            cum_negative.append(sum_n)
            cum_neutral.append(sum_neu)
        
        # 今日总计
        total_positive = sum(hour_stats.get(h, {}).get('positive', 0) for h in hours)
        total_negative = sum(hour_stats.get(h, {}).get('negative', 0) for h in hours)
        total_neutral = sum(hour_stats.get(h, {}).get('neutral', 0) for h in hours)
        total_analyzed = total_positive + total_negative + total_neutral
        
        # 倾向判断
        if total_analyzed == 0:
            tendency = '暂无数据'
        elif total_positive > total_negative * 1.5:
            tendency = '偏利好'
        elif total_negative > total_positive * 1.5:
            tendency = '偏利空'
        else:
            tendency = '多空均衡'
        
        return jsonify({
            'success': True,
            'data': {
                'x_axis': x_axis,
                'series': {
                    'positive': positive_data,
                    'negative': negative_data,
                    'neutral': neutral_data,
                    'cumulative_positive': cum_positive,
                    'cumulative_negative': cum_negative,
                    'cumulative_neutral': cum_neutral
                },
                'summary': {
                    'total_positive': total_positive,
                    'total_negative': total_negative,
                    'total_neutral': total_neutral,
                    'total_analyzed': total_analyzed,
                    'tendency': tendency
                }
            },
            'timestamp': datetime.now().astimezone().isoformat()
        })
    except Exception as e:
        error_logger.error(f"API /api/news/score-trend 异常: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/news/score-trend]: {str(e)}")
        return jsonify({
            'success': False,
            'message': '服务器内部错误'
        }), 500
