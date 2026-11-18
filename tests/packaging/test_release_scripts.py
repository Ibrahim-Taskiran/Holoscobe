"""Offline checks for the release/packaging files (no build, no network)."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_pyproject_version_parses():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^\s*version\s*=\s*"\d+\.\d+\.\d+[^"]*"', text, re.M)


def test_release_script_reads_same_version_pattern():
    script = (ROOT / "scripts" / "release.ps1").read_text(encoding="utf-8")
    assert "pyproject.toml" in script and "win64.zip" in script and ".sha256" in script


def test_spec_bundles_model_icon_and_verifies_hash():
    spec = (ROOT / "packaging" / "holoscobe.spec").read_text(encoding="utf-8")
    assert '"assets"' in spec  # whole assets folder (hand model) is bundled
    assert "sha256" in spec and "icon=" in spec
    manifest = json.loads((ROOT / "assets" / "model_manifest.json").read_text(encoding="utf-8"))
    assert manifest["models"][0]["local_path"].startswith("assets/")


def test_entrypoint_has_self_test():
    assert "--self-test" in (ROOT / "packaging" / "entrypoint.py").read_text(encoding="utf-8")


def test_uninstall_uses_startup_value_name():
    startup = (ROOT / "src" / "handcontrol" / "windows" / "startup.py").read_text(encoding="utf-8")
    name = re.search(r'^VALUE_NAME = "([^"]+)"', startup, re.M).group(1)
    key = re.search(r'^RUN_KEY = r"([^"]+)"', startup, re.M).group(1)
    un = (ROOT / "scripts" / "uninstall.ps1").read_text(encoding="utf-8")
    assert f"'{name}'" in un and key in un


def test_install_scripts_support_dry_run():
    for n in ("install.ps1", "uninstall.ps1"):
        assert "$DryRun" in (ROOT / "scripts" / n).read_text(encoding="utf-8")


def test_workflows_exist():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    rel = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "pytest" in ci and "--require-hashes" in ci and "offscreen" in ci
    assert "v*" in rel and "release.ps1" in rel
