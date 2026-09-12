"""TrendZen 边缘节点（树莓派）worker 包。

在 Pi 上以 ``python -m edge_node`` 启动，监听 127.0.0.1，
通过 autossh 反向隧道暴露为服务器本机的 http://127.0.0.1:<port>。
仅依赖 backend.backtest.engine / strategies，不碰 DB、不取数（df 由服务器下发）。
"""
