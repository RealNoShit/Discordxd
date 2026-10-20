# Mr.Gambler 🎲

**A modular Discord bot for listening to live radio stations from around the world.**

Mr.Gambler lets you paste a [Radio Garden](https://radio.garden/) station or location link into Discord, choose a station, and listen together in a voice channel. It automatically attempts to find the station's underlying audio stream—no manual stream URLs or playlist downloads required.

> **Status:** Working personal project. Automatic stream resolution is experimental, and some stations may be unavailable due to Cloudflare restrictions, offline streams, or broadcaster limitations.

## Features

- 🌍 **Radio Garden links:** Play a station directly from a `/listen/` URL.
- 📍 **Browse by location:** Paste a `/visit/` URL and choose a station from a Discord dropdown.
- 🔎 **Station search:** Search for stations by name using Radio Browser.
- 🔊 **Voice playback:** Stream radio directly into a Discord voice channel with FFmpeg.
- ⚡ **Automatic stream resolution:** Try Radio Garden redirects, then browser-based resolution and other fallbacks.
- 💾 **Stream caching:** Save successfully resolved station URLs locally for reuse.
- 🧩 **Modular design:** Radio functionality lives in its own Discord cog, making it easier to add more features.

## Commands

| Command | Description |
| --- | --- |
| `/radio play link:<url>` | Play a Radio Garden station (`/listen/`) or browse stations at a location (`/visit/`). |
| `/radio search query:<name>` | Search for radio stations by name and select one. |
| `/radio stop` | Stop the current station. |
| `/radio leave` | Disconnect the bot from the voice channel. |

**Example:**

```text
/radio play link:https://radio.garden/listen/anr/a04pATzh
```

Join a voice channel before playing a station.

## Getting started

### Requirements

- Python 3.10 or newer
- [FFmpeg](https://ffmpeg.org/download.html) installed and available on your `PATH`
- A Discord bot token from the [Discord Developer Portal](https://discord.com/developers/applications)

### 1. Clone the repository

```powershell
git clone https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
cd YOUR_REPOSITORY
```

Replace the placeholder with your repository's URL.

### 2. Install Python dependencies

```powershell
py -m pip install -r requirements.txt
```

Install Chromium for the optional automated browser resolver:

```powershell
py -m playwright install chromium
```

### 3. Configure your Discord token

Copy `.env.example` to `.env`:

```powershell
Copy-Item .env.example .env
```

Then edit `.env`:

```dotenv
DISCORD_TOKEN=your_discord_bot_token_here
```

**Never commit `.env` or share your real bot token.** The `.gitignore` excludes `.env` and the local stream cache.

### 4. Invite the bot

In the Discord Developer Portal, configure an installation/invite URL for your application with the `bot` and `applications.commands` scopes. Grant the bot permission to **View Channels**, **Connect**, and **Speak** in the voice channels where you want to use it.

### 5. Start Mr.Gambler

```powershell
py bot.py
```

The bot registers its slash commands when it starts. Global commands can take a little time to appear in Discord.

## How stream resolution works

When you choose a Radio Garden station, Mr.Gambler attempts to find a playable stream:

1. Check the local stream cache.
2. Request the Radio Garden audio endpoint and inspect its redirect.
3. If needed, attempt resolution through an automated Chromium session.
4. Try supported fallbacks, including Radio Browser.
5. Send the resulting audio stream to Discord through FFmpeg.

Not every station is guaranteed to work. Radio Garden and individual broadcasters can change endpoints, restrict automated requests, or take streams offline.

## Project structure

```text
MrGambler/
├── bot.py                 # Bot startup and cog loading
├── cogs/
│   ├── __init__.py
│   └── radio.py           # Commands, station lookup, stream resolution
├── requirements.txt      # Python dependencies
├── .env.example           # Example environment variables
├── .gitignore
└── README.md
```

The `.env` and `stream_cache.json` files are local and should not be committed.

## Adding new features

The bot loads extensions listed in `COGS` inside `bot.py`. Add a new module under `cogs/`, expose an `async def setup(bot)` function, and register the extension in `COGS`.

## Troubleshooting

- **No sound:** Make sure FFmpeg is installed, the bot can connect and speak, and the station is online.
- **A station fails:** Try another station. Some Radio Garden redirects may be blocked or their underlying streams unavailable.
- **Chromium resolver fails:** Run `py -m playwright install chromium` and restart the bot.
- **Commands are missing:** Confirm the bot was invited with `applications.commands` and give global command registration time to propagate.

## Acknowledgments

- [Radio Garden](https://radio.garden/) for discovering radio stations around the world.
- [Radio Browser](https://www.radio-browser.info/) for community-maintained station listings.
- [discord.py](https://discordpy.readthedocs.io/) for the Discord integration.
- [FFmpeg](https://ffmpeg.org/) for audio streaming.

*Mr.Gambler is an independent hobby project and is not affiliated with Radio Garden, Radio Browser, or Discord.*
