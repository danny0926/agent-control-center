from __future__ import annotations

import json
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import (
    Confidence,
    DiscoveredDocument,
    ImportPreview,
    ProductUnderstanding,
    RepositoryFacts,
    normalized_path,
)
from .plan_parser import parse_product_plan


DOCUMENT_CANDIDATES = (
    ("product", "PRD.md", "產品需求"),
    ("overview", "README.md", "專案說明"),
    ("agent_rules", "AGENTS.md", "Agent 工作規則"),
    ("agent_rules", "CLAUDE.md", "Claude 工作規則"),
    ("roadmap", "ROADMAP.md", "產品路線圖"),
    ("roadmap", "docs/PRODUCT_COMPLETION_PLAN.md", "產品完成計畫"),
    ("contract", "web/API_CONTRACT.md", "API 契約"),
)


def _run_git(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def _read_text(path: Path, limit: int = 160_000) -> str:
    raw = path.read_bytes()[:limit]
    for encoding in ("utf-8-sig", "utf-8", "cp950"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _first_meaningful_paragraph(text: str) -> str | None:
    clean_lines: list[str] = []
    in_code = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line or line.startswith(("#", "-", "*", ">", "|", "[")):
            continue
        line = re.sub(r"[`*_]", "", line)
        if len(line) >= 18:
            clean_lines.append(line)
        if sum(map(len, clean_lines)) >= 240:
            break
    if not clean_lines:
        return None
    return " ".join(clean_lines)[:360]


def _purpose_from_named_section(text: str) -> str | None:
    """Prefer an author-designated short summary without assuming a project domain."""
    heading = re.search(
        r"^#{1,3}\s+(?:一句話|產品摘要|專案摘要|目的|願景|product summary|overview|purpose|vision)\s*$",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not heading:
        return None
    section = text[heading.end():]
    lines: list[str] = []
    started = False
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if line.startswith("#"):
            break
        if not line or line == "---":
            if started:
                break
            continue
        if line.startswith(("|", "```")):
            continue
        clean = re.sub(r"[*_`>]", "", line).strip()
        if clean:
            lines.append(clean)
            started = True
        if sum(map(len, lines)) >= 240:
            break
    return " ".join(lines)[:360] if lines else None


def _title(text: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return match.group(1).strip()[:120] if match else fallback


def _detect_languages(root: Path) -> list[str]:
    markers = {
        "Python": ("pyproject.toml", "requirements.txt", "setup.py"),
        "TypeScript / JavaScript": ("package.json", "tsconfig.json"),
        "Rust": ("Cargo.toml",),
        "Go": ("go.mod",),
        "Ruby": ("Gemfile",),
    }
    return [name for name, files in markers.items() if any((root / file).exists() for file in files)]


def _detect_test_commands(root: Path) -> list[str]:
    commands: list[str] = []
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists():
        commands.append("python -m pytest")
    package_json = root / "package.json"
    if package_json.exists():
        try:
            scripts = json.loads(_read_text(package_json)).get("scripts", {})
        except (json.JSONDecodeError, AttributeError):
            scripts = {}
        if "test" in scripts:
            commands.append("npm test")
        if "build" in scripts:
            commands.append("npm run build")
    if (root / "Cargo.toml").exists():
        commands.append("cargo test")
    if (root / "go.mod").exists():
        commands.append("go test ./...")
    return commands


def scan_local_repository(raw_path: str) -> ImportPreview:
    root = normalized_path(raw_path)
    if not root.is_dir():
        raise ValueError("選擇的路徑不是資料夾。")
    if not (root / ".git").exists() and _run_git(root, "rev-parse", "--show-toplevel") is None:
        raise ValueError("這個資料夾不是 Git repository。第一版只支援匯入 Git 專案。")

    documents: list[DiscoveredDocument] = []
    text_by_path: dict[str, str] = {}
    for kind, relative, explanation in DOCUMENT_CANDIDATES:
        path = root / relative
        if not path.is_file():
            continue
        text = _read_text(path)
        text_by_path[relative] = text
        documents.append(
            DiscoveredDocument(
                kind=kind,
                path=relative.replace("\\", "/"),
                title=_title(text, path.stem),
                explanation=explanation,
            )
        )

    primary_path = next((item for item in ("PRD.md", "README.md") if item in text_by_path), None)
    primary_text = text_by_path.get(primary_path or "", "")
    purpose = _purpose_from_named_section(primary_text) or _first_meaningful_paragraph(primary_text)
    project_name = _title(primary_text, root.name) if primary_text else root.name

    missing: list[str] = []
    if "PRD.md" not in text_by_path:
        missing.append("找不到 PRD；產品目的目前主要從 README 推測。")
    if not any(doc.kind == "roadmap" for doc in documents):
        missing.append("找不到明確的 Roadmap 或產品完成計畫。")
    if not any(doc.kind == "agent_rules" for doc in documents):
        missing.append("找不到 AGENTS.md 或 CLAUDE.md；Agent 工作邊界尚不明確。")
    if not purpose:
        purpose = "尚未從現有文件可靠辨識產品目的，匯入前需要人工補上一句說明。"

    confidence = Confidence.HIGH if primary_path == "PRD.md" else Confidence.MEDIUM
    if not documents:
        confidence = Confidence.LOW

    facts = RepositoryFacts(
        root_path=str(root),
        repository_name=root.name,
        current_branch=_run_git(root, "branch", "--show-current"),
        remote_url=_run_git(root, "remote", "get-url", "origin"),
        languages=_detect_languages(root),
        test_commands=_detect_test_commands(root),
    )
    warnings = ["匯入預覽只讀取已知的專案說明與設定檔，不會修改來源 repository。"]
    if facts.remote_url is None:
        warnings.append("沒有找到 origin remote；仍可作為純本機專案管理。")

    roadmap_path = next((doc.path for doc in documents if doc.kind == "roadmap"), None)
    proposed_plan = (
        parse_product_plan(text_by_path[roadmap_path], roadmap_path, purpose)
        if roadmap_path and roadmap_path in text_by_path
        else []
    )

    return ImportPreview(
        preview_id=str(uuid.uuid4()),
        facts=facts,
        understanding=ProductUnderstanding(
            name=project_name,
            plain_language_purpose=purpose,
            confidence=confidence,
            evidence_paths=[doc.path for doc in documents if doc.kind in {"product", "overview"}],
            missing_information=missing,
            conflicts=[],
        ),
        documents=documents,
        proposed_plan=proposed_plan,
        warnings=warnings,
        scanned_at=datetime.now(timezone.utc),
    )
