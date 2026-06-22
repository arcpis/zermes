"""Tests for hermes_cli/skills_config.py and skills_tool disabled filtering."""
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# get_disabled_skills
# ---------------------------------------------------------------------------

class TestGetDisabledSkills:
    def test_empty_config(self):
        from zermes.hermes_cli.skills_config import get_disabled_skills
        assert get_disabled_skills({}) == set()

    def test_reads_global_disabled(self):
        from zermes.hermes_cli.skills_config import get_disabled_skills
        config = {"skills": {"disabled": ["skill-a", "skill-b"]}}
        assert get_disabled_skills(config) == {"skill-a", "skill-b"}

    def test_reads_platform_disabled(self):
        from zermes.hermes_cli.skills_config import get_disabled_skills
        config = {"skills": {
            "disabled": ["skill-a"],
            "platform_disabled": {"telegram": ["skill-b"]}
        }}
        assert get_disabled_skills(config, platform="telegram") == {"skill-b"}

    def test_platform_falls_back_to_global(self):
        from zermes.hermes_cli.skills_config import get_disabled_skills
        config = {"skills": {"disabled": ["skill-a"]}}
        # no platform_disabled for cli -> falls back to global
        assert get_disabled_skills(config, platform="cli") == {"skill-a"}

    def test_missing_skills_key(self):
        from zermes.hermes_cli.skills_config import get_disabled_skills
        assert get_disabled_skills({"other": "value"}) == set()

    def test_empty_disabled_list(self):
        from zermes.hermes_cli.skills_config import get_disabled_skills
        assert get_disabled_skills({"skills": {"disabled": []}}) == set()


# ---------------------------------------------------------------------------
# save_disabled_skills
# ---------------------------------------------------------------------------

class TestSaveDisabledSkills:
    @patch("zermes.hermes_cli.skills_config.save_config")
    def test_saves_global_sorted(self, mock_save):
        from zermes.hermes_cli.skills_config import save_disabled_skills
        config = {}
        save_disabled_skills(config, {"skill-z", "skill-a"})
        assert config["skills"]["disabled"] == ["skill-a", "skill-z"]
        mock_save.assert_called_once()

    @patch("zermes.hermes_cli.skills_config.save_config")
    def test_saves_platform_disabled(self, mock_save):
        from zermes.hermes_cli.skills_config import save_disabled_skills
        config = {}
        save_disabled_skills(config, {"skill-x"}, platform="telegram")
        assert config["skills"]["platform_disabled"]["telegram"] == ["skill-x"]

    @patch("zermes.hermes_cli.skills_config.save_config")
    def test_saves_empty(self, mock_save):
        from zermes.hermes_cli.skills_config import save_disabled_skills
        config = {"skills": {"disabled": ["skill-a"]}}
        save_disabled_skills(config, set())
        assert config["skills"]["disabled"] == []

    @patch("zermes.hermes_cli.skills_config.save_config")
    def test_creates_skills_key(self, mock_save):
        from zermes.hermes_cli.skills_config import save_disabled_skills
        config = {}
        save_disabled_skills(config, {"skill-x"})
        assert "skills" in config
        assert "disabled" in config["skills"]


# ---------------------------------------------------------------------------
# _is_skill_disabled
# ---------------------------------------------------------------------------

