# -*- coding: utf-8 -*-
import os
import json
import pymysql
from pathlib import Path

from db_config import load_db_config

# ================== 配置区 ==================
REGION_ID = 10000002  # 行情所属星域(伏尔戈 The Forge / 吉他)


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
        os.path.join(base_dir, 'Reactions', '混合聚合物'),
        os.path.join(base_dir, 'Reactions', '中间产物'),
        os.path.join(base_dir, 'Reactions', '合成物'),
        os.path.join(base_dir, 'Reactions', '燃料块'),
        os.path.join(base_dir, 'Reactions', '分子锻造材料'),
        os.path.join(base_dir, 'Components', '旗舰基础组件'),
        os.path.join(base_dir, 'Components', '旗舰高级组件'),
        os.path.join(base_dir, 'Components', 'T2制造组件'),
        os.path.join(base_dir, 'Components', '基础材料'),
        os.path.join(base_dir, 'Planetary_Commodities', 'P1'),
        os.path.join(base_dir, 'Planetary_Commodities', 'P2'),
        os.path.join(base_dir, 'Planetary_Commodities', 'P3'),
        os.path.join(base_dir, 'Planetary_Commodities', 'P4'),
    ]


SEARCH_ROOTS = _get_search_roots()
# ===========================================


_PATH_LOOKUP_CACHE = {}   # 物品名 -> 配方文件路径(配方目录在运行期不变,查找一次后缓存)
_JSON_DATA_CACHE = {}     # 文件路径 -> (mtime, 解析后的 dict),文件变更自动失效


def find_json_file(name):
    """
    在所有配置的根目录及其子目录中递归查找 {name}.json
    返回找到的完整路径；没找到返回 None
    """
    if name in _PATH_LOOKUP_CACHE:
        return _PATH_LOOKUP_CACHE[name]

    target = f"{name}.json"
    found_paths = []

    for root in SEARCH_ROOTS:
        if not os.path.isdir(root):
            print(f"警告：目录不存在，已跳过: {root}")
            continue

        for path in Path(root).rglob(target):
            found_paths.append(str(path))

    if not found_paths:
        _PATH_LOOKUP_CACHE[name] = None
        return None

    if len(found_paths) > 1:
        print(f"警告：找到多个 {target}，使用:")
        for i, p in enumerate(found_paths):
            marker = "  -> " if i == 0 else "     "
            print(f"{marker}{p}")

    result = found_paths[0]
    _PATH_LOOKUP_CACHE[name] = result
    return result


def _load_recipe_json(path):
    """读取配方 JSON,按 mtime 缓存,避免递归时重复读盘解析"""
    mtime = os.path.getmtime(path)
    cached = _JSON_DATA_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    _JSON_DATA_CACHE[path] = (mtime, data)
    return data


class _QueryContext:
    """单次查询的共享上下文：复用数据库连接并缓存价格，避免递归时每个材料节点都新建连接"""

    def __init__(self):
        self.conn = None
        self.price_cache = {}

    def get_conn(self):
        if self.conn is None:
            self.conn = pymysql.connect(**load_db_config())
        return self.conn

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None


def _query_price_map(ids, ctx):
    """根据 ID 列表查询数据库中的 buy_max 和 sell_min（用于成本计算，结果缓存进 ctx）"""
    if not ids:
        return {}

    result = {}
    missing = []
    for tid in ids:
        if tid in ctx.price_cache:
            result[tid] = ctx.price_cache[tid]
        else:
            missing.append(tid)

    if missing:
        try:
            conn = ctx.get_conn()
            with conn.cursor() as cursor:
                placeholders = ','.join(['%s'] * len(missing))
                sql = (f"SELECT type_id, buy_max, sell_min FROM market_prices "
                       f"WHERE region_id = %s AND type_id IN ({placeholders})")
                cursor.execute(sql, [REGION_ID, *missing])
                rows = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
            for tid in missing:
                pair = rows.get(tid, (0, 0))
                ctx.price_cache[tid] = pair
                result[tid] = pair
        except pymysql.Error as e:
            print(f"数据库错误: {e}")
            for tid in missing:
                result.setdefault(tid, (0, 0))

    return result


def _query_p1(data, quantity, ctx):
    """
    基础材料：直接查询数据库中该物品的 buy_max/sell_min
    """
    item_id = data['id']
    item_name = data['name']

    price_map = _query_price_map([item_id], ctx)
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


