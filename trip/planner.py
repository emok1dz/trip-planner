"""南京 3 天劳动节行程：调用高德 MCP 获取天气、景点、打车路线，生成页面数据。"""

from __future__ import annotations

import datetime as dt
import json
import math
import time
from pathlib import Path
from typing import Any

from . import amap_rest
from .amap_mcp import AmapMcpClient, McpError

CITY = "南京"
DAY_COLORS = ["0xE5484D", "0x0091FF", "0x30A46C"]  # 地图上每天路线的颜色
WEEK = "一二三四五六日"

# 按地理位置聚类的行程骨架：同一天的 3 个景点彼此相近，打车 10~30 分钟。
# location 为内置的近似坐标（GCJ-02），仅在高德 MCP 不可用时兜底使用。
ITINERARY: list[dict[str, Any]] = [
    {
        "theme": "钟山风景区 · 民国风情",
        "spots": [
            {"name": "中山陵", "keyword": "中山陵", "stay": 2.5, "ticket": "免费（需提前在“中山陵园风景区”小程序预约）",
             "intro": "孙中山先生陵寝，392 级台阶登顶可俯瞰钟山，建议早上 8 点前到达避开人流。",
             "location": [118.848, 32.0646]},
            {"name": "明孝陵", "keyword": "明孝陵", "stay": 2.0, "ticket": "70 元",
             "intro": "明太祖朱元璋与马皇后合葬陵，世界文化遗产，石象路两侧石像生非常出片。",
             "location": [118.8306, 32.059]},
            {"name": "南京总统府", "keyword": "南京总统府", "stay": 2.0, "ticket": "35 元（需实名预约）",
             "intro": "中国近代史遗址博物馆，600 余年历史，可看到太平天国天王府和民国总统府旧址。",
             "location": [118.7975, 32.0446]},
        ],
    },
    {
        "theme": "博物馆 · 老城南 · 秦淮夜色",
        "spots": [
            {"name": "南京博物院", "keyword": "南京博物院", "stay": 3.0, "ticket": "免费（提前 7 天预约，节假日秒光）",
             "intro": "中国三大博物馆之一，历史馆、民国馆必看，民国馆里可以体验民国街景。",
             "location": [118.8237, 32.0412]},
            {"name": "老门东", "keyword": "老门东历史街区", "stay": 2.0, "ticket": "免费",
             "intro": "保留明清老城南风貌的街区，青砖黛瓦，小吃众多，适合下午慢逛。",
             "location": [118.7895, 32.013]},
            {"name": "夫子庙秦淮风光带", "keyword": "夫子庙", "stay": 2.5, "ticket": "街区免费，秦淮河画舫约 80 元",
             "intro": "夜游秦淮河是南京名片，灯光亮起后（约 18:30）乘画舫最佳。",
             "location": [118.7887, 32.0215]},
        ],
    },
    {
        "theme": "铭记历史 · 古寺湖光",
        "spots": [
            {"name": "侵华日军南京大屠杀遇难同胞纪念馆", "keyword": "侵华日军南京大屠杀遇难同胞纪念馆", "stay": 2.5,
             "ticket": "免费（需预约，周一闭馆）",
             "intro": "铭记历史、缅怀同胞，馆内请保持肃静，参观约 2~3 小时。",
             "location": [118.7425, 32.0365]},
            {"name": "鸡鸣寺", "keyword": "鸡鸣寺", "stay": 1.5, "ticket": "10 元（含三支香）",
             "intro": "“南朝四百八十寺”之首，寺后可登明城墙远眺玄武湖。",
             "location": [118.7963, 32.0631]},
            {"name": "玄武湖", "keyword": "玄武湖景区", "stay": 2.5, "ticket": "免费",
             "intro": "江南最大的城内公园，傍晚沿湖骑行或散步，城墙与紫峰大厦同框。",
             "location": [118.7980, 32.072]},
        ],
    },
]

# 南京 5 月上旬历史同期气候（行程日期不在高德 4 日预报范围内时作参考）
CLIMATE_EARLY_MAY = [
    {"dayweather": "多云", "nightweather": "多云", "daytemp": "26", "nighttemp": "16", "daywind": "东南", "daypower": "1-3"},
    {"dayweather": "晴", "nightweather": "多云", "daytemp": "27", "nighttemp": "17", "daywind": "东", "daypower": "1-3"},
    {"dayweather": "阴转小雨", "nightweather": "小雨", "daytemp": "24", "nighttemp": "17", "daywind": "东北", "daypower": "3-4"},
]


# ---------------------------------------------------------------- 工具函数

