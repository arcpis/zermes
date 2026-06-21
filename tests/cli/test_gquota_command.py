from unittest.mock import MagicMock, patch


def test_gquota_uses_chat_console_when_tui_is_live():
    from zermes.agent.google_oauth import GoogleOAuthError
    from zermes.cli import HermesCLI

    cli = HermesCLI.__new__(HermesCLI)
    cli.console = MagicMock()
    cli._app = object()

    live_console = MagicMock()

    with patch("zermes.cli.ChatConsole", return_value=live_console), \
         patch("zermes.agent.google_oauth.get_valid_access_token", side_effect=GoogleOAuthError("No Google OAuth credentials found")), \
         patch("zermes.agent.google_oauth.load_credentials", return_value=None), \
         patch("zermes.agent.google_code_assist.retrieve_user_quota"):
        cli._handle_gquota_command("/gquota")

    assert live_console.print.call_count == 2
    cli.console.print.assert_not_called()
