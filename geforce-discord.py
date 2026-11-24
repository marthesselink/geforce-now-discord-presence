#!/usr/bin/env python3
"""Show supported GeForce NOW streams as games in the local Discord client."""

import contextlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid


LOG = Path.home() / "Library/Application Support/NVIDIA/GeForceNOW/console.log"
CATALOG = Path.home() / "Library/Application Support/GeForce Discord Presence/games.tsv"
CATALOG_URL = "https://discord.com/api/v10/games/detectable"
CATALOG_MAX_AGE = 7 * 24 * 60 * 60
CATALOG_MISS_MAX_AGE = 60 * 60
HEADER = struct.Struct("<II")
APP_NAME = re.compile(r'^\s*"appName"\s*:\s*("(?:[^"\\]|\\.)*")')
STREAM_LAUNCH = "streamingService  sessionStartResumeResult in launchStreaming:"
FIRST_FRAME = "streamingService  onStreamingFirstFrame"
STOP_EVENTS = ("calling stopstreaming internal", "gfnStreamingExit")
POLL_SECONDS = 2


def game_key(title):
    title = unicodedata.normalize("NFKC", title.replace("®", "").replace("™", ""))
    return "".join(character for character in title.casefold() if character.isalnum())


def refresh_catalog():
    # The worker exits after writing the index, freeing memory used by the full response.
    import gzip
    import urllib.request

    request = urllib.request.Request(CATALOG_URL, headers={
        "Accept-Encoding": "gzip",
        "User-Agent": "GeForceNOWDiscordPresence/1.0",
    })
    with urllib.request.urlopen(request, timeout=10) as response:
        source = response
        if response.headers.get("Content-Encoding") == "gzip":
            source = gzip.GzipFile(fileobj=response)
        entries = json.load(source)

    games = index_games(entries)
    if not games:
        raise ValueError("Discord returned an empty games catalog")

    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    index = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=CATALOG.parent, delete=False
    )
    temporary = Path(index.name)
    try:
        with index:
            for key, app_id in games.items():
                index.write(f"{key}\t{app_id}\n")
        temporary.replace(CATALOG)
    finally:
        temporary.unlink(missing_ok=True)
    return len(games)


def index_games(entries):
    names, aliases = {}, {}

    def add(index, title, app_id):
        key = game_key(title)
        if key:
            index[key] = app_id if index.get(key, app_id) == app_id else None

    for entry in entries:
        app_id = entry["id"]
        if app_id.isascii() and app_id.isdecimal():
            add(names, entry["name"], app_id)
            for alias in entry.get("aliases", ()):
                add(aliases, alias, app_id)
    # Prefer official names to aliases. Leave ambiguous matches out.
    return {key: app_id for key, app_id in (aliases | names).items() if app_id}


def find_game_id(title):
    key = game_key(title)
    with contextlib.suppress(OSError):
        with CATALOG.open(encoding="utf-8") as index:
            for line in index:
                name, _, app_id = line.rstrip("\n").partition("\t")
                if name == key:
                    return app_id
    return None


def catalog_is_stale(max_age):
    try:
        return time.time() - CATALOG.stat().st_mtime >= max_age
    except OSError:
        return True


class Presence:
    def __init__(self, app_id):
        self.socket = self.connect()
        self.reader = self.socket.makefile("rb")
        try:
            self.send(0, {"v": 1, "client_id": app_id})
            if self.receive().get("evt") != "READY":
                raise ValueError("Discord handshake failed")
        except BaseException:
            self.close()
            raise

    @staticmethod
    def connect():
        directories = dict.fromkeys((tempfile.gettempdir(), "/tmp"))
        for directory in directories:
            for slot in range(10):
                path = Path(directory) / f"discord-ipc-{slot}"
                if not path.is_socket():
                    continue
                with contextlib.ExitStack() as cleanup:
                    connection = cleanup.enter_context(socket.socket(socket.AF_UNIX))
                    connection.settimeout(2)
                    try:
                        connection.connect(str(path))
                    except OSError:
                        continue
                    cleanup.pop_all()
                    return connection
        raise ConnectionError("No Discord IPC socket found")

    def send(self, opcode, message):
        data = json.dumps(message).encode()
        self.socket.sendall(HEADER.pack(opcode, len(data)) + data)

    def receive(self):
        while True:
            header = self.reader.read(HEADER.size)
            if len(header) != HEADER.size:
                raise ConnectionError("Discord closed the IPC socket")
            opcode, size = HEADER.unpack(header)
            if size > 1024 * 1024:
                raise ValueError("Discord IPC reply is too large")
            data = self.reader.read(size)
            if len(data) != size:
                raise ConnectionError("Discord sent an incomplete IPC reply")
            if opcode == 3:
                self.socket.sendall(HEADER.pack(4, len(data)) + data)
                continue
            if opcode != 1:
                raise ConnectionError("Discord closed the IPC session")
            return json.loads(data)

    def set_activity(self, activity):
        nonce = uuid.uuid4().hex
        self.send(1, {
            "cmd": "SET_ACTIVITY",
            "args": {"pid": os.getpid(), "activity": activity},
            "nonce": nonce,
        })
        while True:
            reply = self.receive()
            if reply.get("nonce") != nonce:
                continue
            if reply.get("evt") == "ERROR" or reply.get("cmd") != "SET_ACTIVITY":
                raise ValueError("Discord rejected the activity")
            return

    def close(self):
        self.reader.close()
        self.socket.close()


