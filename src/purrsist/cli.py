from importlib.metadata import version

from commands import goals, tracking

from .output import print_cli

# Global Variables
APP_VERSION = version("purrsist")


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
    if not query:
        return "", []

    command = query[0].strip()
    options = []
    if len(query) > 1:
        options = query[1:]
        for i in range(len(options)):
            options[i] = options[i].strip()

    return command, options


# All space seperated options are currently valid, this function will validate options in future
def is_valid_option():
    pass


def options_handler(options, command):
    # Reject any options passed to the command for now
    if options:
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


# Command Registry
# Maps a command name to its help text and its handler. `exit` has no handler
# here because repl() breaks out of the loop for it before dispatching.
COMMANDS = {
    "exit": {"description": "Exit the program", "options": {}, "handler": None},
    "help": {
        "description": "List available commands",
        "options": {},
        "handler": show_help,
    },
    "version": {
        "description": "Show the current version of the program",
        "options": {},
        "handler": show_version,
    },
    "goal": {
        "description": "Manage your goals",
        "options": {},
        "handler": goals.handle,
    },
    "track": {
        "description": "Track time against a goal with a timer",
        "options": {},
        "handler": tracking.handle,
    },
}


# Main REPL Loop
def repl():
    while True:
        try:
            command, options = query_input()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if command == "exit":
            break

        entry = COMMANDS.get(command)
        if entry and entry["handler"]:
            entry["handler"](options)
        else:
            print_cli(
                "[error] Please enter a valid command! Use 'help' to see the list of available commands."
            )

    exit_message()
