#!/usr/bin/env python3
"""Create a reusable local website without copying preview/demo data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
DESIGN = ROOT / "static" / "design-system.css"
RUNTIME = ROOT / "templates" / "runtime.js"
DESIGN_SYSTEM = "workhub-v1"
TEMPLATES = {
    "radar": ("信息雷达", "信息收集、舆情监控、来源聚合"),
    "library": ("知识资料库", "文档检索、资料归档、研究笔记"),
    "brief": ("分析简报", "研究结论、周期报告、专题分析"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="列出版式与适用场景")
    create = commands.add_parser("create", help="复制版式；正式站点默认无演示数据")
    create.add_argument("--template", required=True, choices=TEMPLATES)
    create.add_argument("--output", required=True, type=Path)
    create.add_argument("--name", required=True)
    create.add_argument("--description", default="")
    create.add_argument("--demo", action="store_true", help="明确选择复制演示数据")
    args = parser.parse_args()
    if args.command == "list":
        print(json.dumps([{"id":key,"name":value[0],"description":value[1]} for key,value in TEMPLATES.items()], ensure_ascii=False, indent=2))
        return 0
    if not args.name.strip():
        parser.error("网站名称不能为空")
    source = ROOT / "templates" / args.template
    destination = args.output.expanduser().absolute()
    if destination.is_symlink():
        parser.error("输出目录不能是符号链接")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        parser.error("为保护现有网站，输出目录必须不存在或为空")
    if not (source / "index.html").is_file():
        parser.error("模板文件缺失：" + str(source))
    if not DESIGN.is_file() or not RUNTIME.is_file():
        parser.error("统一设计系统或模板运行脚本缺失，请恢复工作台文件")
    data = json.loads((source / "data.json").read_text(encoding="utf-8")) if args.demo else {"items": [], "is_demo": False}
    data.update(name=args.name.strip(), description=args.description or TEMPLATES[args.template][1])
    destination.mkdir(parents=True, exist_ok=True)
    for file in source.iterdir():
        if file.is_file() and file.name not in ("data.json", "index.html", "runtime.js", "design-system.css"):
            shutil.copyfile(file, destination / file.name)
    # Preview loads canonical assets through the hub. A generated site owns
    # local copies and has no dependency on Workhub's URL or listening port.
    page = (source / "index.html").read_text(encoding="utf-8")
    page = page.replace('href="/design-system.css"', 'href="design-system.css"')
    page = page.replace('src="/templates/runtime.js"', 'src="runtime.js"')
    (destination / "index.html").write_text(page, encoding="utf-8")
    shutil.copyfile(DESIGN, destination / "design-system.css")
    shutil.copyfile(RUNTIME, destination / "runtime.js")
    (destination / "data.json").write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    manifest = {"schema_version":1,"template_id":args.template,"design_system":DESIGN_SYSTEM,
                "design_sha256":hashlib.sha256(DESIGN.read_bytes()).hexdigest(),
                "name":args.name.strip(),"data_file":"data.json"}
    (destination / "workhub-site.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"created":str(destination.resolve()),"template":args.template,"demo":args.demo,"item_count":len(data["items"]),"next":"用 scripts/install.py --project /项目 --site-dir " + str(destination.resolve()) + " --template " + args.template + " 接入门户"},ensure_ascii=False,indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print("模板生成失败：" + str(error), file=sys.stderr)
        raise SystemExit(1)
