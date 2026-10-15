# -*- coding: utf-8 -*-

import os
import json
import csv
import sys
import time
import threading
import subprocess
import re
import hmac

# 从 flask 库导入五个工具：
# Flask: 创建 Web 应用的核心类
# render_template: 渲染 HTML 模板文件
# request: 获取前端发来的 HTTP 请求数据
# jsonify: 将 Python 字典转成 JSON 格式响应给前端
# session: 基于签名 Cookie 的会话(管理员登录态)
from flask import Flask, render_template, request, jsonify, session

# 行情更新流水线:手动更新经 subprocess 调用,定时更新在进程内直接调用 main()
import update_market

# 从同目录的 Select.py 中导入查询与目录函数
# query_by_name: 读取 JSON 制作清单并查询数据库计算成本
# get_catalog: 物品目录
# get_recipes: 全部配方轻量索引
from Select import query_by_name, get_catalog, get_recipes

# 配置加载:数据库连接 / 管理员密钥 / 定时任务参数
from db_config import load_db_config, load_security_config, load_schedule_config

# 创建一个 Flask 应用实例
# __name__ 是当前模块名，Flask 用它来确定资源路径
app = Flask(__name__)

# 会话签名密钥与管理员密码:启动时强制读取,缺失/为空直接报错提示
_security = load_security_config()
app.secret_key = _security['secret_key']
# Cookie 属性:SameSite=Lax 拦截跨站 POST 伪造(CSRF);部署到 HTTPS 后可再加 SESSION_COOKIE_SECURE
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# 更新任务互斥锁:手动更新(网页按钮)与定时更新(后台线程)同一时间只允许一个执行
_update_lock = threading.Lock()

# 登录防暴力破解(内存计数,进程重启清零):任意 60 秒窗口内失败 5 次即锁定该 IP 60 秒
_login_failures = {}
LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_SECONDS = 60
LOGIN_FAILURES_MAX_ENTRIES = 1000  # 字典上限,超过时清理已过期记录防内存无限增长

# 定时更新参数:服务启动 30 秒后进行首次更新(先让服务就绪),此后按配置间隔执行
AUTO_UPDATE_STARTUP_DELAY = 30
AUTO_UPDATE_MIN_INTERVAL = 60   # 间隔下限,防止误配成过小值刷爆 ESI


# ================== 管理员登录态 ==================
@app.route('/admin', methods=['GET'])
def admin_page():
    """管理控制台页面:独立于主页,主页面不再展示任何管理员入口"""
    return render_template('admin.html')


@app.route('/admin/status', methods=['GET'])
def admin_status():
    """返回当前会话是否为管理员,前端据此渲染更新按钮(游客锁定/管理员可用)"""
    return jsonify({'success': True, 'admin': bool(session.get('admin'))})


@app.route('/admin/login', methods=['POST'])
def admin_login():
    """校验 config.ini 中的管理员密码,成功后会话获得 admin 标记(Cookie 经 secret_key 签名)"""
    ip = request.remote_addr or 'unknown'
    now = time.time()
    rec = _login_failures.get(ip)
    if rec and rec['count'] >= LOGIN_MAX_FAILURES \
            and now - rec['last'] < LOGIN_LOCKOUT_SECONDS:
        return jsonify({'success': False,
                        'error': f'尝试次数过多,请 {LOGIN_LOCKOUT_SECONDS} 秒后再试'}), 429

    data = request.get_json(silent=True) or {}
    password = data.get('password', '')
    # 常量时间比较,避免攻击者通过响应耗时逐位猜测密码
    if password and hmac.compare_digest(
            password.encode('utf-8'), _security['admin_password'].encode('utf-8')):
        _login_failures.pop(ip, None)
        session['admin'] = True
        return jsonify({'success': True})

    rec = _login_failures.setdefault(ip, {'count': 0, 'last': 0})
    # 距上次失败已超过锁定窗口则重新累计(零星输错不会跨天累积触发锁定)
    if now - rec['last'] >= LOGIN_LOCKOUT_SECONDS:
        rec['count'] = 0
    rec['count'] += 1
    rec['last'] = now
    # 防字典无限增长:超过上限时清理已过期记录
    if len(_login_failures) > LOGIN_FAILURES_MAX_ENTRIES:
        for key in [k for k, v in _login_failures.items()
                    if now - v['last'] >= LOGIN_LOCKOUT_SECONDS]:
            _login_failures.pop(key, None)
    return jsonify({'success': False, 'error': '密码错误'}), 401


