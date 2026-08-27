import signal

from purrsist import __main__ as main_module


def test_main_swallows_keyboard_interrupt_during_shutdown(monkeypatch, capsys):
    monkeypatch.setattr(main_module, "welcome_message", lambda: None)

    def _raise():
        raise KeyboardInterrupt

    monkeypatch.setattr(main_module, "repl", _raise)

    main_module.main()  # must not raise

    captured = capsys.readouterr()
    assert captured.out == "\n"


def test_main_ignores_sigint_after_keyboard_interrupt_shutdown(monkeypatch):
    monkeypatch.setattr(main_module, "welcome_message", lambda: None)
    monkeypatch.setattr(
        main_module,
        "repl",
        lambda: (_ for _ in ()).throw(KeyboardInterrupt),
    )
    calls = []
    monkeypatch.setattr(
        signal, "signal", lambda sig, handler: calls.append((sig, handler))
    )

    main_module.main()

    assert calls == [(signal.SIGINT, signal.SIG_IGN)]


def test_main_ignores_sigint_after_normal_shutdown(monkeypatch):
    monkeypatch.setattr(main_module, "welcome_message", lambda: None)
    monkeypatch.setattr(main_module, "repl", lambda: None)
    calls = []
    monkeypatch.setattr(
        signal, "signal", lambda sig, handler: calls.append((sig, handler))
    )

    main_module.main()

    assert calls == [(signal.SIGINT, signal.SIG_IGN)]
