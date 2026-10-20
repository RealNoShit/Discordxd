"""Radio commands and stream resolution for Mr.Gambler."""
import logging
import asyncio
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlparse

import discord
import httpx
from discord import app_commands

log = logging.getLogger('radio-bot')
GARDEN_API = 'https://radio.garden/api'
RADIO_BROWSER = (
    'https://de1.api.radio-browser.info/json',
    'https://nl1.api.radio-browser.info/json',
    'https://at1.api.radio-browser.info/json',
)
ID_RE = re.compile(r'^[A-Za-z0-9_-]{4,64}$')
CACHE_PATH = Path(__file__).resolve().parent.parent / 'stream_cache.json'


# The known ANR stream remains as a fallback, not the primary resolution method.
KNOWN_STREAMS = {'a04pATzh': 'https://stream.anr.dk/anr'}


def load_cache():
    try:
        data = json.loads(CACHE_PATH.read_text(encoding='utf-8'))
        return {k: v for k, v in data.items() if ID_RE.fullmatch(k) and valid_direct_stream(v)}
    except (OSError, ValueError, TypeError):
        return {}


def valid_direct_stream(url):
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    return parsed.scheme in ('http', 'https') and bool(parsed.hostname) and parsed.hostname not in ('radio.garden', 'www.radio.garden')


STREAM_CACHE = {}  # Populated after functions are defined at module import.


def save_stream(station_id, stream_url):
    if not valid_direct_stream(stream_url):
        return
    STREAM_CACHE[station_id] = stream_url
    try:
        CACHE_PATH.write_text(json.dumps(STREAM_CACHE, indent=2), encoding='utf-8')
    except OSError as exc:
        log.warning('Unable to write stream cache: %s', exc)


