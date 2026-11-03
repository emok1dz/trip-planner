# 南京劳动节3日游智能行程规划

华为云码道 + 高德地图 MCP Server 实现的智能行程规划 Web 应用。

ICT 大赛实践赛题 **1.7 MCP-智能行程规划** 的作品：通过 MCP 协议接入高德地图，生成
**南京 3 天劳动节（2026-05-01 ~ 2026-05-03）** 的旅行攻略 Web 应用。

| 赛题提示词要求 | 实现情况 |
| --- | --- |
| Python + HTML 生成 Web 服务 | `app.py`（Python 标准库 http.server）+ `web/` 静态页面 |
| 天气卡片展示 3 天天气详情 + 旅行小贴士 | 高德 MCP `maps_weather`；小贴士会根据天气自动调整（降雨/高温） |
| 每天的旅行计划，每天 3 个景点 | 按地理位置聚类，三天各 3 个景点，带时间表 |
| 网页地图绘制旅游路线和位置 | 高德地图绘制当天 A/B/C 景点标注和沿真实道路的打车路线，支持 + / − / 滚轮缩放 |
| 直接显示高德地图，不用 JS 生成的地图 | 地图图片由高德地图服务渲染（没有用 JS/Canvas 自己画）；另用 MCP `maps_schema_personal_map` 生成可在高德地图中打开的全程行程地图 |
| 简约美观，景区图片以卡片展示 | 景点卡片：高德 POI 照片、评分、地址、门票、游玩时长 |
| 同一天景区之间打车 | MCP `maps_direction_driving` 计算车程、距离，显示打车费用，并附“高德打车/导航”链接 |
| 自动运行打开，无需手动安装依赖 | 零第三方依赖，`python app.py` 自动打开浏览器 |

## 一、准备高德 Key（实验手册 2.1）

1. 登录 [高德开放平台](https://lbs.amap.com/)，进入 **控制台**。
2. **账号中心 → 账号认证 → 个人开发者认证**。
3. **应用管理 → 我的应用 → 创建新应用 → 添加 Key**，服务平台选择 **Web 服务**，提交。

## 二、在华为云码道中配置高德 MCP Server（实验手册 2.2）

码道 CodeArts Agent：Chat 右上角 **设置 → 配置 MCP 服务器**，在 `mcp_settings.json` 中写入
（本仓库根目录的 [`mcp_settings.json`](mcp_settings.json) 就是这份配置），把 key 换成自己的，`Ctrl + S` 保存：

```json
{
  "mcpServers": {
    "amap-maps-streamableHTTP": {
      "url": "https://mcp.amap.com/mcp?key=您在高德官网上申请的key",
      "type": "streamableHttp"
    }
  }
}
```

然后在码道智能体中输入实验手册里的提示词即可（本仓库就是按这份提示词实现的结果）：

```text
##南京3天劳动节（26年5月1日到26年5月3日）的旅行攻略应用。
#帮我制作旅行攻略应用，考虑出行时间和路线，以及天气状况路线规划。
#通过python和html生成一个web服务，页面包含天气卡片展示3天的天气详情以及旅行小贴士，展示每天的旅行计划，每天安排3个景点。
#制作网页地图自定义绘制旅游路线和位置。
##网页使用简约美观页面风格，景区图片以卡片展示。
#直接在页面显示高德MCP展示的地图，不要用JS生成的地图。
##同一天行程景区之间我想打车前往。
#生成应用后自动运行打开，无需手动安装其他依赖。
```

## 三、运行（实验手册 2.3）

需要 Python 3.8+，**无需 pip 安装任何依赖**。

```bash
# 1. 配置 Key（二选一）
copy .env.example .env        # Windows；macOS/Linux 用 cp，然后编辑 .env 填入 AMAP_MAPS_API_KEY
# 或: set AMAP_MAPS_API_KEY=xxxx

# 2. 启动（Windows 也可以直接双击 start.bat）
python app.py
```

启动时程序会连接 `https://mcp.amap.com/mcp?key=...`，依次调用高德 MCP 工具，并在控制台打印调用记录：

```
连接高德 MCP Server …
已连接，可用工具 15 个: maps_weather, maps_text_search, ...
  → MCP maps_weather {"city": "南京"}
  → MCP maps_text_search {"keywords": "中山陵", "city": "南京", "citylimit": true}
  → MCP maps_search_detail {"id": "..."}
  → MCP maps_direction_driving {"origin": "...", "destination": "..."}
  ...
旅行攻略已启动：http://127.0.0.1:8000/
```

结果缓存在 `data/plan_cache.json`，再次启动直接使用；`python app.py --refresh` 重新调用 MCP。
没有配置 Key 时使用内置示例数据 `data/sample_plan.json`，页面同样可以浏览（地图位置会显示配置提示）。

> 说明：高德天气只提供未来 4 天预报。行程日期不在预报范围内时，天气卡片显示南京 5 月上旬
> 历史同期气候（卡片上有标注），同时在下方列出 MCP 返回的最新实时预报。
> 可以用 `TRIP_START_DATE=2026-11-05` 之类的设置把行程改到近期，就能看到行程日期的实时预报。

## 行程概览

| 天 | 主题 | 景点（打车串联） |
| --- | --- | --- |
| 5/1 周五 | 钟山风景区 · 民国风情 | 中山陵 → 明孝陵 → 南京总统府 |
| 5/2 周六 | 博物馆 · 老城南 · 秦淮夜色 | 南京博物院 → 老门东 → 夫子庙秦淮风光带 |
| 5/3 周日 | 铭记历史 · 古寺湖光 | 侵华日军南京大屠杀遇难同胞纪念馆 → 鸡鸣寺 → 玄武湖 |

## 项目结构

```
app.py               Web 服务入口：生成行程、提供 /api/plan、/api/map，自动打开浏览器
trip/amap_mcp.py     零依赖 MCP 客户端（Streamable HTTP：initialize / tools/list / tools/call）
trip/planner.py      行程规划：调用 maps_weather / maps_text_search / maps_search_detail /
                     maps_direction_driving / maps_schema_personal_map
trip/amap_rest.py    同一 Key 的高德 Web 服务补充：静态地图、道路折线、打车费、景区照片
web/                 页面（index.html / style.css / app.js）
mcp_settings.json    码道 MCP 服务器配置模板
tests/               离线测试（内置模拟高德 MCP Server）：python -m unittest discover -s tests
```

## 四、发布作品（实验手册 3.1）

在码道对话框中输入，由码道代为执行（需要你的华为云账号登录）：

```text
npx skills add https://gitcode.com/Lingxi-HandsOn/gallery.git --skill huawei-cloud-publish-ict-work -y 2>&1; 发布ICT大赛作品。
```