def _query_crafted(data, quantity, tier, ctx):
    """
    P2/P3/P4 通用合成物品成本计算。
    根据 recipe 递归计算原材料成本，最终落实到 P1 市场价格。
    单个成本 = Σ(单个原材料合成成本 × 所需数量) / outputCount

    同时从数据库读取该物品自身的市场价（buy_max / sell_min），
    方便与合成成本进行对比。
    """
    item_id = data.get('id')   # 标准矿石等无固定 ID 的物品为 None
    item_name = data['name']
    recipe = data.get('recipe', {})
    output_count = recipe.get('outputCount', 1)
    inputs = recipe.get('inputs', [])

    # 查询该物品自身的市场价格（buy_max / sell_min）；无 ID 的物品没有直接市场价
    if item_id is not None:
        market_price_map = _query_price_map([item_id], ctx)
        market_buy, market_sell = market_price_map.get(item_id, (0, 0))
    else:
        market_buy, market_sell = 0, 0

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

        # 递归计算原材料成本（基础材料会查询数据库，合成物会继续递归）
        sub_result = query_by_name(sub_name, total_num, _ctx=ctx)
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

        # 无配方的材料(基础材料/矿物/燃料块等)没有子材料,避免把自身当作子材料重复渲染
        sub_materials = sub_result.get('materials', []) if sub_result.get('output_count') is not None else []

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


def query_by_name(name, quantity=1, _ctx=None):
    """
    根据物品名称查询成本。
    - 基础材料：直接返回数据库中的市场价格
    - 有配方的物品：读取 recipe，递归计算原材料成本（最终落实到基础材料价格）

    递归调用共享 _ctx（数据库连接 + 价格缓存），顶层调用自动创建/关闭。
    """
    top_level = _ctx is None
    if top_level:
        _ctx = _QueryContext()
    try:
        json_path = find_json_file(name)
        if json_path is None:
            print(f"错误：未找到 {name}.json（已搜索全部配方目录）")
            return None

        print(f"找到文件: {json_path}")

        try:
            data = _load_recipe_json(json_path)
        except Exception as e:
            print(f"JSON 读取/解析失败: {e}")
            return None

        tier = data.get('tier', 'P1')

        # 有 recipe 的物品（P2~P4、反应物、组件、标准矿石等）按配方推算价值；否则按数据库市场价
        if data.get('recipe') or tier in ('P2', 'P3', 'P4'):
            return _query_crafted(data, quantity, tier, _ctx)
        else:
            return _query_p1(data, quantity, _ctx)
    finally:
        if top_level:
            _ctx.close()


def get_catalog():
    """
    从 items / market_prices 读取所有物品的 ID、name、buy_max、sell_min 和分类,
    分类在 update_market.py 入库时已写入 items.category(P1~P4 / categories.json 自定义 / 其他)。
    返回列表,形如 [{'id':34,'name':'三钛合金','buy_max':9.58,'sell_min':10,'tier':'其他'}, ...]
    """
    conn = None
    try:
        conn = pymysql.connect(**load_db_config())
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT i.type_id, i.name, p.buy_max, p.sell_min, p.updated_at, i.category
                FROM items i
                LEFT JOIN market_prices p
                    ON p.type_id = i.type_id AND p.region_id = %s
                ORDER BY i.name ASC
            """, (REGION_ID,))
            rows = cursor.fetchall()
            return [
                {
                    'id': row[0],
                    'name': row[1],
                    'buy_max': row[2],
                    'sell_min': row[3],
                    'update_time': str(row[4]) if row[4] is not None else '-',
                    'tier': row[5] or '其他'
                }
                for row in rows
            ]
    except pymysql.Error as e:
        print(f"读取目录失败: {e}")
        return []
    finally:
        if conn:
            conn.close()


def get_recipes():
    """
    汇总全部配方 JSON 为轻量索引,供制造清单汇总页(/bom)前端递归展开使用。
    同名物品保留先出现的(与 find_json_file 的多命中取首个行为一致)。
    返回列表: [{name, id, tier, outputCount, inputs: [{id, name, count}]}],
    无配方物品 outputCount 为 None、inputs 为空列表。
    """
    recipes = []
    seen = set()
    for root in SEARCH_ROOTS:
        if not os.path.isdir(root):
            continue
        for path in sorted(Path(root).rglob('*.json')):
            try:
                data = _load_recipe_json(str(path))
            except Exception:
                continue
            if not isinstance(data, dict) or not data.get('name'):
                continue
            name = data['name']
            if name in seen:
                continue
            seen.add(name)
            recipe = data.get('recipe') or {}
            recipes.append({
                'name': name,
                'id': data.get('id'),
                'tier': data.get('tier', '其他'),
                'outputCount': recipe.get('outputCount', 1) if recipe else None,
                'inputs': [
                    {
                        'id': inp.get('materialId'),
                        'name': inp.get('materialname'),
                        'count': inp.get('count', 0)
                    }
                    for inp in recipe.get('inputs', [])
                    if inp.get('materialname')
                ] if recipe else [],
            })
    return recipes
