# -*- coding: utf-8 -*-
"""垃圾回收化矿:读取 reprocessing.json,结合行情库计算 55% 化矿产出与收益。

衍生装备的材料表在生成阶段已替换为其 T1 母装备的工业材料表,
接口原样透出 basis_id / basis_name 供页面标注化矿基准。
"""
import json
from pathlib import Path

import pymysql

from db_config import load_db_config

REGION_ID = 10000002
MAX_RATE = 0.55
DATA_PATH = Path(__file__).resolve().parent / "reprocessing.json"

_data_cache = {"mtime": None, "data": None}


def load_data():
    """按 mtime 缓存化矿清单,文件更新后自动重载。"""
    mtime = DATA_PATH.stat().st_mtime
    if _data_cache["data"] is None or _data_cache["mtime"] != mtime:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            _data_cache["data"] = json.load(f)
        _data_cache["mtime"] = mtime
    return _data_cache["data"]


def price_ids():
    """页面和行情更新需要报价的 type_id:化矿物品本身 + 全部化矿产物。"""
    data = load_data()
    ids = {item["id"] for item in data["items"]}
    ids.update(int(tid) for tid in data["material_names"])
    return ids


def _query_prices(ids):
    """批量读取吉他 4-4 行情;行情表里的缺失物品按 0 处理。"""
    if not ids:
        return {}, None
    result = {}
    updated_at = None
    conn = None
    try:
        conn = pymysql.connect(**load_db_config())
        with conn.cursor() as cursor:
            ids = list(ids)
            for i in range(0, len(ids), 500):
                batch = ids[i:i + 500]
                placeholders = ",".join(["%s"] * len(batch))
                cursor.execute(
                    "SELECT type_id, buy_max, sell_min, updated_at FROM market_prices "
                    f"WHERE region_id = %s AND type_id IN ({placeholders})",
                    [REGION_ID, *batch],
                )
                for tid, buy_max, sell_min, row_updated in cursor.fetchall():
                    result[tid] = (buy_max or 0, sell_min or 0)
                    if row_updated and (updated_at is None or row_updated > updated_at):
                        updated_at = row_updated
    finally:
        if conn:
            conn.close()
    return result, updated_at


def get_catalog():
    """返回页面所需的全部物品、化矿配方与当前行情。

    材料名称单独放在 materials 映射中,避免在每个物品里重复。
    """
    data = load_data()
    ids = price_ids()
    prices, updated_at = _query_prices(ids)

    materials = {}
    for tid, name in data["material_names"].items():
        buy_max, sell_min = prices.get(int(tid), (0, 0))
        materials[tid] = {"name": name, "buy_max": buy_max, "sell_min": sell_min}

    items = []
    for item in data["items"]:
        buy_max, sell_min = prices.get(item["id"], (0, 0))
        items.append({
            "id": item["id"],
            "name": item["name"],
            "group": item["group"],
            "kind": item["kind"],
            "meta_level": item["meta_level"],
            "portion_size": item["portion_size"],
            "basis_id": item.get("basis_id"),
            "basis_name": item.get("basis_name"),
            "buy_max": buy_max,
            "sell_min": sell_min,
            "materials": item["materials"],
        })

    return {
        "max_rate": data.get("max_rate", MAX_RATE),
        "updated_at": updated_at.strftime("%Y-%m-%d %H:%M:%S") if updated_at else None,
        "items": items,
        "materials": materials,
    }
