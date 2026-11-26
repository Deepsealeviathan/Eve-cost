# -*- coding: utf-8 -*-
"""生成 reprocessing.json:全部 T1 衍生装备(衍生 1~4 级)与 T1 弹药的化矿数据。

材料数量来自官方 SDE 的 typeMaterials.jsonl,物品/材料中文名与分组优先取网易 ESI,
缺失时回退到 SDE 中文名。输出文件供 Web 页面与 update_market.py 读取,运行期不再需要 SDE。

用法:
    python build_reprocessing_data.py
    python build_reprocessing_data.py --sde /path/to/sde.zip
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
OUTPUT = BASE_DIR / "reprocessing.json"

CATEGORY_EQUIPMENT = 7
CATEGORY_AMMO = 8


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


def collect_candidates(zip_path):
    """按分类、衍生等级与化矿材料筛出候选物品。"""
    with zipfile.ZipFile(zip_path) as zf:
        groups = {row["_key"]: row for row in read_jsonl(zf, "groups.jsonl")}
        materials = {
            row["_key"]: row.get("materials") or []
            for row in read_jsonl(zf, "typeMaterials.jsonl")
        }
        candidates = {}
        for row in read_jsonl(zf, "types.jsonl"):
            group = groups.get(row.get("groupID"))
            if not group or not row.get("published"):
                continue
            category_id = group.get("categoryID")
            meta_level = row.get("metaLevel")
            meta_group = row.get("metaGroupID")
            if category_id == CATEGORY_EQUIPMENT and meta_level is not None and 1 <= meta_level <= 4:
                kind = "equipment"
            elif category_id == CATEGORY_AMMO and meta_group in (1, None) \
                    and meta_level in (None, 0):
                # Tech I 弹药包含有 metaGroupID=1 的常规弹药,以及炸弹/脚本/电容装料等
                # SDE 未标 metaGroupID 的基础弹药;排除 T2(2)、势力(4)、死亡空间(6)等
                kind = "ammo"
            else:
                continue
            if not materials.get(row["_key"]):
                continue
            candidates[row["_key"]] = {
                "kind": kind,
                "meta_level": meta_level or 0,
                "group_id": row.get("groupID"),
                "portion_size": row.get("portionSize") or 1,
                "sde_name": zh_name(row.get("name")),
                "sde_group": zh_name(group.get("name")),
                "materials": materials[row["_key"]],
            }
    return candidates


def resolve_esi(candidates):
    """批量取网易 ESI 的物品名、分组名与材料名,尽可能使用晨曦本地化文本。"""
    type_ids = set(candidates)
    for info in candidates.values():
        type_ids.update(m["materialTypeID"] for m in info["materials"])
    group_ids = {info["group_id"] for info in candidates.values()}

    def fetch_type(type_id):
        return type_id, esi_get(f"/universe/types/{type_id}")

    def fetch_group(group_id):
        return group_id, esi_get(f"/universe/groups/{group_id}")

    type_data = {}
    group_data = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for type_id, data in pool.map(fetch_type, sorted(type_ids)):
            if data:
                type_data[type_id] = data
        for group_id, data in pool.map(fetch_group, sorted(group_ids)):
            if data:
                group_data[group_id] = data

    missing = sorted(set(candidates) - set(type_data))
    print(f"ESI 物品信息: {len(candidates) - len(missing)}/{len(candidates)} 个可用")
    if missing:
        print(f"晨曦不存在/未发布而跳过 {len(missing)} 个: {missing[:10]}...")

    items = []
    for type_id, info in candidates.items():
        esi_type = type_data.get(type_id)
        if not esi_type:
            continue
        group = group_data.get(info["group_id"])
        materials = []
        for mat in info["materials"]:
            mat_id = mat["materialTypeID"]
            mat_type = type_data.get(mat_id)
            materials.append({
                "id": mat_id,
                "name": (mat_type or {}).get("name") or f"未知材料 {mat_id}",
                "quantity": mat["quantity"],
            })
        items.append({
            "id": type_id,
            "name": esi_type.get("name") or info["sde_name"],
            "group": (group or {}).get("name") or info["sde_group"],
            "kind": info["kind"],
            "meta_level": info["meta_level"],
            "portion_size": esi_type.get("portion_size") or info["portion_size"],
            "materials": materials,
        })

    items.sort(key=lambda x: (x["kind"], x["group"], x["name"]))
    return items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sde", help="已下载的 SDE jsonl zip;省略则自动下载最新版")
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()

    sde_path = args.sde
    temporary = False
    if not sde_path:
        sde_path = download_sde()
        temporary = True
    try:
        candidates = collect_candidates(sde_path)
        print(f"SDE 候选:装备 {sum(v['kind'] == 'equipment' for v in candidates.values())} 个,"
              f"弹药 {sum(v['kind'] == 'ammo' for v in candidates.values())} 个")
        items = resolve_esi(candidates)
    finally:
        if temporary:
            os.unlink(sde_path)

    material_names = {}
    for item in items:
        for mat in item["materials"]:
            material_names[str(mat["id"])] = mat["name"]
            mat.pop("name", None)

    payload = {
        "version": 1,
        "max_rate": 0.55,
        "material_names": material_names,
        "items": items,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"已写入 {args.output}:{len(items)} 个物品,{len(material_names)} 种化矿产物")


if __name__ == "__main__":
    main()