class TestIsSkillDisabled:
    @patch("zermes.hermes_cli.config.load_config")
    def test_globally_disabled(self, mock_load):
        mock_load.return_value = {"skills": {"disabled": ["bad-skill"]}}
        from zermes.tools.skills_tool import _is_skill_disabled
        assert _is_skill_disabled("bad-skill") is True

    @patch("zermes.hermes_cli.config.load_config")
    def test_globally_enabled(self, mock_load):
        mock_load.return_value = {"skills": {"disabled": ["other"]}}
        from zermes.tools.skills_tool import _is_skill_disabled
        assert _is_skill_disabled("good-skill") is False

    @patch("zermes.hermes_cli.config.load_config")
    def test_platform_disabled(self, mock_load):
        mock_load.return_value = {"skills": {
            "disabled": [],
            "platform_disabled": {"telegram": ["tg-skill"]}
        }}
        from zermes.tools.skills_tool import _is_skill_disabled
        assert _is_skill_disabled("tg-skill", platform="telegram") is True

    @patch("zermes.hermes_cli.config.load_config")
    def test_platform_enabled_overrides_global(self, mock_load):
        mock_load.return_value = {"skills": {
            "disabled": ["skill-a"],
            "platform_disabled": {"telegram": []}
        }}
        from zermes.tools.skills_tool import _is_skill_disabled
        # telegram has explicit empty list -> skill-a is NOT disabled for telegram
        assert _is_skill_disabled("skill-a", platform="telegram") is False

    @patch("zermes.hermes_cli.config.load_config")
    def test_platform_falls_back_to_global(self, mock_load):
        mock_load.return_value = {"skills": {"disabled": ["skill-a"]}}
        from zermes.tools.skills_tool import _is_skill_disabled
        # no platform_disabled for cli -> global
        assert _is_skill_disabled("skill-a", platform="cli") is True

    @patch("zermes.hermes_cli.config.load_config")
    def test_empty_config(self, mock_load):
        mock_load.return_value = {}
        from zermes.tools.skills_tool import _is_skill_disabled
        assert _is_skill_disabled("any-skill") is False

    @patch("zermes.hermes_cli.config.load_config")
    def test_exception_returns_false(self, mock_load):
        mock_load.side_effect = Exception("config error")
        from zermes.tools.skills_tool import _is_skill_disabled
        assert _is_skill_disabled("any-skill") is False

    @patch("zermes.hermes_cli.config.load_config")
    @patch.dict("os.environ", {"HERMES_PLATFORM": "discord"})
    def test_env_var_platform(self, mock_load):
        mock_load.return_value = {"skills": {
            "platform_disabled": {"discord": ["discord-skill"]}
        }}
        from zermes.tools.skills_tool import _is_skill_disabled
        assert _is_skill_disabled("discord-skill") is True


# ---------------------------------------------------------------------------
# get_disabled_skill_names — explicit platform param & env var fallback
# ---------------------------------------------------------------------------

class TestGetDisabledSkillNames:
    """Tests for zermes.agent.skill_utils.get_disabled_skill_names."""

    def test_explicit_platform_param(self, tmp_path, monkeypatch):
        """Explicit platform= parameter should resolve per-platform list."""
        config = tmp_path / "config.yaml"
        config.write_text(
            "skills:\n"
            "  disabled:\n"
            "    - global-skill\n"
            "  platform_disabled:\n"
            "    telegram:\n"
            "      - tg-only-skill\n"
        )
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.delenv("HERMES_PLATFORM", raising=False)
        monkeypatch.delenv("HERMES_SESSION_PLATFORM", raising=False)

        from zermes.agent.skill_utils import get_disabled_skill_names
        result = get_disabled_skill_names(platform="telegram")
        assert result == {"tg-only-skill"}

    def test_session_platform_env_var(self, tmp_path, monkeypatch):
        """HERMES_SESSION_PLATFORM should be used when HERMES_PLATFORM is unset."""
        config = tmp_path / "config.yaml"
        config.write_text(
            "skills:\n"
            "  disabled:\n"
            "    - global-skill\n"
            "  platform_disabled:\n"
            "    discord:\n"
            "      - discord-skill\n"
        )
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.delenv("HERMES_PLATFORM", raising=False)
        monkeypatch.setenv("HERMES_SESSION_PLATFORM", "discord")

        from zermes.agent.skill_utils import get_disabled_skill_names
        result = get_disabled_skill_names()
        assert result == {"discord-skill"}

    def test_hermes_platform_takes_precedence(self, tmp_path, monkeypatch):
        """HERMES_PLATFORM should win over HERMES_SESSION_PLATFORM."""
        config = tmp_path / "config.yaml"
        config.write_text(
            "skills:\n"
            "  platform_disabled:\n"
            "    telegram:\n"
            "      - tg-skill\n"
            "    discord:\n"
            "      - discord-skill\n"
        )
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setenv("HERMES_PLATFORM", "telegram")
        monkeypatch.setenv("HERMES_SESSION_PLATFORM", "discord")

        from zermes.agent.skill_utils import get_disabled_skill_names
        result = get_disabled_skill_names()
        assert result == {"tg-skill"}

    def test_explicit_param_overrides_env_vars(self, tmp_path, monkeypatch):
        """Explicit platform= param should override all env vars."""
        config = tmp_path / "config.yaml"
        config.write_text(
            "skills:\n"
            "  platform_disabled:\n"
            "    telegram:\n"
            "      - tg-skill\n"
            "    slack:\n"
            "      - slack-skill\n"
        )
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setenv("HERMES_PLATFORM", "telegram")
        monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")

        from zermes.agent.skill_utils import get_disabled_skill_names
        result = get_disabled_skill_names(platform="slack")
        assert result == {"slack-skill"}

    def test_no_platform_returns_global(self, tmp_path, monkeypatch):
        """No platform env vars or param should return global list."""
        config = tmp_path / "config.yaml"
        config.write_text(
            "skills:\n"
            "  disabled:\n"
            "    - global-skill\n"
            "  platform_disabled:\n"
            "    telegram:\n"
            "      - tg-skill\n"
        )
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.delenv("HERMES_PLATFORM", raising=False)
        monkeypatch.delenv("HERMES_SESSION_PLATFORM", raising=False)

        from zermes.agent.skill_utils import get_disabled_skill_names
        result = get_disabled_skill_names()
        assert result == {"global-skill"}


