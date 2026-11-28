# -*- coding: utf-8 -*-
"""生成冰矿与冰矿产物的配方 JSON(Ore/IceOres、Ore/IceProducts)。

数据口径:
- 冰矿:官方 SDE 分组 465「Ice」,部分产物数量取 typeMaterials.jsonl(按 portionSize 归一)
- 冰矿产物:SDE 分组 423,即冰矿化矿后得到的 7 种材料(重水 / 液化臭氧 / 同位素等)
- 名称优先用网易 ESI(晨曦中文),缺失时回退到 SDE 中文名

默认只重写仓库中已有的冰矿文件(不凭空增加目录条目),保证重复执行结果稳定;
需要把全部可化矿冰矿(含「高密度」等旧版变体)一并生成时加 --all。

用法:
    python build_ice_data.py
    python build_ice_data.py --sde /path/to/sde.jsonl.zip
    python build_ice_data.py --all
"""
import argparse
import json
import os
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ESI = "https://ali-esi.evepc.163.com/latest"
DATASOURCE = "serenity"
SDE_URL = "https://developers.eveonline.com/static-data/eve-online-static-data-latest-jsonl.zip"
HEADERS = {"User-Agent": "eve-cost/0.9 (https://github.com/Deepsealeviathan/Eve-cost)"}
MAX_WORKERS = 8
MAX_RETRIES = 4

BASE_DIR = Path(__file__).resolve().parent
ORE_DIR = BASE_DIR / "Ore" / "IceOres"
PRODUCT_DIR = BASE_DIR / "Ore" / "IceProducts"

GROUP_ICE = 465          # 冰矿
GROUP_ICE_PRODUCT = 423  # 冰矿产物
TIER_ICE = "冰矿"
TIER_PRODUCT = "冰矿产物"


