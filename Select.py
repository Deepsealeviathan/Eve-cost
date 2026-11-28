# -*- coding: utf-8 -*-
import os
import json
import logging
import re
import time
import pymysql
from pathlib import Path

from db_config import load_db_config, get_region_id

log = logging.getLogger('eve_cost.select')

# ================== 配置区 ==================
# 行情所属星域(默认伏尔戈 The Forge / 吉他),可在 config.ini [market] 修改
REGION_ID = get_region_id()


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
        os.path.join(base_dir, 'Salvage'),
        os.path.join(base_dir, 'AncientSalvage'),
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

# 名称索引有效期(秒):新增/改名配方 JSON 后最多 10 秒自动生效,无需重启服务
_NAME_INDEX_TTL = 10.0
_NAME_INDEX = {'built': 0.0, 'exact': {}, 'normalized': {}}
_JSON_DATA_CACHE = {}     # 文件路径 -> (mtime, 解析后的 dict),文件变更自动失效

# 全角符号归一化表:国服物品名用「（）」,用户习惯输入「()」
_FULLWIDTH_MAP = str.maketrans({
    '（': '(', '）': ')', '【': '[', '】': ']', '〔': '(', '〕': ')',
    '×': 'x', 'Ｘ': 'X', 'ｘ': 'x', '－': '-', '　': ' ',
})


def normalize_name(name):
    """物品名归一化:全角括号/乘号转半角,去掉所有空白。

    「白釉冰（4级）」与「白釉冰(4级)」归一化后同键,用户用半角括号也能查到。
    """
    if not name:
        return ''
    return re.sub(r'\s+', '', str(name).translate(_FULLWIDTH_MAP))


def _build_name_index():
    """遍历配方目录,建立 精确名 -> 路径、归一化名 -> 路径 两张索引。"""
    exact = {}
    normalized = {}
    for root in SEARCH_ROOTS:
        if not os.path.isdir(root):
            log.warning('配方目录不存在,已跳过: %s', root)
            continue
        for path in sorted(str(p) for p in Path(root).rglob('*.json')):
            name = os.path.splitext(os.path.basename(path))[0]
            if name in exact:
                log.warning('配方文件重名,使用先出现的: %s(忽略 %s)', exact[name], path)
                continue
            exact[name] = path
            normalized.setdefault(normalize_name(name), path)
    return exact, normalized


def _name_index():
    """按 TTL 刷新名称索引;避免每个材料节点都递归扫描目录。"""
    now = time.time()
    if now - _NAME_INDEX['built'] > _NAME_INDEX_TTL:
        exact, normalized = _build_name_index()
        _NAME_INDEX.update(built=now, exact=exact, normalized=normalized)
    return _NAME_INDEX['exact'], _NAME_INDEX['normalized']


def find_json_file(name):
    """查找 {name}.json:先精确匹配,再按归一化名匹配(全角/半角括号、空格差异)。

    索引带 TTL,新建配方文件后无需重启服务;找不到返回 None。
    """
    if not name:
        return None
    exact, normalized = _name_index()
    path = exact.get(name)
    if path:
        return path
    key = normalize_name(name)
    path = normalized.get(key)
    if path:
        log.info('名称归一化命中: %r -> %s', name, path)
    return path



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
        # ESI 调整价(adjusted_price)全量缓存,首次用到时加载一次;{} 表示表不存在或为空
        self.adjusted_all = None

    def get_conn(self):
        if self.conn is None:
            # 连接建立可能被网络转发层偶发中断(如 WSL 端口转发抖动),自动重试一次
            last_err = None
            for _ in range(2):
                try:
                    self.conn = pymysql.connect(**load_db_config())
                    return self.conn
                except (pymysql.Error, OSError) as e:
                    last_err = e
                    time.sleep(0.1)
            raise last_err
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
        # 查询中连接偶发中断(转发层抖动)时丢弃旧连接、换新连接重试一次;仍失败才降级为 0 价
        for attempt in (0, 1):
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
                break
            except (pymysql.Error, OSError) as e:
                ctx.close()
                if attempt == 1:
                    log.error('数据库错误: %s', e)
                    for tid in missing:
                        result.setdefault(tid, (0, 0))

    return result


