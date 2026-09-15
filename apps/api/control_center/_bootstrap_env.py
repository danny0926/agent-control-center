"""Load the project-root .env into os.environ at import time.

無第三方相依。目的：不論本服務被誰、用什麼方式重啟（即使完全沒帶
環境變數），只要專案根目錄有 .env，帳密等設定就會被自動補上，
以維持固定的遠端存取帳密（見專案 AGENTS.md「遠端存取」一節）。

已在環境裡的變數優先，不會被 .env 覆寫——顯式帶入的值仍然贏。
"""
from __future__ import annotations

import os
from pathlib import Path

# apps/api/control_center/_bootstrap_env.py → 專案根是往上第 3 層。
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or (_PROJECT_ROOT / ".env")
    try:
        text = env_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()
