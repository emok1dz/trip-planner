"""零依赖的高德地图 MCP Server 客户端（Streamable HTTP 传输）。

与码道 mcp_settings.json 中配置的是同一个服务：
    https://mcp.amap.com/mcp?key=<你的高德 Key>

只用到 MCP 协议的三个方法：initialize / tools/list / tools/call。
"""

from __future__ import annotations

import itertools
import json
import urllib.error
import urllib.request
from typing import Any

AMAP_MCP_URL = "https://mcp.amap.com/mcp?key={key}"
PROTOCOL_VERSION = "2025-03-26"


class McpError(RuntimeError):
    pass


def parse_sse(body: str) -> list[dict]:
    """把 text/event-stream 响应体解析成 JSON-RPC 消息列表。"""
    messages, data_lines = [], []
    for line in body.splitlines() + [""]:
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif line == "" and data_lines:
            payload = "\n".join(data_lines)
            data_lines = []
            try:
                messages.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
    return messages


class AmapMcpClient:
    def __init__(self, key: str | None = None, url: str | None = None, timeout: float = 30):
        if not url:
            if not key:
                raise ValueError("需要高德 Key 或 MCP URL")
            url = AMAP_MCP_URL.format(key=key)
        self.url = url
        self.timeout = timeout
        self.session_id: str | None = None
        self._ids = itertools.count(1)
        self.tools: dict[str, dict] = {}
        self.calls: list[str] = []  # 记录调用过的工具，页面上展示

    # ---------- 底层 JSON-RPC ----------
    def _post(self, message: dict) -> list[dict]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(
            self.url, data=json.dumps(message).encode(), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                body = resp.read().decode("utf-8", "replace")
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            raise McpError(f"HTTP {exc.code}: {exc.read()[:300]!r}") from exc
        except urllib.error.URLError as exc:
            raise McpError(f"无法连接高德 MCP 服务: {exc.reason}") from exc

        if not body.strip():
            return []
        if "text/event-stream" in ctype:
            return parse_sse(body)
        data = json.loads(body)
        return data if isinstance(data, list) else [data]

    def _request(self, method: str, params: dict | None = None) -> Any:
        rid = next(self._ids)
        msgs = self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        for msg in msgs:
            if msg.get("id") == rid:
                if "error" in msg:
                    raise McpError(f"{method} 失败: {msg['error']}")
                return msg.get("result")
        # 高德 Key 错误时服务直接返回 REST 风格的 {"status":"0","info":"INVALID_USER_KEY"}
        for msg in msgs:
            if msg.get("info"):
                raise McpError(f"{method} 失败: {msg.get('info')}")
        raise McpError(f"{method} 没有收到响应")

    def _notify(self, method: str) -> None:
        self._post({"jsonrpc": "2.0", "method": method})

    # ---------- MCP 方法 ----------
    def connect(self) -> "AmapMcpClient":
        result = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "nanjing-trip-planner", "version": "1.0"},
            },
        )
        if not isinstance(result, dict) or "protocolVersion" not in result:
            raise McpError(f"initialize 返回异常: {result}")
        self._notify("notifications/initialized")
        tools = (self._request("tools/list") or {}).get("tools", [])
        self.tools = {t["name"]: t for t in tools}
        return self

    def has(self, name: str) -> bool:
        return name in self.tools

    def call(self, name: str, arguments: dict) -> Any:
        """调用工具。高德 MCP 的结果放在 content[0].text 中（JSON 字符串），这里自动解析。"""
        self.calls.append(name)
        result = self._request("tools/call", {"name": name, "arguments": arguments}) or {}
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        text = "\n".join(texts)
        if result.get("isError"):
            raise McpError(f"{name} 返回错误: {text[:300]}")
        if result.get("structuredContent") is not None and not text:
            return result["structuredContent"]
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text
