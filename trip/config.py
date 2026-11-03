"""读取配置：环境变量优先，其次项目根目录下的 .env 文件。"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def amap_key() -> str | None:
    key = os.getenv("AMAP_MAPS_API_KEY", "").strip()
    return key if key and "你的" not in key and key != "your_amap_key" else None


def start_date() -> dt.date:
    # 实验题要求：2026 年 5 月 1 日 ~ 5 月 3 日（劳动节）
    return dt.date.fromisoformat(os.getenv("TRIP_START_DATE", "2026-05-01"))


def port() -> int:
    return int(os.getenv("PORT", "8000"))