def _query_adjusted_prices(ids, ctx):
    """读取 ESI 调整价(adjusted_price),用于按官方公式计算 EIV。

    首次调用时把整张表加载进 ctx(跟踪物品只有几百条),后续查找零查询。
    表不存在(未升级 schema / 未跑过行情更新)时返回空映射,前端据此提示数据未就绪。
    """
    if not ids:
        return {}

    if ctx.adjusted_all is None:
        # 与价格查询一致:连接类错误丢弃旧连接重试一次;表不存在(1146)直接按空数据处理
        for attempt in (0, 1):
            try:
                conn = ctx.get_conn()
                with conn.cursor() as cursor:
                    cursor.execute("SELECT type_id, adjusted_price FROM adjusted_prices")
                    ctx.adjusted_all = {row[0]: row[1] for row in cursor.fetchall()}
                break
            except (pymysql.Error, OSError) as e:
                ctx.close()
                if getattr(e, 'args', [None])[0] == 1146:
                    ctx.adjusted_all = {}
                    break
                if attempt == 1:
                    log.error('读取调整价失败: %s', e)
                    ctx.adjusted_all = {}

    return {tid: ctx.adjusted_all.get(tid) for tid in ids}


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

    # 官方 EIV：按 ME0 单轮材料量 × ESI 调整价计算；
    # ME/改装件的材料减免不影响安装费，所以这里用 recipe 的原始 count。
    adjusted = _query_adjusted_prices(
        [inp.get('materialId') for inp in inputs if inp.get('materialId') is not None], ctx)
    eiv_per_run = 0.0
    eiv_complete = True
    for inp in inputs:
        sub_id = inp.get('materialId')
        if sub_id is None:
            continue
        adjusted_price = adjusted.get(sub_id)
        if adjusted_price is None:
            eiv_complete = False
        else:
            eiv_per_run += (inp.get('count', 0) or 0) * adjusted_price

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
            log.warning('无法计算材料 %s 的成本', sub_name)
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
        'total_market_sell': (market_sell or 0) * quantity,
        # 官方制造安装费(EIV)取数：单轮 EIV 与是否缺调整价
        'eiv_per_run': eiv_per_run,
        'eiv_complete': eiv_complete
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
            log.warning('未找到配方文件: %s.json', name)
            return None

        try:
            data = _load_recipe_json(json_path)
        except Exception as e:
            log.error('JSON 读取/解析失败: %s', e)
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


_CATALOG_CACHE = {'ts': 0.0, 'data': None}
CATALOG_TTL = 30.0   # 目录缓存有效期(秒):目录页/组件页/健康页共用,避免每次请求都扫库


def invalidate_catalog_cache():
    """行情更新后主动失效目录缓存,让页面立刻看到新价格。"""
    _CATALOG_CACHE['ts'] = 0.0
    _CATALOG_CACHE['data'] = None


def get_catalog(use_cache=True):
    """
    从 items / market_prices 读取所有物品的 ID、name、买卖价与挂单量、分类,
    分类在 update_market.py 入库时已写入 items.category(P1~P4 / categories.json 自定义 / 其他)。
    返回列表,形如:
    [{'id':34,'name':'三钛合金','buy_max':9.58,'buy_min':9.1,'sell_max':10.5,
      'sell_min':10,'buy_volume':123,'sell_volume':456,'adjusted_price':9.9,
      'update_time':'...','tier':'矿物'}, ...]

    adjusted_price 来自 adjusted_prices 表(ESI 调整价),供清单汇总页按官方 EIV 公式
    估算安装费;表未建时为 None。
    结果带 30 秒进程内缓存(use_cache=False 可强制读库),多页共用一份目录。
    """
    if use_cache and _CATALOG_CACHE['data'] is not None \
            and time.time() - _CATALOG_CACHE['ts'] < CATALOG_TTL:
        return _CATALOG_CACHE['data']

    conn = None
    # 连接偶发中断(转发层抖动)时自动重试一次
    for attempt in (0, 1):
        try:
            conn = pymysql.connect(**load_db_config())
            with conn.cursor() as cursor:
                # adjusted_prices 仅用于安装费估算;旧库未建该表时降级为不带调整价的查询
                try:
                    cursor.execute("""
                        SELECT i.type_id, i.name, p.buy_max, p.buy_min, p.sell_max, p.sell_min,
                               p.buy_volume, p.sell_volume, p.updated_at, i.category,
                               a.adjusted_price
                        FROM items i
                        LEFT JOIN market_prices p
                            ON p.type_id = i.type_id AND p.region_id = %s
                        LEFT JOIN adjusted_prices a ON a.type_id = i.type_id
                        ORDER BY i.name ASC
                    """, (REGION_ID,))
                    rows = cursor.fetchall()
                    has_adjusted = True
                except pymysql.Error as e:
                    if getattr(e, 'args', [None])[0] != 1146:
                        raise
                    cursor.execute("""
                        SELECT i.type_id, i.name, p.buy_max, p.buy_min, p.sell_max, p.sell_min,
                               p.buy_volume, p.sell_volume, p.updated_at, i.category
                        FROM items i
                        LEFT JOIN market_prices p
                            ON p.type_id = i.type_id AND p.region_id = %s
                        ORDER BY i.name ASC
                    """, (REGION_ID,))
                    rows = cursor.fetchall()
                    has_adjusted = False
            data = [
                {
                    'id': row[0],
                    'name': row[1],
                    'buy_max': row[2] or 0,
                    'buy_min': row[3] or 0,
                    'sell_max': row[4] or 0,
                    'sell_min': row[5] or 0,
                    'buy_volume': row[6] or 0,
                    'sell_volume': row[7] or 0,
                    'update_time': str(row[8]) if row[8] is not None else '-',
                    'tier': row[9] or '其他',
                    'adjusted_price': row[10] if has_adjusted else None,
                }
                for row in rows
            ]
            if use_cache:
                _CATALOG_CACHE.update(ts=time.time(), data=data)
            return data
        except (pymysql.Error, OSError) as e:
            if attempt == 1:
                log.error('读取目录失败: %s', e)
                return []
            time.sleep(0.1)
        finally:
            if conn:
                conn.close()
                conn = None



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


