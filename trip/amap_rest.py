"""高德 Web 服务 REST 接口（与 MCP 使用同一个 Key）。

MCP 返回的数据已能完成行程规划；这里只做补充：
  * 打车路线的完整 polyline（用于在地图上沿真实道路画线）和打车费用 taxi_cost
  * 景区照片
  * 静态地图图片（页面上显示的高德地图）
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

BASE = "https://restapi.amap.com"


def _get(path: str, params: dict, timeout: float = 20) -> bytes:
    url = f"{BASE}{path}?{urllib.parse.urlencode(params, safe=',;:|*')}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def _get_json(path: str, params: dict) -> dict:
    data = json.loads(_get(path, params))
    if str(data.get("status")) != "1":
        raise RuntimeError(f"{path}: {data.get('info')}")
    return data


def driving(key: str, origin: str, destination: str) -> dict:
    """返回 {distance(米), duration(秒), taxi_cost(元), polyline:[[lng,lat],...]}"""
    data = _get_json(
        "/v3/direction/driving",
        {"key": key, "origin": origin, "destination": destination, "extensions": "base"},
    )
    route = data["route"]
    path = route["paths"][0]
    points: list[list[float]] = []
    for step in path.get("steps", []):
        for pair in (step.get("polyline") or "").split(";"):
            if "," in pair:
                lng, lat = pair.split(",")
                points.append([float(lng), float(lat)])
    return {
        "distance": float(path.get("distance") or 0),
        "duration": float(path.get("duration") or 0),
        "taxi_cost": float(route["taxi_cost"]) if route.get("taxi_cost") else None,
        "polyline": points,
    }


def poi_photos(key: str, poi_id: str) -> list[str]:
    data = _get_json(
        "/v5/place/detail", {"key": key, "id": poi_id, "show_fields": "photos,business"}
    )
    pois = data.get("pois") or []
    if not pois:
        return []
    return [p["url"] for p in pois[0].get("photos") or [] if p.get("url")]


def static_map(key: str, markers: list[tuple[str, str, str]], paths: list[tuple[str, list]],
               zoom: int | None = None, center: str | None = None,
               size: str = "750*420") -> bytes:
    """高德静态地图。markers: [(label, color, "lng,lat")]；paths: [(color, [[lng,lat],...])]"""
    params = {"key": key, "size": size, "scale": 2}
    if zoom:
        params["zoom"] = zoom
        if center:
            params["location"] = center
    if markers:
        params["markers"] = "|".join(f"mid,{color},{label}:{loc}" for label, color, loc in markers)
    if paths:
        params["paths"] = "|".join(
            f"6,{color},0.9,,:" + ";".join(f"{p[0]:.6f},{p[1]:.6f}" for p in _simplify(pts))
            for color, pts in paths
            if len(pts) >= 2
        )
    body = _get("/v3/staticmap", params)
    if body[:1] == b"{":  # 出错时返回 JSON
        raise RuntimeError(json.loads(body).get("info", "staticmap error"))
    return body


def _simplify(points: list, limit: int = 50) -> list:
    """静态地图 URL 长度有限，均匀抽稀折线（保留首尾）。"""
    if len(points) <= limit:
        return points
    step = (len(points) - 1) / (limit - 1)
    return [points[round(i * step)] for i in range(limit)]
