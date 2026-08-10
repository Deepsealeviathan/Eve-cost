# -*- coding: utf-8 -*-
import csv
import time
import pymysql
from pathlib import Path

# ================== 配置区 ==================
DB_CONFIG = {
    'host': '127.0.0.1',
    'user': 'root',
    'password': '622513',      # 新版 pymysql 推荐用 password
    'database': 'eve',
    'port': 3306,
    'charset': 'utf8mb4',      # 避免生僻字/表情符号出错
    'autocommit': False,       # 关闭自动提交，手动批量 commit
}

CSV_FILE = Path(__file__).resolve().parent / 'data.csv'  # 默认读取本脚本所在目录的 data.csv
BATCH_SIZE = 100             # 每 100 条批量提交一次，可酌情调整
# ==========================================

def main():
    update_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    print(f"开始导入，当前时间: {update_time}")

    if not CSV_FILE.exists():
        print(f"错误：找不到文件 {CSV_FILE.resolve()}")
        return

    # 参数化 SQL，彻底避免 SQL 注入；注意 %s 是 pymysql 的占位符，不是格式化符号
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

        with open(CSV_FILE, encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            batch = []

            for row_num, row in enumerate(reader, start=2):  # start=2 表示从第 2 行开始计数（跳过表头）
                # 构造参数元组，顺序必须与 SQL 里的 %s 一一对应
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

                # 达到批次上限就执行一次批量更新
                if len(batch) >= BATCH_SIZE:
                    cursor.executemany(sql, batch)
                    conn.commit()
                    total += len(batch)
                    print(f"已更新 {total} 条...")
                    batch.clear()

            # 处理最后不足一批的剩余数据
            if batch:
                cursor.executemany(sql, batch)
                conn.commit()
                total += len(batch)

        print(f"导入完成，共更新 {total} 条记录。")

    except pymysql.MySQLError as e:
        print(f"数据库错误: {e}")
        if conn:
            conn.rollback()
    except Exception as e:
        print(f"发生异常: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
            print("数据库连接已关闭。")


if __name__ == '__main__':
    main()