def _has_missing_material(materials):
    """材料树中任意层级是否存在缺失/无价的材料(missing 标志)。"""
    for m in materials or []:
        if m.get('missing'):
            return True
        if _has_missing_material(m.get('sub_materials')):
            return True
    return False


def compute_profit_rows():
    """
    遍历全部"可制造物品"(有配方且有输入),计算单件合成成本与市场价。
    供 update_market.py 在行情更新后预计算利润快照使用。

    全程共享一个 _QueryContext:数据库连接与价格缓存只建一份,
    250+ 个物品的递归展开实际只打一次数据库批量查询。
    返回行列表: [{type_id, name, category, unit_cost_instant, unit_cost_buyorder,
                  market_sell_min, market_buy_max, complete}]
    """
    rows = []
    ctx = _QueryContext()
    try:
        for r in get_recipes():
            if not r['outputCount'] or not r['inputs'] or r['id'] is None:
                continue
            result = query_by_name(r['name'], 1, _ctx=ctx)
            if result is None:
                continue
            cost_instant = result.get('total_sell') or 0
            cost_buyorder = result.get('total_buy') or 0
            # 材料树有缺价材料、或成本为 0(全部材料无价)时,快照标记为不可信
            complete = 0 if (_has_missing_material(result.get('materials')) or cost_instant <= 0) else 1
            rows.append({
                'type_id': r['id'],
                'name': r['name'],
                'category': r['tier'],
                'unit_cost_instant': cost_instant,
                'unit_cost_buyorder': cost_buyorder,
                'market_sell_min': result.get('market_sell') or 0,
                'market_buy_max': result.get('market_buy') or 0,
                'complete': complete,
            })
    finally:
        ctx.close()
    return rows


def get_profit_snapshot():
    """
    读取利润快照表(利润排行页数据源)。
    表尚不存在(未跑过更新流水线 / 未升级 schema)时返回空结果而不是报错,
    前端据此提示"快照尚未生成"。
    """
    conn = None
    for attempt in (0, 1):
        try:
            conn = pymysql.connect(**load_db_config())
            with conn.cursor() as cursor:
                cursor.execute("SELECT MAX(updated_at) FROM profit_snapshot")
                updated_at = cursor.fetchone()[0]
                cursor.execute("""
                    SELECT type_id, name, category, unit_cost_instant, unit_cost_buyorder,
                           market_sell_min, market_buy_max, complete
                    FROM profit_snapshot
                """)
                rows = cursor.fetchall()
            return {
                'updated_at': str(updated_at) if updated_at else None,
                'items': [
                    {
                        'type_id': row[0],
                        'name': row[1],
                        'category': row[2],
                        'unit_cost_instant': row[3],
                        'unit_cost_buyorder': row[4],
                        'market_sell_min': row[5],
                        'market_buy_max': row[6],
                        'complete': row[7],
                    }
                    for row in rows
                ],
            }
        except (pymysql.Error, OSError) as e:
            # 1146 = 表不存在:尚未生成过快照,按空数据返回
            if getattr(e, 'args', [None])[0] == 1146:
                return {'updated_at': None, 'items': []}
            if attempt == 1:
                log.error('读取利润快照失败: %s', e)
                return {'updated_at': None, 'items': []}
            time.sleep(0.1)
        finally:
            if conn:
                conn.close()
                conn = None