def _haversine_km(a: list[float], b: list[float]) -> float:
    lng1, lat1, lng2, lat2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def taxi_fare_estimate(km: float) -> float:
    """南京出租车计价估算：起步 11 元/3 公里，之后约 2.4 元/公里。"""
    return round(11 + max(0.0, km - 3) * 2.4, 1)


def _loc_str(loc: list[float]) -> str:
    return f"{loc[0]:.6f},{loc[1]:.6f}"


def _parse_loc(value: Any) -> list[float] | None:
    if isinstance(value, str) and "," in value:
        lng, lat = value.split(",")[:2]
        return [float(lng), float(lat)]
    return None


def _fmt_time(minutes: float) -> str:
    m = int(round(minutes))
    return f"{m // 60:02d}:{m % 60:02d}"


def nav_url(a: dict, b: dict) -> str:
    """高德地图打车/驾车导航链接（手机上会唤起高德 App）。"""
    import urllib.parse

    q = urllib.parse.urlencode({
        "from": f"{_loc_str(a['location'])},{a['name']}",
        "to": f"{_loc_str(b['location'])},{b['name']}",
        "mode": "car", "policy": "1", "src": "nanjing-trip", "coordinate": "gaode", "callnative": "0",
    })
    return f"https://uri.amap.com/navigation?{q}"


# ---------------------------------------------------------------- 主流程

