import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

MOCK_NEWS = [
    {
        "id": "900001",
        "title": "测试普通新闻：沪深两市午盘震荡整理",
        "digest": "今日沪深两市午盘维持震荡整理态势，板块轮动明显，成交量较昨日有所萎缩。市场人士表示，当前处于政策真空期，投资者观望情绪较浓。",
        "source": "测试数据源",
        "time": "",
        "ctime": "",
        "url": "https://example.com/news/900001",
        "type": "stock",
        "import": "0"
    },
    {
        "id": "900002",
        "title": "测试重要新闻：央行宣布降准50个基点",
        "digest": "中国人民银行决定于下月15日下调金融机构存款准备金率0.5个百分点，预计释放长期资金约1万亿元。此次降准旨在优化金融机构资金结构，增强金融服务实体经济能力。",
        "source": "测试数据源",
        "time": "",
        "ctime": "",
        "url": "https://example.com/news/900002",
        "type": "stock",
        "import": "3"
    }
]

call_count = 0
base_time = int(time.time())

class MockHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global call_count, base_time
        call_count += 1
        
        parsed = urlparse(self.path)
        
        if '/tapp/news/push/stock/' in parsed.path:
            current_time = base_time + call_count * 60
            
            news_list = []
            for item in MOCK_NEWS:
                item_copy = dict(item)
                item_copy["time"] = str(current_time - 3600)
                item_copy["ctime"] = str(current_time - 3600)
                news_list.append(item_copy)
            
            new_item = {
                "id": f"9001{call_count:03d}",
                "source": "测试数据源",
                "time": str(current_time),
                "ctime": str(current_time),
                "url": f"https://example.com/news/9001{call_count:03d}",
                "type": "stock"
            }
            
            if call_count % 3 == 0:
                new_item["title"] = f"【重要】大盘暴雷！沪指暴跌5%触发熔断 - 第{call_count}轮请求"
                new_item["digest"] = f"今日A股市场遭遇重挫，沪指开盘后迅速下挫，盘中跌幅一度超过5%，触发熔断机制。分析人士指出，多重利空因素叠加导致市场恐慌性抛售。央行紧急发声安抚市场情绪，建议投资者保持理性。"
                new_item["import"] = "3"
            elif call_count % 3 == 2:
                new_item["title"] = f"【重要】某地发布天气预警 - 第{call_count}轮请求"
                new_item["digest"] = f"气象部门发布消息，某地区未来三天将有中到大雨，局部暴雨。请市民注意防范，出行携带雨具。此消息与股市无关，仅供参考。"
                new_item["import"] = "3"
            else:
                new_item["title"] = f"普通新闻：两市成交额小幅波动 - 第{call_count}轮请求"
                new_item["digest"] = f"今日沪深两市成交额较前一交易日小幅波动，市场整体表现平稳。板块方面，新能源、半导体等板块表现活跃。"
                new_item["import"] = "0"
            
            news_list.append(new_item)
            
            response = {
                "data": {
                    "list": news_list
                }
            }
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(response, ensure_ascii=False).encode('utf-8'))
            
            if call_count % 3 == 0:
                tag = "暴雷"
            elif call_count % 3 == 2:
                tag = "重要(废)"
            else:
                tag = "普通"
            print(f"[{time.strftime('%H:%M:%S')}] 第{call_count}轮请求，新增1条{tag}新闻，共返回{len(news_list)}条")
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    host = '127.0.0.1'
    port = 8899
    
    server = HTTPServer((host, port), MockHandler)
    print(f"模拟新闻服务启动: http://{host}:{port}")
    print(f"接口地址: http://{host}:{port}/tapp/news/push/stock/")
    print(f"基础数据: {len(MOCK_NEWS)}条")
    print(f"每次请求新增1条:")
    print(f"  第1轮: 普通新闻")
    print(f"  第2轮: 重要新闻(废消息)")
    print(f"  第3轮: 大盘暴雷(重要)")
    print(f"  循环...")
    print("按 Ctrl+C 停止\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.server_close()
