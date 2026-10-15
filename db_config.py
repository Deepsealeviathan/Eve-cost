# -*- coding: utf-8 -*-
"""配置加载器:从 config.ini 读取数据库连接、管理员密钥与定时任务参数,避免密码硬编码进代码。

config.ini 不存在时请复制 config.example.ini 并修改。
"""
import configparser
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parent / 'config.ini'


def _load_parser():
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"找不到配置文件 {CONFIG_FILE},请复制 config.example.ini 为 config.ini 并填写数据库密码"
        )
    parser = configparser.ConfigParser()
    parser.read(CONFIG_FILE, encoding='utf-8')
    return parser


def load_db_config():
    """读取 config.ini 的 [database] 段,返回 pymysql.connect 可用的参数字典。"""
    parser = _load_parser()
    section = parser['database']

    return {
        'host': section.get('host', '127.0.0.1'),
        'port': section.getint('port', 3306),
        'user': section['user'],
        'password': section['password'],
        'database': section.get('database', 'eve'),
        'charset': 'utf8mb4',
        'autocommit': False,
    }


def load_security_config():
    """读取 [security] 段:admin_password(管理员登录密码)与 secret_key(Flask 会话签名密钥)。

    两项均不能为空,否则启动报错并提示;部署到公网前务必改成强随机值。
    """
    parser = _load_parser()
    if not parser.has_section('security'):
        raise KeyError(
            "config.ini 缺少 [security] 段:请参照 config.example.ini "
            "补充 admin_password(管理员密码)与 secret_key(会话签名密钥)"
        )
    section = parser['security']
    admin_password = section.get('admin_password', '').strip()
    secret_key = section.get('secret_key', '').strip()
    if not admin_password:
        raise ValueError("config.ini [security].admin_password 不能为空:请设置管理员登录密码")
    if not secret_key:
        raise ValueError("config.ini [security].secret_key 不能为空:请设置一串随机字符用于会话签名")
    return {'admin_password': admin_password, 'secret_key': secret_key}


def load_schedule_config():
    """读取 [schedule].update_interval_seconds(行情自动更新间隔秒数,缺省 7200=2 小时)。"""
    parser = _load_parser()
    if not parser.has_section('schedule'):
        return {'update_interval_seconds': 7200}
    raw = parser['schedule'].get('update_interval_seconds', '7200')
    try:
        interval = int(raw.strip())
    except ValueError:
        raise ValueError(
            f"config.ini [schedule].update_interval_seconds 必须是整数秒数,当前值: {raw!r}"
            "(默认 7200 = 2 小时)"
        )
    return {'update_interval_seconds': interval}
