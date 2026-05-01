# -*- coding: utf-8 -*-         

# 从 flask 库导入四个工具：
# Flask: 创建 Web 应用的核心类
# render_template: 渲染 HTML 模板文件
# request: 获取前端发来的 HTTP 请求数据
# jsonify: 将 Python 字典转成 JSON 格式响应给前端
from flask import Flask, render_template, request, jsonify


# 从同目录的 query_logic.py 中导入 query_craft_cost 函数
# 该函数负责读取 JSON 制作清单并查询数据库计算成本
from Select import query_by_name

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
def query_batch():
    """批量查询接口：支持同时查多个物品"""
    try:
        data = request.get_json()
        items = data.get('items', [])

        if not items:
            return jsonify({'success': False, 'error': '请至少输入一个物品'})

        results = []
        grand_total_buy = 0
        grand_total_sell = 0

        for item in items:
            name = item.get('name', '').strip()
            quantity = int(item.get('quantity', 1))

            if not name:
                continue

            result = query_by_name(name, quantity)
            if result:
                results.append(result)
                grand_total_buy += result['total_buy']
                grand_total_sell += result['total_sell']

        return jsonify({
            'success': True,
            'data': {
                'items': results,
                'grand_total_buy': grand_total_buy,
                'grand_total_sell': grand_total_sell
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# 判断当前文件是否是直接运行（不是被其他文件导入）
if __name__ == '__main__':
    # 启动 Flask 内置开发服务器
    # debug=True: 开启调试模式，代码修改后自动重启，报错显示详细信息
    # host='0.0.0.0': 允许局域网内其他设备访问（不仅限于本机）
    # port=5000: 服务运行在 5000 端口
    app.run(debug=True, host='0.0.0.0', port=5000)