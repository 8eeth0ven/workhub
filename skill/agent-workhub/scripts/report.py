#!/usr/bin/env python3
"""Stable skill-local entry point to the shared Workhub CLI."""

import os
from pathlib import Path
import sys


def main() -> None:
    backend = Path(__file__).resolve().parents[3] / "workhub.py"
    if not backend.is_file():
        print(f"未找到工作台后端，请重新安装或恢复技能所属仓库：{backend}", file=sys.stderr)
        raise SystemExit(1)
    os.execv(sys.executable, [sys.executable, str(backend), *sys.argv[1:]])


if __name__ == "__main__":
    main()
