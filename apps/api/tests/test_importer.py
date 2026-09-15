from pathlib import Path
import subprocess

import pytest

from control_center.importer import scan_local_repository


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_scan_local_repository_finds_human_readable_product_context(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    (tmp_path / "PRD.md").write_text(
        "# Small Product\n\n這個產品幫助團隊知道現在卡在哪裡，以及下一個需要誰回答的問題。\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text("# Rules\n\nDo not invent progress.\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='small'\n", encoding="utf-8")

    preview = scan_local_repository(str(tmp_path))

    assert preview.understanding.name == "Small Product"
    assert "知道現在卡在哪裡" in preview.understanding.plain_language_purpose
    assert preview.facts.languages == ["Python"]
    assert {document.kind for document in preview.documents} == {"product", "agent_rules"}
    assert any("Roadmap" in item for item in preview.understanding.missing_information)


def test_scan_prefers_author_designated_one_sentence_summary(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    (tmp_path / "PRD.md").write_text(
        "# Product — PRD\n\n## 一句話\n\n**把混亂的工作變成大家看得懂的下一步。**\n\n"
        "## 背景\n\n這是一段很長而且不應該取代產品摘要的市場背景。\n",
        encoding="utf-8",
    )

    preview = scan_local_repository(str(tmp_path))

    assert preview.understanding.plain_language_purpose == "把混亂的工作變成大家看得懂的下一步。"


def test_scan_rejects_non_git_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="不是 Git repository"):
        scan_local_repository(str(tmp_path))