class Planner:
    def __init__(self, key: str | None, start_date: dt.date, log=print):
        self.key = key
        self.start = start_date
        self.log = log
        self.mcp: AmapMcpClient | None = None
        self.warnings: list[str] = []

    # ---- 高德 MCP 调用（失败时记录警告并返回 None）
    def _mcp(self, tool: str, args: dict) -> Any:
        if not self.mcp or not self.mcp.has(tool):
            return None
        try:
            self.log(f"  → MCP {tool} {json.dumps(args, ensure_ascii=False)}")
            return self.mcp.call(tool, args)
        except McpError as exc:
            self.warnings.append(f"{tool}: {exc}")
            return None

    def build(self) -> dict:
        source = "sample"
        if self.key:
            try:
                self.log("连接高德 MCP Server …")
                self.mcp = AmapMcpClient(self.key).connect()
                self.log(f"已连接，可用工具 {len(self.mcp.tools)} 个: {', '.join(self.mcp.tools)}")
                source = "mcp"
            except McpError as exc:
                self.warnings.append(f"高德 MCP 连接失败，使用内置示例数据: {exc}")
                self.log(self.warnings[-1])
        else:
            self.warnings.append("未配置高德 Key，使用内置示例数据（地图与实时天气不可用）")

        dates = [self.start + dt.timedelta(days=i) for i in range(len(ITINERARY))]
        weather = self.build_weather(dates)
        days = [self.build_day(i, dates[i]) for i in range(len(ITINERARY))]
        personal_map = self.build_personal_map(days)

        return {
            "title": f"南京 {len(days)} 日劳动节旅行攻略",
            "city": CITY,
            "start_date": dates[0].isoformat(),
            "end_date": dates[-1].isoformat(),
            "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "source": source,
            "mcp_tools_used": sorted(set(self.mcp.calls)) if self.mcp else [],
            "weather": weather,
            "tips": self.build_tips(weather),
            "days": days,
            "personal_map_url": personal_map,
            "warnings": self.warnings,
        }

    # ---- 天气：maps_weather
    def build_weather(self, dates: list[dt.date]) -> dict:
        data = self._mcp("maps_weather", {"city": CITY})
        forecasts = (data or {}).get("forecasts") if isinstance(data, dict) else None
        forecasts = forecasts or []
        by_date = {f.get("date"): f for f in forecasts}
        cards, matched = [], 0
        for i, d in enumerate(dates):
            f = by_date.get(d.isoformat())
            if f:
                matched += 1
                kind = "高德实时预报"
            else:
                f = CLIMATE_EARLY_MAY[i % len(CLIMATE_EARLY_MAY)]
                kind = "历史同期气候参考"
            cards.append({
                "date": d.isoformat(), "week": f"周{WEEK[d.weekday()]}", "kind": kind,
                "dayweather": f.get("dayweather"), "nightweather": f.get("nightweather"),
                "daytemp": f.get("daytemp"), "nighttemp": f.get("nighttemp"),
                "wind": f"{f.get('daywind', '')}风 {f.get('daypower', '')}级",
            })
        if matched == len(dates):
            note = "以下为高德 MCP（maps_weather）返回的实时预报。"
        elif forecasts:
            note = ("行程日期不在高德 4 日预报范围内，卡片显示历史同期气候；"
                    "下方附高德 MCP 返回的最新实时预报，出发前 3 天再查看一次即可获得准确预报。")
        else:
            note = "未获取到实时天气，卡片显示南京 5 月上旬历史同期气候。"
        live = [{
            "date": f.get("date"), "week": f"周{WEEK[int(f['week']) - 1]}" if str(f.get("week", "")).isdigit() else f.get("week"),
            "dayweather": f.get("dayweather"), "nightweather": f.get("nightweather"),
            "daytemp": f.get("daytemp"), "nighttemp": f.get("nighttemp"),
        } for f in forecasts]
        return {"cards": cards, "live": live, "note": note}

    # ---- 景点：maps_text_search + maps_search_detail
    def resolve_spot(self, spec: dict) -> dict:
        spot = {k: spec[k] for k in ("name", "intro", "ticket", "stay")}
        spot.update({"location": spec["location"], "address": "", "poi_id": None, "photos": [],
                     "rating": None, "opentime": None, "tel": None, "verified": False})
        res = self._mcp("maps_text_search", {"keywords": spec["keyword"], "city": CITY, "citylimit": True})
        pois = (res or {}).get("pois") if isinstance(res, dict) else None
        if pois:
            poi = pois[0]
            spot["poi_id"] = poi.get("id")
            spot["address"] = poi.get("address") or ""
            loc = _parse_loc(poi.get("location"))
            if loc:
                spot["location"], spot["verified"] = loc, True
            spot["photos"] = [p.get("url") for p in poi.get("photos") or [] if isinstance(p, dict) and p.get("url")]
        if spot["poi_id"]:
            detail = self._mcp("maps_search_detail", {"id": spot["poi_id"]})
            if isinstance(detail, dict):
                loc = _parse_loc(detail.get("location"))
                if loc:
                    spot["location"], spot["verified"] = loc, True
                spot["address"] = detail.get("address") or spot["address"]
                spot["rating"] = detail.get("rating") or (detail.get("biz_ext") or {}).get("rating") or None
                spot["opentime"] = detail.get("opentime2") or detail.get("open_time") or None
                spot["tel"] = detail.get("tel") or None
                photos = detail.get("photos") or []
                spot["photos"] = spot["photos"] or [p.get("url") for p in photos if isinstance(p, dict) and p.get("url")]
        # MCP 未返回照片时，用同一 Key 调用高德 POI 详情接口补充景区照片
        if self.key and self.mcp and spot["poi_id"] and not spot["photos"]:
            try:
                spot["photos"] = amap_rest.poi_photos(self.key, spot["poi_id"])
            except Exception as exc:  # noqa: BLE001
                self.warnings.append(f"{spot['name']} 照片获取失败: {exc}")
        spot["photos"] = [u.replace("http://", "https://", 1) for u in spot["photos"] if u][:3]
        return spot

    # ---- 打车：maps_direction_driving
    def build_leg(self, a: dict, b: dict) -> dict:
        leg = {"from": a["name"], "to": b["name"], "estimated": True, "polyline": [a["location"], b["location"]],
               "nav_url": nav_url(a, b)}
        km = _haversine_km(a["location"], b["location"]) * 1.35  # 直线距离 → 道路距离的经验系数
        leg.update({"distance_km": round(km, 1), "duration_min": round(km / 22 * 60 + 5), "taxi_cost": taxi_fare_estimate(km)})

        res = self._mcp("maps_direction_driving", {"origin": _loc_str(a["location"]), "destination": _loc_str(b["location"])})
        paths = (((res or {}).get("route") or {}).get("paths") or []) if isinstance(res, dict) else []
        if paths:
            p = paths[0]
            km = float(p.get("distance") or 0) / 1000
            leg.update({"distance_km": round(km, 1), "duration_min": round(float(p.get("duration") or 0) / 60),
                        "taxi_cost": taxi_fare_estimate(km), "estimated": False,
                        "steps": [s.get("instruction") for s in p.get("steps") or [] if s.get("instruction")][:12]})
            pts = []
            for s in p.get("steps") or []:
                for pair in (s.get("polyline") or "").split(";"):
                    loc = _parse_loc(pair)
                    if loc:
                        pts.append(loc)
            if pts:
                leg["polyline"] = pts
        # 补充：真实道路折线 + 高德打车费用
        if self.key and self.mcp:
            try:
                r = amap_rest.driving(self.key, _loc_str(a["location"]), _loc_str(b["location"]))
                if r["polyline"] and len(leg["polyline"]) <= 2:
                    leg["polyline"] = r["polyline"]
                if r["taxi_cost"]:
                    leg["taxi_cost"] = r["taxi_cost"]
                if leg["estimated"]:
                    leg.update({"distance_km": round(r["distance"] / 1000, 1), "duration_min": round(r["duration"] / 60),
                                "estimated": False})
            except Exception as exc:  # noqa: BLE001
                self.warnings.append(f"{a['name']}→{b['name']} 路线补充失败: {exc}")
        return leg

    def build_day(self, i: int, date: dt.date) -> dict:
        spec = ITINERARY[i]
        self.log(f"规划第 {i + 1} 天：{spec['theme']}")
        spots = [self.resolve_spot(s) for s in spec["spots"]]
        legs = [self.build_leg(spots[j], spots[j + 1]) for j in range(len(spots) - 1)]

        # 时间表：9:00 出发，景点间打车，中午留 1 小时午餐
        t, lunch_done, schedule = 9 * 60, False, []
        for j, s in enumerate(spots):
            s["arrive"] = _fmt_time(t)
            t += s["stay"] * 60
            s["leave"] = _fmt_time(t)
            schedule.append({"time": f"{s['arrive']}-{s['leave']}", "type": "spot", "text": s["name"]})
            if not lunch_done and t >= 11.5 * 60 and j < len(spots) - 1:
                schedule.append({"time": f"{_fmt_time(t)}-{_fmt_time(t + 60)}", "type": "meal", "text": "午餐"})
                t += 60
                lunch_done = True
            if j < len(legs):
                leg = legs[j]
                end = t + 10 + leg["duration_min"]  # 预留 10 分钟候车
                schedule.append({"time": f"{_fmt_time(t)}-{_fmt_time(end)}", "type": "taxi",
                                 "text": f"打车 {leg['distance_km']} 公里 · 车程约 {leg['duration_min']} 分钟（另留 10 分钟候车）· 约 {leg['taxi_cost']:.0f} 元"})
                t = end
        return {
            "index": i + 1, "date": date.isoformat(), "week": f"周{WEEK[date.weekday()]}", "theme": spec["theme"],
            "color": "#" + DAY_COLORS[i % len(DAY_COLORS)][2:], "map_color": DAY_COLORS[i % len(DAY_COLORS)],
            "spots": spots, "legs": legs, "schedule": schedule,
            "taxi_total": round(sum(l["taxi_cost"] for l in legs)),
        }

    # ---- 行程专属地图：maps_schema_personal_map（生成可在高德 App/网页打开的行程地图链接）
    def build_personal_map(self, days: list[dict]) -> str | None:
        if not self.mcp or not self.mcp.has("maps_schema_personal_map"):
            return None
        line_list = [{
            "title": f"第{d['index']}天 {d['theme']}",
            "pointInfoList": [{"name": s["name"], "lon": s["location"][0], "lat": s["location"][1],
                               "poiId": s["poi_id"] or ""} for s in d["spots"]],
        } for d in days]
        res = self._mcp("maps_schema_personal_map", {"orgName": "南京劳动节3日游", "lineList": line_list})
        if isinstance(res, str):
            return res.strip() or None
        if isinstance(res, dict):
            for k in ("url", "uri", "schema", "link"):
                if res.get(k):
                    return res[k]
        return None

    @staticmethod
    def build_tips(weather: dict) -> list[str]:
        tips = [
            "五一是南京客流最高峰：中山陵、南京博物院、总统府、纪念馆都需提前实名预约，建议提前 7 天蹲放票。",
            "同一天景点之间打车最省心；节假日景区门口打车难，可提前在高德地图“打车”里预约，或步行到附近路口上车。",
            "钟山风景区内有观光小火车，中山陵到明孝陵也可乘坐，体力不够时可作为替代。",
            "夫子庙秦淮河画舫晚上排队较长，建议 18:00 前到码头购票。",
            "必吃：鸭血粉丝汤、盐水鸭、小笼包、梅花糕、赤豆元宵，老门东和夫子庙周边都有老字号。",
            "纪念馆周一闭馆，请注意日期；馆内保持肃静，着装得体。",
        ]
        cards = weather.get("cards") or []
        if any("雨" in (c.get("dayweather") or "") + (c.get("nightweather") or "") for c in cards):
            tips.insert(0, "行程中可能有降雨，请携带雨具；雨天可把南京博物院等室内场馆调整到下雨当天。")
        temps = [int(c["daytemp"]) for c in cards if str(c.get("daytemp", "")).lstrip("-").isdigit()]
        if temps and max(temps) >= 26:
            tips.insert(0, f"白天最高约 {max(temps)}°C，紫外线较强，注意防晒补水；早晚温差大，带件薄外套。")
        return tips


def build_plan(key: str | None, start_date: dt.date, cache: Path | None = None, log=print) -> dict:
    t0 = time.time()
    plan = Planner(key, start_date, log=log).build()
    log(f"行程数据生成完成（{plan['source']}，耗时 {time.time() - t0:.1f}s）")
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan
