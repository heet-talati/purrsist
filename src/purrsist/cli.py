from importlib.metadata import version

# Global Variables
APP_VERSION = version("purrsist")
COMMANDS = {
    "exit": {"description": "Exit the program", "options": {}},
    "help": {"description": "List available commands", "options": {}},
    "version": {
        "description": "Show the current version of the program",
        "options": {},
    },
}


# Command Line Interface (CLI) Functions
def welcome_message():
    print(f"""{"=" * 50}
  Purrsist - Keep at it, don't let Purr down! 😺
{"=" * 50}""")


def exit_message():
    print(f"""{"=" * 50}
  Purrsist signing off🐾🐾 See you next time! 😺
{"=" * 50}""")


def query_input():
    query = input("purrsist > ").split()
    command = query[0].strip()
    options = []
    if len(query) > 1:
        options = query[1:]
        for i in range(len(options)):
            options[i] = options[i].strip()

    return command, options


def print_cli(str, padding=1):
    print("  " * padding + str)


# All space seperated options are currently valid, this function will validate options in future
def is_valid_option():
    pass


def options_handler(options, command):
    # Reject any options passed to the command for now
    if len(options) > 0:
        print_cli(
            f"[error] The '{command}' command does not take any options. Please try again."
        )
        return True


# Command Handlers
def show_version(options=None):
    if options_handler(options, "version"):
        return
    print_cli(f"✓ Purrsist version {APP_VERSION}")


def show_help(options=None):
    if options_handler(options, "help"):
        return
    print_cli("Available commands:")
    for command, info in COMMANDS.items():
        description = info["description"]
        options = info["options"]

        print_cli(f"  - {command}: {description}")
        if options:
            for option in options:
                print_cli(f"-{option}", 3)


# Main REPL Loop
def repl():
    command, options = query_input()

    while command != "exit":
        match command:
            case "help":
                show_help(options)
            case "version":
                show_version(options)
            case _:
                print_cli(
                    "[error] Please enter a valid command! Use 'help' to see the list of available commands."
                )
        command, options = query_input()

    exit_message()
