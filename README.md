# Mr.Gambler (modular)

Keep your existing `.env` file in the project root (beside `bot.py`).

## Structure
- `bot.py`: entry point, loads extensions and registers slash commands
- `cogs/radio.py`: all radio commands and stream logic
- `cogs/__init__.py`: makes `cogs` a Python package
- `requirements.txt`: Python dependencies

## Install / run (PowerShell)
```powershell
py -m pip install -r requirements.txt
py bot.py
```

## Adding a feature
Create `cogs/newfeature.py` with an `async def setup(bot)` that registers its commands, then add `'cogs.newfeature'` to `COGS` in `bot.py`.

Radio Garden Cloudflare restrictions are **not** solved by this restructuring. The known ANR stream remains supported.
