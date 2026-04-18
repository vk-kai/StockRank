import sys
sys.path.insert(0, 'backend')
from feishu_pusher import send_feishu_message
from datetime import datetime

title = '突发：A股大盘暴跌超10% 两市超5000只个股跌停'
news_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
content = news_time + '\n\n<font color="red">今日A股市场遭遇历史性暴跌，上证指数收盘大跌10.2%，深证成指暴跌11.5%，创业板指暴跌12.8%。两市超过5000只个股跌停，市场恐慌情绪蔓延。</font>\n\nA股遭遇历史性暴跌，超5000只个股跌停，受多重利空因素叠加影响'

result = send_feishu_message(title, content, url='https://example.com/news/test')
print('推送结果:', result)
