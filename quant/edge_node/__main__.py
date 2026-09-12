"""``python -m edge_node`` 启动入口。

只绑 127.0.0.1 —— 对外暴露交给 autossh 反向隧道，worker 本身不监听公网。
"""
from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("EDGE_NODE_HOST", "127.0.0.1")
    port = int(os.getenv("EDGE_NODE_PORT", "8766"))
    uvicorn.run(
        "edge_node.worker:app",
        host=host,
        port=port,
        log_level=os.getenv("EDGE_NODE_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
