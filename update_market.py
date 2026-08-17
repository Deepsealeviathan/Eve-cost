# -*- coding: utf-8 -*-
"""
行情更新流水线(直连 ESI 版):
1. 扫描配方 JSON 和 categories.json,自动收集需要跟踪的物品(type_id / 名称 / 分类)
2. 从网易 ESI 镜像整域拉取伏尔戈星域(The Forge)全部市场订单
3. 过滤出吉他 4-4 加达里海军组装车间(location_id=60003760)的订单,按物品聚合价格
4. 直接 upsert 到 MySQL(items / market_prices 两张表),不落任何中间文件

用法: python update_market.py
"""
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymysql
import requests

from db_config import load_db_config

# ================== 用户配置 ==================
ESI = "https://ali-esi.evepc.163.com/latest"   # 网易国服 ESI 镜像
DATASOURCE = "serenity"                          # 晨曦服务器
REGION_ID = 10000002                             # 伏尔戈星域(The Forge)
JITA_44 = 60003760                               # 吉他 IV - 卫星 4 - 加达里海军组装车间

HEADERS = {"User-Agent": "eve-cost/0.5 (https://github.com/Deepsealeviathan/Eve-cost)"}
MAX_WORKERS = 8        # 并发拉取页数,出现大量连接错误时调小
MAX_RETRIES = 4
BATCH_SIZE = 100

BASE_DIR = Path(__file__).resolve().parent

# 配方 JSON 搜索目录(分类即目录名 P1~P4)
RECIPE_ROOTS = [
    'Ore', 'MoonMaterials', 'Gas', 'Commodities',
    'Planetary_Commodities/P1', 'Planetary_Commodities/P2',
    'Planetary_Commodities/P3', 'Planetary_Commodities/P4',
]

# 不出现在任何配方中、但有市场价的物品,在此手动补充 type_id(静态数据,不会变)
EXTRA_TYPE_IDS = {
    "氧燃料块": 4312,
    "氢燃料块": 4246,
    "氦燃料块": 4247,
    "氮燃料块": 4051,
}
# ==============================================

_thread_local = threading.local()


def get_session():
    """每个线程独享一个 requests.Session,复用连接。"""
    if not hasattr(_thread_local, 'session'):
        _thread_local.session = requests.Session()
        _thread_local.session.headers.update(HEADERS)
    return _thread_local.session


def esi_get(path, params=None):
    """带重试的 GET;多次失败返回 None。"""
    url = f"{ESI}{path}"
    params = {**(params or {}), "datasource": DATASOURCE}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = get_session().get(url, params=params, timeout=30)
            if resp.status_code in (420, 429, 500, 502, 503, 504):
                time.sleep(2 * attempt)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            print(f"[重试 {attempt}/{MAX_RETRIES}] {path}: {e}")
            time.sleep(2 * attempt)
    return None


