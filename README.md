# Eve-cost

EVE Online(国服晨曦)制造成本估算工具:直连网易 ESI 镜像抓取吉他 4-4(加达里海军组装车间)实时行情并入库,按配方清单估算材料总成本,提供 Web 页面与命令行两种使用方式。

行情数据来源:[网易 ESI 镜像](https://ali-esi.evepc.163.com/ui/)(`datasource=serenity`,伏尔戈星域整域订单,过滤吉他 4-4 空间站)

## 目录结构

```
├── app.py                     # Flask Web 服务(页面查询入口)
├── Select.py                  # 成本计算核心逻辑(P1~P4 递归计算,被 app.py 调用)
├── update_market.py           # 行情流水线:ESI 整域拉取 → 吉他 4-4 聚合 → upsert MySQL
├── db_config.py               # 数据库配置加载器(读取 config.ini)
├── config.example.ini         # 数据库配置模板(复制为 config.ini 后填写密码)
├── schema.sql                 # 数据库建表脚本
├── templates/                 # Web 页面模板
├── Doc/                       # 开发文档
├── Planetary_Commodities/     # 行星产物配方(P1 / P2 / P3 / P4)
├── Ore/                       # 矿物(基础材料,按市场价计算)
│   └── StandardOres/          # 标准矿石(无直接市场价,按"100 单位提炼产物"折算单个矿石价值)
├── MoonMaterials/             # 卫星原料(基础材料)
├── Gas/                       # 气云(基础材料)
└── Commodities/               # 挖坟材料(基础材料)
```

## 环境准备

- Python 3.8+
- MySQL 5.7 / 8.0

```bash
pip install -r requirements.txt

# 数据库配置:复制模板并填写密码(config.ini 已被 .gitignore 忽略)
cp config.example.ini config.ini
```

## 数据库初始化

```bash
mysql -u root -p < schema.sql
```

共两张表:`items`(物品名称与分类)和 `market_prices`(行情快照,按 type_id + region_id 覆盖更新)。入库使用 upsert,无需预先插行。

## 使用方式(推荐:Web 页面)

```bash
# 1. 更新行情与数据库(直连 ESI,无中间文件)
python update_market.py

# 2. 启动 Web 服务后浏览器访问 http://localhost:5000
python app.py
```

Web 页面支持:单个/批量成本查询、物品目录浏览(分类 + 搜索)、一键更新数据库(调用 `update_market.py`)。

### 跟踪物品与分类规则

`update_market.py` 自动收集需要跟踪行情的物品,无需手工维护清单:

- **配方文件**:扫描各配方目录下 JSON 的 `id` 和配方 `inputs` 的 `materialId`
- **补充物品**:既不出现在配方中又有市场价的物品(如燃料块),在 `update_market.py` 顶部的 `EXTRA_TYPE_IDS` 中登记 type_id
- **分类**:行星产物按目录记 P1~P4;其余按根目录 `categories.json`(格式 `{"分类名": ["物品名", ...]}`);都不在则为「其他」。分类随行情一并写入 `items` 表

## 使用方式(命令行)

```python
from Select import query_by_name, get_catalog

result = query_by_name('机械元件', quantity=3)   # 返回材料明细与总成本
items = get_catalog()                             # 返回全部物品目录
```

## 配方文件格式

P1(直接查询数据库市场价):

```json
{
  "id": 2393,
  "name": "细菌",
  "tier": "P1"
}
```

P2 / P3 / P4(含合成配方,成本递归计算、最终落实到 P1 市场价):

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

所有脚本路径均基于脚本自身位置自动定位,Windows / Linux 通用,可在任意工作目录下执行。
