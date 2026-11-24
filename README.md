# GeForce NOW Discord Presence

A small macOS helper that shows the game you’re streaming through GeForce NOW as the title of your Discord activity. It detects when a stream starts and clears the activity when you stop playing.

## Requirements

- The native GeForce NOW app for macOS
- A local Discord client with Rich Presence IPC enabled. Tested with Vesktop on macOS.
- A maintained Python 3 release. [Download Python for macOS](https://www.python.org/downloads/macos/) if needed. The helper uses only the standard library and has been tested with Python 3.9 and 3.14. Python 3.9 is past end of support.

## Get started

1. Download the project with **Code → Download ZIP** and extract it, or clone the repository.
2. In GeForce NOW, open **Settings → Connections** and turn off **Discord rich presence** so NVIDIA’s activity card doesn’t take priority.
3. Keep your Discord client open with **Share my activity** enabled.
4. Open Terminal in the extracted project folder and run:

   ```sh
   python3 geforce-discord.py
   ```

5. Start a game in GeForce NOW. Press **Ctrl+C** in Terminal to stop the helper and clear its activity.

## Start at login

Keep the project in a permanent folder. Stop the foreground helper, then run:

```sh
python3 launch_agent.py install
```

This starts a macOS LaunchAgent for your user. It runs at login and restarts if it exits. To stop it and remove automatic startup:

```sh
python3 launch_agent.py uninstall
```

If you move this folder or change Python installations, uninstall and reinstall the LaunchAgent. You can turn NVIDIA’s built-in Discord presence back on in GeForce NOW settings.

## How it works

The helper reads GeForce NOW’s local `console.log`, waits for the stream’s first frame and looks up the game name in Discord’s public detectable-games catalog. It sends the title and play-session start time to the local client through [Discord Rich Presence IPC](https://github.com/discord/discord-rpc/blob/master/documentation/hard-mode.md).

The compact catalog index lives at `~/Library/Application Support/GeForce Discord Presence/games.tsv`. It refreshes automatically during play as needed and can be reused offline. To refresh it immediately or diagnose catalog download errors:

```sh
python3 geforce-discord.py --refresh-catalog
```

The catalog request downloads public game metadata. It includes no account token, game title or GeForce NOW log contents. The displayed activity is shared through your Discord client according to its activity-sharing settings.

## Compatibility

- A title needs a unique name or alias in Discord’s game catalog to appear. Unmatched games are skipped.
- The helper uses the native macOS client’s log format and Discord’s detectable-games endpoint. Either may change. Browser-based GeForce NOW sessions are outside its scope.
- The helper has been tested for profile activity in Vesktop. Discord Quest progress has not been verified.

Run the local tests with `python3 -m unittest discover -s tests`.

Independent project. GeForce NOW and Discord are trademarks of their respective owners.

[MIT license](LICENSE)
