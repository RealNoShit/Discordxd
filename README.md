# Radio Garden Discord Bot (prototype)

## Setup (Windows / PowerShell)

1. Install Python 3.11+ and FFmpeg. Confirm `ffmpeg -version` works in PowerShell.
2. Create a bot at https://discord.com/developers/applications and copy its bot token. Never share the token.
3. Invite the bot using OAuth2 scopes `bot` and `applications.commands`; grant `View Channels`, `Connect`, `Speak`, and `Send Messages`.
4. Open PowerShell in this directory and run:

```powershell
py -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
py bot.py
```

Set `DISCORD_TOKEN` in `.env`. Optionally set `DISCORD_GUILD_ID` to your server's numeric ID for quicker slash command registration.

## Commands

- `/radio play link:<Radio Garden station URL>` — join your VC and stream
- `/radio search query:<station/city/country>` — select a station from results
- `/radio stop` — stop streaming
- `/radio leave` — disconnect

## Notes

This is an **untested integration prototype**. Radio Garden's unofficial API may change or block automated clients; some streams may be geo-restricted or fail. Search results for places/countries may not include stations directly; try station names or a link. Streaming third-party broadcasts may require permission: check applicable terms and rights. The bot must stay running to keep playing. Keep `.env` private.
