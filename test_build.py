#!/usr/bin/env python3
"""
测试打包后的程序
"""

import subprocess
import time
import sys
import os
from pathlib import Path

IS_WIN = sys.platform.startswith("win")
EXEC_SUFFIX = ".exe" if IS_WIN else ""


def test_program():
    """测试打包后的程序是否正常启动"""
    print("=" * 60)
    print("测试 DataPivot 打包后的程序")
    print("=" * 60)

    # 跨平台可执行文件查找
    build_dir = Path(__file__).parent / "dist"
    executable = build_dir / f"DataPivot{EXEC_SUFFIX}"
    if not executable.exists():
        # 也可能是没有扩展名的文件（Mac/Linux 但 build.py 输出 .exe）
        alt = build_dir / "DataPivot"
        if alt.exists() and os.access(str(alt), os.X_OK):
            executable = alt
        elif IS_WIN and (build_dir / "DataPivot.exe").exists():
            executable = build_dir / "DataPivot.exe"
        else:
            print(f"\n❌ 可执行文件不存在: {executable}")
            print("请先运行打包脚本: python build.py")
            return False

    print(f"\n✅ 找到可执行文件: {executable}")

    # 启动程序
    print("\n[1/3] 启动程序...")
    process = subprocess.Popen(
        [str(executable)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # 等待程序启动
    print("  等待程序启动...")
    time.sleep(5)

    # 检查进程是否还在运行
    if process.poll() is not None:
        print("  ❌ 程序已退出")
        stdout, stderr = process.communicate()
        print(f"  输出: {stdout}")
        print(f"  错误: {stderr}")
        return False

    print("  ✅ 程序已启动")

    # 测试 API（用 urllib 替代 requests，减少外部依赖）
    print("\n[2/3] 测试 API...")
    try:
        import urllib.request
        import urllib.error
        req = urllib.request.Request("http://localhost:8080/")
        response = urllib.request.urlopen(req, timeout=5)
        if response.status == 200:
            print("  ✅ API 响应正常")
        else:
            print(f"  ❌ API 响应状态码: {response.status}")
            return False
    except Exception as e:
        print(f"  ❌ 无法连接到 API: {e}")
        return False

    # 测试静态文件
    print("\n[3/3] 测试静态文件...")
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:8080/index.html")
        response = urllib.request.urlopen(req, timeout=5)
        body = response.read().decode("utf-8", errors="replace")
        if response.status == 200 and "DataPivot" in body:
            print("  ✅ 静态文件正常")
        else:
            print(f"  ❌ 静态文件响应异常")
    except Exception as e:
        print(f"  ❌ 静态文件测试失败: {e}")
        return False

    # 停止程序
    print("\n停止程序...")
    process.terminate()
    time.sleep(2)

    if process.poll() is not None:
        print("  ✅ 程序已正常停止")
    else:
        print("  ⚠️  程序仍在运行，可能需要手动关闭")

    print("\n" + "=" * 60)
    print("✅ 测试完成！")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = test_program()
    sys.exit(0 if success else 1)
