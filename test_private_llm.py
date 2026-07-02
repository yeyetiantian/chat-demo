#!/usr/bin/env python3
"""
私有 LLM 连接测试脚本（零依赖，只用 Python 标准库）
用法:
    python3 test_private_llm.py
"""

import json
import urllib.request
import urllib.parse

# ===== 配置区 =====
TOKEN_URL = "http://aidm-issue.apps-qa.saic-gm.com/aidm/sgmidp/oauth2/v3.0/token"
API_URL = "http://qa-zone1.silk.saic-gm.com/aibd-diana/dianaQwen27B/v1/chat/completions"
CLIENT_ID = "PSADP0RMX4u6LM0ql4Ym0TLE2KyHGz759WV008f1qoGD7iA17dfVn4911Zu"
CLIENT_SECRET = "PSADP0o4h011xazMzUz2rDf6XuI5defSOSVgvBQj32uWm1u61vo0Kn2Ojk7"
# modelName = "dianaQwen27B"
# MODEL = "qwen-27b"
modelName = "dianaDeepSeekV"
MODEL = "dianamodel"

def _request(method: str, url: str, headers: dict = None, data: dict = None,
             timeout: int = 30) -> tuple[int, str | dict]:
    """通用 HTTP 请求（用 urllib，不需要 requests）"""
    if data is not None and isinstance(data, dict):
        if headers and headers.get("Content-Type") == "application/json":
            body = json.dumps(data).encode("utf-8")
        else:
            body = urllib.parse.urlencode(data).encode("utf-8")
    else:
        body = data

    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            content_type = resp.headers.get("Content-Type", "")
            if "application/json" in content_type or "json" in content_type:
                return resp.status, json.loads(raw)
            return resp.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")[:500]
    except urllib.error.URLError as e:
        return 0, f"连接失败: {e.reason}"
    except Exception as e:
        return 0, str(e)


def get_token() -> str | None:
    """获取 OAuth2 token"""
    print(f"[1/3] 正在获取 token...")
    print(f"      POST {TOKEN_URL}")
    print(f"      client_id: {CLIENT_ID}")

    status, data = _request("POST", TOKEN_URL, data={
        "scope": "ALL",
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }, timeout=15)

    if status != 200:
        print(f"❌ 获取 token 失败 (HTTP {status}): {str(data)[:200]}")
        return None

    if isinstance(data, str):
        print(f"❌ 响应不是 JSON: {data[:200]}")
        return None

    token = data.get("access_token")
    if not token:
        print(f"❌ 响应中没有 access_token: {json.dumps(data, ensure_ascii=False)}")
        return None

    expires_in = data.get("expires_in", "未知")
    print(f"✅ 获取 token 成功 (有效期: {expires_in}s)")
    print(f"   token: {token[:20]}...{token[-10:]}")
    return token


def chat(token: str, user_input: str) -> str:
    """发送对话请求"""
    print(f"\n[2/3] 发送对话请求...")
    print(f"      model: {MODEL}")
    print(f"      user: {user_input}")

    headers = {
        "access_token": token,
        "Content-Type": "application/json",
        "apiTag": "V1",
        "clientRequestId": "01",
        "client_id": CLIENT_ID,
    }

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "你是一个数据查询助手。"},
            {"role": "user", "content": user_input},
        ],
        "temperature": 0.1,
    }

    status, data = _request("POST", f"http://qa-zone1.silk.saic-gm.com/aibd-diana/{modelName}/v1/chat/completions", headers=headers, data=payload, timeout=60)

    if status != 200:
        return f"❌ API 请求失败 (HTTP {status}): {str(data)[:300]}"

    if isinstance(data, str):
        return f"❌ 响应不是 JSON: {data[:200]}"

    choices = data.get("choices", [])
    if not choices:
        return f"❌ 响应中没有 choices: {json.dumps(data, ensure_ascii=False)[:200]}"

    content = choices[0].get("message", {}).get("content", "")
    total_tokens = data.get("usage", {}).get("total_tokens", "未知")
    print(f"      token 消耗: {total_tokens}")
    return content


def tool_call_test(token: str) -> str:
    """测试 LLM 是否支持工具自动调用"""
    print(f"\n[4] 测试工具调用...")
    print(f"      定义两个简单工具，让 AI 自动选择调用")

    headers = {
        "access_token": token,
        "Content-Type": "application/json",
        "apiTag": "V1",
        "clientRequestId": "01",
        "client_id": CLIENT_ID,
    }

    # 定义两个简单工具（OpenAI 工具调用格式）
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "获取指定城市的当前天气",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "城市名称，如 上海、北京"
                        }
                    },
                    "required": ["city"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_current_time",
                "description": "获取当前时间",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        }
    ]

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "你是一个助手，可以根据用户问题调用合适的工具。"},
            {"role": "user", "content": "上海今天天气怎么样？"}
        ],
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.1,
    }

    status, data = _request("POST", f"http://qa-zone1.silk.saic-gm.com/aibd-diana/{modelName}/v1/chat/completions", headers=headers, data=payload, timeout=60)

    if status != 200:
        return f"❌ API 请求失败 (HTTP {status}): {str(data)[:300]}"

    if isinstance(data, str):
        return f"❌ 响应不是 JSON: {data[:200]}"

    choices = data.get("choices", [])
    if not choices:
        return f"❌ 响应中没有 choices: {json.dumps(data, ensure_ascii=False)[:200]}"

    message = choices[0].get("message", {})
    content = message.get("content", "")
    tool_calls = message.get("tool_calls", [])

    print(f"      token 消耗: {data.get('usage', {}).get('total_tokens', '未知')}")

    if tool_calls:
        result = f"✅ 支持工具调用！自动调用了: {tool_calls[0]['function']['name']}"
        for tc in tool_calls:
            result += f"\n  - 工具: {tc['function']['name']}"
            result += f"\n    参数: {tc['function']['arguments']}"
        return result
    elif content:
        return f"⚠️  未调用工具，直接回答: {content[:100]}"
    else:
        return "❌ 响应异常: 既无 tool_calls 也无 content"


def main():
    print("=" * 60)
    print("  私有 LLM 连接测试")
    print("=" * 60)

    token = get_token()
    if not token:
        print("\n❌ 测试失败: 无法获取 token")
        exit(1)

    reply = chat(token, "你好，请用一句话介绍你自己")
    print(f"\n[3/3] AI 回复:")
    print(f"      {reply}")
    print()

    if reply and not reply.startswith("❌"):
        print("--- 测试数据查询 ---")
        reply2 = chat(token, "今天是2026年7月1日，请问昨天是几月几号？")
        print(f"AI 回复: {reply2}")
        print()

        print("--- 测试工具调用 ---")
        reply3 = tool_call_test(token)
        print(f"AI 回复: {reply3}")
    else:
        print(f"\n❌ 基础对话失败，跳过后续测试")

    print("\n" + "=" * 60)
    if reply and not reply.startswith("❌"):
        print("✅ 测试完成: 私有 LLM 连接正常")
    else:
        print("❌ 测试失败")


if __name__ == "__main__":
    main()
