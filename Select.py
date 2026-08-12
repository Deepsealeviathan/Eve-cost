# -*- coding: utf-8 -*-
import os
import json
import pymysql
from pathlib import Path

# ================== 配置区 ==================
DB_CONFIG = {
    'host': '127.0.0.1',
    'user': 'root',
    'password': '622513',
    'database': 'eve',
    'port': 3306,
    'charset': 'utf8mb4',
}


def _get_search_roots():
    """
    返回配方 JSON 的搜索根目录。
    路径基于本脚本所在目录自动定位，Windows / Linux 通用。
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return [
        os.path.join(base_dir, 'Ore'),
        os.path.join(base_dir, 'MoonMaterials'),
        os.path.join(base_dir, 'Gas'),
        os.path.join(base_dir, 'Commodities'),
        os.path.join(base_dir, 'Planetary_Commodities', 'P1'),
        os.path.join(base_dir, 'Planetary_Commodities', 'P2'),
        os.path.join(base_dir, 'Planetary_Commodities', 'P3'),
        os.path.join(base_dir, 'Planetary_Commodities', 'P4'),
    ]


SEARCH_ROOTS = _get_search_roots()
# ===========================================


def find_json_file(name):
    """
    在所有配置的根目录及其子目录中递归查找 {name}.json
    返回找到的完整路径；没找到返回 None
    """
    target = f"{name}.json"
    found_paths = []

    for root in SEARCH_ROOTS:
        if not os.path.isdir(root):
            print(f"警告：目录不存在，已跳过: {root}")
            continue

        for path in Path(root).rglob(target):
            found_paths.append(str(path))

    if not found_paths:
        return None

    # 优先使用非 old 目录下的文件（old 为历史备份格式）
    non_old_paths = [p for p in found_paths if f"{os.sep}old{os.sep}" not in p]
    chosen_paths = non_old_paths if non_old_paths else found_paths

    if len(found_paths) > 1:
        print(f"警告：找到多个 {target}，使用:")
        for p in found_paths:
            marker = "  -> " if p == chosen_paths[0] else "     "
            print(f"{marker}{p}")

    return chosen_paths[0]


def _query_price_map(ids):
    """根据 ID 列表查询数据库中的 buy_max 和 sell_min（用于成本计算）"""
    if not ids:
        return {}

    conn = None
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            placeholders = ','.join(['%s'] * len(ids))
            sql = f"SELECT ID, buy_max, sell_min FROM test WHERE ID IN ({placeholders})"
            cursor.execute(sql, ids)
            rows = cursor.fetchall()
            return {row[0]: (row[1], row[2]) for row in rows}
    except pymysql.Error as e:
        print(f"数据库错误: {e}")
        return {}
    finally:
        if conn:
            conn.close()


def _query_p1(data, quantity):
    """
    P1 基础材料：直接查询数据库中该物品的 buy_max/sell_min
    """
    item_id = data['id']
    item_name = data['name']

    price_map = _query_price_map([item_id])
    buy_max, sell_min = price_map.get(item_id, (0, 0))

    total_buy = (buy_max or 0) * quantity
    total_sell = (sell_min or 0) * quantity

    return {
        'name': item_name,
        'quantity': quantity,
        'tier': data.get('tier', 'P1'),
        'materials': [{
            'name': item_name,
            'id': item_id,
            'num_per_unit': 1,
            'total_num': quantity,
            'buy_max': buy_max,
            'sell_min': sell_min,
            'total_buy': total_buy,
            'total_sell': total_sell
        }],
        'total_buy': total_buy,
        'total_sell': total_sell
    }


def _query_p2(data, quantity):
    """
    P2 合成物品：根据 recipe 计算单个合成品的成本。
    outputCount 表示一次合成产出数量，
    单个成本 = 原材料总成本 / outputCount。
    """
    item_id = data['id']
    item_name = data['name']
    recipe = data.get('recipe', {})
    output_count = recipe.get('outputCount', 1)
    inputs = recipe.get('inputs', [])

    ids = [inp.get('materialId') for inp in inputs if inp.get('materialId') is not None]
    price_map = _query_price_map(ids)

    materials = []
    total_buy = 0
    total_sell = 0

    for inp in inputs:
        mid = inp.get('materialId')
        mname = inp.get('materialname', '未知材料')
        count_per_batch = inp.get('count', 0)

        if mid is None:
            continue

        # 单个 P2 产出所需的原材料数量
        num_per_unit = count_per_batch / output_count if output_count else 0
        total_num = num_per_unit * quantity
        buy_max, sell_min = price_map.get(mid, (0, 0))

        mat_buy = (buy_max or 0) * total_num
        mat_sell = (sell_min or 0) * total_num

        materials.append({
            'name': mname,
            'id': mid,
            'num_per_unit': num_per_unit,
            'total_num': total_num,
            'buy_max': buy_max,
            'sell_min': sell_min,
            'total_buy': mat_buy,
            'total_sell': mat_sell
        })

        total_buy += mat_buy
        total_sell += mat_sell

    return {
        'name': item_name,
        'quantity': quantity,
        'tier': 'P2',
        'output_count': output_count,
        'materials': materials,
        'total_buy': total_buy,
        'total_sell': total_sell
    }


def _query_crafted(data, quantity, tier):
    """
    P2/P3/P4 通用合成物品成本计算。
    根据 recipe 递归计算原材料成本，最终落实到 P1 市场价格。
    单个成本 = Σ(单个原材料合成成本 × 所需数量) / outputCount

    同时从数据库读取该物品自身的市场价（buy_max / sell_min），
    方便与合成成本进行对比。
    """
    item_id = data['id']
    item_name = data['name']
    recipe = data.get('recipe', {})
    output_count = recipe.get('outputCount', 1)
    inputs = recipe.get('inputs', [])

    # 查询该物品自身的市场价格（buy_max / sell_min）
    market_price_map = _query_price_map([item_id])
    market_buy, market_sell = market_price_map.get(item_id, (0, 0))

    materials = []
    total_buy = 0
    total_sell = 0

    for inp in inputs:
        sub_id = inp.get('materialId')
        sub_name = inp.get('materialname', '未知材料')
        count_per_batch = inp.get('count', 0)

        if sub_id is None:
            continue

        # 单个当前物品产出所需的原材料数量
        num_per_unit = count_per_batch / output_count if output_count else 0
        total_num = num_per_unit * quantity

        # 递归计算原材料成本（P1 会查询数据库，P2/P3/P4 会继续递归）
        sub_result = query_by_name(sub_name, total_num)
        if sub_result is None:
            print(f"警告：无法计算材料 {sub_name} 的成本")
            materials.append({
                'name': sub_name,
                'id': sub_id,
                'num_per_unit': num_per_unit,
                'total_num': total_num,
                'buy_max': 0,
                'sell_min': 0,
                'total_buy': 0,
                'total_sell': 0,
                'sub_materials': [],
                'missing': True
            })
            continue

        # 单个原材料的合成成本
        sub_unit_buy = sub_result['total_buy'] / total_num if total_num else 0
        sub_unit_sell = sub_result['total_sell'] / total_num if total_num else 0

        # P1 没有子材料，避免把自身当作子材料重复渲染
        sub_materials = sub_result.get('materials', []) if sub_result.get('tier') != 'P1' else []

        materials.append({
            'name': sub_name,
            'id': sub_id,
            'num_per_unit': num_per_unit,
            'total_num': total_num,
            'buy_max': sub_unit_buy,
            'sell_min': sub_unit_sell,
            'total_buy': sub_result['total_buy'],
            'total_sell': sub_result['total_sell'],
            'sub_materials': sub_materials
        })

        total_buy += sub_result['total_buy']
        total_sell += sub_result['total_sell']

    return {
        'name': item_name,
        'id': item_id,
        'quantity': quantity,
        'tier': tier,
        'output_count': output_count,
        'materials': materials,
        'total_buy': total_buy,
        'total_sell': total_sell,
        'market_buy': market_buy or 0,
        'market_sell': market_sell or 0,
        'total_market_buy': (market_buy or 0) * quantity,
        'total_market_sell': (market_sell or 0) * quantity
    }


def query_by_name(name, quantity=1):
    """
    根据物品名称查询成本。
    - P1：直接返回数据库中的市场价格
    - P2/P3/P4：读取 recipe，递归计算原材料成本（最终落实到 P1 价格）
    """
    json_path = find_json_file(name)
    if json_path is None:
        print(f"错误：在以下目录及其子目录中均未找到 {name}.json")
        return None

    print(f"找到文件: {json_path}")

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"JSON 读取/解析失败: {e}")
        return None

    tier = data.get('tier', 'P1')

    if tier in ('P2', 'P3', 'P4'):
        return _query_crafted(data, quantity, tier)
    else:
        return _query_p1(data, quantity)


# 物品名 -> 分类 映射的模块级缓存（None 表示尚未扫描）
_TIER_MAP = None


def _get_tier_map():
    """
    构建「物品名 -> 分类」映射：
    1. 扫描 Planetary_Commodities/P1~P4 目录，分类记为 P1/P2/P3/P4（前端归入「行星商品」大类）
    2. 读取根目录 categories.json（格式 {"分类名": ["物品名", ...]}），如「矿物」「气云」
    不在任何分类中的物品，在 get_catalog 中归入「其他」。
    结果模块级缓存；新增分类或配方文件后重启服务生效。
    """
    global _TIER_MAP
    if _TIER_MAP is not None:
        return _TIER_MAP

    tier_map = {}
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for tier in ('P1', 'P2', 'P3', 'P4'):
        tier_dir = Path(base_dir) / 'Planetary_Commodities' / tier
        if not tier_dir.is_dir():
            continue
        for json_file in tier_dir.glob('*.json'):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    item_name = json.load(f).get('name')
            except Exception:
                item_name = None
            # JSON 里的 name 与数据库一致；读取失败则退回使用文件名
            tier_map[item_name or json_file.stem] = tier

    # 自定义分类（矿物 / 卫星原料 / 气云 / 燃料 / 挖坟材料 等），可自由增改
    cat_file = Path(base_dir) / 'categories.json'
    if cat_file.is_file():
        try:
            with open(cat_file, 'r', encoding='utf-8') as f:
                for cat_name, item_names in json.load(f).items():
                    for item_name in item_names:
                        tier_map[item_name] = cat_name
        except Exception as e:
            print(f"警告：categories.json 读取失败，已忽略: {e}")

    _TIER_MAP = tier_map
    return tier_map


def get_catalog():
    """
    从 MySQL 的 test 表中读取所有物品的 ID、name、buy_max、sell_min，
    并按 Planetary_Commodities 目录归属附上 tier 分类（P1~P4 或「其他」）。
    返回列表，形如 [{'id':34,'name':'三钛合金','buy_max':9.58,'sell_min':10,'tier':'其他'}, ...]
    """
    conn = None
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            cursor.execute("SELECT ID, name, buy_max, sell_min, update_time FROM test ORDER BY name ASC")
            rows = cursor.fetchall()
            tier_map = _get_tier_map()
            return [
                {
                    'id': row[0],
                    'name': row[1],
                    'buy_max': row[2],
                    'sell_min': row[3],
                    'update_time': str(row[4]) if row[4] is not None else '-',
                    'tier': tier_map.get(row[1], '其他')
                }
                for row in rows
            ]
    except pymysql.Error as e:
        print(f"读取目录失败: {e}")
        return []
    finally:
        if conn:
            conn.close()
