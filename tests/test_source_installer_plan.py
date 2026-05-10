from __future__ import annotations

from pathlib import Path

from scripts import install_zermes


def test_default_prefix_by_platform():
    home = Path("/home/example")

    assert install_zermes.default_prefix(platform="linux", home=home) == (
        home / ".local" / "share" / "zermes"
    )
    assert install_zermes.default_prefix(platform="darwin", home=home) == (
        home / "Applications" / "Zermes"
    )
    assert install_zermes.default_prefix(platform="win32", home=home) == (
        home / "AppData" / "Local" / "Zermes"
    )


def test_default_data_dir_uses_hermes_home_compatibility():
    home = Path("/home/example")

    assert install_zermes.default_data_dir(home=home) == home / ".hermes"


def test_plan_computes_runtime_release_paths(tmp_path):
    prefix = tmp_path / "app"
    data_dir = tmp_path / "data"
    parser = install_zermes.build_parser()
    args = parser.parse_args(
        [
            "--dry-run",
            "--non-interactive",
            "--prefix",
            str(prefix),
            "--data-dir",
            str(data_dir),
            "--release-id",
            "source-install",
        ]
    )

    plan = install_zermes.build_plan(args, repo_root=tmp_path / "repo")

    assert Path(plan.runtime_dir) == (prefix / "runtime").resolve()
    assert Path(plan.release_dir) == (
        prefix / "runtime" / "releases" / "source-install"
    ).resolve()
    assert Path(plan.source_dir) == (
        prefix / "runtime" / "releases" / "source-install" / "source"
    ).resolve()
    assert Path(plan.venv_dir) == (
        prefix / "runtime" / "releases" / "source-install" / "venv"
    ).resolve()
    assert Path(plan.build_dir) == (
        prefix / "runtime" / "releases" / "source-install" / "build"
    ).resolve()
    assert Path(plan.bin_dir) == (prefix / "bin").resolve()
    assert Path(plan.active_path) == (prefix / "runtime" / "active.json").resolve()
    assert Path(plan.previous_path) == (prefix / "runtime" / "previous.json").resolve()
