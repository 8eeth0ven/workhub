"""Bundled module links and read-only associations with workspace websites.

Catalog metadata is shipped with Workhub. Listing does not contact GitHub,
search project directories, probe servers, install modules or execute code.
Only module.json directly inside an already admitted site's project is read.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import stat


REPOSITORY = "https://github.com/8eeth0ven/workhub-model"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_SITES = 2000
# Download assets were verified at publication; this is a versioned catalog,
# not a claim that the remote repository's newest release was queried.
_MODULES = (
    {
        "id": "auto-opinion", "version": "0.1.0",
        "name": {"zh-CN": "车圈舆情监控", "en": "Automotive opinion monitor"},
        "description": {"zh-CN": "整理公开汽车新闻与热搜，生成日报并保留来源状态。",
                        "en": "Collect public automotive headlines and trends into digests with source health."},
        "download_url": REPOSITORY + "/releases/download/v0.1.0/auto-opinion-0.1.0.zip",
    },
    {
        "id": "ai-opinion", "version": "0.1.1",
        "name": {"zh-CN": "AI 产品舆情监控", "en": "AI product opinion monitor"},
        "description": {"zh-CN": "跟踪 AI 产品、硬件与人物言论，合并重复并查看增量。",
                        "en": "Track AI products, hardware and public statements with deduplication and incremental briefs."},
        "download_url": REPOSITORY + "/releases/download/ai-opinion-v0.1.1/ai-opinion-0.1.1.zip",
    },
    {
        "id": "compute-search", "version": "0.1.0",
        "name": {"zh-CN": "算力产业链研究", "en": "Compute investment research"},
        "description": {"zh-CN": "用七类研究卡、GPU 目录起价和产业动态检验投资问题。",
                        "en": "Study seven value-chain stages, GPU catalog starting prices and industry signals."},
        "download_url": REPOSITORY + "/releases/download/compute-search-v0.1.0/compute-search-0.1.0.zip",
    },
    {
        "id": "coding-graph", "version": "0.1.0",
        "name": {"zh-CN": "代码与图检索", "en": "Code & graph learning"},
        "description": {"zh-CN": "查看 AI 原生工程动态与深入资料，检索本机 Python 静态代码关系。",
                        "en": "Explore AI-native engineering updates, advanced resources and local Python static code relationships."},
        "download_url": REPOSITORY + "/releases/download/coding-graph-v0.1.0/coding-graph-0.1.0.zip",
    },
    {
        "id": "english-slices", "version": "0.1.0",
        "name": {"zh-CN": "英语成片学习", "en": "English in slices"},
        "description": {"zh-CN": "导入自己的词表，连续浏览词片，按需朗读单词和生活句子。",
                        "en": "Import your vocabulary, browse continuous slices and listen to words and everyday phrases."},
        "download_url": REPOSITORY + "/releases/download/english-slices-v0.1.0/english-slices-0.1.0.zip",
    },
    {
        "id": "industry-atlas", "version": "0.1.0",
        "name": {"zh-CN": "产业知识图谱", "en": "Industry evidence atlas"},
        "description": {"zh-CN": "整理实体用途、产地和上下游关系，逐条保留证据、时间与变更。",
                        "en": "Organize roles, origins and upstream/downstream relationships with evidence, dates and changes."},
        "download_url": REPOSITORY + "/releases/download/industry-atlas-v0.1.0/industry-atlas-0.1.0.zip",
    },
)
MODULE_IDS = frozenset(item["id"] for item in _MODULES)

# Pinned archive digests are verified release artifacts, never supplied by HTTP.
_PACKAGE_SHA256 = {
    "auto-opinion": "9fc18ae0fc1fc1f11b360cb59a5ad24c7d44db7536d5130cea62294f551d2d99",
    "ai-opinion": "1d5612e1cc5089b4d9ca07bbc0705407b7fe7109ccbc6cf0fd3e35ff06fb27d4",
    "compute-search": "d453a03487989be46dea699f7fc3a541121286c071818c82193f9c170b4a0108",
    "coding-graph": "079f1373ddd4aebd86a0c7ab6f561d5ff7f4380be144b2e007e70be889dff461",
    "english-slices": "aa43c8aa63fa1530953ff2c0f23b1a3efbba9737acbf372f2b4b6a9db8b89736",
    "industry-atlas": "007849860a8979f1d8d2ac2416fd1067246d8567bb481a001d240b5236a24da7"
}


def trusted_module(module_id):
    """Return server-owned installation metadata for a fixed catalog identity."""
    if not isinstance(module_id, str) or module_id not in MODULE_IDS:
        raise ValueError("unknown module")
    item = next(item for item in _MODULES if item["id"] == module_id)
    return dict(deepcopy(item), sha256=_PACKAGE_SHA256[module_id])


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate manifest field")
        result[key] = value
    return result


def _installed_module(project_path):
    """Read one bounded regular manifest; return only its known module identity."""
    if not isinstance(project_path, str) or not project_path or len(project_path) > 4096 or "\0" in project_path:
        return None
    root = Path(project_path)
    if not root.is_absolute():
        return None
    directory_fd = manifest_fd = None
    try:
        root_info = root.lstat()
        if not stat.S_ISDIR(root_info.st_mode):
            return None  # Includes symbolic project directories.
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        if os.open in os.supports_dir_fd:
            directory_fd = os.open(root, flags | getattr(os, "O_DIRECTORY", 0))
            manifest_fd = os.open("module.json", flags, dir_fd=directory_fd)
        else:
            # Platforms without dir_fd still reject links and compare inode
            # identity after open; no directory traversal or recursive scan.
            target = root / "module.json"
            before = target.lstat()
            if not stat.S_ISREG(before.st_mode):
                return None
            manifest_fd = os.open(target, flags)
            after = os.fstat(manifest_fd)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                return None
        info = os.fstat(manifest_fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_MANIFEST_BYTES:
            return None
        with os.fdopen(manifest_fd, "rb") as stream:
            manifest_fd = None
            raw = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            return None
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
                or data.get("schema_version") != 1 or data.get("kind") != "workhub-module"
                or not isinstance(data.get("id"), str) or data["id"] not in MODULE_IDS):
            return None
        return data["id"]
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None
    finally:
        if manifest_fd is not None:
            os.close(manifest_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def module_catalog(sites=()):
    """Associate current workspace site IDs; registration does not imply readiness."""
    modules = deepcopy(_MODULES)
    by_id = {item["id"]: item for item in modules}
    for item in modules:
        item["documentation_url"] = REPOSITORY + "/tree/main/modules/" + item["id"]
        item["site_ids"] = []
    checked = {}
    for index, site in enumerate(sites):
        if index >= MAX_SITES:
            break
        if not isinstance(site, dict):
            continue
        identifier, project = site.get("id"), site.get("project_path")
        if (not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", identifier)
                or not isinstance(project, str)):
            continue
        if project not in checked:
            checked[project] = _installed_module(project)
        module_id = checked[project]
        if module_id is not None and identifier not in by_id[module_id]["site_ids"]:
            by_id[module_id]["site_ids"].append(identifier)
    return {"modules": list(modules)}
