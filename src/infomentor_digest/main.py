import argparse
import json
import sys
from pathlib import Path

from .config import ENV_FILE, Settings
from .discover import discover
from .notify import send
from .run import outcome, run
from .schedule import now, serve
from .setup import setup
from .state import Store


def main() -> int:
    parser = argparse.ArgumentParser(prog="infomentor-digest")
    parser.add_argument(
        "command",
        choices=("run", "schedule", "setup", "discover", "test-notify", "forget"),
        help="run: report what is new, once. "
        "schedule: report at once, then at every RUN_AT time. "
        "setup: ask for what the digest needs and write .env. "
        "discover: log in and record what the account reaches. "
        "test-notify: send a test message. "
        "forget: drop the reported facts, so the next run starts over.",
    )
    parser.add_argument("--out", type=Path, default=Path("discovery"))
    parser.add_argument(
        "--force", action="store_true", help="report every fact, even a reported one"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the digest instead of sending it"
    )
    args = parser.parse_args()

    try:
        return dispatch(args)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1


def dispatch(args: argparse.Namespace) -> int:
    """Run one command. A setting the digest cannot work with raises `RuntimeError`."""
    if args.command == "setup":
        setup(ENV_FILE)
        return 0

    settings = Settings()  # type: ignore[call-arg]

    if args.command == "discover":
        report = discover(settings, args.out)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    if args.command == "forget":
        dropped = Store.load(settings.state_file).forget()
        print(f"forgot {dropped} facts. The next run seeds and sends nothing.")
        return 0

    if args.command == "test-notify":
        send(settings, "InfoMentor digest", "Delivery works.")
        print("sent")
        return 0

    if args.command == "schedule":
        serve(settings)
        return 0

    print(outcome(run(settings, now().date(), force=args.force, dry_run=args.dry_run)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
