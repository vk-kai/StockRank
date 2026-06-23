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
    """获取今日利好/利空/中性趋势数据
    
    时间分桶规则：
    - 盘前 00:00-08:59 综合统计一次
    - 盘中 09:00-15:00 每10分钟统计一次
    - 盘后 15:00-23:59 综合统计一次
    """
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
        now = datetime.now()
        
        # 时间桶标签函数
        def get_bucket_label(dt):
            """根据时间返回所属的时间桶标签"""
            hour = dt.hour
            minute = dt.minute
            # 盘前：0:00 - 8:59
            if hour < 9:
                return '盘前'
            # 盘中：9:00 - 15:00（每10分钟）
            if hour < 15 or (hour == 15 and minute == 0):
                bucket_minute = (minute // 10) * 10
                return f"{hour:02d}:{bucket_minute:02d}"
            # 盘后：15:00 之后
            return '盘后'
        
        # 生成完整时间轴模板（按顺序）
        def generate_full_axis():
            axis = ['盘前']
            for h in range(9, 15):
                for m in range(0, 60, 10):
                    axis.append(f"{h:02d}:{m:02d}")
            axis.append('15:00')
            axis.append('盘后')
            return axis
        
        # 按时间桶分组统计（只统计今天）
        bucket_stats = {}  # {bucket_label: {'positive': n, 'negative': n, 'neutral': n}}
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
                        if dt.tzinfo is not None:
                            dt = dt.astimezone().replace(tzinfo=None)
                else:
                    continue
            except (ValueError, TypeError, OSError):
                continue
            
            # 只统计今天
            if dt.strftime('%Y-%m-%d') != today:
                continue
            
            bucket = get_bucket_label(dt)
            if bucket not in bucket_stats:
                bucket_stats[bucket] = {'positive': 0, 'negative': 0, 'neutral': 0}
            
            cached = ai_cache.get(news_id, {})
            score = cached.get('score')
            
            if score is not None:
                if score > 50:
                    bucket_stats[bucket]['positive'] += 1
                elif score < 50:
                    bucket_stats[bucket]['negative'] += 1
                else:
                    bucket_stats[bucket]['neutral'] += 1
        
        # 生成时间轴：只显示到当前时间为止
        current_bucket = get_bucket_label(now)
        full_axis = generate_full_axis()
        
        x_axis = []
        for label in full_axis:
            if label == '盘前':
                x_axis.append(label)
                continue
            if label == '盘后':
                # 只有当前已进入盘后才显示
                if now.hour >= 15:
                    x_axis.append(label)
                continue
            # 普通时间点（9:00 ~ 15:00）
            if label == '15:00':
                if now.hour >= 15:
                    x_axis.append(label)
                continue
            h, m = map(int, label.split(':'))
            if (h < now.hour) or (h == now.hour and m <= now.minute):
                x_axis.append(label)
        
        # 构建图表数据
        positive_data = [bucket_stats.get(label, {}).get('positive', 0) for label in x_axis]
        negative_data = [bucket_stats.get(label, {}).get('negative', 0) for label in x_axis]
        neutral_data = [bucket_stats.get(label, {}).get('neutral', 0) for label in x_axis]
        
        # 今日总计
        total_positive = sum(s.get('positive', 0) for s in bucket_stats.values())
        total_negative = sum(s.get('negative', 0) for s in bucket_stats.values())
        total_neutral = sum(s.get('neutral', 0) for s in bucket_stats.values())
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
                    'neutral': neutral_data
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
