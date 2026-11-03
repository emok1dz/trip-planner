"""离线测试：启动一个模拟的高德 MCP Server（Streamable HTTP），验证 MCP 客户端与行程生成流程。

    python -m unittest discover -s tests
"""

import datetime as dt
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trip import amap_mcp, planner  # noqa: E402
from trip.amap_mcp import AmapMcpClient, parse_sse  # noqa: E402

COORDS = {"中山陵": "118.848,32.064", "明孝陵": "118.830,32.059"}
TOOLS = ["maps_weather", "maps_text_search", "maps_search_detail", "maps_direction_driving",
         "maps_schema_personal_map"]


def fake_tool(name, args):
    if name == "maps_weather":
        return {"city": "南京市", "forecasts": [
            {"date": "2026-05-01", "week": "5", "dayweather": "晴", "nightweather": "多云", "daytemp": "28",
             "nighttemp": "17", "daywind": "东", "daypower": "1-3"},
            {"date": "2026-05-02", "week": "6", "dayweather": "小雨", "nightweather": "小雨", "daytemp": "22",
             "nighttemp": "16", "daywind": "北", "daypower": "3-4"},
        ]}
    if name == "maps_text_search":
        kw = args["keywords"]
        return {"pois": [{"id": "B" + str(abs(hash(kw)) % 10000), "name": kw, "address": kw + "路1号"}]}
    if name == "maps_search_detail":
        return {"id": args["id"], "location": "118.80,32.05", "address": "详细地址", "rating": "4.8",
                "photos": [{"url": "http://example.com/a.jpg"}]}
    if name == "maps_direction_driving":
        return {"route": {"paths": [{"distance": "5200", "duration": "900",
                                     "steps": [{"instruction": "向东行驶", "polyline": "118.80,32.05;118.81,32.06"}]}]}}
    if name == "maps_schema_personal_map":
        return "amapuri://workInAmap/createWithToken?polymericId=test"
    raise KeyError(name)


class FakeMcp(BaseHTTPRequestHandler):
    sse = False

    def log_message(self, *a):
        pass

    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if "id" not in msg:
            self.send_response(202)
            self.end_headers()
            return
        if msg["method"] == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "fake-amap", "version": "1"}}
        elif msg["method"] == "tools/list":
            assert self.headers.get("Mcp-Session-Id") == "s1"
            result = {"tools": [{"name": t, "inputSchema": {"type": "object"}} for t in TOOLS]}
        else:
            p = msg["params"]
            result = {"content": [{"type": "text", "text": json.dumps(fake_tool(p["name"], p["arguments"]),
                                                                      ensure_ascii=False)
                                   if not isinstance(fake_tool(p["name"], p["arguments"]), str)
                                   else fake_tool(p["name"], p["arguments"])}]}
        body = json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}, ensure_ascii=False)
        self.send_response(200)
        self.send_header("Mcp-Session-Id", "s1")
        if FakeMcp.sse:
            self.send_header("Content-Type", "text/event-stream")
            data = f"event: message\ndata: {body}\n\n".encode()
        else:
            self.send_header("Content-Type", "application/json")
            data = body.encode()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class TestMcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeMcp)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/mcp"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_parse_sse(self):
        msgs = parse_sse('event: message\ndata: {"id": 1}\n\ndata: {"id": 2}\n')
        self.assertEqual([m["id"] for m in msgs], [1, 2])

    def test_client_json_and_sse(self):
        for sse in (False, True):
            FakeMcp.sse = sse
            c = AmapMcpClient(url=self.url).connect()
            self.assertEqual(sorted(c.tools), sorted(TOOLS))
            self.assertEqual(c.call("maps_weather", {"city": "南京"})["city"], "南京市")
        FakeMcp.sse = False

    def test_build_plan_with_mcp(self):
        real = AmapMcpClient.__init__

        def init(self, key=None, url=None, timeout=30):
            real(self, url=TestMcp.url)

        with mock.patch.object(AmapMcpClient, "__init__", init), \
                mock.patch.object(planner.amap_rest, "driving", side_effect=RuntimeError("offline")), \
                mock.patch.object(planner.amap_rest, "poi_photos", return_value=[]):
            plan = planner.build_plan("fake-key", dt.date(2026, 5, 1), log=lambda *a: None)

        self.assertEqual(plan["source"], "mcp")
        self.assertEqual(len(plan["days"]), 3)
        self.assertTrue(all(len(d["spots"]) == 3 for d in plan["days"]))
        self.assertIn("maps_weather", plan["mcp_tools_used"])
        cards = plan["weather"]["cards"]
        self.assertEqual(cards[0]["kind"], "高德实时预报")
        self.assertEqual(cards[2]["kind"], "历史同期气候参考")
        spot = plan["days"][0]["spots"][0]
        self.assertTrue(spot["verified"])
        self.assertEqual(spot["photos"], ["https://example.com/a.jpg"])
        leg = plan["days"][0]["legs"][0]
        self.assertFalse(leg["estimated"])
        self.assertEqual(leg["distance_km"], 5.2)
        self.assertEqual(leg["duration_min"], 15)
        self.assertTrue(plan["personal_map_url"].startswith("amapuri://"))
        self.assertTrue(any("雨" in t for t in plan["tips"]))

    def test_offline_plan(self):
        plan = planner.build_plan(None, dt.date(2026, 5, 1), log=lambda *a: None)
        self.assertEqual(plan["source"], "sample")
        self.assertEqual(plan["days"][2]["week"], "周日")
        self.assertTrue(all(l["estimated"] for d in plan["days"] for l in d["legs"]))

    def test_taxi_fare(self):
        self.assertEqual(planner.taxi_fare_estimate(2), 11)
        self.assertEqual(planner.taxi_fare_estimate(8), 23.0)


if __name__ == "__main__":
    unittest.main()
