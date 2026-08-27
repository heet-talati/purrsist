from purrsist import cli, exit_message, welcome_message


def test_initialization(capsys, monkeypatch):
    monkeypatch.setattr(cli.tracking, "current_streak_days", lambda: 0)
    welcome_message()
    captured = capsys.readouterr()
    assert "Purrsist - Keep at it, don't let Purr down! 😺" in captured.out
    assert "streak" not in captured.out


def test_welcome_message_shows_streak_badge(capsys, monkeypatch):
    monkeypatch.setattr(cli.tracking, "current_streak_days", lambda: 3)
    welcome_message()
    captured = capsys.readouterr()
    assert "3-day streak" in captured.out


def test_exit_message(capsys):
    exit_message()
    captured = capsys.readouterr()
    assert "Purrsist signing off🐾🐾 See you next time! 😺" in captured.out


def test_print_cli_default_padding(capsys):
    cli.print_cli("hello")
    captured = capsys.readouterr()
    assert captured.out == "  hello\n"


def test_print_cli_custom_padding(capsys):
    cli.print_cli("hello", padding=3)
    captured = capsys.readouterr()
    assert captured.out == "      hello\n"


def test_is_valid_option_is_unimplemented():
    assert cli.is_valid_option() is None


def test_query_input_command_only(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "help")
    command, options = cli.query_input()
    assert command == "help"
    assert options == []


def test_query_input_with_options(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "help  -verbose  -all ")
    command, options = cli.query_input()
    assert command == "help"
    assert options == ["-verbose", "-all"]


def test_query_input_empty(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "   ")
    command, options = cli.query_input()
    assert command == ""
    assert options == []


def test_options_handler_rejects_options(capsys):
    result = cli.options_handler(["-x"], "version")
    captured = capsys.readouterr()
    assert result is True
    assert "does not take any options" in captured.out


def test_options_handler_allows_no_options(capsys):
    result = cli.options_handler([], "version")
    captured = capsys.readouterr()
    assert result is None
    assert captured.out == ""


def test_options_handler_allows_none(capsys):
    result = cli.options_handler(None, "version")
    captured = capsys.readouterr()
    assert result is None
    assert captured.out == ""


def test_show_version(capsys):
    cli.show_version([])
    captured = capsys.readouterr()
    assert f"Purrsist version {cli.APP_VERSION}" in captured.out


def test_show_version_default_options(capsys):
    cli.show_version()
    captured = capsys.readouterr()
    assert f"Purrsist version {cli.APP_VERSION}" in captured.out


def test_show_version_rejects_options(capsys):
    cli.show_version(["-x"])
    captured = capsys.readouterr()
    assert "does not take any options" in captured.out
    assert "Purrsist version" not in captured.out


def test_show_help(capsys):
    cli.show_help([])
    captured = capsys.readouterr()
    for command in cli.COMMANDS:
        assert command in captured.out


def test_show_help_default_options(capsys):
    cli.show_help()
    captured = capsys.readouterr()
    assert "Available commands" in captured.out


def test_show_help_rejects_options(capsys):
    cli.show_help(["-x"])
    captured = capsys.readouterr()
    assert "does not take any options" in captured.out


def test_repl_exit_immediately(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "exit")
    cli.repl()
    captured = capsys.readouterr()
    assert "signing off" in captured.out


def test_repl_invalid_command_then_exit(monkeypatch, capsys):
    responses = iter(["nonsense", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    cli.repl()
    captured = capsys.readouterr()
    assert "Please enter a valid command" in captured.out
    assert "signing off" in captured.out


def test_repl_empty_input_then_exit(monkeypatch, capsys):
    responses = iter(["", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    cli.repl()
    captured = capsys.readouterr()
    assert "Please enter a valid command" in captured.out
    assert "signing off" in captured.out


def test_repl_dispatches_help_and_version(monkeypatch, capsys):
    responses = iter(["help", "version", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    cli.repl()
    captured = capsys.readouterr()
    assert "Available commands" in captured.out
    assert f"Purrsist version {cli.APP_VERSION}" in captured.out


def test_repl_handles_keyboard_interrupt(monkeypatch, capsys):
    def raise_interrupt(_):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", raise_interrupt)
    cli.repl()
    captured = capsys.readouterr()
    assert "signing off" in captured.out


def test_repl_handles_eof_error(monkeypatch, capsys):
    def raise_eof(_):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    cli.repl()
    captured = capsys.readouterr()
    assert "signing off" in captured.out


def test_repl_handles_eof_error_after_a_command(monkeypatch, capsys):
    responses = iter(["version"])

    def _next_input(_):
        try:
            return next(responses)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", _next_input)
    cli.repl()
    captured = capsys.readouterr()
    assert f"Purrsist version {cli.APP_VERSION}" in captured.out
    assert "signing off" in captured.out
