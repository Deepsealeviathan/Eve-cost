# -*- coding: utf-8 -*-
import os
import json
import pymysql
from pathlib import Path

# ================== 配置区 ==================
# 配置搜索根目录列表，程序会递归搜索它们的所有子目录
# 你可以把 Ore、Planetart 的父目录直接写进来，也可以分别写
SEARCH_ROOTS = [
    r'D:\\eve\\New\\Ore',
    r'D:\\eve\\New\\Planetary_Commodities\\P1',
    r'D:\\eve\\New\\Planetary_Commodities\\P2',
    r'D:\\eve\\New\\Planetary_Commodities\\P3',
    r'D:\\eve\\New\\Planetary_Commodities\\P4',
    # 如果以后还有新目录，直接在这里追加即可
]

# MySQL 连接配置
DB_CONFIG = {
    'host': '127.0.0.1',
    'user': 'root',
    'password': '622513',
    'database': 'eve',
    'port': 3306,
    'charset': 'utf8mb4',
}
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
        
        # rglob('*/*.json') 的简化写法，直接按文件名匹配
        # 它会自动进入 P1、P2、P3、P4 等所有子目录
        for path in Path(root).rglob(target):
            found_paths.append(str(path))
    
    if not found_paths:
        return None
    
    if len(found_paths) > 1:
        print(f"警告：找到多个 {target}，默认使用第一个:")
        for p in found_paths:
            print(f"  - {p}")
    
    return found_paths[0]


def query_by_name(name, quantity=1):
    # 1. 调用函数查找Json原材料清单
    json_path = find_json_file(name)
    if json_path is None:
        print(f"错误：在以下目录及其子目录中均未找到 {name}.json")
#        for root in SEARCH_ROOTS:
#            print(f"  搜索过: {root}")
#        return None
    
    print(f"找到文件: {json_path}")

    # 2. 读取找到的Json原材料清单
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"JSON 读取/解析失败: {e}")
        return None

    # 3. 从 list 中获取该物品对应的 ID
    item_list = data.get('list') # 读取Json文件中list下的数据
    if not item_list or not isinstance(item_list, dict):
        return None
    materials_raw = []   # 用于保存数据，例如：[{'name':'氧', 'id':3683, 'num':1}, ...]
    ids = []         # 假设有多个物品，用于保存多个物品的ID，例如：[3683, 34, 16633]

    # 循环取出材料名和材料的ID、Num
    # mat_name 是材料名
    # info 是材料ID和Num
    # 例如("氧", {"ID": 3683,  "Num": 1})
    for mat_name, info in item_list.items():
        if not isinstance(info, dict):
            continue
        mid = info.get("ID")
        mnum = info.get("Num")
        if mid is not None:
            materials_raw.append({'name': mat_name, 'id': mid, 'num': mnum}) # 写入到materials 数组中
            ids.append(mid) # 写入到ids数组中

    if not ids:
        print("清单中没有有效的材料")
        return

    # 4. 连接数据库查询 buy_max 和 sell_max
    conn = None
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            # 根据 ID 的数量，生成对应数量的 %s 占位符，并用逗号连接。
            # 假设ids = [2393, 3683]
            # len(ids) = 2
            # 所以placeholders = "%s,%s"
            placeholders = ','.join(['%s'] * len(ids))
            # 从 test 表中查询 ID 在 [2393, 3683] 这些值中的记录，并返回 ID、buy_max、sell_max 三列。
            sql = f"SELECT ID, buy_max, sell_max FROM test WHERE ID IN ({placeholders})"
            # 执行 SQL 查询，并把 ids 中的值安全地填充到 %s 占位符里。
            # 相当于SELECT ID, buy_max, sell_max FROM test WHERE ID IN (2393, 3683)
            cursor.execute(sql, ids)
            # 获取查询结果的所有行。
            rows = cursor.fetchall()
            # 转成字典方便查找：{3683: (buy_max, sell_max), ...}
            # 例如:
            # price_map = {
            #   2393: (100, 80),
            #   3683: (50, 40)
            #   }
            price_map = {row[0]: (row[1], row[2]) for row in rows}
    except pymysql.Error as e:
        print(f"数据库错误: {e}")
        return
    finally:
        if conn:
            conn.close()

    # 5. 打印结果
#    print(f"\n{'='*60}")
#    print(f"制作清单: {name}")
#    print(f"{'='*60}")
#    print(f"{'材料':<12} {'ID':<8} {'数量':<6} {'buy_max':<10} {'sell_max':<10}")
#    print("-" * 60)

    materials = []
    total_buy = 0
    total_sell = 0

    for mat in materials_raw:
        mid = mat['id']
        num_per_unit = mat['num']
        total_num = num_per_unit * quantity
        buy_max, sell_max = price_map.get(mid, (0, 0))

        # 求列表中单个总价
        mat_buy = (buy_max or 0) * total_num
        mat_sell = (sell_max or 0) * total_num
#       print(f"{mat['name']:<12} {mid:<8} {mnum:<6} {str(buy_max):<10} {str(sell_max):<10}")
        materials.append({
            'name': mat['name'],
            'id': mid,
            'num_per_unit': num_per_unit,
            'total_num': total_num,
            'buy_max': buy_max,
            'sell_max': sell_max,
            'total_buy': mat_buy,
            'total_sell': mat_sell
        })
        # 累加最终的总价格
        total_buy += mat_buy
        total_sell += mat_sell

    # 返回结果
    return {
        'name': name,
        'quantity': quantity,
        'materials': materials,
        'total_buy': total_buy,
        'total_sell': total_sell
    }

# 0628更新 里加一个读取 test 表目录的函数。 从数据库中获取所有物品的 name、buy_max、sell_min 并提供给前端目录栏
def get_catalog():
    """
    从 MySQL 的 test 表中读取所有物品的 ID、name、buy_max、sell_min
    返回列表，形如 [{'id':34,'name':'三钛合金','buy_max':9.58,'sell_min':10}, ...]
    """
    conn = None
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            cursor.execute("SELECT ID, name, buy_max, sell_min FROM test ORDER BY name ASC")
            rows = cursor.fetchall()
            return [
                {
                    'id': row[0],
                    'name': row[1],
                    'buy_max': row[2],
                    'sell_min': row[3]
                }
                for row in rows
            ]
    except pymysql.Error as e:
        print(f"读取目录失败: {e}")
        return []
    finally:
        if conn:
            conn.close()