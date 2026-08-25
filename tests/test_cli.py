# import pytest
from src.purrsist import exit_message, welcome_message


def test_initialization(capsys):
    welcome_message()
    captured = capsys.readouterr()
    assert (
        captured.out
        == """==================================================
  Purrsist - Keep at it, don't let Purr down! 😺
==================================================\n"""
    )


def test_exit_message(capsys):
    exit_message()
    captured = capsys.readouterr()
    assert (
        captured.out
        == """==================================================
  Purrsist signing off🐾🐾 See you next time! 😺
==================================================\n"""
    )


def test_repl(capsys):
    pass
