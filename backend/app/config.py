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
# LLM 提供商选择
# ============================================================
# 可选值: deepseek（默认） | private | openai
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek").lower()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "")

# 统一设置 OPENAI 环境变量（Chat Demo / LangChain 通过此变量连接）
if LLM_PROVIDER == "deepseek" and DEEPSEEK_API_KEY:
    os.environ["OPENAI_API_KEY"] = DEEPSEEK_API_KEY
    if DEEPSEEK_BASE_URL:
        os.environ["OPENAI_BASE_URL"] = DEEPSEEK_BASE_URL
elif LLM_PROVIDER == "openai":
    api_key = os.getenv("OPENAI_API_KEY", "")
    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key
elif LLM_PROVIDER == "private":
    # 私有 LLM 用占位 key，实际认证通过自定义 httpx client 处理
    os.environ["OPENAI_API_KEY"] = "private-llm-placeholder"

# ============================================================
# 私有 LLM 配置（仅 LLM_PROVIDER=private 时生效）
# ============================================================
PRIVATE_LLM_TOKEN_URL = os.getenv("PRIVATE_LLM_TOKEN_URL", "")
PRIVATE_LLM_API_URL = os.getenv("PRIVATE_LLM_API_URL", "")
PRIVATE_LLM_CLIENT_ID = os.getenv("PRIVATE_LLM_CLIENT_ID", "")
PRIVATE_LLM_CLIENT_SECRET = os.getenv("PRIVATE_LLM_CLIENT_SECRET", "")
PRIVATE_LLM_MODEL = os.getenv("PRIVATE_LLM_MODEL", "qwen-72b-chat-int4")

# ============================================================
# AI Agent 配置
# ============================================================
AI_RECURSION_LIMIT = int(os.getenv("AI_RECURSION_LIMIT", "200"))
AI_STRICT_MODE = os.getenv("AI_STRICT_MODE", "").lower() in ("1", "true", "yes")

# 日志级别
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ============================================================
# 数据库配置
# ============================================================
def _resolve_duckdb_path() -> str:
    # 1. 环境变量显式指定
    env_path = os.getenv("DUCKDB_PATH")
    if env_path and Path(env_path).exists():
        return str(Path(env_path).resolve())

    if getattr(sys, "frozen", False):
        # 2. 优先使用 exe 同目录的外部数据库（用户可替换）
        external = Path(sys.executable).parent / "vcloud_duck.db"
        if external.exists():
            return str(external.resolve())
        # 3. 内置默认数据库（PyInstaller 烘焙进去的）
        builtin = Path(getattr(sys, "_MEIPASS", "")) / "vcloud_duck.db"
        if builtin.exists():
            return str(builtin.resolve())
        # 仍然尝试 exe 目录
        return str(external.resolve())
    # 开发模式
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
