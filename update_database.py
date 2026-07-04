# -*- coding: utf-8 -*-
"""
数据库更新流水线（并发优化版）：
1. 从 json_url.txt 读取 API 地址，多线程并发下载 JSON 并生成 data.csv
2. 读取 data.csv 批量更新 MySQL 的 test 表
"""
import os
import json
import csv
import time
import threading
import requests
import pymysql
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================== 用户配置 ==================
JSON_DIR = r'D:\\eve\\New\\Json\\'
URL_FILE = 'json_url.txt'
CSV_FILE = 'data.csv'

DB_CONFIG = {
    'host': '127.0.0.1',
    'user': 'root',
    'password': '622513',
    'database': 'eve',
    'port': 3306,
    'charset': 'utf8mb4',
    'autocommit': False,
}

# 并发数：根据你的网络情况和 API 服务器限速调整
# 如果拉取过程中出现大量 429/连接错误，把这个数字调小，比如 10 或 5
MAX_WORKERS = 20
BATCH_SIZE = 100
MAX_RETRIES = 3
# =============================================

# 每个线程独享一个 requests.Session，复用连接
_thread_local = threading.local()


def get_session():
    if not hasattr(_thread_local, 'session'):
        _thread_local.session = requests.Session()
        # 让 Session 对 http/https 都使用连接池
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20)
        _thread_local.session.mount('http://', adapter)
        _thread_local.session.mount('https://', adapter)
    return _thread_local.session


def read_url_list():
    """读取 URL 文件，返回非空行列表"""
    os.makedirs(JSON_DIR, exist_ok=True)
    url_path = os.path.join(JSON_DIR, URL_FILE)
    if not os.path.exists(url_path):
        raise FileNotFoundError(f"找不到 URL 文件: {url_path}")

    with open(url_path, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]


def fetch_one(args):
    """
    下载单条 JSON 并返回 CSV 行数据
    args = (index, url_line)，index 用于保持 CSV 输出顺序
    """
    index, url_line = args

    json_url = url_line.rsplit(";", 1)[-1]
    filename = json_url.rsplit("/", 1)[-1]
    type_id = filename.rsplit('.', 1)[0]
    name = url_line.rsplit(";", 1)[0]
    save_path = os.path.join(JSON_DIR, filename)

    session = get_session()
    data = None

    # 失败重试
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(json_url, timeout=30)
            response.raise_for_status()
            data = response.json()
            break
        except Exception as e:
            print(f"[重试 {attempt}/{MAX_RETRIES}] {name} 下载失败: {e}")
            time.sleep(0.5 * attempt)  # 递增等待

    if data is None:
        print(f"[失败] {name} (ID: {type_id}) 多次重试后仍无法下载")
        return index, None

    # 保存原始 JSON
    try:
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        print(f"[失败] {name} JSON 保存失败: {e}")
        return index, None

    row = {
        'typeID': type_id,
        'name': name,
        'max': data['all']['max'],
        'min': data['all']['min'],
        'buy_max': data['buy']['max'],
        'buy_min': data['buy']['min'],
        'sell_max': data['sell']['max'],
        'sell_min': data['sell']['min'],
    }

    print(f"[成功] {name} (ID: {type_id})")
    return index, row


def download_all(urls):
    """并发下载所有 JSON，返回按原顺序排列的 CSV 行列表"""
    indexed_urls = [(i, line) for i, line in enumerate(urls)]
    results = []

    print(f"开始并发下载，共 {len(indexed_urls)} 条，线程数 {MAX_WORKERS}...")
    start = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # submit + as_completed 能最快拿到结果
        future_to_idx = {
            executor.submit(fetch_one, item): item[0]
            for item in indexed_urls
        }
        for future in as_completed(future_to_idx):
            idx, row = future.result()
            if row is not None:
                results.append((idx, row))

    # 按原始顺序排列（虽然 DB 更新不依赖顺序，但 CSV 看起来舒服）
    results.sort(key=lambda x: x[0])
    elapsed = time.time() - start
    print(f"下载完成，成功 {len(results)}/{len(indexed_urls)} 条，耗时 {elapsed:.1f} 秒")
    return [row for _, row in results]


def write_csv(rows):
    """把下载结果写入 CSV"""
    csv_path = os.path.join(JSON_DIR, CSV_FILE)
    fieldnames = ['typeID', 'name', 'max', 'min',
                  'buy_max', 'buy_min', 'sell_max', 'sell_min']

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"CSV 已保存: {csv_path}")


def sync_csv_to_db():
    """读取 CSV 批量更新数据库"""
    update_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    print(f"开始同步数据库，当前时间: {update_time}")

    csv_path = Path(JSON_DIR) / CSV_FILE
    if not csv_path.exists():
        raise FileNotFoundError(f"找不到 CSV 文件: {csv_path}")

    sql = """
        UPDATE test 
        SET name = %s, `max` = %s, `min` = %s, 
            buy_max = %s, buy_min = %s, sell_max = %s, sell_min = %s, 
            update_time = %s
        WHERE ID = %s
    """

    conn = None
    total = 0

    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()

        with open(csv_path, encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            batch = []

            for row in reader:
                params = (
                    row.get('name'),
                    row.get('max'),
                    row.get('min'),
                    row.get('buy_max'),
                    row.get('buy_min'),
                    row.get('sell_max'),
                    row.get('sell_min'),
                    update_time,
                    row.get('typeID'),
                )
                batch.append(params)

                if len(batch) >= BATCH_SIZE:
                    cursor.executemany(sql, batch)
                    conn.commit()
                    total += len(batch)
                    print(f"已更新 {total} 条...")
                    batch.clear()

            if batch:
                cursor.executemany(sql, batch)
                conn.commit()
                total += len(batch)

        print(f"导入完成，共更新 {total} 条记录。")
        return total

    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()
            print("数据库连接已关闭。")


def main():
    urls = read_url_list()
    if not urls:
        print("URL 列表为空，无需更新")
        return 0

    rows = download_all(urls)
    if not rows:
        print("没有成功下载任何数据，停止同步数据库")
        return 0

    write_csv(rows)
    total = sync_csv_to_db()
    return total


if __name__ == '__main__':
    main()
