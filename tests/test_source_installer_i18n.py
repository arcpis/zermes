from __future__ import annotations

import argparse

import pytest

from scripts import install_zermes


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "zh-CN"),
        ("", "zh-CN"),
        ("1", "zh-CN"),
        ("2", "en-US"),
        ("zh-CN", "zh-CN"),
        ("en-US", "en-US"),
    ],
)
def test_normalize_language(raw, expected):
    assert install_zermes.normalize_language(raw) == expected


def test_normalize_language_rejects_unknown():
    with pytest.raises(ValueError, match="unsupported language"):
        install_zermes.normalize_language("fr-FR")


def test_prompt_language_uses_default_on_enter():
    assert install_zermes.prompt_language(lambda _prompt: "") == "zh-CN"


def test_prompt_language_accepts_english_choice():
    assert install_zermes.prompt_language(lambda _prompt: "2") == "en-US"


def test_parser_rejects_unknown_language_choice():
    parser = install_zermes.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--language", "fr-FR"])


def test_build_plan_defaults_language_for_non_interactive(tmp_path):
    args = argparse.Namespace(
        prefix=tmp_path / "app",
        data_dir=tmp_path / "data",
        release_id="source-install",
        language=None,
        dry_run=True,
    )

    plan = install_zermes.build_plan(args, repo_root=tmp_path / "repo")

    assert plan.language == "zh-CN"