async def browser_resolve_stream(station_id):
    """Attempt the redirect inside Chromium. Cloudflare may still deny access."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.warning('Playwright not installed: browser-based Radio Garden resolver unavailable')
        return None

    endpoint = f'{GARDEN_API}/ara/content/listen/{station_id}/channel.mp3'
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                context = await browser.new_context()
                page = await context.new_page()
                # Allow the site to initialize its normal browser session first.
                try:
                    await page.goto('https://radio.garden/', wait_until='domcontentloaded', timeout=12000)
                except Exception as exc:
                    log.info('Radio Garden homepage did not fully load: %s', exc)

                # Capture the redirect from the actual browser network stack.
                # Avoid following a live audio stream forever.
                async def capture():
                    async with page.expect_response(lambda r: r.url.split('?')[0] == endpoint, timeout=12000) as response_info:
                        await page.evaluate("url => { fetch(url, {redirect: 'follow'}).catch(() => {}); }", endpoint)
                    return await response_info.value

                response = await capture()
                if response.status in (301, 302, 303, 307, 308):
                    headers = await response.all_headers()
                    destination = headers.get('location')
                    if valid_direct_stream(destination):
                        log.info('Chromium resolved Radio Garden station %s', station_id)
                        return destination
                log.info('Chromium Radio Garden request returned HTTP %s for %s', response.status, station_id)
            finally:
                await browser.close()
    except Exception as exc:
        log.warning('Chromium stream resolution failed for %s: %s', station_id, exc)
    return None



def normalize(value):
    value = unicodedata.normalize('NFKD', value or '')
    value = ''.join(c for c in value if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', ' ', value.casefold()).strip()


def parse_radio_garden_url(value):
    parsed = urlparse(value.strip())
    if parsed.scheme not in ('https', 'http') or parsed.hostname not in ('radio.garden', 'www.radio.garden'):
        return None, None
    parts = [part for part in parsed.path.split('/') if part]
    if len(parts) != 3 or parts[0] not in ('visit', 'listen') or not ID_RE.fullmatch(parts[2]):
        return None, None
    return parts[0], parts[2]


def station_id_from_link(value):
    kind, item_id = parse_radio_garden_url(value)
    return item_id if kind == 'listen' else None


async def garden_get(path, **params):
    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        response = await client.get(GARDEN_API + path, params=params)
        response.raise_for_status()
        return response.json()


async def lookup_station(station_id):
    data = (await garden_get(f'/ara/content/channel/{station_id}')).get('data', {})
    return data.get('title') or data.get('name') or station_id


async def get_location_stations(location_id):
    payload = await garden_get(f'/ara/content/page/{location_id}/channels')
    stations = []
    for section in payload.get('data', {}).get('content', []):
        for item in section.get('items', []):
            page = item.get('page') or {}
            station_id = page.get('id') or station_id_from_link('https://radio.garden' + (page.get('url') or ''))
            if station_id and ID_RE.fullmatch(str(station_id)):
                stations.append((str(station_id), page.get('title') or str(station_id), page.get('subtitle') or ''))
    return stations[:25]


async def browser_request(path, params=None):
    async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers={'User-Agent': 'MrGamblerRadioBot/1.0'}) as client:
        last_error = None
        for base in RADIO_BROWSER:
            try:
                response = await client.get(base + path, params=params)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                log.warning('Radio Browser mirror failed (%s): %s', base, exc)
        raise RuntimeError(f'Radio Browser is unavailable: {last_error}')


def usable_stream(station):
    url = (station.get('url_resolved') or station.get('url') or '').strip()
    parsed = urlparse(url)
    return url if parsed.scheme in ('https', 'http') and parsed.hostname else None


async def browser_search(query, limit=25):
    data = await browser_request('/stations/search', {'name': query, 'limit': limit, 'hidebroken': 'true', 'order': 'votes', 'reverse': 'true'})
    return [s for s in data if usable_stream(s)]


async def match_garden_station(name, subtitle=''):
    """Match by station name, and use city/country metadata as a tie breaker."""
    candidates = await browser_search(name, limit=100)
    target = normalize(name)
    exact = [s for s in candidates if normalize(s.get('name')) == target]
    if not exact:
        return None
    if len(exact) == 1:
        return exact[0]
    location = normalize(subtitle)
    if location:
        location_tokens = set(location.split())
        ranked = sorted(exact, key=lambda s: len(location_tokens & set(normalize(' '.join((s.get('country') or '', s.get('state') or ''))).split())), reverse=True)
        if len(location_tokens & set(normalize(' '.join((ranked[0].get('country') or '', ranked[0].get('state') or ''))).split())) > 0:
            return ranked[0]
    # Several identically named stations: don't silently pick an unrelated one.
    return None


async def play_stream(interaction, stream_url, name):
    member = interaction.user
    if not isinstance(member, discord.Member) or not member.voice or not member.voice.channel:
        await interaction.followup.send('Join a voice channel first.', ephemeral=True)
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
        log.info('Playing %s from %s', name, stream_url)
        source = discord.FFmpegPCMAudio(
            stream_url,
            before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            options='-vn -loglevel warning',
        )
        vc.play(source, after=lambda error: log.error('Playback failed: %s', error) if error else log.info('Stream ended: %s', name))
        await interaction.followup.send(f'📻 Now playing **{discord.utils.escape_markdown(name)}** in {channel.mention}', ephemeral=True)
    except (discord.DiscordException, OSError, RuntimeError) as exc:
        log.exception('Could not play station')
        await interaction.followup.send(f'Could not start playback: `{str(exc)[:160]}`', ephemeral=True)


async def resolve_garden_stream(station_id):
    """Resolve direct stream with cache, HTTP, then real Chromium network request."""
    if station_id in STREAM_CACHE:
        return STREAM_CACHE[station_id]

    url = f'{GARDEN_API}/ara/content/listen/{station_id}/channel.mp3'
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            response = await client.get(url, headers={'Referer': 'https://radio.garden/'})
        if response.status_code in (301, 302, 303, 307, 308):
            destination = response.headers.get('location', '')
            parsed = urlparse(destination)
            if parsed.scheme in ('http', 'https') and parsed.hostname and parsed.hostname not in ('radio.garden', 'www.radio.garden'):
                save_stream(station_id, destination)
                return destination
        log.info('Radio Garden stream resolution returned HTTP %s for %s', response.status_code, station_id)
    except httpx.HTTPError as exc:
        log.info('Radio Garden stream resolution failed for %s: %s', station_id, exc)
    browser_stream = await browser_resolve_stream(station_id)
    if browser_stream:
        save_stream(station_id, browser_stream)
        return browser_stream
    return KNOWN_STREAMS.get(station_id)


async def play_garden_station(interaction, station_id, name, subtitle=''):
    # First try the actual station's redirect or a verified stream, NOT a fuzzy name match.
    stream = await resolve_garden_stream(station_id)
    if stream:
        await play_stream(interaction, stream, name)
        return

    # Radio Garden may issue a Cloudflare challenge to non-browser requests.
    # Use the existing radio directory as a fallback, without substituting a wrong station.
    try:
        station = await match_garden_station(name, subtitle)
    except (RuntimeError, httpx.HTTPError) as exc:
        log.warning('Station match failed: %s', exc)
        await interaction.followup.send('Radio Garden blocked the stream and the fallback directory is unavailable.', ephemeral=True)
        return
    if not station:
        await interaction.followup.send(
            f'Radio Garden blocked the audio request for **{discord.utils.escape_markdown(name)}**, '
            'and no verified alternative stream was found. I will not play a different station instead.',
            ephemeral=True,
        )
        return
    await play_stream(interaction, usable_stream(station), station.get('name') or name)


class StationSelect(discord.ui.Select):
    def __init__(self, stations, source):
        self.source = source
        self.stations = {str(i): item for i, item in enumerate(stations)}
        options = []
        for i, item in enumerate(stations):
            if source == 'garden':
                _, name, subtitle = item
            else:
                name, subtitle = item.get('name') or 'Unnamed station', ', '.join(filter(None, [item.get('country'), item.get('state')]))
            options.append(discord.SelectOption(label=str(name)[:100], description=str(subtitle)[:100] or None, value=str(i)))
        super().__init__(placeholder='Choose a radio station', options=options)

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        item = self.stations[self.values[0]]
        if self.source == 'garden':
            station_id, name, subtitle = item
            await play_garden_station(interaction, station_id, name, subtitle)
        else:
            await play_stream(interaction, usable_stream(item), item.get('name') or 'Radio station')


class StationView(discord.ui.View):
    def __init__(self, stations, source):
        super().__init__(timeout=120)
        self.add_item(StationSelect(stations, source))


radio = app_commands.Group(name='radio', description='Listen to live radio stations')

@radio.command(name='play', description='Play a Radio Garden station or browse a location')
@app_commands.describe(link='Radio Garden /listen/ or /visit/ URL')
async def play(interaction: discord.Interaction, link: str):
    await interaction.response.defer(ephemeral=True)
    kind, item_id = parse_radio_garden_url(link)
    if not item_id:
        await interaction.followup.send('Invalid Radio Garden link. Use a /listen/ or /visit/ URL.', ephemeral=True)
        return
    try:
        if kind == 'listen':
            name = await lookup_station(item_id)
            await play_garden_station(interaction, item_id, name)
        else:
            stations = await get_location_stations(item_id)
            if not stations:
                await interaction.followup.send('No stations found at this location.', ephemeral=True)
                return
            await interaction.followup.send('Select a station from this location:', view=StationView(stations, 'garden'), ephemeral=True)
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        log.warning('Radio Garden request failed: %s', exc)
        await interaction.followup.send('Radio Garden could not load that link. You can still use `/radio search` to find a playable station.', ephemeral=True)


@radio.command(name='search', description='Search for playable radio stations by name')
@app_commands.describe(query='Radio station name')
async def search(interaction: discord.Interaction, query: str):
    await interaction.response.defer(ephemeral=True)
    try:
        stations = await browser_search(query)
    except (RuntimeError, httpx.HTTPError) as exc:
        log.warning('Radio Browser search failed: %s', exc)
        await interaction.followup.send('Radio search is temporarily unavailable.', ephemeral=True)
        return
    if not stations:
        await interaction.followup.send('No playable stations found. Try another name.', ephemeral=True)
        return
    await interaction.followup.send(f'Stations matching **{discord.utils.escape_markdown(query)}**:', view=StationView(stations[:25], 'browser'), ephemeral=True)


@radio.command(name='stop', description='Stop the current radio station')
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client if interaction.guild else None
    if not vc or not (vc.is_playing() or vc.is_paused()):
        await interaction.response.send_message('Nothing is playing.', ephemeral=True)
        return
    if not isinstance(interaction.user, discord.Member) or not interaction.user.voice or interaction.user.voice.channel != vc.channel:
        await interaction.response.send_message("Join the bot's voice channel first.", ephemeral=True)
        return
    vc.stop()
    await interaction.response.send_message('Radio stopped.')


@radio.command(name='leave', description='Disconnect the bot from voice')
async def leave(interaction: discord.Interaction):
    vc = interaction.guild.voice_client if interaction.guild else None
    if not vc:
        await interaction.response.send_message("I'm not in a voice channel.", ephemeral=True)
        return
    if not isinstance(interaction.user, discord.Member) or not interaction.user.voice or interaction.user.voice.channel != vc.channel:
        await interaction.response.send_message("Join the bot's voice channel first.", ephemeral=True)
        return
    await vc.disconnect()
    await interaction.response.send_message('Disconnected.')


STREAM_CACHE.update(load_cache())


async def setup(bot):
    """Called by discord.py when this extension loads."""
    bot.tree.add_command(radio)


async def teardown(bot):
    bot.tree.remove_command(radio.name)
