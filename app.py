# -*- coding: utf-8 -*-         

import os
import json
import csv
import sys
import subprocess
import re

# 从 flask 库导入四个工具：
# Flask: 创建 Web 应用的核心类
# render_template: 渲染 HTML 模板文件
# request: 获取前端发来的 HTTP 请求数据
# jsonify: 将 Python 字典转成 JSON 格式响应给前端
from flask import Flask, render_template, request, jsonify




# 从同目录的 query_logic.py 中导入 query_craft_cost 函数
# 该函数负责读取 JSON 制作清单并查询数据库计算成本
from Select import query_by_name, get_catalog

# 创建一个 Flask 应用实例
# __name__ 是当前模块名，Flask 用它来确定资源路径
app = Flask(__name__)

# 装饰器：定义路由规则
# 当用户访问根路径 http://localhost:5000/ 时，执行下面的 index 函数
@app.route('/')
# 定义处理根路径请求的视图函数
# 返回 templates 文件夹下的 index.html 页面给浏览器
def index():
    return render_template('index.html')

# 装饰器：定义 /query 路由，只接受 POST 请求
# 前端点击查询按钮时，会向这个地址发送 POST 请求
@app.route('/query', methods=['POST'])


# 定义处理 /query 请求的视图函数
def query():
    # 开始异常捕获块，防止程序出错时直接崩溃
    try:
        # 从 HTTP 请求体中解析 JSON 数据
        # 前端通过 fetch 发送的 {"name":"氧", "quantity":8} 会在这里被提取
        data = request.get_json()

        # 从 JSON 中取出 name 字段的值
        # data.get('name', '') 表示如果 name 不存在则返回空字符串
        # .strip() 去掉首尾空格，防止用户误输入空格
        name = data.get('name', '').strip()

        # 从 JSON 中取出 quantity 字段的值，默认给 1
        # int() 将字符串或数字转成整数，比如 "8" → 8
        quantity = int(data.get('quantity', 1))

        # 判断 name 是否为空字符串
        if not name:
            # 返回 JSON 错误提示给前端
            # success: False 表示请求处理失败
            return jsonify({'success': False, 'error': '物品名称不能为空'})
        # 判断数量是否小于 1
        if quantity < 1:
            # 返回 JSON 错误提示给前端
            return jsonify({'success': False, 'error': '数量必须大于0'})

        # 调用查询函数，传入物品名和制作数量
        # 返回值是字典（包含材料明细和总成本），失败返回 None
        result = query_by_name(name, quantity)  
        # 判断查询函数是否返回了 None                                     
        if result is None:
            # 返回找不到文件的错误
            return jsonify({'success': False, 'error': f'未找到 {name}.json 或清单格式错误'})

        # 查询成功，将结果包装成 JSON 返回给前端
        # success: True 表示成功
        # data: result 把查询到的明细数据传给前端
        return jsonify({'success': True, 'data': result})

    # 捕获 try 块中发生的任何异常
    # e 是异常对象，包含错误信息
    except Exception as e:
        # 将异常信息转成字符串，作为错误返回给前端                              
        return jsonify({'success': False, 'error': str(e)})


# 装饰器：注册 /query_batch 路由，只接受 HTTP POST 请求
# 前端点击"批量查询"时，会向这个地址发送 POST 请求
@app.route('/query_batch', methods=['POST'])
# 定义批量查询的视图函数
def query_batch():
    """批量查询接口：支持同时查多个物品"""
    # 开始异常捕获块，防止代码出错时 Flask 直接返回 500 错误页面
    try:
        # 从 HTTP 请求体中解析 JSON 数据
        data = request.get_json()
        # 前端 fetch 发送的 {"items": [{"name":"氧","quantity":2}, ...]} 在这里被提取
        # 从解析后的字典中取出 'items' 字段的值
        # data.get('items', []) 表示如果 items 不存在，默认返回空列表 []
        items = data.get('items', [])
        # 判断 items 是否为空列表
        if not items:
            # 空列表时返回 JSON 错误提示给前端
            # success: False 表示请求处理失败
            return jsonify({'success': False, 'error': '请至少输入一个物品'})


        # 初始化空列表，用于存放每个物品查询成功的结果
        results = []
        # 初始化数字 0，用于累加所有物品的收购价总成本
        grand_total_buy = 0
        # 初始化数字 0，用于累加所有物品的出售价总成本
        grand_total_sell = 0

        # 开始循环遍历前端传来的每个物品
        for item in items:
            # 从当前物品字典中取出 name 字段的值
            # .strip() 去掉首尾空格，防止用户误输入空格
            name = item.get('name', '').strip()
            # 从当前物品字典中取出 quantity 字段的值，默认给 1
            # int() 将字符串转成整数，比如 "3" → 3
            quantity = int(item.get('quantity', 1))


            # 判断 name 是否为空字符串（用户可能只填了数量没填名称）
            if not name:
                # 跳过当前这个物品，继续处理下一个
                continue
            
            # 调用 Select.py 中的查询函数，传入物品名和制作数量
            # 返回值是字典（包含该物品的材料明细和总成本），失败返回 None
            result = query_by_name(name, quantity)
            # 判断查询函数是否返回了有效结果（不是 None）
            if result:
                # 将该物品的查询结果追加到 results 列表中
                results.append(result)
                # 将该物品的收购总成本累加到全局收购总价
                grand_total_buy += result['total_buy']
                # 将该物品的出售总成本累加到全局出售价总价
                grand_total_sell += result['total_sell']

        # 所有物品处理完毕，构造 JSON 响应返回给前端
        return jsonify({
            # success: True 表示批量查询整体成功
            'success': True,
            # data 字段包裹所有返回数据
            'data': {
                # items: 每个物品的详细查询结果数组
                'items': results,
                # grand_total_buy: 所有物品收购价的总和
                'grand_total_buy': grand_total_buy,
                # grand_total_sell: 所有物品出售价的总和
                'grand_total_sell': grand_total_sell
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# 0628 /catalog 接口返回所有物品的 name、buy_max、sell_min
@app.route('/catalog', methods=['GET'])
def catalog():
    """返回数据库中所有物品的目录（名称、buy_max、sell_min）"""
    try:
        items = get_catalog()
        return jsonify({'success': True, 'data': items})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# 0704
@app.route('/update_database', methods=['POST'])
def update_database():
    """执行数据库更新流水线（下载 JSON + 同步 MySQL）"""
    try:
        script_path = os.path.join(os.path.dirname(__file__), 'update_database.py')

        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=600  # 给 10 分钟，防止数据量大时超时
        )

        if result.returncode != 0:
            return jsonify({'success': False, 'error': result.stderr or '更新脚本执行失败'})

        # 从输出中解析更新条数
        match = re.search(r'导入完成，共更新 (\d+) 条记录', result.stdout)
        updated = int(match.group(1)) if match else None

        return jsonify({
            'success': True,
            'updated': updated,
            'output': result.stdout
        })

    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': '更新超时，请稍后重试'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# 判断当前文件是否是直接运行（不是被其他文件导入）
if __name__ == '__main__':
    # 启动 Flask 内置开发服务器
    # debug=True: 开启调试模式，代码修改后自动重启，报错显示详细信息
    # host='0.0.0.0': 允许局域网内其他设备访问（不仅限于本机）
    # port=5000: 服务运行在 5000 端口
    app.run(debug=True, host='0.0.0.0', port=5000)