def esi_get(path):
    """带重试的 ESI GET;404 返回 None。"""
    url = f"{ESI}{path}"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params={"datasource": DATASOURCE, "language": "zh"},
                                headers=HEADERS, timeout=30)
            if resp.status_code == 404:
                return None
            if resp.status_code in (420, 429, 500, 502, 503, 504):
                raise requests.RequestException(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            if attempt == MAX_RETRIES:
                print(f"[失败] {path}: {e}")
                return None
            import time
            time.sleep(2 * attempt)
    return None


def download_sde():
    fd, path = tempfile.mkstemp(prefix="eve-sde-", suffix=".zip")
    os.close(fd)
    print(f"下载 SDE: {SDE_URL}")
    with requests.get(SDE_URL, headers=HEADERS, timeout=300, stream=True) as resp:
        resp.raise_for_status()
        with open(path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
    return path


def read_jsonl(zf, name):
    with zf.open(name) as f:
        for line in f:
            yield json.loads(line)


def zh_name(value):
    """SDE 名称字段是多语言 dict;取中文,缺失时取英文。"""
    if isinstance(value, dict):
        return value.get("zh") or value.get("en") or ""
    return value or ""


def collect_sde(zip_path):
    """从 SDE 筛出冰矿与冰矿产物,并带出每种冰矿的化矿材料。"""
    with zipfile.ZipFile(zip_path) as zf:
        materials = {
            row["_key"]: row.get("materials") or []
            for row in read_jsonl(zf, "typeMaterials.jsonl")
        }
        ores = {}
        products = {}
        for row in read_jsonl(zf, "types.jsonl"):
            if not row.get("published"):
                continue
            group_id = row.get("groupID")
            if group_id == GROUP_ICE and materials.get(row["_key"]):
                ores[row["_key"]] = {
                    "portion_size": row.get("portionSize") or 1,
                    "sde_name": zh_name(row.get("name")),
                    "materials": materials[row["_key"]],
                }
            elif group_id == GROUP_ICE_PRODUCT:
                products[row["_key"]] = zh_name(row.get("name"))
    return ores, products


def existing_ore_ids():
    """仓库中已有冰矿文件的 type_id 集合(默认模式下只重写这些)。"""
    ids = set()
    for path in ORE_DIR.glob("*.json"):
        try:
            ids.add(int(json.loads(path.read_text(encoding="utf-8"))["id"]))
        except (ValueError, KeyError, json.JSONDecodeError):
            continue
    return ids


def resolve_names(type_ids):
    """批量取网易 ESI 中文名,返回 {type_id: name}。"""
    def fetch(type_id):
        return type_id, esi_get(f"/universe/types/{type_id}")

    names = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for type_id, data in pool.map(fetch, sorted(type_ids)):
            if data and data.get("name"):
                names[type_id] = data["name"]
    return names


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sde", help="已下载的 SDE jsonl zip;省略则自动下载最新版")
    parser.add_argument("--all", action="store_true",
                        help="生成全部可化矿冰矿(含高密度等旧版变体),默认只重写已有文件")
    args = parser.parse_args()

    sde_path = args.sde
    temporary = False
    if not sde_path:
        sde_path = download_sde()
        temporary = True
    try:
        ores, products = collect_sde(sde_path)
    finally:
        if temporary:
            os.unlink(sde_path)

    print(f"SDE 冰矿: {len(ores)} 种,冰矿产物: {len(products)} 种")
    if not args.all:
        keep = existing_ore_ids()
        missing = keep - set(ores)
        if missing:
            print(f"警告:仓库中有 {len(missing)} 个冰矿 ID 已不在 SDE:{sorted(missing)}")
        ores = {tid: info for tid, info in ores.items() if tid in keep}
        print(f"默认模式:只重写已有冰矿 {len(ores)} 种(加 --all 可生成全部)")

    # 需要中文名的:冰矿本身 + 其化矿产物
    product_ids = {m["materialTypeID"] for info in ores.values() for m in info["materials"]}
    names = resolve_names(set(ores) | product_ids)

    written = 0
    for type_id, info in sorted(ores.items(), key=lambda kv: names.get(kv[0], kv[1]["sde_name"])):
        name = names.get(type_id) or info["sde_name"]
        if not name:
            print(f"跳过无名称冰矿: {type_id}")
            continue
        inputs = []
        for mat in info["materials"]:
            mat_id = mat["materialTypeID"]
            inputs.append({
                "materialId": mat_id,
                "materialname": names.get(mat_id) or products.get(mat_id) or f"未知材料 {mat_id}",
                "count": mat["quantity"],
            })
        write_json(ORE_DIR / f"{name}.json", {
            "id": type_id,
            "name": name,
            "tier": TIER_ICE,
            "recipe": {"outputCount": info["portion_size"], "inputs": inputs},
        })
        written += 1

    used_products = sorted(product_ids)
    for type_id in used_products:
        name = names.get(type_id) or products.get(type_id)
        if not name:
            print(f"跳过无名称冰矿产物: {type_id}")
            continue
        path = PRODUCT_DIR / f"{name}.json"
        payload = {"id": type_id, "name": name, "tier": TIER_PRODUCT}
        if path.exists():
            old = json.loads(path.read_text(encoding="utf-8"))
            if old == payload:
                continue
        write_json(path, payload)

    print(f"已写入冰矿 {written} 个、冰矿产物 {len(used_products)} 个到 {ORE_DIR.parent}")

    # 自检:重读刚写入的文件,确认材料数量与 SDE 完全一致
    mismatched = []
    for type_id, info in ores.items():
        name = names.get(type_id) or info["sde_name"]
        path = ORE_DIR / f"{name}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        got = {i["materialId"]: i["count"] for i in data["recipe"]["inputs"]}
        want = {m["materialTypeID"]: m["quantity"] for m in info["materials"]}
        if got != want or data["recipe"]["outputCount"] != info["portion_size"]:
            mismatched.append(name)
    print("自检:" + ("全部与 SDE 一致" if not mismatched else f"{len(mismatched)} 个不一致 {mismatched}"))


if __name__ == "__main__":
    main()
