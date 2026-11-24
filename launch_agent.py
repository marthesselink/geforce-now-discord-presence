"""Install or remove the login service for the current macOS user."""

import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time


LABEL = "io.github.geforce-now-discord-presence"
AGENT = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
SCRIPT = Path(__file__).resolve().with_name("geforce-discord.py")
DOMAIN = f"gui/{os.getuid()}"
SERVICE = f"{DOMAIN}/{LABEL}"


def launchctl(*args, quiet=False):
    return subprocess.run(
        ["/bin/launchctl", *args],
        check=False,
        capture_output=quiet,
    ).returncode


def install():
    if not SCRIPT.is_file():
        raise SystemExit(f"Script not found: {SCRIPT}")
    if AGENT.exists() or launchctl("print", SERVICE, quiet=True) == 0:
        raise SystemExit("A login service already exists. Run uninstall before reinstalling it.")

    AGENT.parent.mkdir(parents=True, exist_ok=True)
    with AGENT.open("xb") as file:
        plistlib.dump({
            "Label": LABEL,
            "ProgramArguments": [sys.executable, "-B", str(SCRIPT)],
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": 10,
        }, file)
    if launchctl("bootstrap", DOMAIN, str(AGENT)):
        AGENT.unlink()
        raise SystemExit("Could not load the login service. Run this from your macOS desktop session.")
    print("Installed the login service for the current user.")


def uninstall():
    if launchctl("print", SERVICE, quiet=True) == 0:
        if launchctl("bootout", SERVICE):
            raise SystemExit("Could not stop the login service. Its configuration is still in place.")
        # launchd can take a moment to remove the job after bootout returns.
        for _ in range(20):
            if launchctl("print", SERVICE, quiet=True) != 0:
                break
            time.sleep(0.25)
        else:
            raise SystemExit("The login service is still unloading. Try uninstall again.")
    AGENT.unlink(missing_ok=True)
    print("Removed the login service for the current user.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall"))
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("This command requires macOS.")
    if os.geteuid() == 0:
        parser.error("Run this command as your desktop user without sudo.")
    if args.action == "install":
        install()
    else:
        uninstall()


if __name__ == "__main__":
    main()
