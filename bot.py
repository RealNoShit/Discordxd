import asyncio
import logging
import os
import re
from urllib.parse import urlparse

import discord
import httpx
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("radio-bot")
API = "https://radio.garden/api"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def station_id_from_link(value: str) -> str | None:
    parsed = urlparse(value.strip())
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ("radio.garden", "www.radio.garden"):
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 3 and parts[0] == "listen" and ID_RE.fullmatch(parts[2]):
        return parts[2]
    return None


async def api_get(path: str, **params):
    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        response = await client.get(f"{API}{path}", params=params)
        response.raise_for_status()
        return response.json()


async def lookup_station(station_id: str) -> str:
    try:
        data = (await api_get(f"/ara/content/channel/{station_id}")).get("data", {})
        return data.get("title") or data.get("name") or station_id
    except (httpx.HTTPError, ValueError):
        return station_id


async def search_stations(query: str):
    payload = await api_get("/search", q=query)
    results = []
    for hit in payload.get("hits", {}).get("hits", []):
        source = hit.get("_source", {})
        if source.get("type") != "channel":
            continue
        url = source.get("url", "")
        station_id = station_id_from_link("https://radio.garden" + url)
        if station_id:
            results.append((station_id, source.get("title", station_id), source.get("subtitle", "")))
    return results[:25]


async def play_station(interaction: discord.Interaction, station_id: str, name: str):
    member = interaction.user
    if not isinstance(member, discord.Member) or not member.voice or not member.voice.channel:
        await interaction.followup.send("Join a voice channel first.", ephemeral=True)
        return
    channel = member.voice.channel
    vc = interaction.guild.voice_client if interaction.guild else None
    try:
        if vc is None:
            vc = await channel.connect(timeout=20, reconnect=True)
        elif vc.channel != channel:
            await vc.move_to(channel)
        if vc.is_playing() or vc.is_paused():
            vc.stop()
        # Radio Garden's documented endpoint redirects to the live station stream.
        url = f"{API}/ara/content/listen/{station_id}/channel.mp3"
        source = discord.FFmpegPCMAudio(
            url,
            before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            options="-vn",
        )
        vc.play(source, after=lambda error: log.error("Playback failed: %s", error) if error else None)
        await interaction.followup.send(f"📻 Now playing **{discord.utils.escape_markdown(name)}** in {channel.mention}")
    except (discord.DiscordException, OSError, RuntimeError) as exc:
        log.exception("Could not play station")
        await interaction.followup.send(f"Could not start playback: `{str(exc)[:160]}`", ephemeral=True)


class StationSelect(discord.ui.Select):
    def __init__(self, stations):
        options = [discord.SelectOption(label=name[:100], description=subtitle[:100] or None, value=station_id) for station_id, name, subtitle in stations]
        super().__init__(placeholder="Choose a radio station", min_values=1, max_values=1, options=options)
        self.names = {station_id: name for station_id, name, _ in stations}

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        station_id = self.values[0]
        await play_station(interaction, station_id, self.names[station_id])


class StationView(discord.ui.View):
    def __init__(self, stations):
        super().__init__(timeout=120)
        self.add_item(StationSelect(stations))


intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
radio = app_commands.Group(name="radio", description="Listen to live Radio Garden stations")


@radio.command(name="play", description="Play a Radio Garden station link")
@app_commands.describe(link="Example: https://radio.garden/listen/station-name/AbCd1234")
async def play(interaction: discord.Interaction, link: str):
    await interaction.response.defer(ephemeral=True)
    station_id = station_id_from_link(link)
    if not station_id:
        await interaction.followup.send("That doesn't look like a supported Radio Garden station link. Use a /listen/.../... URL.", ephemeral=True)
        return
    name = await lookup_station(station_id)
    await play_station(interaction, station_id, name)


@radio.command(name="search", description="Search Radio Garden stations by name, city, or country")
@app_commands.describe(query="Station, city, or country")
async def search(interaction: discord.Interaction, query: str):
    await interaction.response.defer(ephemeral=True)
    try:
        stations = await search_stations(query)
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Search failed: %s", exc)
        await interaction.followup.send("Radio Garden search is currently unavailable. Try /radio play with a station link.", ephemeral=True)
        return
    if not stations:
        await interaction.followup.send("No stations found. Try a different search, or use /radio play.", ephemeral=True)
        return
    await interaction.followup.send(f"Stations matching **{discord.utils.escape_markdown(query)}**:", view=StationView(stations), ephemeral=True)


@radio.command(name="stop", description="Stop the current radio station")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client if interaction.guild else None
    if not vc or not vc.is_playing():
        await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        return
    if not isinstance(interaction.user, discord.Member) or not interaction.user.voice or interaction.user.voice.channel != vc.channel:
        await interaction.response.send_message("Join the bot's voice channel first.", ephemeral=True)
        return
    vc.stop()
    await interaction.response.send_message("Radio stopped.")


@radio.command(name="leave", description="Disconnect the bot from voice")
async def leave(interaction: discord.Interaction):
    vc = interaction.guild.voice_client if interaction.guild else None
    if not vc:
        await interaction.response.send_message("I'm not in a voice channel.", ephemeral=True)
        return
    if not isinstance(interaction.user, discord.Member) or not interaction.user.voice or interaction.user.voice.channel != vc.channel:
        await interaction.response.send_message("Join the bot's voice channel first.", ephemeral=True)
        return
    await vc.disconnect()
    await interaction.response.send_message("Disconnected.")


bot.tree.add_command(radio)


@bot.event
async def on_ready():
    log.info("Logged in as %s", bot.user)


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Set DISCORD_TOKEN in your .env file")
    async with bot:
        guild_id = os.getenv("DISCORD_GUILD_ID", "").strip()
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        else:
            await bot.tree.sync()
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
