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

class MockHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global call_count
        call_count += 1
        
        parsed = urlparse(self.path)
        
        if '/tapp/news/push/stock/' in parsed.path:
            news_list = []
            for item in MOCK_NEWS:
                item_copy = dict(item)
                item_copy["time"] = str(int(time.time()))
                item_copy["ctime"] = str(int(time.time()))
                news_list.append(item_copy)
            
            new_item = {
                "id": f"9001{call_count:03d}",
                "source": "测试数据源",
                "time": str(int(time.time())),
                "ctime": str(int(time.time())),
                "url": f"https://example.com/news/9001{call_count:03d}",
                "type": "stock"
            }
            
            if call_count % 3 == 0:
                new_item["title"] = f"暴雷：某上市公司财务造假被立案调查（第{call_count}次请求）"
                new_item["digest"] = f"证监会发布公告，某上市公司因涉嫌重大财务造假被正式立案调查。经初步查实，该公司近三年虚增利润超过50亿元，涉嫌欺诈发行。公司股票已紧急停牌，预计复牌后将面临重大退市风险。投资者需密切关注后续进展。"
                new_item["import"] = "3"
            elif call_count % 2 == 0:
                new_item["title"] = f"重要：国务院发布新一轮经济刺激政策（第{call_count}次请求）"
                new_item["digest"] = f"国务院常务会议决定推出新一轮经济刺激措施，包括加大基建投资、降低企业税负、扩大消费补贴等多项举措。分析人士认为，此次政策力度超出市场预期，将对相关行业产生积极影响。"
                new_item["import"] = "3"
            else:
                new_item["title"] = f"普通：两市融资余额小幅增加（第{call_count}次请求）"
                new_item["digest"] = f"截至昨日收盘，沪深两市融资余额合计增加15.6亿元，其中沪市增加8.2亿元，深市增加7.4亿元。融资买入额较前一交易日有所回升。"
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
            
            tag = "普通" if call_count % 3 != 0 and call_count % 2 != 0 else ("重要" if call_count % 2 == 0 and call_count % 3 != 0 else "暴雷")
            print(f"[{time.strftime('%H:%M:%S')}] 第{call_count}次请求，新增1条{tag}新闻，共返回{len(news_list)}条")
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
    print(f"  第1次: 普通新闻")
    print(f"  第2次: 重要新闻（import=3）")
    print(f"  第3次: 暴雷新闻（import=3）")
    print(f"  循环...")
    print("按 Ctrl+C 停止\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.server_close()