class StreamLog:
    def __init__(self, path):
        self.path = path
        self.file_id = None
        self.offset = 0
        self.launching = False
        self.pending = None
        self.session = None

    def reset_stream(self):
        self.launching = False
        self.pending = None
        self.session = None

    def update(self):
        try:
            log = self.path.open("rb")
        except OSError:
            self.file_id = None
            self.reset_stream()
            return
        with log:
            info = os.fstat(log.fileno())
            file_id = info.st_dev, info.st_ino
            if file_id != self.file_id or info.st_size < self.offset:
                self.reset_stream()
                self.file_id = file_id
                log.seek(max(0, info.st_size - 1024 * 1024))
                if log.tell():
                    log.readline()
                self.offset = log.tell()
            log.seek(self.offset)
            while line := log.readline():
                if not line.endswith(b"\n"):
                    break
                self.offset = log.tell()
                self.process(line.decode(errors="replace"))

    def process(self, line):
        if STREAM_LAUNCH in line:
            self.launching = True
            self.pending = None
        elif FIRST_FRAME in line and self.launching:
            self.session = (self.pending, int(time.time())) if self.pending else None
            self.launching = False
            self.pending = None
        elif any(event in line for event in STOP_EVENTS):
            self.reset_stream()
        elif self.launching and self.pending is None and (match := APP_NAME.match(line)):
            with contextlib.suppress(ValueError):
                self.pending = json.loads(match[1]).strip() or None


def geforce_pid():
    result = subprocess.run(
        ["/usr/bin/pgrep", "-nx", "-u", str(os.getuid()), "GeForceNOW"],
        capture_output=True,
        check=False,
    )
    return int(result.stdout) if result.returncode == 0 else None


def process_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def stop_presence(presence):
    if presence is not None:
        with contextlib.suppress(OSError, ValueError):
            presence.set_activity(None)
        presence.close()


def main():
    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log = StreamLog(LOG)
    session = None
    game_pid = None
    current_game = None
    app_id = None
    presence = None
    refresh = None
    refresh_after = 0
    next_attempt = 0
    started_at = 0
    try:
        while running:
            log.update()
            if log.session and log.session is not session:
                game_pid = geforce_pid()
            if log.session and (game_pid is None or not process_alive(game_pid)):
                log.reset_stream()
            if log.session is not session:
                stop_presence(presence)
                presence = None
                session = log.session
                current_game, started_at = session or (None, 0)
                app_id = find_game_id(current_game) if current_game else None
                next_attempt = 0
            now = time.monotonic()
            if refresh is not None and (result := refresh.poll()) is not None:
                refresh = None
                if result == 0 and current_game and app_id is None:
                    app_id = find_game_id(current_game)
            max_age = CATALOG_MAX_AGE if app_id else CATALOG_MISS_MAX_AGE
            if current_game and refresh is None and now >= refresh_after and catalog_is_stale(max_age):
                refresh_after = now + 15 * 60
                refresh = subprocess.Popen(
                    [sys.executable, "-B", __file__, "--refresh-catalog"],
                    stdout=subprocess.DEVNULL,
                )
            if app_id and now >= next_attempt:
                try:
                    if presence is None:
                        presence = Presence(app_id)
                    presence.set_activity({
                        "type": 0,
                        "name": current_game,
                        "timestamps": {"start": started_at},
                    })
                    next_attempt = time.monotonic() + 30
                except (OSError, ValueError):
                    if presence is not None:
                        presence.close()
                    presence = None
                    next_attempt = time.monotonic() + 10
            time.sleep(POLL_SECONDS)
    finally:
        stop_presence(presence)


if __name__ == "__main__":
    if sys.argv[1:] == ["--refresh-catalog"]:
        try:
            print(f"Indexed {refresh_catalog()} game names and aliases.")
        except (OSError, ValueError, KeyError, TypeError) as error:
            sys.exit(f"Could not refresh the Discord game catalog: {error}")
    elif sys.argv[1:]:
        sys.exit("Usage: python3 geforce-discord.py [--refresh-catalog]")
    else:
        main()
