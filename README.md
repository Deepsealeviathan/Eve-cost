# Eve-cost

EVE Online（国服）制造成本估算工具：抓取吉他（Jita）市场实时行情并入库，按配方清单估算材料总成本，提供 Web 页面与命令行两种使用方式。

行情数据来源：[EVE 市场网](https://www.ceve-market.org)（默认查询 伏尔戈星域 / 吉他）

## 目录结构

```
├── app.py                     # Flask Web 服务（页面查询入口）
├── Select.py                  # 成本计算核心逻辑（P1~P4 递归计算，被 app.py 调用）
├── update_database.py         # 行情下载 + 数据库同步一体化流水线（并发版，推荐）
├── templates/                 # Web 页面模板
├── Doc/                       # 开发文档
├── Json/
│   ├── Getdata.py             # 独立脚本：下载行情 → 本地 .json + data.csv（单线程老流程）
│   ├── Update2Mysql.py        # 独立脚本：data.csv → MySQL
│   ├── json_url.txt           # 物品清单（每行：物品名;API地址）
│   ├── data.csv               # 行情汇总表
│   └── *.json                 # 各物品缓存行情（按 typeID 命名）
├── Planetary_Commodities/     # 行星产物配方（P1 / P2 / P3 / P4）
├── Ore/                       # 矿物（基础材料，按市场价计算）
│   └── StandardOres/          # 标准矿石（无直接市场价，按"100 单位提炼产物"折算单个矿石价值）
├── MoonMaterials/             # 卫星原料（基础材料）
├── Gas/                       # 气云（基础材料）
└── Commodities/               # 挖坟材料（基础材料）
```

## 环境准备

- Python 3.8+
- MySQL 5.7 / 8.0

```bash
pip install -r requirements.txt
```

数据库连接配置在 `Select.py`、`update_database.py`、`Json/Update2Mysql.py` 顶部的 `DB_CONFIG`。

## 数据库初始化

```sql
create database EVE;

create table test(
    ID int primary key,
    name varchar(20),
    `max` double,
    `min` double,
    buy_max double,
    buy_min double,
    sell_max double,
    sell_min double,
    update_time time
);
```

> 注意：`update_database.py` / `Update2Mysql.py` 只执行 UPDATE，物品需要先以对应 ID 存在于 `test` 表中才会被更新。

## 使用方式（推荐：Web 页面）

```bash
# 1. 按需编辑 Json/json_url.txt 追加物品（格式：物品名;API地址）

# 2. 更新行情与数据库（并发下载，自动入库）
python update_database.py

# 3. 启动 Web 服务后浏览器访问 http://localhost:5000
python app.py
```

Web 页面支持：单个/批量成本查询、物品目录浏览（分类 + 搜索）、一键更新数据库（调用 `update_database.py`）。

### 物品目录分类规则

侧栏分类由两部分自动构建，修改后重启 `app.py` 生效：

- **行星商品（P1~P4）**：扫描 `Planetary_Commodities/P1~P4` 目录下的配方文件
- **自定义分类**：项目根目录 `categories.json`，格式如下，可自由增改分类和物品：

```json
{
    "矿物": ["类银超金属", "三钛合金"],
    "气云": ["富勒体-C50", "富勒体-C60"]
}
```

未归入任何分类的物品显示在「其他」大类中，前端分类导航根据返回数据自动生成。

## 使用方式（命令行）

```python
from Select import query_by_name, get_catalog

result = query_by_name('机械元件', quantity=3)   # 返回材料明细与总成本
items = get_catalog()                             # 返回全部物品目录
```

`Json/` 下两个独立脚本保留了单线程老流程，可单独执行：

```bash
python Json/Getdata.py        # 仅下载行情
python Json/Update2Mysql.py   # 仅同步数据库
```

## 配方文件格式

P1（直接查询数据库市场价）：

```json
{
  "id": 2393,
  "name": "细菌",
  "tier": "P1"
}
```

P2 / P3 / P4（含合成配方，成本递归计算、最终落实到 P1 市场价）：

```json
{
  "id": 3689,
  "name": "机械元件",
  "tier": "P2",
  "recipe": {
    "outputCount": 5,
    "inputs": [
      { "materialId": 2398, "materialname": "反应金属", "count": 40 },
      { "materialId": 2399, "materialname": "稀有金属", "count": 40 }
    ]
  }
}
```

所有脚本路径均基于脚本自身位置自动定位，Windows / Linux 通用，可在任意工作目录下执行。