def get_price_history(type_id):
    """
    读取单个物品的历史日线(近 90 天,由 update_market.py 增量维护),供趋势图使用。
    表不存在或无数据时返回空列表。
    """
    conn = None
    for attempt in (0, 1):
        try:
            conn = pymysql.connect(**load_db_config())
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT date, average, highest, lowest, volume, order_count
                    FROM price_history
                    WHERE type_id = %s
                    ORDER BY date ASC
                """, (type_id,))
                rows = cursor.fetchall()
            return [
                {
                    'date': str(row[0]),
                    'average': row[1],
                    'highest': row[2],
                    'lowest': row[3],
                    'volume': row[4],
                    'order_count': row[5],
                }
                for row in rows
            ]
        except (pymysql.Error, OSError) as e:
            if getattr(e, 'args', [None])[0] == 1146:
                return []
            if attempt == 1:
                log.error('读取历史行情失败: %s', e)
                return []
            time.sleep(0.1)
        finally:
            if conn:
                conn.close()
                conn = None


def _safe_rows(cursor, sql, params=()):
    """执行统计查询;表不存在(1146,未升级 schema)时返回空列表而不是中断整个自检。"""
    try:
        cursor.execute(sql, params)
        return cursor.fetchall()
    except pymysql.Error as e:
        if getattr(e, 'args', [None])[0] == 1146:
            return []
        raise


def get_health():
    """数据自检页数据源:行情新鲜度、无报价物品、配方/调整价/历史行情/利润快照覆盖度。

    不写库、不改状态,失败时由调用方统一报错。
    """
    items = get_catalog()
    recipes = get_recipes()

    priced = [i for i in items if (i.get('buy_max') or 0) > 0 or (i.get('sell_min') or 0) > 0]
    unpriced = sorted(
        ({'id': i['id'], 'name': i['name'], 'tier': i['tier']}
         for i in items if not ((i.get('buy_max') or 0) > 0 or (i.get('sell_min') or 0) > 0)),
        key=lambda x: (x['tier'], x['name']),
    )
    category_counts = {}
    for i in items:
        category_counts[i['tier']] = category_counts.get(i['tier'], 0) + 1

    recipe_names = {r['name'] for r in recipes if r['outputCount']}
    craftable = [r for r in recipes if r['outputCount'] and r['inputs']]
    material_ids = {inp['id'] for r in recipes for inp in r['inputs'] if inp.get('id') is not None}

    health = {
        'generated_at': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()),
        'items': {
            'total': len(items),
            'priced': len(priced),
            'unpriced': len(unpriced),
            'unpriced_list': unpriced,
            'without_recipe': len([i for i in items if i['name'] not in recipe_names]),
            'by_category': dict(sorted(category_counts.items(), key=lambda kv: -kv[1])),
        },
        'recipes': {
            'total': len(recipes),
            'craftable': len(craftable),
            'material_ids': len(material_ids),
        },
        'market': {'updated_at': None},
        'adjusted': {'count': 0, 'updated_at': None, 'missing_materials': []},
        'history': {'rows': 0, 'type_ids': 0, 'from': None, 'to': None},
        'snapshot': {'count': 0, 'updated_at': None},
    }

    conn = None
    for attempt in (0, 1):
        try:
            conn = pymysql.connect(**load_db_config())
            with conn.cursor() as cursor:
                rows = _safe_rows(
                    cursor, "SELECT MAX(updated_at) FROM market_prices WHERE region_id = %s",
                    (REGION_ID,))
                if rows and rows[0][0]:
                    health['market']['updated_at'] = str(rows[0][0])

                rows = _safe_rows(cursor, "SELECT type_id, updated_at FROM adjusted_prices")
                health['adjusted']['count'] = len(rows)
                adj_time = max((r[1] for r in rows if r[1]), default=None)
                if adj_time:
                    health['adjusted']['updated_at'] = str(adj_time)
                adjusted_ids = {r[0] for r in rows}
                health['adjusted']['missing_materials'] = sorted(
                    material_ids - adjusted_ids)

                rows = _safe_rows(
                    cursor,
                    "SELECT COUNT(*), COUNT(DISTINCT type_id), MIN(date), MAX(date) FROM price_history")
                if rows and rows[0][0]:
                    health['history'].update(
                        rows=rows[0][0], type_ids=rows[0][1],
                        **{'from': str(rows[0][2]) if rows[0][2] else None,
                           'to': str(rows[0][3]) if rows[0][3] else None})

                rows = _safe_rows(
                    cursor, "SELECT COUNT(*), MAX(updated_at) FROM profit_snapshot")
                if rows and rows[0][0]:
                    health['snapshot'].update(
                        count=rows[0][0],
                        updated_at=str(rows[0][1]) if rows[0][1] else None)
            return health
        except (pymysql.Error, OSError) as e:
            if attempt == 1:
                raise
            time.sleep(0.1)
        finally:
            if conn:
                conn.close()
                conn = None
