-- Eve-cost 数据库结构(0.5.0 起)
-- 旧的 test 表已废弃,可手动 DROP TABLE test;

CREATE DATABASE IF NOT EXISTS eve DEFAULT CHARSET utf8mb4;
USE eve;

-- 物品静态信息:名称与分类,由 update_market.py 自动维护
CREATE TABLE IF NOT EXISTS items (
    type_id  INT PRIMARY KEY,
    name     VARCHAR(64) NOT NULL,
    category VARCHAR(32) NOT NULL DEFAULT '其他'
);

-- 行情快照:每次更新整体覆盖,只保留最新一档
CREATE TABLE IF NOT EXISTS market_prices (
    type_id     INT NOT NULL,
    region_id   INT NOT NULL,
    buy_max     DOUBLE,
    buy_min     DOUBLE,
    sell_max    DOUBLE,
    sell_min    DOUBLE,
    buy_volume  BIGINT,
    sell_volume BIGINT,
    updated_at  DATETIME,
    PRIMARY KEY (type_id, region_id)
);