def collect_tracked_items():
    """
    收集需要跟踪行情的物品:
    - 扫描 RECIPE_ROOTS 下所有配方 JSON,取自身 id 和配方 inputs 的 materialId
    - 追加 EXTRA_TYPE_IDS 中的物品
    - 分类:行星产物按目录记 P1~P4,其余查 categories.json,都不在则「其他」
    返回 {type_id: {"name": str, "category": str}}
    """
    name_category = {}

    def add(type_id, name):
        if type_id is None or not name:
            return
        name_category.setdefault(name, None)  # 占位,分类稍后统一打
        tracked.setdefault(int(type_id), name)

    tracked = {}
    for root in RECIPE_ROOTS:
        root_path = BASE_DIR / root
        if not root_path.is_dir():
            continue
        for json_file in root_path.rglob('*.json'):
            try:
                data = json.loads(json_file.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            add(data.get('id'), data.get('name'))
            for inp in data.get('recipe', {}).get('inputs', []):
                add(inp.get('materialId'), inp.get('materialname'))

    for name, type_id in EXTRA_TYPE_IDS.items():
        tracked.setdefault(type_id, name)
        name_category.setdefault(name, None)

    # 分类:行星产物目录 > categories.json > 其他
    for tier in ('P1', 'P2', 'P3', 'P4'):
        tier_dir = BASE_DIR / 'Planetary_Commodities' / tier
        if not tier_dir.is_dir():
            continue
        for json_file in tier_dir.glob('*.json'):
            try:
                item_name = json.loads(json_file.read_text(encoding='utf-8')).get('name')
            except (json.JSONDecodeError, UnicodeDecodeError):
                item_name = None
            if item_name:
                name_category[item_name] = tier

    cat_file = BASE_DIR / 'categories.json'
    if cat_file.is_file():
        for cat_name, names in json.loads(cat_file.read_text(encoding='utf-8')).items():
            for item_name in names:
                # categories.json 不覆盖行星产物的 P1~P4 分类
                if name_category.get(item_name) not in ('P1', 'P2', 'P3', 'P4'):
                    name_category[item_name] = cat_name

    return {
        type_id: {"name": name, "category": name_category.get(name) or '其他'}
        for type_id, name in tracked.items()
    }


def fetch_region_orders():
    """整域拉取 The Forge 全部订单(并发分页),返回订单列表。"""
    first = esi_get(f"/markets/{REGION_ID}/orders/")
    if first is None:
        raise RuntimeError("拉取订单第 1 页失败")
    pages = int(first.headers.get("X-Pages", 1))
    orders = first.json()
    print(f"订单共 {pages} 页,并发拉取中...")

    def fetch_page(page):
        resp = esi_get(f"/markets/{REGION_ID}/orders/", {"page": page})
        return resp.json() if resp is not None else []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for batch in pool.map(fetch_page, range(2, pages + 1)):
            orders.extend(batch)

    print(f"拉取完成,共 {len(orders)} 条订单")
    return orders


def aggregate_jita44(orders):
    """过滤吉他 4-4 订单并按 type_id 聚合出 buy/sell 的 max/min/volume。"""
    stats = {}
    for o in orders:
        if o["location_id"] != JITA_44:
            continue
        s = stats.setdefault(o["type_id"], {
            "buy_max": 0.0, "buy_min": None, "buy_volume": 0,
            "sell_max": 0.0, "sell_min": None, "sell_volume": 0,
        })
        price, vol = o["price"], o["volume_remain"]
        if o["is_buy_order"]:
            s["buy_max"] = max(s["buy_max"], price)
            s["buy_min"] = price if s["buy_min"] is None else min(s["buy_min"], price)
            s["buy_volume"] += vol
        else:
            s["sell_max"] = max(s["sell_max"], price)
            s["sell_min"] = price if s["sell_min"] is None else min(s["sell_min"], price)
            s["sell_volume"] += vol
    print(f"吉他 4-4 有订单的物品: {len(stats)} 种")
    return stats


def sync_to_db(tracked, stats):
    """upsert items 和 market_prices,无订单的物品价格置 0。"""
    now = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())

    items_sql = """
        INSERT INTO items (type_id, name, category)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category)
    """
    prices_sql = """
        INSERT INTO market_prices
            (type_id, region_id, buy_max, buy_min, sell_max, sell_min,
             buy_volume, sell_volume, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            buy_max = VALUES(buy_max), buy_min = VALUES(buy_min),
            sell_max = VALUES(sell_max), sell_min = VALUES(sell_min),
            buy_volume = VALUES(buy_volume), sell_volume = VALUES(sell_volume),
            updated_at = VALUES(updated_at)
    """

    items_rows = [(tid, info["name"], info["category"]) for tid, info in tracked.items()]
    price_rows = []
    for tid in tracked:
        s = stats.get(tid)
        if s:
            price_rows.append((
                tid, REGION_ID, s["buy_max"], s["buy_min"] or 0,
                s["sell_max"], s["sell_min"] or 0,
                s["buy_volume"], s["sell_volume"], now,
            ))
        else:
            price_rows.append((tid, REGION_ID, 0, 0, 0, 0, 0, 0, now))

    conn = None
    try:
        conn = pymysql.connect(**load_db_config())
        with conn.cursor() as cursor:
            for sql, rows in ((items_sql, items_rows), (prices_sql, price_rows)):
                for i in range(0, len(rows), BATCH_SIZE):
                    cursor.executemany(sql, rows[i:i + BATCH_SIZE])
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

    return len(price_rows)


def main():
    print("收集跟踪物品清单...")
    tracked = collect_tracked_items()
    print(f"共 {len(tracked)} 种物品")

    orders = fetch_region_orders()
    stats = aggregate_jita44(orders)

    print("同步数据库...")
    total = sync_to_db(tracked, stats)
    print(f"导入完成,共更新 {total} 条记录。")
    return total


if __name__ == '__main__':
    main()
