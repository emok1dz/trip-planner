"""南京 3 天劳动节旅行攻略 —— Web 服务入口。

    python app.py            # 生成行程（调用高德 MCP）、启动服务并自动打开浏览器
    python app.py --refresh  # 忽略缓存，重新调用高德 MCP
    python app.py --no-browser

只使用 Python 标准库，无需安装任何依赖（Python 3.8+）。
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from trip import amap_rest, config
from trip.planner import build_plan

WEB = config.ROOT / "web"
CACHE = config.ROOT / "data" / "plan_cache.json"
SAMPLE = config.ROOT / "data" / "sample_plan.json"


class State:
    plan: dict = {}
    key: str | None = None
    map_cache: dict[tuple, bytes] = {}
    lock = threading.Lock()


def load_plan(refresh: bool = False) -> dict:
    key = State.key
    if not refresh and CACHE.exists():
        plan = json.loads(CACHE.read_text(encoding="utf-8"))
        if plan.get("start_date") == config.start_date().isoformat() and (plan.get("source") == "mcp" or not key):
            print(f"使用缓存的行程数据 {CACHE.name}（生成于 {plan.get('generated_at')}，--refresh 可重新生成）")
            return plan
    if not key and SAMPLE.exists() and config.start_date().isoformat() == "2026-05-01":
        print("未配置高德 Key（AMAP_MAPS_API_KEY），使用内置示例数据。")
        return json.loads(SAMPLE.read_text(encoding="utf-8"))
    return build_plan(key, config.start_date(), cache=CACHE if key else None)


def day_map(day_index: int, zoom: int | None) -> bytes:
    """当天路线的高德静态地图：A/B/C 标注景点，沿打车路线画线。"""
    day = State.plan["days"][day_index - 1]
    ck = (day_index, zoom, State.plan.get("generated_at"))
    with State.lock:
        if ck in State.map_cache:
            return State.map_cache[ck]
    markers = [(chr(65 + i), day["map_color"], f"{s['location'][0]:.6f},{s['location'][1]:.6f}")
               for i, s in enumerate(day["spots"])]
    paths = [(day["map_color"], leg["polyline"]) for leg in day["legs"]]
    center = None
    if zoom:
        locs = [s["location"] for s in day["spots"]]
        center = f"{sum(l[0] for l in locs) / len(locs):.6f},{sum(l[1] for l in locs) / len(locs):.6f}"
    img = amap_rest.static_map(State.key, markers, paths, zoom=zoom, center=center)
    with State.lock:
        State.map_cache[ck] = img
    return img


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, fmt, *args):  # 安静一点
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write("  " + fmt % args + "\n")

    def _json(self, obj, status=HTTPStatus.OK):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/api/plan":
            plan = dict(State.plan, has_key=bool(State.key))
            return self._json(plan)
        if url.path == "/api/map":
            if not State.key:
                return self._json({"error": "未配置高德 Key"}, HTTPStatus.SERVICE_UNAVAILABLE)
            try:
                day = int(q.get("day", ["1"])[0])
                zoom = int(q["zoom"][0]) if q.get("zoom") and q["zoom"][0] else None
                if zoom is not None:
                    zoom = max(3, min(17, zoom))
                img = day_map(day, zoom)
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "max-age=3600")
            self.send_header("Content-Length", str(len(img)))
            self.end_headers()
            self.wfile.write(img)
            return
        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path == "/api/refresh":
            if not State.key:
                return self._json({"error": "未配置高德 Key，无法刷新"}, HTTPStatus.BAD_REQUEST)
            State.plan = build_plan(State.key, config.start_date(), cache=CACHE)
            State.map_cache.clear()
            return self._json({"ok": True})
        self.send_error(HTTPStatus.NOT_FOUND)


def free_port(preferred: int) -> int:
    for p in [preferred, *range(preferred + 1, preferred + 50)]:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return 0


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows 控制台中文
    ap = argparse.ArgumentParser(description="南京 3 天劳动节旅行攻略")
    ap.add_argument("--refresh", action="store_true", help="重新调用高德 MCP 生成行程")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    config.load_env()
    State.key = config.amap_key()
    State.plan = load_plan(refresh=args.refresh)
    for w in State.plan.get("warnings", []):
        print("  [提示]", w)

    port = free_port(config.port())
    server = ThreadingHTTPServer((args.host, port), Handler)
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{server.server_port}/"
    print(f"\n旅行攻略已启动：{url}  （Ctrl+C 退出）")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
