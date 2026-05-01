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


def query_by_name(name):
    # 1. 调用函数查找Json原材料清单
    json_path = find_json_file(name)
    if json_path is None:
        print(f"错误：在以下目录及其子目录中均未找到 {name}.json")
        for root in SEARCH_ROOTS:
            print(f"  搜索过: {root}")
        return None
    
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
    materials = []   # 用于保存数据，例如：[{'name':'氧', 'id':3683, 'num':1}, ...]
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
            materials.append({'name': mat_name, 'id': mid, 'num': mnum}) # 写入到materials 数组中
            ids.append(mid) # 写入到ids数组中

    if not ids:
        print("清单中没有有效的材料")
        return

    # 4. 连接数据库查询 buy_max 和 sell_max
    conn = None
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            placeholders = ','.join(['%s'] * len(ids))
            sql = f"SELECT ID, buy_max, sell_max FROM test WHERE ID IN ({placeholders})"
            cursor.execute(sql, ids)
            rows = cursor.fetchall()
            
            # 转成字典方便查找：{3683: (buy_max, sell_max), ...}
            price_map = {row[0]: (row[1], row[2]) for row in rows}

    except pymysql.Error as e:
        print(f"数据库错误: {e}")
        return
    finally:
        if conn:
            conn.close()

    # 5. 打印结果
    print(f"\n{'='*60}")
    print(f"制作清单: {name}")
    print(f"{'='*60}")
    print(f"{'材料':<12} {'ID':<8} {'数量':<6} {'buy_max':<10} {'sell_max':<10}")
    print("-" * 60)

    total_buy = 0
    total_sell = 0

    for mat in materials:
        mid = mat['id']
        mnum = mat['num'] or 0
        buy_max, sell_max = price_map.get(mid, (None, None))

        print(f"{mat['name']:<12} {mid:<8} {mnum:<6} {str(buy_max):<10} {str(sell_max):<10}")

        # 累计总成本
        if buy_max is not None:
            total_buy += buy_max * mnum
        if sell_max is not None:
            total_sell += sell_max * mnum

    print("-" * 60)
    print(f"按收购价(buy_max) 预估总成本: {total_buy:,.2f}")
    print(f"按出售价(sell_max) 预估总成本: {total_sell:,.2f}")
    print(f"{'='*60}")


if __name__ == '__main__':
    item_name = input("请输入制作清单名称: ").strip()
    if item_name:
        query_by_name(item_name)