from pathlib import Path
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_faster_whisper_is_not_a_base_dependency():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]

    assert not any(dep.startswith("faster-whisper") for dep in deps)

    voice_extra = data["project"]["optional-dependencies"]["voice"]
    assert any(dep.startswith("faster-whisper") for dep in voice_extra)


def test_zermes_package_metadata_keeps_hermes_compatibility_entrypoints():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["project"]["name"] == "zermes-agent"
    scripts = data["project"]["scripts"]
    assert scripts["zermes"] == "hermes_cli.main:main"
    assert scripts["zermes-agent"] == "run_agent:main"
    assert scripts["hermes"] == "hermes_cli.main:main"
    assert scripts["hermes-agent"] == "run_agent:main"


def test_optional_dependency_self_references_use_zermes_package_name():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    optional_deps = data["project"]["optional-dependencies"]

    assert any(dep.startswith("zermes-agent[") for dep in optional_deps["all"])
    assert not any(
        dep.startswith("hermes-agent[")
        for deps in optional_deps.values()
        for dep in deps
    )


def test_manifest_includes_bundled_skills():
    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "graft skills" in manifest
    assert "graft optional-skills" in manifest