# ---------------------------------------------------------------------------
# _find_all_skills — disabled filtering
# ---------------------------------------------------------------------------

class TestFindAllSkillsFiltering:
    @patch("zermes.tools.skills_tool._get_disabled_skill_names", return_value={"my-skill"})
    @patch("zermes.tools.skills_tool.skill_matches_platform", return_value=True)
    def test_disabled_skill_excluded(self, mock_platform, mock_disabled, tmp_path, monkeypatch):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("---\nname: my-skill\ndescription: A test skill\n---\nContent")
        # Point SKILLS_DIR at the real tempdir so iter_skill_index_files
        # (which uses os.walk) can actually find the file.
        import zermes.tools.skills_tool as _st
        import zermes.agent.skill_utils as _su
        monkeypatch.setattr(_st, "SKILLS_DIR", tmp_path)
        monkeypatch.setattr(_su, "get_external_skills_dirs", lambda: [])
        from zermes.tools.skills_tool import _find_all_skills
        skills = _find_all_skills()
        assert not any(s["name"] == "my-skill" for s in skills)

    @patch("zermes.tools.skills_tool._get_disabled_skill_names", return_value=set())
    @patch("zermes.tools.skills_tool.skill_matches_platform", return_value=True)
    def test_enabled_skill_included(self, mock_platform, mock_disabled, tmp_path, monkeypatch):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("---\nname: my-skill\ndescription: A test skill\n---\nContent")
        import zermes.tools.skills_tool as _st
        import zermes.agent.skill_utils as _su
        monkeypatch.setattr(_st, "SKILLS_DIR", tmp_path)
        monkeypatch.setattr(_su, "get_external_skills_dirs", lambda: [])
        from zermes.tools.skills_tool import _find_all_skills
        skills = _find_all_skills()
        assert any(s["name"] == "my-skill" for s in skills)

    @patch("zermes.tools.skills_tool._get_disabled_skill_names", return_value={"my-skill"})
    @patch("zermes.tools.skills_tool.skill_matches_platform", return_value=True)
    def test_skip_disabled_returns_all(self, mock_platform, mock_disabled, tmp_path, monkeypatch):
        """skip_disabled=True ignores the disabled set (for config UI)."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("---\nname: my-skill\ndescription: A test skill\n---\nContent")
        import zermes.tools.skills_tool as _st
        import zermes.agent.skill_utils as _su
        monkeypatch.setattr(_st, "SKILLS_DIR", tmp_path)
        monkeypatch.setattr(_su, "get_external_skills_dirs", lambda: [])
        from zermes.tools.skills_tool import _find_all_skills
        skills = _find_all_skills(skip_disabled=True)
        assert any(s["name"] == "my-skill" for s in skills)


# ---------------------------------------------------------------------------
# _get_categories
# ---------------------------------------------------------------------------

class TestGetCategories:
    def test_extracts_unique_categories(self):
        from zermes.hermes_cli.skills_config import _get_categories
        skills = [
            {"name": "a", "category": "mlops", "description": ""},
            {"name": "b", "category": "coding", "description": ""},
            {"name": "c", "category": "mlops", "description": ""},
        ]
        cats = _get_categories(skills)
        assert cats == ["coding", "mlops"]

    def test_none_becomes_uncategorized(self):
        from zermes.hermes_cli.skills_config import _get_categories
        skills = [{"name": "a", "category": None, "description": ""}]
        assert "uncategorized" in _get_categories(skills)