@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    """退出管理员登录"""
    session.pop('admin', None)
    return jsonify({'success': True})


# ================== 页面与查询接口(游客可用) ==================
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
            # 空列表时返回 JSON 错误提示
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
    """执行行情更新流水线(直连 ESI 拉取吉他 4-4 订单并 upsert 到 MySQL)。

    仅管理员可用:游客会话直接 403;同一时间只允许一个更新任务(手动与定时互斥)。
    """
    if not session.get('admin'):
        return jsonify({'success': False, 'error': '需要管理员登录后才能更新数据库'}), 403
    if not _update_lock.acquire(blocking=False):
        return jsonify({'success': False, 'error': '已有更新任务正在进行,请稍后再试'})

    try:
        script_path = os.path.join(os.path.dirname(__file__), 'update_market.py')

        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=600  # 给 10 分钟，防止数据量大时超时
        )

        if result.returncode != 0:
            return jsonify({'success': False, 'error': result.stderr or '更新脚本执行失败'})

        # 从输出中解析更新条数(与 update_market.py 的打印保持一致的半角逗号)
        match = re.search(r'导入完成,共更新 (\d+) 条记录', result.stdout)
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
    finally:
        _update_lock.release()


# 组件制造计算器页面
@app.route('/components')
def components_page():
    """组件制造计算页:目录选件 + 数量加减 + 建筑加成减免"""
    return render_template('components.html')


# 制造清单汇总页:粘贴购物单,一键递归展开到最终原材料
@app.route('/bom')
def bom_page():
    """制造清单汇总页:粘贴清单 + 建筑加成/蓝图ME → 汇总矿物/行星商品等最终原材料"""
    return render_template('bom.html')


# 0.6.0 /recipes 接口返回全部配方的轻量索引,供 BOM 页前端递归展开
@app.route('/recipes', methods=['GET'])
def recipes():
    """返回全部配方索引(name/id/tier/outputCount/inputs)"""
    try:
        return jsonify({'success': True, 'data': get_recipes()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ================== 定时行情更新(后台线程) ==================
def _auto_update_loop(interval_seconds):
    """启动后延迟 AUTO_UPDATE_STARTUP_DELAY 秒做首次更新,此后每 interval_seconds 秒更新一次。

    与手动更新共用 _update_lock:更新进行中则跳过本次定时任务,异常只记录日志不打断循环。
    """
    time.sleep(AUTO_UPDATE_STARTUP_DELAY)
    while True:
        if _update_lock.acquire(blocking=False):
            try:
                print(f'[定时更新] {time.strftime("%Y-%m-%d %H:%M:%S")} 开始行情更新...', flush=True)
                update_market.main()
                print(f'[定时更新] {time.strftime("%Y-%m-%d %H:%M:%S")} 行情更新完成', flush=True)
            except Exception as e:
                print(f'[定时更新] 行情更新失败: {e}', flush=True)
            finally:
                _update_lock.release()
        else:
            print('[定时更新] 跳过:已有更新任务正在进行', flush=True)
        time.sleep(interval_seconds)


# 判断当前文件是否是直接运行（不是被其他文件导入）
if __name__ == '__main__':
    # 启动 Flask 内置开发服务器
    # host='0.0.0.0': 允许局域网内其他设备访问（不仅限于本机）
    # port=5000: 服务运行在 5000 端口
    # debug 默认关闭:调试模式会向局域网暴露 Werkzeug 调试器(可执行任意代码),安全风险
    # 本地开发需要自动重载时显式开启: EVE_COST_DEBUG=1 python app.py
    debug = os.environ.get('EVE_COST_DEBUG', '0') == '1'

    # 定时行情更新:启动 30 秒后首次执行,此后按 config.ini [schedule] 间隔(默认 2 小时)
    interval = max(AUTO_UPDATE_MIN_INTERVAL, load_schedule_config()['update_interval_seconds'])
    threading.Thread(
        target=_auto_update_loop, args=(interval,),
        daemon=True, name='auto-update',
    ).start()
    print(f'定时行情更新已启用:启动 {AUTO_UPDATE_STARTUP_DELAY}s 后首次执行,此后每 {interval}s 一次', flush=True)

    app.run(debug=debug, host='0.0.0.0', port=5000)
