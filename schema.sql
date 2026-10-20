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

-- 利润快照(0.8.0):每次行情更新后由 update_market.py 预计算,利润排行页直接读取
CREATE TABLE IF NOT EXISTS profit_snapshot (
    type_id            INT PRIMARY KEY,        -- 物品 ID(无固定 ID 的物品不入快照)
    name               VARCHAR(64) NOT NULL,
    category           VARCHAR(32) NOT NULL DEFAULT '其他',
    unit_cost_instant  DOUBLE,                 -- 单件合成成本:材料按最低卖单即时采购
    unit_cost_buyorder DOUBLE,                 -- 单件合成成本:材料按最高买单挂单收购
    market_sell_min    DOUBLE,                 -- 该物品当前最低卖单(挂单卖出参考价)
    market_buy_max     DOUBLE,                 -- 该物品当前最高买单(即时卖出到手价)
    complete           TINYINT NOT NULL DEFAULT 1,  -- 0=配方含无价材料,成本不可信
    updated_at         DATETIME
);

-- 历史行情(0.8.0):每次更新增量拉取近 90 天日线,趋势图使用
CREATE TABLE IF NOT EXISTS price_history (
    type_id     INT NOT NULL,
    date        DATE NOT NULL,
    average     DOUBLE,
    highest     DOUBLE,
    lowest      DOUBLE,
    volume      BIGINT,
    order_count INT,
    PRIMARY KEY (type_id, date)
);
