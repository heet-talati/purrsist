from .cli import repl, welcome_message


def main():
    welcome_message()
    repl()


if __name__ == "__main__":
    main()
