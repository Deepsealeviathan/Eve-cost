# Eve-cost

EVE Online(国服晨曦)制造成本估算工具:直连网易 ESI 镜像抓取吉他 4-4(加达里海军组装车间)实时行情并入库,按配方清单估算材料总成本(支持蓝图 ME、改装件、建筑减免与官方 EIV 公式的制造安装费),附带市场深度、利润排行、价格趋势、垃圾回收化矿收益与数据自检,提供 Web 页面与命令行两种使用方式。

行情数据来源:[网易 ESI 镜像](https://ali-esi.evepc.163.com/ui/)(`datasource=serenity`,伏尔戈星域整域订单,过滤吉他 4-4 空间站)

## 目录结构

```
├── app.py                     # Flask Web 服务(页面查询入口)
├── Select.py                  # 成本计算核心逻辑(P1~P4 递归计算 + EIV,被 app.py 调用)
├── update_market.py           # 行情流水线:ESI 整域拉取 → 吉他 4-4 聚合 → 历史行情 + 利润快照 + 调整价 → upsert MySQL
├── reprocessing.py            # 垃圾化矿:读取化矿清单 + 行情,生成页面数据
├── reprocessing.json          # 全部 T1 衍生装备(衍生 1~4 级)与 T1 弹药的化矿配方
├── build_reprocessing_data.py # 从官方 SDE + 网易 ESI 重新生成 reprocessing.json
├── build_ice_data.py          # 从官方 SDE + 网易 ESI 重新生成冰矿/冰矿产物配方 JSON
├── db_config.py               # 配置加载器(数据库 / 管理员密钥 / 定时任务 / 行情星域)
├── config.example.ini         # 配置模板(复制为 config.ini 后填写密码)
├── schema.sql                 # 数据库建表脚本
├── templates/                 # Web 页面模板(index / components / bom / profit / reprocess / admin / admin_health)
├── static/craft_rules.js      # 制造减免规则(结构 / 改装件 / 安等系数 / 安装费费率),两页共用
├── Doc/                       # 开发文档
├── Planetary_Commodities/     # 行星产物配方(P1 / P2 / P3 / P4)
├── Ore/                       # 矿物(基础材料,按市场价计算)
│   ├── StandardOres/          # 标准矿石(无直接市场价,按"100 单位提炼产物"折算单个矿石价值)
│   ├── IceOres/               # 冰矿(按"1 单位精炼产物"折算价值,含白釉冰 / 白釉冰（4级）等 12 种)
│   └── IceProducts/           # 冰矿精炼产物(重水、液化臭氧、同位素、锶包合物,基础材料)
├── MoonMaterials/             # 卫星原料(基础材料)
├── Gas/                       # 气云(基础材料)
├── Commodities/               # 挖坟材料(基础材料)
├── Salvage/                   # 打捞材料(基础材料)
├── AncientSalvage/            # 远古打捞(基础材料)
└── Reactions/                 # 反应配方
    ├── 混合聚合物/            # 矿物+气云+燃料块反应产物
    ├── 中间产物/              # 卫星原料+燃料块反应产物(纯产物)
    ├── 合成物/                # 中间产物+燃料块反应产物
    ├── 分子锻造材料/          # 气云+挖坟材料反应产物(神经链接/新富勒烯)
    └── 燃料块/                # 氧/氢/氦/氮燃料块(每轮 40 个,按官方蓝图算自制成本)
└── Components/                # 制造组件配方
    ├── 旗舰基础组件/          # 基础旗舰组件(矿物+合成物等)
    ├── 旗舰高级组件/          # 高级旗舰组件(合成物+分子锻造材料等)
    ├── T2制造组件/            # T2 组件(合成物+分子锻造材料等)
    └── 基础材料/              # 不可合成的组件输入(深渊材料/旗舰组件材料等,按市场价)
```

## 环境准备

- Python 3.9+(Flask 3.x 要求 3.9 及以上)
- MySQL 5.7 / 8.0

```bash
pip install -r requirements.txt

# 数据库配置:复制模板并填写密码(config.ini 已被 .gitignore 忽略)
cp config.example.ini config.ini
```

`config.ini` 共四个段:

- `[database]`:MySQL 连接参数(必填)
- `[security]`:`admin_password`(管理员登录密码)与 `secret_key`(会话签名密钥,可用 `python3 -c "import secrets; print(secrets.token_hex(32))"` 生成),部署到公网前务必修改
- `[schedule]`:`update_interval_seconds`,行情自动更新间隔(秒,默认 7200 = 2 小时,最小 60)
- `[market]`:`region_id`,行情所属星域(默认 10000002 伏尔戈/吉他);行情更新、成本估算、化矿页共用,一般不用改

## 数据库初始化

```bash
mysql -u root -p < schema.sql
```

共五张表:`items`(物品名称与分类)、`market_prices`(行情快照,按 type_id + region_id 覆盖更新)、`price_history`(0.8.0,近 90 天历史日线,趋势图用)、`profit_snapshot`(0.8.0,利润快照,每次行情更新后自动重算)和 `adjusted_prices`(ESI 调整价,制造安装费/EIV 计算用)。入库使用 upsert,无需预先插行;建表语句全部 `IF NOT EXISTS`,**从旧版本升级时在已有库上重跑一次即可,不影响旧数据**。

## 使用方式(推荐:Web 页面)

```bash
# 1. 更新行情与数据库(直连 ESI,无中间文件)
python update_market.py

# 2. 启动 Web 服务后浏览器访问 http://localhost:38000
python app.py
```

Web 页面支持:单个/批量成本查询(行星商品、矿物提炼、虫洞打捞材料等按材料口径估算,清单可存进 URL 分享、结果可导出 CSV、物品弹窗展示买卖盘挂单量与价差)、物品目录浏览(分类 + 搜索 + 价格新鲜度 + 近 90 天走势图 + 买卖盘挂单量与价差)、冰矿精炼成本(白釉冰 / 白釉冰（4级）等 12 种冰矿按 1 单位精炼产物折算,与冰矿市价对比)、组件制造计算器(访问 `/components`,目录选组件、数量加减、建筑加成减免、星系成本系数与官方 EIV 制造安装费)、制造清单汇总(访问 `/bom`,粘贴购物单一键展开最终原材料;支持建筑 / 改装件 / 星系安等 / 蓝图 ME / **星系成本系数**,按每道制造工序算安装费并汇总,汇总表可排序、导出 CSV / 复制时附安装费与总计)、利润排行(访问 `/profit`,全部可制造物品的利润/利润率对比,支持挂单/即时两种卖出口径与税率设置)、垃圾回收化矿(访问 `/reprocess`,全部 T1 衍生装备与 T1 弹药按最高 55% 化矿率计算产物价值、利润与批量收益,支持整段粘贴“物品名 + 数量”自动汇总矿物)以及数据自检(访问 `/admin/health`,行情新鲜度、无报价物品清单、配方/调整价/历史行情覆盖度)。

### 游客模式与管理员

面向公网部署设计,查询功能不需要登录:

- **游客**:访问 `http://localhost:38000/` 即游客模式,可直接使用全部查询功能(单查/批量/目录/组件计算器/BOM 汇总),页面上没有任何管理员入口或更新按钮
- **管理员**:单独访问 `http://localhost:38000/admin` 进入管理控制台,输入 `config.ini` 中 `[security].admin_password` 登录后可手动更新行情数据库(更新日志直接显示在页面上);密码错误 5 次锁定 60 秒;登录态经签名 Cookie 保存,闲置 30 分钟自动失效
- **定时自动更新**:服务启动 30 秒后执行首次行情更新,此后每 `update_interval_seconds`(默认 2 小时)自动执行一次,手动更新与定时更新互斥、同一时间只跑一个任务;更新进度与结果打印在服务日志中

### 公网部署

部署到公网服务器(Nginx 反向代理 + gunicorn + systemd + 自签 HTTPS)的完整路线见 **[Doc/部署指南.md](Doc/部署指南.md)**,含架构说明、资源测算、全部配置文件、验收清单与常见坑速查。反代适配(ProxyFix 真实 IP、HTTPS Cookie、gunicorn 下定时更新)已内置在代码中,按部署指南设置对应环境变量即可启用。

### 跟踪物品与分类规则

`update_market.py` 自动收集需要跟踪行情的物品,无需手工维护清单:

- **配方文件**:扫描各配方目录下 JSON 的 `id` 和配方 `inputs` 的 `materialId`(跟踪清单完全由配方文件决定,不再有手工维护的补充清单)
- **分类**:行星产物按目录记 P1~P4;其余按根目录 `categories.json`(格式 `{"分类名": ["物品名", ...]}`);都不在则为「其他」。分类随行情一并写入 `items` 表
- **调整价**:同一份跟踪清单从 ESI `/markets/prices/` 拉取 `adjusted_price`,写入 `adjusted_prices` 表,供组件页按官方 EIV 公式计算制造安装费
- **化矿物品**:`reprocessing.json` 中的衍生装备/T1 弹药及其化矿产物只跟踪 `market_prices`,不写入主物品目录,也不拉取历史行情;只是为了让化矿页能显示当前买入价和矿物价值

## 使用方式(命令行)

```python
from Select import query_by_name, get_catalog

result = query_by_name('机械元件', quantity=3)   # 返回材料明细、总成本与单轮 EIV
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

## 更新化矿清单

`reprocessing.json` 已随仓库提供,正常使用无需重新生成。游戏版本更新后需要补充新物品时:

```bash
python build_reprocessing_data.py
```

脚本会下载官方 SDE 的 `typeMaterials` 化矿数据,并从网易 ESI 取晨曦中文名与分组,筛出衍生等级 1~4 的全部装备与全部 T1 弹药。已有 SDE 压缩包时可加 `--sde /path/to/sde.zip` 跳过下载。

## 更新冰矿配方

`Ore/IceOres` / `Ore/IceProducts` 同样随仓库提供,游戏版本更新(或想要「高密度」等旧版冰矿变体)时可重新生成:

```bash
python build_ice_data.py                 # 只重写仓库中已有的 12 种冰矿,结果稳定
python build_ice_data.py --all           # 生成全部可化矿冰矿(含高密度变体)
python build_ice_data.py --sde sde.zip   # 复用已下载的 SDE
```

脚本从 SDE 分组 465「冰矿」与 423「冰矿产物」取材料表,名称优先用网易 ESI 晨曦中文名,写完自动回读自检材料数量与 SDE 是否一致。

## 更新日志

各版本变更与升级提示见 [CHANGELOG.md](CHANGELOG.md)。
