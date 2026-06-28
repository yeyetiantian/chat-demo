#!/usr/bin/env python3
"""DataPivot 后端启动入口"""
import os
import sys
import signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    from app.utils.logger import setup_logging
    setup_logging()

    # 在 uvicorn 导入之前加载 .env（config.py 在 import 时自动加载）
    from app.config import DEEPSEEK_API_KEY
    if not DEEPSEEK_API_KEY:
        print("⚠️  环境变量 DEEPSEEK_API_KEY 未设置，AI 对话将使用本地关键词回退。")
        print("   配置方式: 在 backend/app/.env 中添加 DEEPSEEK_API_KEY=sk-xxx")
    else:
        print(f"✅ DEEPSEEK_API_KEY 已配置 (长度={len(DEEPSEEK_API_KEY)})")

    import uvicorn

    # 处理 Ctrl+C 优雅退出
    def handle_sigint(signum, frame):
        print("\n🛑 收到退出信号，正在关闭服务...")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)

    try:
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8080,
            reload=True,
            # 降低 reloader 的信号干扰
            reload_delay=0.5,
        )
    except KeyboardInterrupt:
        print("\n🛑 服务已停止")
