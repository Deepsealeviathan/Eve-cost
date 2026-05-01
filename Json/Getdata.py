# -*- coding: utf-8 -*-
"""
整合脚本：从 json_url.txt 读取地址，下载 JSON 并解析关键字段，
同时保存原始 .json 文件和汇总 data.csv。
"""

# -*- coding: utf-8 -*-
import os
import json
import csv
import requests

# ================== 用户配置 ==================
JSON_DIR = r'D:\\eve\\New\\Json\\'      # JSON 文件保存目录
CSV_FILE = 'data.csv' #Json文件导出到该表格中
URL_FILE = 'json_url.txt' #写入Json API，数据来自EVE市场网，如需增加物品直接在该文件中添加物品名+API
# =============================================

def main():
    # 确保保存目录存在
    os.makedirs(JSON_DIR, exist_ok=True)
    
    # 读取 URL 列表（格式：名称;URL）
    with open(JSON_DIR+URL_FILE, 'r', encoding='utf-8') as file:
        urls = file.read().splitlines()
    
    # ========== 下载 JSON 到指定目录 ==========
    for url_line in urls:
        if not url_line.strip():
            continue
            
        json_url = url_line.rsplit(";", 1)[-1]     # 获取 URL
        filename = json_url.rsplit("/", 1)[-1]     # 获取文件名，如 34.json
        type_id = filename.rsplit('.', 1)[0]       # 例如：34
        name = url_line.rsplit(";", 1)[0]
        save_path = os.path.join(JSON_DIR, filename) #组合成JSON保存路径和.json文件名
        
        try:
            response = requests.get(json_url, timeout=30)
            response.raise_for_status()
            data = response.json()

            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
                

            with open(JSON_DIR+filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)

            row = [
                type_id,
                name,
                data['all']['max'],
                data['all']['min'],
                data['buy']['max'],
                data['buy']['min'],
                data['sell']['max'],
                data['sell']['min']
            ]

            print(f"[成功] {name} (ID: {type_id}) ")
        except Exception as e:
            print(f"下载失败 {filename}: {e}")
    
    # ========== 读取本地 JSON 生成 CSV ==========
    # 'w' 重新创建 csv 文件并写入表头
    with open(JSON_DIR+CSV_FILE, 'w', newline='', encoding='utf-8') as csvfile:
        csvwrite = csv.writer(csvfile)
        csvwrite.writerow(['typeID', 'name', 'max', 'min', 
                           'buy_max', 'buy_min', 'sell_max', 'sell_min']) 
    
    # 遍历 URL 列表，从本地 JSON 目录读取对应文件
    for url_line in urls:
        if not url_line.strip():
            continue

        json_url = url_line.rsplit(";", 1)[-1]     # 获取 URL 
        filename = url_line.rsplit("/", 1)[-1]       # 通过Url获取.json文件名
        type_id = filename.rsplit(".", 1)[0]              # 获取物品ID
        name = url_line.rsplit(";", 1)[0]        # 获取物品名称
        
        # 拼接完整的 JSON 读取路径
        json_path = os.path.join(JSON_DIR, filename)
        
        try:
            # 对应 2.py: with open(path,'r') as file:
            with open(json_path, 'r', encoding='utf-8') as file:
                data = json.load(file)
            
            # 对应 2.py 的调试输出
            print(f"ID:{type_id}")
            print(type(data))
            print(data.keys())
            print(name + filename)
            
            # 'a' 在 csv 文件末尾写入（对应原 2.py 逻辑）
            with open(JSON_DIR+CSV_FILE, 'a', newline='', encoding='utf-8') as csvfile:
                csvwrite = csv.writer(csvfile)
                csvwrite.writerow([
                    type_id, name,
                    data['all']['max'], data['all']['min'],
                    data['buy']['max'], data['buy']['min'],
                    data['sell']['max'], data['sell']['min']
                ])
                
        except FileNotFoundError:
            print(f"找不到本地文件: {json_path}")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"数据解析错误 {filename}: {e}")
        except Exception as e:
            print(f"未知错误 {filename}: {e}")


if __name__ == '__main__':
    main()