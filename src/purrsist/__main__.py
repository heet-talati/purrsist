import signal

from .cli import repl, welcome_message


def main():
    welcome_message()
    try:
        repl()
    except KeyboardInterrupt:
        # A second Ctrl+C can land anywhere, including mid-shutdown (e.g.
        # during exit_message()'s print, after repl() already broke out of
        # its loop) -- swallow it instead of crashing with a raw traceback.
        print()
    finally:
        # A rapid double Ctrl+C can deliver its second SIGINT after we've
        # already returned here, while Python is unwinding back through its
        # own runpy bootstrap -- no try/except of ours can catch a
        # KeyboardInterrupt raised in a frame that isn't on our call stack
        # anymore. Ignoring SIGINT once we've committed to shutting down
        # stops that straggler from being raised as an exception at all.
        signal.signal(signal.SIGINT, signal.SIG_IGN)


if __name__ == "__main__":
    main()
