# -*- coding: utf-8 -*-
"""数据库配置加载器:从 config.ini 读取连接参数,避免密码硬编码进代码。

config.ini 不存在时请复制 config.example.ini 并修改。
"""
import configparser
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parent / 'config.ini'


def load_db_config():
    """读取 config.ini 的 [database] 段,返回 pymysql.connect 可用的参数字典。"""
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"找不到配置文件 {CONFIG_FILE},请复制 config.example.ini 为 config.ini 并填写数据库密码"
        )

    parser = configparser.ConfigParser()
    parser.read(CONFIG_FILE, encoding='utf-8')
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
