import os
import sys
from pathlib import Path

# ============================================================
# 加载 .env 文件（按优先级从多个位置查找）
#   1. $DATAPIVOT_ENV 显式指定
#   2. 可执行文件 (sys.executable) 同目录 — 打包 dist/ 场景
#   3. 当前工作目录 (Path.cwd)
#   4. 若 PyInstaller frozen → _MEIPASS 临时解压目录
#   5. 开发场景: backend/app/.env → backend/.env → 项目根 .env
# ============================================================
def _try_load_dotenv() -> list:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return []
    loaded = []

    def _load(p: Path | None) -> bool:
        if p is None or not p.exists() or not p.is_file():
            return False
        try:
            if load_dotenv(dotenv_path=str(p), override=False, encoding="utf-8"):
                loaded.append(str(p))
                return True
        except Exception:
            pass
        return False

    custom = os.getenv("DATAPIVOT_ENV")
    if custom:
        _load(Path(custom))
    if getattr(sys, "frozen", False):
        _load(Path(sys.executable).parent / ".env")
    _load(Path.cwd() / ".env")
    if getattr(sys, "frozen", False):
        _load(Path(getattr(sys, "_MEIPASS", "")) / ".env")
    _base = Path(__file__).parent
    _load(_base / ".env")
    _load(_base.parent / ".env")
    _load(_base.parent.parent / ".env")
    return loaded


_loaded_envs = _try_load_dotenv()
if _loaded_envs:
    print("✅ 已加载 .env 文件:")
    for _p in _loaded_envs:
        print(f"   - {_p}")
else:
    print("ℹ️  未找到 .env 文件，仅使用系统环境变量")

# ============================================================
# API Key 配置
# ============================================================
# 配置方式:
#   1. 设置环境变量: export DEEPSEEK_API_KEY="sk-xxx"
#   2. 创建 .env 文件: backend/app/.env → DEEPSEEK_API_KEY=sk-xxx
#   获取 Key: https://platform.deepseek.com/api_keys
# ============================================================
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "")

# Chat Demo agent 通过 OPENAI_API_KEY / OPENAI_BASE_URL 连接 DeepSeek
# (DeepSeek API 兼容 OpenAI SDK)
if DEEPSEEK_API_KEY and not os.getenv("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = DEEPSEEK_API_KEY
if DEEPSEEK_BASE_URL and os.getenv("OPENAI_BASE_URL") is None:
    os.environ["OPENAI_BASE_URL"] = DEEPSEEK_BASE_URL

# 日志级别
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ============================================================
# 数据库配置
# ============================================================
def _resolve_duckdb_path() -> str:
    env_path = os.getenv("DUCKDB_PATH")
    if env_path and Path(env_path).exists():
        return str(Path(env_path).resolve())
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidate = base / "vcloud_duck.db"
        if candidate.exists():
            return str(candidate.resolve())
    src_path = Path(__file__).parent.parent.parent / "vcloud_duck.db"
    if src_path.exists():
        return str(src_path.resolve())
    if env_path:
        return env_path
    return str(src_path.resolve())


DB_PATH = Path(_resolve_duckdb_path())
DUCKDB_PATH = str(DB_PATH)

# ============================================================
# 字段常量
# ============================================================
RULE_TYPE_MAP = {
    0: "统计",
    1: "报警",
    2: "事件",
}
