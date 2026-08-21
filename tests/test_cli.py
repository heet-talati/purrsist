import pytest
from src.purrsist import welcome_message

def test_initialization(capsys):
  welcome_message()
  captured = capsys.readouterr()
  assert captured.out == """==================================================
  Purrsist - Keep at it, don't let the cat down! 
==================================================\n""" 