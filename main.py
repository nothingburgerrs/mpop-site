import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
import os
import random
import io
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import asyncio
import json
import traceback
import aiohttp # For fetching era art when rendering show graphics
import graphics # Template-based show boards (see graphics.py)
import dashboard_api # In-process management API for the web dashboard
from PIL import Image, ImageDraw, ImageFont
import calendar

ARG_TZ = timezone(timedelta(hours=-3))

# Load token from .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True # Required for message content for wait_for

# --- Global data storage and file persistence ---
DATA_FILE = "data.json"

# Default placeholder image for albums
DEFAULT_ALBUM_IMAGE = "https://placehold.co/128x128.png?text=Album"

import re as _re
def sanitize_url(url, fallback=None):
    """Extract a raw URL from a possible markdown link like [text](url), or return fallback if invalid."""
    if not url or not isinstance(url, str):
        return fallback or DEFAULT_ALBUM_IMAGE
    url = url.strip()
    md_match = _re.match(r'\[.*?\]\((https?://[^)]+)\)', url)
    if md_match:
        return md_match.group(1)
    if url.startswith(('http://', 'https://')):
        return url
    return fallback or DEFAULT_ALBUM_IMAGE

# Hidden canonical groups - receive silent bonuses (not displayed anywhere)
_CANONICAL_GROUPS = {"H10N-Y", "HOUR*LY", "ROM.COM"}

def _get_hidden_bonus(group_name: str) -> float:
    """Returns hidden multiplier for canonical groups. Not displayed anywhere."""
    if group_name.upper() in _CANONICAL_GROUPS:
        return 1.15
    return 1.0

# Concert cities list
CONCERT_CITIES = [
    "Seoul", "Busan", "Daegu", "Incheon",
    "Tokyo", "Osaka", "Kyoto",
    "New York", "Los Angeles", "Toronto", "Mexico City", "Buenos Aires", "São Paulo",
    "London", "Paris", "Berlin", "Rome", "Madrid", "Amsterdam",
    "Shanghai", "Bangkok", "Singapore", "Mumbai",
    "Sydney", "Melbourne"
]

TOUR_COUNTRIES = {
    # Asia
    "South Korea": {"popularity_req": 100, "venue_cost": 200_000, "base_attendance": 5000, "revenue_mult": 1.5},
    "Japan": {"popularity_req": 300, "venue_cost": 300_000, "base_attendance": 8000, "revenue_mult": 2.0},
    "China": {"popularity_req": 500, "venue_cost": 350_000, "base_attendance": 10000, "revenue_mult": 2.2},
    "Thailand": {"popularity_req": 250, "venue_cost": 180_000, "base_attendance": 6000, "revenue_mult": 1.4},
    "Philippines": {"popularity_req": 200, "venue_cost": 150_000, "base_attendance": 5500, "revenue_mult": 1.3},
    "Indonesia": {"popularity_req": 200, "venue_cost": 160_000, "base_attendance": 6000, "revenue_mult": 1.3},
    "Singapore": {"popularity_req": 400, "venue_cost": 250_000, "base_attendance": 4000, "revenue_mult": 1.8},
    # Americas
    "United States": {"popularity_req": 800, "venue_cost": 500_000, "base_attendance": 12000, "revenue_mult": 3.0},
    "Mexico": {"popularity_req": 300, "venue_cost": 200_000, "base_attendance": 7000, "revenue_mult": 1.5},
    "Brazil": {"popularity_req": 350, "venue_cost": 220_000, "base_attendance": 8000, "revenue_mult": 1.6},
    "Argentina": {"popularity_req": 300, "venue_cost": 180_000, "base_attendance": 6500, "revenue_mult": 1.4},
    # Europe
    "United Kingdom": {"popularity_req": 600, "venue_cost": 400_000, "base_attendance": 10000, "revenue_mult": 2.5},
    "France": {"popularity_req": 500, "venue_cost": 350_000, "base_attendance": 8000, "revenue_mult": 2.2},
    "Germany": {"popularity_req": 500, "venue_cost": 350_000, "base_attendance": 8000, "revenue_mult": 2.2},
    # Oceania
    "Australia": {"popularity_req": 450, "venue_cost": 300_000, "base_attendance": 9000, "revenue_mult": 2.0},
}

# Music shows with their scoring systems
# Format: {max_digital, max_physical, max_sns, max_broadcast, digital_divisor, physical_divisor, sns_divisor}
# Some shows split SNS into views_max and posts_max (e.g., Inkigayo: 1400 MV + 600 posts)
MUSIC_SHOWS = {
    "M COUNTDOWN": {
        "max_digital": 6600, "max_physical": 1650, "max_sns": 1650, "max_broadcast": 1100,
        "digital_divisor": 1500, "physical_divisor": 100, "sns_divisor": 5000
    },
    "Music Bank": {
        "max_digital": 3500, "max_physical": 1500, "max_sns": 1000, "max_broadcast": 600,
        "digital_divisor": 2500, "physical_divisor": 75, "sns_divisor": 8000
    },
    "Show! Music Core": {
        "max_digital": 3500, "max_physical": 1500, "max_sns": 1000, "max_broadcast": 600,
        "digital_divisor": 2500, "physical_divisor": 75, "sns_divisor": 8000
    },
    "Inkigayo": {
        "max_digital": 5000, "max_physical": 1000, "max_sns": 2000, "max_broadcast": 1000,
        "digital_divisor": 2000, "physical_divisor": 100, "sns_divisor": 6000,
        "sns_split": True, "max_sns_views": 1400, "max_sns_posts": 600, "posts_divisor": 5
    },
    "The Show": {
        "max_digital": 3500, "max_physical": 1500, "max_sns": 1000, "max_broadcast": 600,
        "digital_divisor": 2500, "physical_divisor": 75, "sns_divisor": 8000
    },
    "Show Champion": {
        "max_digital": 3500, "max_physical": 1500, "max_sns": 1000, "max_broadcast": 2000,
        "digital_divisor": 2500, "physical_divisor": 75, "sns_divisor": 8000,
        "has_voting": True, "max_voting": 2000
    }
}

# Initialize global dictionaries. These will be loaded from data.json on startup.
group_popularity = {}
company_funds = {}
group_data = {}
company_data = {}
album_data = {}
user_balances = {}
user_companies = {}
user_cooldowns = {}
user_daily_limits = {}
user_stream_counts = {}
records_24h = {"global": {"streams": 0, "sales": 0, "views": 0}, "personal": {}}
weekly_streams = {}
preorder_data = {}
article_history = {}
random_events_log = {}

DAILY_LIMITS = {
    "streams": 10,
    "sales": 10,
    "views": 10,
    "charity": 5,
    "work": 10,
    "streamsong": 10
}

RANDOM_EVENTS_GOOD = [
    {"type": "viral_fancam", "title": "Viral Fancam", "description": "A fancam of {member} from {group} is going viral! The clip has over 10M views and counting.", "popularity": (20, 50), "gp": (5, 15), "fanbase": (3, 8)},
    {"type": "variety_moment", "title": "Variety Show Moment", "description": "{member} from {group} had a hilarious moment on Running Man that's trending on all platforms!", "popularity": (15, 35), "gp": (8, 18), "fanbase": (2, 5)},
    {"type": "fan_project", "title": "Fan Project Success", "description": "Fans organized an amazing birthday project for {member} from {group} - the hashtag trended worldwide!", "fanbase": (5, 12), "popularity": (10, 25)},
    {"type": "award_speech", "title": "Touching Award Speech", "description": "{group}'s heartfelt award acceptance speech is making fans emotional worldwide!", "gp": (10, 20), "fanbase": (5, 10), "popularity": (15, 30)},
    {"type": "charity_recognition", "title": "Charity Recognition", "description": "{group} was publicly recognized by UNICEF for their ongoing charity contributions!", "gp": (15, 30), "popularity": (20, 40)},
    {"type": "collab_surprise", "title": "Surprise Collaboration", "description": "{group} surprised fans with an unexpected collaboration with a legendary artist!", "popularity": (25, 50), "streams": (50000, 150000)},
    {"type": "cover_trending", "title": "Cover Goes Viral", "description": "{member}'s acoustic cover of a popular song is trending #1 on YouTube!", "popularity": (30, 60), "views": (100000, 300000)},
    {"type": "cute_interaction", "title": "Adorable Fan Interaction", "description": "{member} from {group} had the most adorable interaction with a young fan at the airport!", "gp": (5, 12), "fanbase": (3, 7)},
    {"type": "weird_fans_clip", "title": "Viral Clip", "description": "{member} from {group} talking about weird fan encounters has everyone laughing!", "popularity": (15, 30), "gp": (8, 15), "fanbase": (2, 6)},
    {"type": "airport_fashion", "title": "Airport Fashion Goals", "description": "{member}'s airport outfit is trending on fashion forums - 'It-Girl' status achieved!", "popularity": (10, 25), "gp": (5, 12)},
    {"type": "predebut_video", "title": "Predebut Video Resurfaces", "description": "A cute predebut video of {member} from {group} has resurfaced and fans are going wild!", "fanbase": (5, 10), "popularity": (8, 20)},
    {"type": "viral_song", "title": "Song Going Viral", "description": "'{song}' by {group} is randomly going viral on TikTok! Streams are skyrocketing!", "popularity": (25, 45), "song_boost": True},
    {"type": "fan_chant_perfect", "title": "Perfect Fan Chant", "description": "{group}'s fans delivered an absolutely perfect fan chant at the concert - video is everywhere!", "fanbase": (8, 15), "gp": (3, 8)},
    {"type": "member_vlive", "title": "Emotional VLive", "description": "{member} from {group} did a surprise 3-hour VLive talking to fans - engagement through the roof!", "fanbase": (10, 18), "popularity": (5, 15)},
    {"type": "dance_challenge", "title": "Dance Challenge Success", "description": "The {group} dance challenge has over 500K participants on TikTok!", "popularity": (20, 40), "gp": (10, 20), "views": (80000, 200000)},
]

RANDOM_EVENTS_BAD = [
    {"type": "dating_scandal", "title": "Dating Scandal", "description": "DISPATCH EXCLUSIVE: {member} from {group} spotted on a late-night date in Hannam-dong. Relationship confirmed.", "popularity": (-30, -10), "gp": (-15, -5), "fanbase": (5, 15), "triggers_hate_train": 0.3},
    {"type": "rude_staff", "title": "Rude to Staff", "description": "A staff member posted anonymously about {member} from {group}'s alleged rude behavior backstage.", "gp": (-20, -8), "popularity": (-25, -10), "triggers_hate_train": 0.4},
    {"type": "live_incident", "title": "Embarrassing Live Moment", "description": "{member} from {group} accidentally {embarrassing_action} during a live broadcast. Clip going viral.", "gp": (-10, -3), "popularity": (-15, -5)},
    {"type": "bullying_internal", "title": "Internal Bullying Allegations", "description": "Fans speculate {member} is being excluded by other {group} members based on recent interactions.", "fanbase": (-8, -3), "gp": (-12, -5), "popularity": (-20, -8)},
    {"type": "bullying_school", "title": "School Bullying Allegations", "description": "Anonymous post claims {member} from {group} was a bully during their school days. Company investigating.", "gp": (-25, -12), "popularity": (-30, -15), "triggers_hate_train": 0.45},
    {"type": "attitude_controversy", "title": "Attitude Controversy", "description": "Fan accounts report {member} from {group}'s cold attitude at recent fan sign event.", "gp": (-15, -5), "fanbase": (-5, -2), "triggers_hate_train": 0.25},
    {"type": "plagiarism_accusation", "title": "Plagiarism Accusation", "description": "{group}'s latest song accused of plagiarizing [redacted artist]. Side-by-side comparisons trending.", "popularity": (-35, -15), "gp": (-20, -10), "triggers_hate_train": 0.5},
    {"type": "lip_sync_exposed", "title": "Lip-Sync Exposed", "description": "{group} caught lip-syncing when the backing track failed during Music Bank performance.", "gp": (-18, -8), "popularity": (-25, -12)},
    {"type": "sasaeng_incident", "title": "Sasaeng Incident", "description": "{member} from {group} had to call security after sasaeng fans followed them home.", "popularity": (-10, -5), "fanbase": (2, 5)},
    {"type": "health_hiatus", "title": "Health Hiatus Announced", "description": "{member} from {group} announces temporary hiatus for mental health recovery. Fans sending support.", "popularity": (-15, -5), "fanbase": (3, 8)},
    {"type": "live_fart", "title": "Unfortunate Sound on Live", "description": "{member} from {group} had an... unfortunate audio moment during their live broadcast. Comments section in chaos.", "gp": (-5, -2), "popularity": (-8, -3)},
    {"type": "drunk_live", "title": "Tipsy Live Broadcast", "description": "{member} from {group} went live after drinking and said some questionable things. Company issued statement.", "gp": (-15, -8), "popularity": (-20, -10), "triggers_hate_train": 0.2},
    {"type": "chart_manipulation", "title": "Chart Manipulation Rumors", "description": "Industry insiders questioning {group}'s sudden chart rise. Investigation pending.", "gp": (-18, -10), "popularity": (-15, -8)},
    {"type": "contract_dispute", "title": "Contract Dispute Rumors", "description": "Reports of {member} from {group} in contract disputes with their agency. Fans worried.", "popularity": (-12, -5), "fanbase": (-3, -1)},
    {"type": "cultural_insensitivity", "title": "Cultural Insensitivity Issue", "description": "{member} from {group}'s old social media post resurfaces with problematic content. Apology pending.", "gp": (-22, -12), "popularity": (-18, -8), "triggers_hate_train": 0.35},
]

RANDOM_EVENTS_BAD.extend([
    {"type": "dating_scandal_crossover", "title": "DATING SCANDAL - CROSSOVER",
     "description": "DISPATCH EXCLUSIVE: {member} from {group} spotted with {other_member} from {other_group}!",
     "popularity": (-25, -10), "gp": (-15, -5), "triggers_hate_train": 0.3, "requires_other_group": True},

    {"type": "member_injury", "title": "Member Injury",
     "description": "{member} from {group} injured during practice. Taking 2-week hiatus for recovery.",
     "popularity": (-10, -5),
     "temporary_debuff": {"duration_days": 14, "stat": "popularity", "amount": -20}},

    {"type": "health_hiatus_extended", "title": "Extended Health Hiatus",
     "description": "{member} from {group} announces extended hiatus for mental health. Fans sending support but worried.",
     "popularity": (-20, -10), "fanbase": (5, 10),
     "temporary_debuff": {"duration_days": 30, "stat": "popularity", "amount": -30}},

    {"type": "concert_cancelled", "title": "Concert Cancelled",
     "description": "{group}'s concert was cancelled due to poor ticket sales. Fans disappointed.",
     "gp": (-20, -10), "popularity": (-25, -15), "fanbase": (-10, -5)},

    {"type": "stage_accident", "title": "Stage Accident",
     "description": "{member} from {group} had a stage accident during live performance. Safety concerns raised.",
     "gp": (-15, -8), "popularity": (-20, -10)},

    {"type": "album_delay", "title": "Album Delay Announced",
     "description": "{group}'s comeback has been delayed indefinitely. No explanation given.",
     "fanbase": (-8, -3), "popularity": (-15, -8)},

    {"type": "member_controversy", "title": "Member Controversy",
     "description": "{member}'s past comments resurface and cause controversy online.",
     "gp": (-18, -10), "popularity": (-15, -8), "triggers_hate_train": 0.35},
])

EMBARRASSING_LIVE_ACTIONS = [
    "accidentally showed their phone screen with embarrassing tabs open",
    "fell asleep mid-broadcast",
    "let out an unexpected noise (viewers are debating what it was)",
    "accidentally called their manager 'mom' on camera",
    "spilled an entire drink on their setup",
    "started singing the wrong group's song",
    "accidentally turned on a weird filter and couldn't turn it off",
    "walked into a glass door on stream",
]

GLOBAL_CHART_COUNTRIES = [
    ("🇰🇷", "South Korea", 1.0),
    ("🇯🇵", "Japan", 0.9),
    ("🇹🇼", "Taiwan", 0.75),
    ("🇭🇰", "Hong Kong", 0.7),
    ("🇨🇳", "China", 0.65),
    ("🇹🇭", "Thailand", 0.6),
    ("🇵🇭", "Philippines", 0.55),
    ("🇮🇩", "Indonesia", 0.5),
    ("🇻🇳", "Vietnam", 0.45),
    ("🇲🇾", "Malaysia", 0.4),
    ("🇸🇬", "Singapore", 0.35),
    ("🇺🇸", "United States", 0.5),
    ("🇬🇧", "United Kingdom", 0.45),
    ("🇫🇷", "France", 0.4),
    ("🇩🇪", "Germany", 0.35),
    ("🇧🇷", "Brazil", 0.8),
    ("🇦🇷", "Argentina", 1.0),
    ("🇲🇽", "Mexico", 0.7),
]

ARTICLE_GOOD_TEMPLATES = [
    "{group} proves their philanthropic side with generous donation",
    "{group}'s {member} praised for professionalism and kindness",
    "Industry insiders praise {group}'s work ethic and talent",
    "{group} sets new standards for idol behavior",
    "Exclusive: {group}'s journey to the top - a story of perseverance",
    "{group} wins hearts with genuine fan interactions",
]

ARTICLE_BAD_TEMPLATES = [
    "EXPOSED: The truth behind {group}'s perfect image",
    "Former staff reveals concerning behavior from {group}",
    "Is {group}'s success manufactured? Industry experts weigh in",
    "{group}'s {member} under fire for past controversy resurfaces",
    "Fans concerned about {group}'s recent behavior",
    "The dark side of {group}: What companies don't want you to know",
]


def load_data():
    """Loads data from data.json into global dictionaries."""
    global group_popularity, company_funds, group_data, album_data, user_balances, user_companies, user_cooldowns, user_daily_limits, user_stream_counts, records_24h, weekly_streams, preorder_data, article_history, random_events_log, events_channel_id, last_random_timestamp, admin_logs

    if os.path.exists(DATA_FILE):
        corrupt_error = None
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            try:
                loaded_data = json.load(f)
                group_popularity.update(loaded_data.get('group_popularity', {}))
                company_funds.update(loaded_data.get('company_funds', {}))
                company_data.update(loaded_data.get('company_data', {}))

                loaded_group_data = loaded_data.get('group_data', {})
                for group_name, data in loaded_group_data.items():
                    data.setdefault('is_disbanded', False)
                    data.setdefault('fanbase', 50)
                    data.setdefault('gp', 30)
                    data.setdefault('payola_suspicion', 0)
                    data.setdefault('has_scandal', False)
                    data.setdefault('active_hate_train', False)
                    data.setdefault('hate_train_fanbase_boost', 0)
                    data.setdefault('members', [])
                    data.setdefault('recent_events', [])
                    data.setdefault('is_subunit', False)
                    data.setdefault('parent_group', None)
                    data.setdefault('subunits', [])
                    data.setdefault('last_tax_month', None)
                    data.setdefault('reputation', 50)
                    data.setdefault('reputation_history', [])
                    group_data[group_name] = data

                loaded_album_data = loaded_data.get('album_data', {})
                for album_name, data in loaded_album_data.items():
                    data.setdefault('streams', 0)
                    data.setdefault('sales', 0)
                    data.setdefault('views', 0)
                    data.setdefault('image_url', DEFAULT_ALBUM_IMAGE)
                    data.setdefault('is_active_promotion', False)
                    data.setdefault('first_24h_tracking', None)
                    data.setdefault('album_type', 'mini')
                    data.setdefault('album_format', 'physical')
                    data.setdefault('stock', 100000 if data.get('album_format') == 'physical' else 0)

                    # Process 'promotion_end_date' to ensure it's a datetime object or None
                    promo_date_value = data.get('promotion_end_date')
                    if isinstance(promo_date_value, str):
                        try:
                            # Convert ISO string back to datetime object
                            data['promotion_end_date'] = datetime.fromisoformat(promo_date_value)
                        except ValueError:
                            # If string is not a valid ISO format, set to None
                            data['promotion_end_date'] = None
                    else:
                        # If it's not a string (e.g., None or already a datetime object from an uncaught previous state)
                        # Ensure it's None if it's not a valid datetime object either
                        if not isinstance(promo_date_value, datetime):
                            data['promotion_end_date'] = None
                        # If it's already a datetime object, keep it.

                    # Ensure charts_info structure is always present
                    data.setdefault('charts_info', {})
                    for chart_type_key in ["MelOn", "Genie", "Bugs", "FLO"]:
                        data['charts_info'].setdefault(chart_type_key, {'rank': None, 'peak': None, 'prev_rank': None})
                    
                    data.setdefault('songs', [])
                    data.setdefault('preorders', 0)
                    data.setdefault('weekly_streams', {})

                    album_data[album_name] = data

                # Reconcile win counts. A group's total is base_wins plus the wins
                # recorded against its albums. base_wins holds everything not tied
                # to a specific album: wins earned before album-level tracking, and
                # any imported history. Without it, recalculating a group's total
                # from its albums silently deletes those wins.
                #
                # A group's stored total is never allowed to drop: base_wins is
                # whatever is needed to keep it whole.
                for group_name, data in group_data.items():
                    album_wins = sum(
                        album_data.get(a, {}).get('wins', 0)
                        for a in data.get('albums', [])
                    )
                    stored_wins = data.get('wins', 0)
                    expected = data.get('base_wins', 0) + album_wins

                    if 'base_wins' not in data or expected < stored_wins:
                        data['base_wins'] = max(0, stored_wins - album_wins)
                        if data['base_wins']:
                            print(f"Preserved {data['base_wins']} untracked win(s) for {group_name}.")

                    # Keep the displayed total consistent with its parts.
                    data['wins'] = data['base_wins'] + album_wins

                user_balances.update(loaded_data.get('user_balances', {}))
                weekly_streams.update(loaded_data.get('weekly_streams', {}))
                preorder_data.update(loaded_data.get('preorder_data', {}))
                article_history.update(loaded_data.get('article_history', {}))
                random_events_log.update(loaded_data.get('random_events_log', {}))

                # Handle user_companies: convert single string to list if old format
                # Ensure user_companies is properly loaded, defaulting to an empty dict if not found
                user_companies.update(loaded_data.get('user_companies', {}))
                for user_id, companies in user_companies.items(): # Iterate over what was just loaded
                    if isinstance(companies, str):
                        user_companies[user_id] = [companies] # Convert old string format to list
                    else:
                        user_companies[user_id] = companies # Assume it's already a list or empty


                # Load cooldowns, converting ISO strings back to datetime objects
                loaded_cooldowns = loaded_data.get('user_cooldowns', {})
                for user_id, commands in loaded_cooldowns.items():
                    user_cooldowns[user_id] = {
                        cmd: datetime.fromisoformat(ts) for cmd, ts in commands.items()
                    }

                user_daily_limits.update(loaded_data.get('user_daily_limits', {}))
                user_stream_counts.update(loaded_data.get('user_stream_counts', {}))
                loaded_records = loaded_data.get('records_24h', {})
                if 'global' in loaded_records:
                    records_24h.update(loaded_records)
                else:
                    records_24h['global'] = loaded_records if loaded_records else {"streams": 0, "sales": 0, "views": 0}
                    records_24h['personal'] = {}

                events_channel_id = loaded_data.get('events_channel_id', None)
                last_random_timestamp = loaded_data.get('last_random_timestamp', None)
                admin_logs = loaded_data.get('admin_logs', [])
                
                print("Data loaded from data.json successfully!")
            except json.JSONDecodeError as e:
                # Only record it here; the file must be closed before renaming.
                corrupt_error = e

        if corrupt_error is not None:
            # Do NOT continue with empty data: the first save_data() afterwards
            # would overwrite a recoverable file with nothing. Preserve the bad
            # file and refuse to start so it can be repaired by hand.
            backup = f"{DATA_FILE}.corrupt-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            try:
                os.replace(DATA_FILE, backup)
                print(f"Corrupt {DATA_FILE} preserved as {backup}")
            except OSError as copy_error:
                print(f"Could not preserve corrupt data file: {copy_error}")
            raise SystemExit(
                f"FATAL: {DATA_FILE} is not valid JSON ({corrupt_error}). "
                "Refusing to start so existing data is not overwritten."
            )
    else:
        print("data.json not found. Starting with empty data.")

def save_data():
    """Saves global dictionaries to data.json."""
    data_to_save = {
        'group_popularity': group_popularity,
        'company_funds': company_funds,
        'group_data': group_data,
        'company_data': company_data,
        'album_data': album_data,
        'user_balances': user_balances,
        'user_cooldowns': user_cooldowns,
        'user_daily_limits': user_daily_limits,
        'user_companies': user_companies,
        'user_stream_counts': user_stream_counts,
        'records_24h': records_24h,
        'weekly_streams': weekly_streams,
        'preorder_data': preorder_data,
        'article_history': article_history,
        'random_events_log': random_events_log,
        'events_channel_id': events_channel_id,
        'last_random_timestamp': last_random_timestamp,
        'admin_logs': admin_logs
    }
    # Custom encoder for datetime objects
    class DateTimeEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            return json.JSONEncoder.default(self, obj)

    # Write to a temp file and swap it into place, so an interrupted write can
    # never leave a truncated save. Opening data.json in 'w' truncates it to
    # zero bytes immediately, which is how a crash mid-write loses everything.
    temp_file = DATA_FILE + ".tmp"
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=4, cls=DateTimeEncoder)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, DATA_FILE) # Atomic on POSIX and Windows
    except Exception as e:
        print(f"ERROR: Failed to save data: {e}")
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except OSError:
            pass
        return
    print("Data saved to data.json.")

# --- Bot Setup ---
class MyBot(commands.Bot):
    async def setup_hook(self):
        print("Setting up bot...")
        load_data()
        await self.tree.sync()
        print(f'Bot {bot.user} has synced slash commands.')

        # Start the web dashboard API in this same event loop, so it shares the
        # live in-memory state the commands use. No-op unless DASHBOARD_API_SECRET
        # is set, so the bot runs exactly as before until the dashboard is wired up.
        await dashboard_api.start(dashboard_api.Deps(
            group_data=group_data,
            album_data=album_data,
            company_funds=company_funds,
            company_data=company_data,
            user_companies=user_companies,
            user_balances=user_balances,
            get_user_companies=get_user_companies,
            is_user_company_owner=is_user_company_owner,
            get_group_owner_company=get_group_owner_company,
            is_user_group_owner=is_user_group_owner,
            save_data=save_data,
        ))

bot = MyBot(command_prefix="/", intents=intents)


# --- ERROR HANDLING ---
# Without these, a failing command shows users "The application did not respond"
# with no explanation, and an exception inside a tasks.Loop stops that loop
# permanently for the rest of the process's life.

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Report command failures instead of leaving the user staring at a timeout."""
    # Failed checks have already told the user why.
    if isinstance(error, app_commands.CheckFailure):
        return

    original = getattr(error, 'original', error)
    command_name = interaction.command.name if interaction.command else 'unknown'
    print(f"ERROR in /{command_name}:")
    traceback.print_exception(type(original), original, original.__traceback__)

    message = (
        f"❌ Something went wrong running `/{command_name}`.\n"
        f"`{type(original).__name__}: {original}`"[:1900]
    )
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass # Interaction already expired; the log above is what matters


def attach_task_error_handler(task, task_name: str):
    """Log task failures and restart the loop.

    discord.py stops a Loop after an unhandled exception, so without this one
    bad record would silently disable a feature until the next reboot.
    """
    async def handler(exception: BaseException):
        print(f"ERROR in scheduled task {task_name}:")
        traceback.print_exception(type(exception), exception, exception.__traceback__)
        if not task.is_running():
            print(f"Restarting {task_name}...")
            task.restart()

    task.error(handler)

# --- EVENTS ---
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    scheduled_tasks = {
        'monthly_tax_check': monthly_tax_check,
        'weekly_streams_reset': weekly_streams_reset,
        'birthday_check': birthday_check,
        'check_expired_boycotts': check_expired_boycotts,
        'decay_company_pressure': decay_company_pressure,
    }
    for task_name, task in scheduled_tasks.items():
        attach_task_error_handler(task, task_name)
        if not task.is_running():
            task.start()
    
    # Backfill any missing pre-release entries to group profiles
    backfill_prereleases()

def get_today_str():
    """Returns today's date in Argentina timezone (UTC-3) as YYYY-MM-DD"""
    return datetime.now(ARG_TZ).strftime("%Y-%m-%d")

def get_current_week_key():
    """Returns the current week key in format YYYY-WW"""
    now = datetime.now(ARG_TZ)
    return f"{now.year}-{now.isocalendar()[1]:02d}"

def get_random_member(group_name: str) -> str:
    """Get a random member from a group, or return 'a member' if none exist."""
    group_entry = group_data.get(group_name, {})
    members = group_entry.get('members', [])
    if members:
        member = random.choice(members)
        # FIX: Handle both dict and string members
        if isinstance(member, dict):
            return member.get('name', 'a member')
        return member
    return "a member"

def get_random_other_group(exclude_group: str) -> str | None:
    active_groups = [
        g for g, gd in group_data.items()
        if not gd.get('is_disbanded') and g != exclude_group
    ]
    return random.choice(active_groups) if active_groups else None

@tasks.loop(hours=1)
async def monthly_tax_check():
    """Check if it's the first day of a new month and deduct taxes from companies."""
    now = datetime.now()
    current_month_key = f"{now.year}-{now.month:02d}"
    
    if now.day == 1:
        companies_taxed = []
        tax_amount = 30_000_000
        
        for company_name, funds in list(company_funds.items()):
            company_groups = [g for g, gd in group_data.items() if gd.get('company') == company_name and not gd.get('is_disbanded')]
            if not company_groups:
                continue
            
            last_tax = None
            for g in company_groups:
                last = group_data[g].get('last_tax_month')
                if last:
                    last_tax = last
                    break
            
            if last_tax != current_month_key:
                old_funds = company_funds[company_name]
                company_funds[company_name] = max(0, old_funds - tax_amount)
                for g in company_groups:
                    group_data[g]['last_tax_month'] = current_month_key
                companies_taxed.append((company_name, old_funds, company_funds[company_name]))
        
        if companies_taxed:
            save_data()
            print(f"Monthly taxes collected from {len(companies_taxed)} companies")

events_channel_id = None
last_random_timestamp = None

def get_random_song_from_group(group_name: str):
    """Get a random song from any of the group's albums."""
    group_albums = [a for a, ad in album_data.items() if ad.get('group') == group_name]
    if not group_albums:
        return None, None
    


def get_group_owner_user_id(group_name: str):
    """Get the Discord user ID of the company owner for a group."""
    company = group_data.get(group_name, {}).get('company')
    if not company:
        return None
    for user_id, companies in user_companies.items():
        if company in companies:
            return user_id
    return None

def add_song_streams(songs: dict, song_name: str, streams_to_add: int, current_week: str = None) -> int:
    """Add streams to a song."""
    if song_name not in songs:
        return 0
    
    song_data = songs[song_name]
    current_streams = song_data.get('streams', 0)
    
    song_data['streams'] = current_streams + streams_to_add
    if current_week:
        song_data.setdefault('weekly_streams', {})
        song_data['weekly_streams'][current_week] = song_data['weekly_streams'].get(current_week, 0) + streams_to_add
    
    today_key = get_today_str()
    song_data.setdefault('daily_streams', {})
    song_data['daily_streams'][today_key] = song_data['daily_streams'].get(today_key, 0) + streams_to_add
    
    keys = sorted(song_data['daily_streams'].keys())
    if len(keys) > 7:
        for old_key in keys[:-7]:
            del song_data['daily_streams'][old_key]
    
    return 0

@tasks.loop(hours=1)
async def weekly_streams_reset():
    """Open a new weekly bucket at the start of each week (Monday midnight).

    Uses Argentina time throughout, matching get_current_week_key(), so the
    rollover fires in the same timezone the week key is derived from.

    Previous weeks are kept: this opens the new week's counter rather than
    replacing the dict, which used to erase all stream history every Monday.
    """
    now = datetime.now(ARG_TZ)
    if now.weekday() != 0 or now.hour != 0:
        return

    current_week = get_current_week_key()
    opened = 0
    for album_name, album_entry in album_data.items():
        weeks = album_entry.get('weekly_streams')
        if not isinstance(weeks, dict):
            weeks = {}
            album_entry['weekly_streams'] = weeks
        if current_week not in weeks:
            weeks[current_week] = 0
            opened += 1

    if opened:
        save_data()
        print(f"Weekly streams: opened week {current_week} for {opened} album(s), history preserved")

# Track which birthdays have been announced today to avoid duplicates
announced_birthdays_today = set()

@tasks.loop(hours=1)
async def birthday_check():
    """Check for member birthdays and announce them."""
    global announced_birthdays_today
    
    now = datetime.now(ARG_TZ)
    today_str = now.strftime("%m-%d")
    today_date = now.strftime("%Y-%m-%d")
    
    # Reset announced set at midnight
    if now.hour == 0:
        announced_birthdays_today = set()
    
    # Only announce at specific hours (9 AM Argentina time)
    if now.hour != 9:
        return
    
    if not events_channel_id:
        return
    
    channel = bot.get_channel(events_channel_id)
    if not channel:
        return
    
    for group_name, group_entry in group_data.items():
        if group_entry.get('is_disbanded'):
            continue
        
        members = group_entry.get('members', [])
        for member in members:
            if not isinstance(member, dict):
                continue
            
            birthday = member.get('birthday')
            if not birthday:
                continue
            
            # Birthday format: MM-DD
            if birthday == today_str:
                member_name = member.get('name', 'Unknown')
                announce_key = f"{group_name}|{member_name}|{today_date}"
                
                if announce_key in announced_birthdays_today:
                    continue
                
                announced_birthdays_today.add(announce_key)
                
                try:
                    await channel.send(
                        f"🎂 **Happy Birthday!** Today is **{member_name}** of **{group_name}**'s birthday! 🎉🎈"
                    )
                except discord.errors.Forbidden:
                    pass

@birthday_check.before_loop
async def before_birthday_check():
    await bot.wait_until_ready()

# === UTILS ===
def ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

def format_number(num):
    if num >= 1_000_000_000: return f"{num / 1_000_000_000:.1f}B"
    if num >= 1_000_000: return f"{num / 1_000_000:.1f}M"
    if num >= 1_000: return f"{num / 1_000:.1f}K"
    return str(num)

def get_user_companies(user_id: str):
    """Returns a list of company names owned by the user."""
    return user_companies.get(user_id, [])

def is_user_company_owner(user_id: str, company_name: str):
    """Checks if a user owns a specific company."""
    return company_name in get_user_companies(user_id)

def get_group_owner_company(group_name: str):
    """Returns the company name that owns the given group."""
    return group_data.get(group_name, {}).get('company')

def is_user_group_owner(user_id: str, group_name: str):
    """Checks if a user owns the company that manages a specific group."""
    group_owner_company = get_group_owner_company(group_name)
    return group_owner_company and is_user_company_owner(user_id, group_owner_company)

def check_cooldown(user_id: str, command_name: str, cooldown_minutes: int):
    """Checks if a user is on cooldown for a specific command."""
    last_used = user_cooldowns.get(user_id, {}).get(command_name)
    if last_used and (datetime.now() - last_used) < timedelta(minutes=cooldown_minutes):
        remaining = timedelta(minutes=cooldown_minutes) - (datetime.now() - last_used)
        return True, remaining
    return False, None

def update_cooldown(user_id: str, command_name: str):
    """Updates the cooldown for a user and command."""
    if user_id not in user_cooldowns:
        user_cooldowns[user_id] = {}
    user_cooldowns[user_id][command_name] = datetime.now()
    save_data()

def get_extra_uses(user_id: str, command_name: str) -> int:
    """Get the number of extra uses a user has purchased for a command."""
    user_data = user_daily_limits.setdefault(user_id, {})
    extras_key = f"extra_{command_name}"
    return user_data.get(extras_key, 0)

def add_extra_use(user_id: str, command_name: str):
    """Add one extra use for a command."""
    user_data = user_daily_limits.setdefault(user_id, {})
    extras_key = f"extra_{command_name}"
    user_data[extras_key] = user_data.get(extras_key, 0) + 1
    save_data()

def get_total_extras_purchased(user_id: str) -> int:
    """Get total extra uses purchased across all commands (for pricing tiers)."""
    user_data = user_daily_limits.get(user_id, {})
    total = 0
    for key in user_data:
        if key.startswith('extra_'):
            total += user_data[key]
    return total

def check_daily_limit(user_id: str, command_name: str, max_uses: int):
    """Checks and updates daily command usage, including purchased extra uses.
    Resets at 00:00 Argentina time (UTC-3)."""
    today = datetime.now(ARG_TZ).strftime("%Y-%m-%d")
    user_data = user_daily_limits.setdefault(user_id, {})
    command_data = user_data.setdefault(command_name, {})
    
    extra_uses = get_extra_uses(user_id, command_name)
    total_max = max_uses + extra_uses

    current_uses = command_data.get(today, 0)

    if current_uses >= total_max:
        return True, total_max - current_uses # True for limited, 0 remaining

    command_data[today] = current_uses + 1
    save_data()
    return False, total_max - (current_uses + 1) # False for not limited, remaining uses


ADMIN_USER_ID = 979346606233104415

admin_logs = []

def add_audit_log(admin_id: str, action: str, target: str, before, after):
    """Add an entry to the admin audit log."""
    global admin_logs
    entry = {
        "admin_id": admin_id,
        "action": action,
        "target": target,
        "before": before,
        "after": after,
        "timestamp": datetime.now().isoformat()
    }
    admin_logs.append(entry)
    if len(admin_logs) > 500:
        admin_logs = admin_logs[-500:]
    save_data()

def ensure_member_schema(member_data: dict, base_pop: int = None) -> dict:
    """Ensure member has all required fields with proper schema.
    
    Args:
        member_data: The member data dict (or string name to convert)
        base_pop: Base popularity to use for new members (defaults to 50 if not provided)
    """
    if not isinstance(member_data, dict):
        member_data = {'name': str(member_data)}
    
    member_data.setdefault('name', 'Unknown')
    member_data.setdefault('popularity', base_pop if base_pop is not None else 50)
    member_data.setdefault('level', 1)
    member_data.setdefault('exp', 0)
    member_data.setdefault('exp_to_next', 100)
    member_data.setdefault('skills', {
        'vocal': {'value': 30, 'cap': 100},
        'dance': {'value': 30, 'cap': 100},
        'stage': {'value': 30, 'cap': 100}
    })
    member_data.setdefault('fan_ratios', {
        'teen': 0.5, 'adult': 0.5,
        'female': 0.5, 'male': 0.5
    })
    member_data.setdefault('fan_multipliers', {'teen': 1.0, 'adult': 1.0, 'female': 1.0, 'male': 1.0})
    member_data.setdefault('image_url', None)
    member_data.setdefault('bio', '')
    member_data.setdefault('history', [])
    member_data.setdefault('group', None)
    return member_data

def recalc_group_from_members(group_name: str):
    """Recalculate group popularity as SUM of member popularities."""
    if group_name not in group_data:
        return
    group_entry = group_data[group_name]
    members = group_entry.get('members', [])
    if not members:
        return
    
    member_pops = []
    for m in members:
        if isinstance(m, dict):
            member_pops.append(m.get('popularity', 50))
    
    # Group popularity = SUM of all member popularities
    total_pop = sum(member_pops) if member_pops else group_entry.get('popularity', 100)
    group_entry['popularity'] = total_pop
    if group_name in group_popularity:
        group_popularity[group_name] = total_pop

def redistribute_popularity(group_name: str, target_total: int = None):
    """Redistribute: DIVIDE total group popularity among members with variance.
    
    Args:
        group_name: The group to redistribute popularity for
        target_total: The TOTAL popularity to divide among members.
                     If None, uses the group's current popularity field.
    
    The total is divided among members with random variance (0.7x to 1.3x base share)
    while ensuring the sum equals the original total.
    """
    if group_name not in group_data:
        return False
    group_entry = group_data[group_name]
    members = group_entry.get('members', [])
    if not members:
        return False
    
    # Use target_total if provided, otherwise use current group popularity
    total_pop = target_total if target_total is not None else group_entry.get('popularity', 100)
    num_members = len(members)
    
    if num_members == 0:
        return False
    
    # Calculate base share per member
    base_share = total_pop // num_members
    
    # Generate random weights for variance (0.7 to 1.3)
    weights = [random.uniform(0.7, 1.3) for _ in range(num_members)]
    weight_sum = sum(weights)
    
    # Normalize weights and distribute popularity
    member_pops = []
    for w in weights:
        normalized = (w / weight_sum) * total_pop
        member_pops.append(max(10, int(normalized)))  # Minimum 10 popularity
    
    # Adjust to ensure sum equals total exactly
    diff = total_pop - sum(member_pops)
    if diff != 0:
        # Add/remove the difference from a random member
        idx = random.randint(0, num_members - 1)
        member_pops[idx] = max(10, member_pops[idx] + diff)
    
    # Apply to members
    for i, m in enumerate(members):
        if isinstance(m, dict):
            m['popularity'] = member_pops[i]
        else:
            new_member = ensure_member_schema({'name': m}, base_pop=member_pops[i])
            new_member['group'] = group_name
            members[i] = new_member
    
    # Group popularity stays as the total
    group_entry['popularity'] = total_pop
    save_data()
    return True

def get_training_cost(member_level: int) -> int:
    """Calculate training cost based on member level. Scalable formula."""
    return max(10000, int(10000 * (member_level ** 1.4)))


# === DYNAMIC PERFORMANCE SYSTEM ===

def calculate_dynamic_result(base_value: int, tier_floor: int, tier_cap: int, 
                            variance_range: tuple = (0.6, 1.4), 
                            viral_chance: float = 0.0, viral_mult_range: tuple = (1.5, 3.0)) -> dict:
    """Calculate a randomized performance result with variance and optional viral bonus.
    
    Returns dict with: base, variance_mult, result, went_viral, viral_bonus, final
    """
    # Apply random variance (never identical outputs)
    variance_mult = random.uniform(variance_range[0], variance_range[1])
    varied_result = int(base_value * variance_mult)
    
    # Clamp to tier bounds
    clamped_result = max(tier_floor, min(tier_cap, varied_result))
    
    # Check for viral (rare, chance-based)
    went_viral = False
    viral_bonus = 0
    if viral_chance > 0 and random.random() < viral_chance:
        went_viral = True
        viral_mult = random.uniform(viral_mult_range[0], viral_mult_range[1])
        viral_bonus = int(clamped_result * (viral_mult - 1))
    
    final = min(tier_cap * 2, clamped_result + viral_bonus)  # Allow viral to exceed cap slightly
    
    return {
        'base': base_value,
        'variance_mult': variance_mult,
        'result': clamped_result,
        'went_viral': went_viral,
        'viral_bonus': viral_bonus,
        'final': final
    }


def get_tier_bounds(popularity: int, command_type: str = 'streams') -> tuple:
    """Get tier floor and cap based on group popularity and command type.
    
    Returns: (tier_floor, tier_cap, tier_name)
    """
    # Different caps for different command types
    if command_type == 'streams':
        if popularity < 500:
            return (500, 15000, 'nugu')
        elif popularity < 2000:
            return (8000, 50000, 'mid')
        elif popularity < 6000:
            return (30000, 120000, 'popular')
        else:
            return (60000, 200000, 'top')
    
    elif command_type == 'streamsong':
        if popularity < 500:
            return (300, 10000, 'nugu')
        elif popularity < 2000:
            return (5000, 35000, 'mid')
        elif popularity < 6000:
            return (20000, 80000, 'popular')
        else:
            return (40000, 150000, 'top')
    
    elif command_type == 'views':
        if popularity < 500:
            return (600, 18000, 'nugu')
        elif popularity < 2000:
            return (10000, 60000, 'mid')
        elif popularity < 6000:
            return (40000, 130000, 'popular')
        else:
            return (80000, 220000, 'top')
    
    elif command_type == 'concert':
        if popularity < 500:
            return (100000, 1000000, 'nugu')
        elif popularity < 2000:
            return (500000, 4000000, 'mid')
        elif popularity < 6000:
            return (2000000, 10000000, 'popular')
        else:
            return (5000000, 15000000, 'top')
    
    else:  # Default
        return (100, 10000, 'default')


def shift_demographics(group_entry: dict, activity_type: str):
    """Shift fan demographics based on activity type. Small changes, always normalized.
    
    Activity mappings:
    POST TYPES:
    - selfie/bts/boyfriend_pov → teen ↑, female ↑
    - meme/challenge → teen ↑, male ↑
    - artistry/serious → adult ↑
    
    EVENTS:
    - fanmeeting → male ↑
    - merchandise → female ↑
    
    SPONSORSHIPS:
    - cosmetics/skincare → female ↑, adult ↑
    - gaming/energy_drink → male ↑, teen ↑
    - luxury_fashion → adult ↑, female ↑
    - kids_brand → teen ↑
    
    VARIETY ACTIVITIES:
    - variety_show → male ↑, teen ↑
    - music_show_mc → female ↑, teen ↑
    - drama_acting → adult ↑, female ↑
    - radio_podcast → adult ↑
    - fashion_magazine → female ↑, adult ↑
    - sports_event → male ↑
    - university_festival → teen ↑, male ↑
    """
    members = group_entry.get('members', [])
    if not members:
        return
    
    # Define shift amounts (small: 0.01-0.03)
    shift_amount = random.uniform(0.01, 0.03)
    
    activity_effects = {
        # Post types (all capped at 1.0x to stay within 0.01-0.03)
        'selfie': {'teen': shift_amount, 'female': shift_amount},
        'bts': {'teen': shift_amount * 0.8, 'female': shift_amount * 0.8},
        'boyfriend_pov': {'teen': shift_amount, 'female': shift_amount},
        'meme': {'teen': shift_amount, 'male': shift_amount},
        'challenge': {'teen': shift_amount, 'male': shift_amount * 0.8},
        'artistry': {'adult': shift_amount},
        'serious': {'adult': shift_amount * 0.8},
        
        # Legacy/generic
        'sns': {'teen': shift_amount, 'female': shift_amount * 0.5},
        'viral': {'teen': shift_amount, 'male': shift_amount * 0.5},
        'fan_event': {'female': shift_amount},
        
        # Events
        'fanmeeting': {'male': shift_amount},
        'merchandise': {'female': shift_amount},
        
        # Sponsorship categories (all capped at 1.0x)
        'cosmetics': {'female': shift_amount, 'adult': shift_amount * 0.8},
        'skincare': {'female': shift_amount * 0.9, 'adult': shift_amount * 0.9},
        'gaming': {'male': shift_amount, 'teen': shift_amount},
        'energy_drink': {'male': shift_amount * 0.9, 'teen': shift_amount * 0.9},
        'luxury_fashion': {'adult': shift_amount, 'female': shift_amount * 0.8},
        'kids_brand': {'teen': shift_amount},
        
        # Variety activities (all capped at 1.0x)
        'variety_show': {'male': shift_amount * 0.7, 'teen': shift_amount * 0.5},
        'variety': {'male': shift_amount * 0.7, 'teen': shift_amount * 0.5},
        'music_show_mc': {'female': shift_amount, 'teen': shift_amount * 0.7},
        'drama_acting': {'adult': shift_amount, 'female': shift_amount * 0.8},
        'radio_podcast': {'adult': shift_amount},
        'fashion_magazine': {'female': shift_amount, 'adult': shift_amount * 0.7},
        'sports_event': {'male': shift_amount},
        'university_festival': {'teen': shift_amount, 'male': shift_amount * 0.7},
        'sports': {'male': shift_amount},
        'festival': {'male': shift_amount * 0.5, 'teen': shift_amount * 0.3},
    }
    
    effects = activity_effects.get(activity_type, {})
    if not effects:
        return
    
    for m in members:
        if not isinstance(m, dict):
            continue
        
        fan_ratios = m.get('fan_ratios', {'teen': 0.5, 'adult': 0.5, 'female': 0.5, 'male': 0.5})
        
        # Apply effects
        for demo_type, shift in effects.items():
            if demo_type in ['teen', 'adult']:
                # Age group: teen + adult = 1
                if demo_type == 'teen':
                    fan_ratios['teen'] = min(0.9, fan_ratios.get('teen', 0.5) + shift)
                    fan_ratios['adult'] = max(0.1, 1.0 - fan_ratios['teen'])
                else:
                    fan_ratios['adult'] = min(0.9, fan_ratios.get('adult', 0.5) + shift)
                    fan_ratios['teen'] = max(0.1, 1.0 - fan_ratios['adult'])
            
            elif demo_type in ['female', 'male']:
                # Gender: female + male = 1
                if demo_type == 'female':
                    fan_ratios['female'] = min(0.9, fan_ratios.get('female', 0.5) + shift)
                    fan_ratios['male'] = max(0.1, 1.0 - fan_ratios['female'])
                else:
                    fan_ratios['male'] = min(0.9, fan_ratios.get('male', 0.5) + shift)
                    fan_ratios['female'] = max(0.1, 1.0 - fan_ratios['male'])
        
        m['fan_ratios'] = fan_ratios


def shift_demographics_for_members(members_list: list, activity_type: str):
    """Shift fan demographics for specific members only. Used when targeting specific members."""
    if not members_list:
        return
    
    shift_amount = random.uniform(0.01, 0.03)
    
    activity_effects = {
        'selfie': {'teen': shift_amount, 'female': shift_amount},
        'bts': {'teen': shift_amount * 0.8, 'female': shift_amount * 0.8},
        'boyfriend_pov': {'teen': shift_amount, 'female': shift_amount},
        'meme': {'teen': shift_amount, 'male': shift_amount},
        'challenge': {'teen': shift_amount, 'male': shift_amount * 0.8},
        'artistry': {'adult': shift_amount},
        'variety_show': {'male': shift_amount * 0.7, 'teen': shift_amount * 0.5},
        'music_show_mc': {'female': shift_amount, 'teen': shift_amount * 0.7},
        'drama_acting': {'adult': shift_amount, 'female': shift_amount * 0.8},
        'radio_podcast': {'adult': shift_amount},
        'fashion_magazine': {'female': shift_amount, 'adult': shift_amount * 0.7},
        'sports_event': {'male': shift_amount},
        'university_festival': {'teen': shift_amount, 'male': shift_amount * 0.7},
    }
    
    effects = activity_effects.get(activity_type, {})
    if not effects:
        return
    
    for m in members_list:
        if not isinstance(m, dict):
            continue
        
        fan_ratios = m.get('fan_ratios', {'teen': 0.5, 'adult': 0.5, 'female': 0.5, 'male': 0.5})
        
        for demo_type, shift in effects.items():
            if demo_type in ['teen', 'adult']:
                if demo_type == 'teen':
                    fan_ratios['teen'] = min(0.9, fan_ratios.get('teen', 0.5) + shift)
                    fan_ratios['adult'] = max(0.1, 1.0 - fan_ratios['teen'])
                else:
                    fan_ratios['adult'] = min(0.9, fan_ratios.get('adult', 0.5) + shift)
                    fan_ratios['teen'] = max(0.1, 1.0 - fan_ratios['adult'])
            elif demo_type in ['female', 'male']:
                if demo_type == 'female':
                    fan_ratios['female'] = min(0.9, fan_ratios.get('female', 0.5) + shift)
                    fan_ratios['male'] = max(0.1, 1.0 - fan_ratios['female'])
                else:
                    fan_ratios['male'] = min(0.9, fan_ratios.get('male', 0.5) + shift)
                    fan_ratios['female'] = max(0.1, 1.0 - fan_ratios['male'])
        
        m['fan_ratios'] = fan_ratios


def apply_level_up_bonuses(group_name: str, member: dict, old_level: int, new_level: int):
    """Apply meaningful bonuses when a member levels up."""
    if new_level <= old_level:
        return
    
    levels_gained = new_level - old_level
    group_entry = group_data.get(group_name, {})
    
    # Popularity bonus: 5-15 per level gained (distributed to group)
    pop_bonus = levels_gained * random.randint(5, 15)
    member['popularity'] = member.get('popularity', 50) + pop_bonus
    
    # GP bonus for group: 1-3 per level
    gp_bonus = levels_gained * random.randint(1, 3)
    group_entry['gp'] = group_entry.get('gp', 30) + gp_bonus
    
    # Fanbase bonus: 1-2 per level
    fanbase_bonus = levels_gained * random.randint(1, 2)
    group_entry['fanbase'] = group_entry.get('fanbase', 50) + fanbase_bonus
    
    # Recalculate group popularity from member sum
    recalc_group_from_members(group_name)
    
    return {'pop': pop_bonus, 'gp': gp_bonus, 'fanbase': fanbase_bonus}


def backfill_prereleases():
    """Auto-link any missing pre-release entries to group profiles on startup.
    Also ensures all albums in album_data are linked to their group's discography."""
    changed = False
    
    for album_name, prerelease_entry in preorder_data.items():
        group_name = prerelease_entry.get('group')
        if not group_name or group_name not in group_data:
            continue
        
        group_entry = group_data[group_name]
        group_entry.setdefault('prereleases', [])
        
        if album_name not in group_entry['prereleases']:
            group_entry['prereleases'].append(album_name)
            changed = True
    
    for album_name, album_entry in album_data.items():
        group_name = album_entry.get('group')
        if not group_name or group_name not in group_data:
            continue
        
        group_entry = group_data[group_name]
        
        if album_entry.get('is_preorder') or album_entry.get('status') == 'preorder':
            group_entry.setdefault('prereleases', [])
            if album_name not in group_entry['prereleases']:
                group_entry['prereleases'].append(album_name)
                changed = True
        else:
            group_entry.setdefault('albums', [])
            if album_name not in group_entry['albums']:
                group_entry['albums'].append(album_name)
                changed = True
    
    if changed:
        save_data()


def update_nations_group():
    """Updates the Nation's Group status. Only 1 group can hold this title at a time.
    Requirements: GP >= 1000, highest GP among all groups, not disbanded, no active hate train."""
    current_nations_group = None
    highest_gp = 0
    
    for group_name, group_entry in group_data.items():
        group_entry['is_nations_group'] = False
        
        if group_entry.get('is_disbanded'):
            continue
        if group_entry.get('active_hate_train'):
            continue
        
        gp = group_entry.get('gp', 30)
        if gp >= 1000 and gp > highest_gp:
            highest_gp = gp
            current_nations_group = group_name
    
    if current_nations_group:
        group_data[current_nations_group]['is_nations_group'] = True
    
    return current_nations_group


# === AUTOCOMPLETE FUNCTIONS ===
async def group_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for group names."""
    choices = []
    for name in group_data.keys():
        if current.lower() in name.lower():
            choices.append(app_commands.Choice(name=name[:100], value=name[:100]))
            if len(choices) >= 25:
                break
    return choices

async def album_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for album names."""
    choices = []
    for name in album_data.keys():
        if current.lower() in name.lower():
            choices.append(app_commands.Choice(name=name[:100], value=name[:100]))
            if len(choices) >= 25:
                break
    return choices

async def company_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for company names."""
    choices = []
    for name in company_funds.keys():
        if current.lower() in name.lower():
            choices.append(app_commands.Choice(name=name[:100], value=name[:100]))
            if len(choices) >= 25:
                break
    return choices

async def user_company_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for companies owned by the user."""
    user_id = str(interaction.user.id)
    owned = get_user_companies(user_id)
    choices = []
    for name in owned:
        if current.lower() in name.lower():
            choices.append(app_commands.Choice(name=name[:100], value=name[:100]))
            if len(choices) >= 25:
                break
    return choices

async def user_group_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for groups owned by the user's companies."""
    user_id = str(interaction.user.id)
    owned_companies = get_user_companies(user_id)
    choices = []
    for name, data in group_data.items():
        if data.get('company') in owned_companies:
            if current.lower() in name.lower():
                choices.append(app_commands.Choice(name=name[:100], value=name[:100]))
                if len(choices) >= 25:
                    break
    return choices

async def user_album_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for albums from groups owned by the user."""
    user_id = str(interaction.user.id)
    owned_companies = get_user_companies(user_id)
    choices = []
    for name, data in album_data.items():
        group_name = data.get('group')
        if group_name and group_data.get(group_name, {}).get('company') in owned_companies:
            if current.lower() in name.lower():
                choices.append(app_commands.Choice(name=name[:100], value=name[:100]))
                if len(choices) >= 25:
                    break
    return choices

async def active_24h_album_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for albums with active 24h tracking."""
    choices = []
    for name, data in album_data.items():
        tracking = data.get('first_24h_tracking')
        if tracking and not tracking.get('ended', False):
            if current.lower() in name.lower():
                choices.append(app_commands.Choice(name=name[:100], value=name[:100]))
                if len(choices) >= 25:
                    break
    return choices

async def song_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for song names across all albums."""
    choices = []
    for album_name, album_entry in album_data.items():
        songs = album_entry.get('songs', {})
        if not isinstance(songs, dict):
            continue
        group_name = album_entry.get('group', '')
        for song_name in songs.keys():
            if current.lower() in song_name.lower():
                display = f"{song_name} ({group_name})"[:100]
                choices.append(app_commands.Choice(name=display, value=song_name[:100]))
                if len(choices) >= 25:
                    return choices
    return choices

async def city_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for concert cities."""
    choices = []
    for city in CONCERT_CITIES:
        if current.lower() in city.lower():
            choices.append(app_commands.Choice(name=city, value=city))
            if len(choices) >= 25:
                break
    return choices

async def member_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for member names across all groups."""
    choices = []
    for group_name, group_entry in group_data.items():
        members = group_entry.get('members', [])
        if not isinstance(members, list):
            continue
        for member in members:
            if isinstance(member, dict):
                member_name = member.get('name', '')
            elif isinstance(member, str):
                member_name = member
            else:
                continue
            if member_name and current.lower() in member_name.lower():
                display = f"{member_name} ({group_name})"[:100]
                choices.append(app_commands.Choice(name=display, value=f"{group_name}|{member_name}"[:100]))
                if len(choices) >= 25:
                    return choices
    return choices

async def user_member_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for members from groups owned by the user."""
    user_id = str(interaction.user.id)
    owned_companies = get_user_companies(user_id)
    choices = []
    for group_name, group_entry in group_data.items():
        if group_entry.get('company') not in owned_companies:
            continue
        members = group_entry.get('members', [])
        if not isinstance(members, list):
            continue
        for member in members:
            if isinstance(member, dict):
                member_name = member.get('name', '')
            elif isinstance(member, str):
                member_name = member
            else:
                continue
            if member_name and current.lower() in member_name.lower():
                display = f"{member_name} ({group_name})"[:100]
                choices.append(app_commands.Choice(name=display, value=f"{group_name}|{member_name}"[:100]))
                if len(choices) >= 25:
                    return choices
    return choices

async def music_show_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for music show names."""
    choices = []
    for show_name in MUSIC_SHOWS.keys():
        if current.lower() in show_name.lower():
            choices.append(app_commands.Choice(name=show_name, value=show_name))
            if len(choices) >= 25:
                break
    return choices

async def group_album_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for albums filtered by selected group (for /addwin)."""
    group_name = interaction.namespace.group_name
    if not group_name:
        return []
    
    group_name_upper = group_name.upper()
    choices = []
    for name, data in album_data.items():
        if data.get('group') == group_name_upper:
            if current.lower() in name.lower():
                choices.append(app_commands.Choice(name=name[:100], value=name[:100]))
                if len(choices) >= 25:
                    break
    return choices

async def preorder_group_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for groups that have active preorders."""
    choices = []
    groups_with_preorders = set()
    for key, entry in preorder_data.items():
        if entry.get('status') == 'open':
            groups_with_preorders.add(entry.get('group', ''))
    
    for group_name in groups_with_preorders:
        if current.lower() in group_name.lower():
            choices.append(app_commands.Choice(name=group_name[:100], value=group_name[:100]))
            if len(choices) >= 25:
                break
    return choices

async def preorder_album_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for albums with active preorders."""
    group_name = interaction.namespace.group_name
    choices = []
    
    for key, entry in preorder_data.items():
        if entry.get('status') != 'open':
            continue
        
        album_name = entry.get('album_name', '')
        entry_group = entry.get('group', '')
        
        if group_name and entry_group.lower() != group_name.lower():
            continue
        
        if current.lower() in album_name.lower():
            display = f"{album_name} ({entry_group})"[:100] if not group_name else album_name[:100]
            choices.append(app_commands.Choice(name=display, value=album_name[:100]))
            if len(choices) >= 25:
                break
    return choices


# === INTERACTIVE VIEWS ===
class AlbumSelectView(ui.View):
    """A view with buttons to select an album for streaming/sales/views."""
    def __init__(self, albums: list, action_type: str, user_id: int):
        super().__init__(timeout=60)
        self.action_type = action_type
        self.user_id = user_id
        self.selected_album = None
        
        for album_name in albums[:5]:
            btn = ui.Button(label=album_name[:80], style=discord.ButtonStyle.primary)
            btn.callback = self.make_callback(album_name)
            self.add_item(btn)
    
    def make_callback(self, album_name: str):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Not your selection.", ephemeral=True)
                return
            self.selected_album = album_name
            self.stop()
            await interaction.response.defer()
        return callback
    
    async def on_timeout(self):
        self.stop()


class GroupSelectView(ui.View):
    """A view with buttons to select a group."""
    def __init__(self, groups: list, action_type: str, user_id: int):
        super().__init__(timeout=60)
        self.action_type = action_type
        self.user_id = user_id
        self.selected_group = None
        
        for group_name in groups[:5]:
            btn = ui.Button(label=group_name[:80], style=discord.ButtonStyle.primary)
            btn.callback = self.make_callback(group_name)
            self.add_item(btn)
    
    def make_callback(self, group_name: str):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Not your selection.", ephemeral=True)
                return
            self.selected_group = group_name
            self.stop()
            await interaction.response.defer()
        return callback
    
    async def on_timeout(self):
        self.stop()


class ActionSelectView(ui.View):
    """A view to select stream/sales/views action."""
    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.selected_action = None
    
    @ui.button(label="Stream", style=discord.ButtonStyle.green, emoji=None)
    async def stream_btn(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your selection.", ephemeral=True)
            return
        self.selected_action = "stream"
        self.stop()
        await interaction.response.defer()
    
    @ui.button(label="Buy Album", style=discord.ButtonStyle.blurple)
    async def sales_btn(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your selection.", ephemeral=True)
            return
        self.selected_action = "sales"
        self.stop()
        await interaction.response.defer()
    
    @ui.button(label="Watch MV", style=discord.ButtonStyle.red)
    async def views_btn(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your selection.", ephemeral=True)
            return
        self.selected_action = "views"
        self.stop()
        await interaction.response.defer()


# === DECORATORS ===
def is_admin():
    async def predicate(interaction: discord.Interaction):

        admin_user_ids = [979346606233104415]
        if interaction.user.id == bot.owner_id or interaction.user.id in admin_user_ids:
            return True
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return False
    return app_commands.check(predicate)

# === BASIC ECONOMY ===
@bot.tree.command(description="Check your balance")
async def balance(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    bal = user_balances.get(user_id, 0)
    await interaction.response.send_message(f"💰 {interaction.user.display_name}, your balance is <:MonthlyPeso:1338642658436059239>{bal:,}.")

@bot.tree.command(description="Work to earn money")
async def work(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    
    is_limited, remaining_uses = check_daily_limit(user_id, "work", DAILY_LIMITS["work"])
    if is_limited:
        await interaction.response.send_message(f"❌ You've reached your daily work limit! Come back tomorrow. (0 uses remaining)", ephemeral=True)
        return
    
    current_bal = user_balances.get(user_id, 0)
    pay = random.randint(10000, 50000)
    new_bal = current_bal + pay
    user_balances[user_id] = new_bal
    save_data() 
    await interaction.response.send_message(f"💼 {interaction.user.display_name}, you worked and earned <:MonthlyPeso:1338642658436059239>{pay:,}! ({remaining_uses} uses left today)")

@bot.tree.command(description="Claim your daily money reward")
async def daily(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    
    is_limited, remaining_uses = check_daily_limit(user_id, "daily", 1)
    if is_limited:
        await interaction.response.send_message(f"⏳ You already claimed your daily reward today!", ephemeral=True)
        return

    current_bal = user_balances.get(user_id, 0)
    pay = 100_000
    new_bal = current_bal + pay
    user_balances[user_id] = new_bal
    save_data() 
    await interaction.response.send_message(f"🖖 {interaction.user.display_name}, you claimed your daily <:MonthlyPeso:1338642658436059239>{pay:,}!")

@bot.tree.command(description="Invest in any company (transfer personal funds to company)")
@app_commands.autocomplete(company_name=company_autocomplete)
async def invest(interaction: discord.Interaction, company_name: str, amount: int):
    user_id = str(interaction.user.id)
    user_bal = user_balances.get(user_id, 0)

    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
        return

    if user_bal < amount:
        await interaction.response.send_message("❌ Not enough personal funds to invest.", ephemeral=True)
        return

    company_name_upper = company_name.upper()

    if company_name_upper not in company_funds:
        await interaction.response.send_message("❌ Company not found.", ephemeral=True)
        return

    current_company_funds = company_funds.get(company_name_upper, 0)

    user_balances[user_id] = user_bal - amount
    company_funds[company_name_upper] = current_company_funds + amount
    save_data() 

    await interaction.response.send_message(f"📈 You invested <:MonthlyPeso:1338642658436059239>{amount:,} in **{company_name_upper}**!")


@bot.tree.command(description="Withdraw funds from your company to personal balance")
@app_commands.autocomplete(company_name=user_company_autocomplete)
async def withdraw(interaction: discord.Interaction, company_name: str, amount: int):
    user_id = str(interaction.user.id)
    company_name_upper = company_name.upper()

    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
        return

    if company_name_upper not in company_funds:
        await interaction.response.send_message("❌ Company not found.", ephemeral=True)
        return

    if not is_user_company_owner(user_id, company_name_upper):
        await interaction.response.send_message(f"❌ You do not own the company `{company_name}`.", ephemeral=True)
        return

    current_company_funds = company_funds.get(company_name_upper, 0)

    if current_company_funds < amount:
        await interaction.response.send_message(f"❌ Not enough company funds. **{company_name_upper}** only has <:MonthlyPeso:1338642658436059239>{format_number(current_company_funds)}.", ephemeral=True)
        return

    company_funds[company_name_upper] = current_company_funds - amount
    user_balances[user_id] = user_balances.get(user_id, 0) + amount
    save_data() 

    await interaction.response.send_message(f"💸 Withdrew <:MonthlyPeso:1338642658436059239>{amount:,} from **{company_name_upper}** to your personal balance!")

@bot.tree.command(description="Check a company's funds")
@app_commands.autocomplete(company_name=company_autocomplete)
async def companyfunds(interaction: discord.Interaction, company_name: str):
    company_name_upper = company_name.upper()

    if company_name_upper not in company_funds:
        await interaction.response.send_message(f"❌ Company `{company_name}` not found.")
    else:
        funds = company_funds.get(company_name_upper, 0)
        await interaction.response.send_message(f"🏢 {company_name}'s Funds: <:MonthlyPeso:1338642658436059239>{funds:,}")

@bot.tree.command(description="Buy physical album copies!")
@app_commands.autocomplete(album_name=album_autocomplete)
async def sales(interaction: discord.Interaction, album_name: str):
    user_id = str(interaction.user.id)
    
    is_limited, remaining_uses = check_daily_limit(user_id, "sales", DAILY_LIMITS["sales"])
    if is_limited:
        await interaction.response.send_message(f"❌ You've reached your daily sales limit! (0 uses remaining)", ephemeral=True)
        return
    
    if album_name not in album_data:
        await interaction.response.send_message("Album not found.", ephemeral=True)
        return

    current_album_data = album_data[album_name]
    group_name = current_album_data.get('group')
    if not group_name or group_name not in group_data:
        await interaction.response.send_message("Album group not found.", ephemeral=True)
        return

    if group_data[group_name].get('is_disbanded'):
        await interaction.response.send_message(f"Cannot buy albums for disbanded groups.", ephemeral=True)
        return

    album_format = current_album_data.get('album_format', 'physical')
    if album_format == 'digital':
        await interaction.response.send_message("This is a digital release - physical copies not available.", ephemeral=True)
        return
    
    current_stock = current_album_data.get('stock', 0)
    if current_stock <= 0:
        await interaction.response.send_message(f"'{album_name}' is **SOLD OUT**! No stock remaining.", ephemeral=True)
        return

    group_entry = group_data[group_name]
    group_current_popularity = get_group_derived_popularity(group_entry)
    fanbase = group_entry.get('fanbase', 50)
    gp = group_entry.get('gp', 30)
    
    import math
    
    # Get tier bounds for sales
    tier_floor, tier_cap, tier_name = get_tier_bounds(group_current_popularity, 'sales')
    
    # Calculate base sales
    effective_pop = group_current_popularity + (fanbase * 0.8) + (gp * 0.2)
    soft_pop = math.sqrt(effective_pop)
    base_sales = int(soft_pop * (tier_cap / math.sqrt(tier_cap)))
    base_sales = max(tier_floor, min(tier_cap, base_sales))
    
    # Apply demographic multipliers
    demo_mults = get_demographic_multipliers(group_entry)
    base_sales = int(base_sales * demo_mults['sales'])
    base_sales = int(base_sales * demo_mults['fandom'])
    
    # Use dynamic result system for variance (wide: 0.5-1.5)
    result = calculate_dynamic_result(
        base_value=base_sales,
        tier_floor=tier_floor,
        tier_cap=tier_cap,
        variance_range=(0.5, 1.5),
        viral_chance=0.05,  # 5% chance for bulk orders
        viral_mult_range=(1.5, 2.5)
    )
    
    sales_to_add = result['final']
    went_bulk = result['went_viral']  # "viral" = bulk order in sales context
    sales_to_add = int(sales_to_add * _get_hidden_bonus(group_name))
    
    update_nations_group()
    if group_entry.get('is_nations_group'):
        sales_to_add = int(sales_to_add * 1.20)
    
    actual_stock = current_album_data.get('stock', 0)
    if actual_stock <= 0:
        await interaction.response.send_message(f"'{album_name}' is **SOLD OUT**!", ephemeral=True)
        return
    sales_to_add = min(sales_to_add, actual_stock)
    current_album_data['stock'] = max(0, actual_stock - sales_to_add)
    current_album_data['sales'] = current_album_data.get('sales', 0) + sales_to_add

    if current_album_data.get('first_24h_tracking'):
        tracking = current_album_data['first_24h_tracking']
        if not tracking.get('ended', False):
            tracking['sales'] = tracking.get('sales', 0) + sales_to_add

    company_name = group_data[group_name]['company']
    if company_name in company_funds:
        company_funds[company_name] += sales_to_add
    else:
        company_funds[company_name] = sales_to_add

    update_cooldown(user_id, "sales")
    save_data() 
    
    bulk_text = " 📦 BULK ORDER!" if went_bulk else ""
    embed = discord.Embed(
        title=album_name,
        description=f"**{group_name}**{bulk_text} • Physical Album",
        color=discord.Color.gold() if went_bulk else discord.Color.green()
    )
    embed.set_thumbnail(url=sanitize_url(current_album_data.get('image_url')))
    embed.add_field(name="Bought", value=f"+{format_number(sales_to_add)}", inline=True)
    embed.add_field(name="Stock Left", value=f"{format_number(current_album_data['stock'])}", inline=True)
    embed.set_footer(text=f"Total Sales: {format_number(current_album_data['sales'])} | {remaining_uses} uses left today")

    await interaction.response.send_message(embed=embed)

    if current_album_data['stock'] == 0:
        try:
            await interaction.channel.send(f"**{album_name}** just SOLD OUT!")
        except discord.errors.Forbidden:
            pass


@bot.tree.command(description="Restock a physical album (costs company funds).")
@app_commands.describe(
    album_name="The album to restock",
    amount="Number of copies to add (default: 500,000)"
)
@app_commands.autocomplete(album_name=user_album_autocomplete)
async def restock(interaction: discord.Interaction, album_name: str, amount: int = 500000):
    user_id = str(interaction.user.id)
    
    if album_name not in album_data:
        await interaction.response.send_message("Album not found.", ephemeral=True)
        return
    
    current_album = album_data[album_name]
    group_name = current_album.get('group')
    
    if not group_name or group_name not in group_data:
        await interaction.response.send_message("Album group not found.", ephemeral=True)
        return
    
    if not is_user_group_owner(user_id, group_name):
        await interaction.response.send_message("You don't manage this group.", ephemeral=True)
        return
    
    if current_album.get('album_format') == 'digital':
        await interaction.response.send_message("Can't restock a digital album.", ephemeral=True)
        return
    
    if amount < 10000:
        await interaction.response.send_message("Minimum restock is 10,000 copies.", ephemeral=True)
        return
    
    if amount > 2000000:
        await interaction.response.send_message("Maximum restock is 2,000,000 copies at once.", ephemeral=True)
        return
    
    cost_per_copy = 0.50
    total_cost = round(amount * cost_per_copy)
    
    company_name = group_data[group_name].get('company')
    if not company_name or company_name not in company_funds:
        await interaction.response.send_message("Company not found.", ephemeral=True)
        return
    
    if company_funds[company_name] < total_cost:
        await interaction.response.send_message(f"Not enough funds! Need <:MonthlyPeso:1338642658436059239>{format_number(total_cost)} to restock {format_number(amount)} copies.", ephemeral=True)
        return
    
    company_funds[company_name] -= total_cost
    current_album['stock'] = current_album.get('stock', 0) + amount
    save_data()
    
    embed = discord.Embed(
        title=f"Restocked - {album_name}",
        description=f"Added **{format_number(amount)}** copies to inventory!",
        color=discord.Color.from_rgb(255, 105, 180)
    )
    embed.add_field(name="Cost", value=f"<:MonthlyPeso:1338642658436059239>{format_number(total_cost)}", inline=True)
    embed.add_field(name="New Stock", value=f"{format_number(current_album['stock'])}", inline=True)
    embed.set_footer(text=f"Company: {company_name}")
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Add a music show win to a group and album")
@app_commands.describe(
    group_name="The group that won",
    show_name="The music show where they won",
    album_name="The album/song that won"
)
@app_commands.autocomplete(group_name=group_autocomplete, show_name=music_show_autocomplete, album_name=group_album_autocomplete)
async def addwin(interaction: discord.Interaction, group_name: str, show_name: str, album_name: str):
    group_name_upper = group_name.upper()

    if group_name_upper not in group_data:
        await interaction.response.send_message(f"❌ Group `{group_name}` not found.")
        return
    if album_name not in album_data or album_data[album_name].get('group') != group_name_upper:
        await interaction.response.send_message(f"❌ Album `{album_name}` not found or does not belong to `{group_name}`.")
        return

    if group_data[group_name_upper].get('is_disbanded'):
        await interaction.response.send_message(f"❌ Cannot add a win for {group_name_upper} as they are disbanded.", ephemeral=True)
        return

    group_entry = group_data[group_name_upper]
    album_entry = album_data[album_name]

    # Increment album's specific wins
    album_entry['wins'] = album_entry.get('wins', 0) + 1

    # Recalculate the group's total: wins not tied to an album, plus album wins.
    # base_wins must be included or wins earned before album-level tracking, and
    # any imported history, would be wiped out here.
    group_total_wins = group_entry.get('base_wins', 0)
    for alb_n in group_entry.get('albums', []):
        if alb_n in album_data:
            group_total_wins += album_data[alb_n].get('wins', 0)

    group_entry['wins'] = group_total_wins

    # Increase group popularity (distributed to members)
    distribute_stat_gain_to_members(group_name_upper, 'popularity', 5)

    save_data()

    await interaction.response.send_message(
        f"🏆 {group_name_upper} wins on {show_name} with {album_name}!"
    )

POST_TYPES = {
    'selfie': {'name': 'Selfie / Selfie Dump', 'description': 'Teen ↑ Female ↑'},
    'bts': {'name': 'Behind-the-Scenes', 'description': 'Teen ↑ Female ↑'},
    'boyfriend_pov': {'name': 'Boyfriend/Girlfriend POV', 'description': 'Teen ↑↑ Female ↑↑'},
    'meme': {'name': 'Funny Meme / Joke', 'description': 'Teen ↑ Male ↑'},
    'challenge': {'name': 'Challenge Video', 'description': 'Teen ↑ Male ↑'},
    'artistry': {'name': 'Artistry / Serious Post', 'description': 'Adult ↑'},
}

@bot.tree.command(description="Post a new social media update for your group!")
@app_commands.describe(
    group_name="The group making the post",
    post_type="Type of post",
    members="Optional: Member name(s) in the post (comma-separated). If blank, whole group participates."
)
@app_commands.choices(post_type=[
    app_commands.Choice(name="Selfie / Selfie Dump", value="selfie"),
    app_commands.Choice(name="Behind-the-Scenes", value="bts"),
    app_commands.Choice(name="Boyfriend/Girlfriend POV", value="boyfriend_pov"),
    app_commands.Choice(name="Funny Meme / Joke", value="meme"),
    app_commands.Choice(name="Challenge Video", value="challenge"),
    app_commands.Choice(name="Artistry / Serious Post", value="artistry"),
])
@app_commands.autocomplete(group_name=group_autocomplete)
async def newpost(interaction: discord.Interaction, group_name: str, post_type: str = "selfie", members: str = None):
    group_name_upper = group_name.upper()
    if group_name_upper not in group_data:
        await interaction.response.send_message(f"❌ Group `{group_name}` not found.")
        return

    if group_data[group_name_upper].get('is_disbanded'):
        await interaction.response.send_message(f"❌ Cannot create a new post for {group_name_upper} as they are disbanded.", ephemeral=True)
        return

    group_entry = group_data[group_name_upper]
    base_pop = get_group_derived_popularity(group_entry)

    variance = random.uniform(0.6, 1.4)
    likes = max(100, int(base_pop * 30 * variance))
    comments = max(10, int(base_pop * 3 * variance))

    popularity_gain = random.randint(1, 5)
    went_viral = False

    if random.random() < 0.12:
        viral_popularity_boost = random.randint(15, 30)
        popularity_gain += viral_popularity_boost
        went_viral = True

    participating_members = []
    if members:
        member_names = [m.strip().upper() for m in members.split(',')]
        for m in group_entry.get('members', []):
            if isinstance(m, dict) and m.get('name', '').upper() in member_names:
                participating_members.append(m)
    
    if participating_members:
        pop_per_member = max(1, popularity_gain // len(participating_members))
        for m in participating_members:
            m['popularity'] = m.get('popularity', 50) + pop_per_member
        shift_demographics_for_members(participating_members, post_type)
        recalc_group_from_members(group_name_upper)
    else:
        distribute_stat_gain_to_members(group_name_upper, 'popularity', popularity_gain)
        shift_demographics(group_entry, post_type)
    
    post_info = POST_TYPES.get(post_type, POST_TYPES['selfie'])
    
    for album_name in group_entry.get('albums', []):
        if album_name in album_data:
            alb = album_data[album_name]
            if alb.get('is_active_promotion'):
                alb['sns_posts'] = alb.get('sns_posts', 0) + 1
                break

    save_data()

    viral_text = " ✨ VIRAL!" if went_viral else ""
    members_text = ""
    if participating_members:
        members_text = f"\n**Featuring:** {', '.join([m.get('name', '?') for m in participating_members])}"
    
    embed = discord.Embed(
        title=f"📱 {group_name_upper} - {post_info['name']}",
        description=f"**{group_name_upper}** posted new content!{viral_text}{members_text}",
        color=discord.Color.gold() if went_viral else discord.Color.from_rgb(255, 105, 180)
    )
    embed.add_field(name="❤️ Likes", value=format_number(likes), inline=True)
    embed.add_field(name="💬 Comments", value=format_number(comments), inline=True)
    embed.add_field(name="📈 Popularity", value=f"+{popularity_gain}", inline=True)
    
    await interaction.response.send_message(embed=embed)

# === FEATURES IMPLEMENTATION ===

@bot.tree.command(description="Stream an album!")
@app_commands.autocomplete(album_name=album_autocomplete)
async def streams(interaction: discord.Interaction, album_name: str):
    user_id = str(interaction.user.id)
    
    is_limited, remaining_uses = check_daily_limit(user_id, "streams", DAILY_LIMITS["streams"])
    if is_limited:
        await interaction.response.send_message(f"❌ You've reached your daily streaming limit! (0 uses remaining)", ephemeral=True)
        return
    
    if album_name not in album_data:
        await interaction.response.send_message("Album not found.", ephemeral=True)
        return

    current_album_data = album_data[album_name]
    group_name = current_album_data.get('group')
    if not group_name or group_name not in group_data:
        await interaction.response.send_message("Album group not found.", ephemeral=True)
        return

    group_entry = group_data[group_name]
    is_disbanded = group_entry.get('is_disbanded', False)
    group_current_popularity = get_group_derived_popularity(group_entry)
    fanbase = group_entry.get('fanbase', 50)
    gp = group_entry.get('gp', 30)

    import math
    
    # Get tier bounds based on group popularity (SUM of member pops)
    tier_floor, tier_cap, tier_name = get_tier_bounds(group_current_popularity, 'streams')
    
    # Calculate base streams using sqrt scaling
    effective_pop = group_current_popularity + (fanbase * 0.5) + (gp * 0.3)
    soft_pop = math.sqrt(effective_pop)
    
    # Base calculation within tier
    base_streams = int(soft_pop * (tier_cap / math.sqrt(tier_cap)))
    base_streams = max(tier_floor, min(tier_cap, base_streams))
    
    # Age curve affects growth potential
    release_date = current_album_data.get('release_date')
    if release_date:
        try:
            release_dt = datetime.fromisoformat(release_date)
            days_since = (datetime.now(ARG_TZ) - release_dt.replace(tzinfo=ARG_TZ)).days
            weeks_since = days_since / 7
            if weeks_since <= 1:
                age_curve = 1.5
            elif weeks_since <= 3:
                age_curve = 1.2
            elif weeks_since <= 7:
                age_curve = 1.0
            elif weeks_since <= 15:
                age_curve = 0.7
            elif weeks_since <= 51:
                age_curve = 0.4
            else:
                age_curve = 0.2
        except:
            age_curve = 1.0
    else:
        age_curve = 1.0
    
    age_multiplier = 0.3 + 0.7 * age_curve
    scaled_base = int(base_streams * age_multiplier)
    
    # Apply demographic multiplier
    demo_mults = get_demographic_multipliers(group_entry)
    scaled_base = int(scaled_base * demo_mults['streams'])
    
    # Calculate viral chance (rare: 2-8% based on GP)
    viral_chance = min(0.08, max(0.02, (gp - 30) / 500)) * demo_mults['viral']
    
    # Use dynamic result system for variance (0.6-1.4 range = sometimes worse, sometimes better)
    result = calculate_dynamic_result(
        base_value=scaled_base,
        tier_floor=tier_floor,
        tier_cap=tier_cap,
        variance_range=(0.4, 1.6),
        viral_chance=viral_chance,
        viral_mult_range=(1.3, 2.0)
    )
    
    streams_to_add = result['final']
    went_viral = result['went_viral']
    streams_to_add = int(streams_to_add * _get_hidden_bonus(group_name))

    if group_entry.get('active_hate_train'):
        hate_boost = group_entry.get('hate_train_fanbase_boost', 0)
        streams_to_add = int(streams_to_add * (1 + hate_boost / 200))
    
    update_nations_group()
    if group_entry.get('is_nations_group'):
        streams_to_add = int(streams_to_add * 1.10)
    
    # ABSOLUTE HARD CAP
    ABSOLUTE_MAX_STREAMS = 150000
    streams_to_add = min(streams_to_add, ABSOLUTE_MAX_STREAMS)

    current_album_data['streams'] = current_album_data.get('streams', 0) + streams_to_add
    
    current_week = get_current_week_key()
    current_album_data.setdefault('weekly_streams', {})
    current_album_data['weekly_streams'][current_week] = current_album_data['weekly_streams'].get(current_week, 0) + streams_to_add
    
    songs = current_album_data.get('songs', {})
    if songs:
        title_track = None
        other_songs = []
        for song_name, song_data in songs.items():
            if song_data.get('is_title', False):
                title_track = song_name
            else:
                other_songs.append(song_name)
        
        if title_track:
            if other_songs:
                title_share = int(streams_to_add * 0.6)
                remaining = streams_to_add - title_share
                base_weights = [(0.3 ** i) * random.uniform(0.5, 1.5) for i in range(len(other_songs))]
                random.shuffle(base_weights)
                total_weight = sum(base_weights)
                bside_shares = [int(remaining * (w / total_weight)) for w in base_weights]
                
                for i, song_name in enumerate(other_songs):
                    add_song_streams(songs, song_name, bside_shares[i], current_week)
            else:
                title_share = streams_to_add
            
            add_song_streams(songs, title_track, title_share, current_week)
        else:
            song_list = list(songs.keys())
            base_weights = [(0.3 ** i) * random.uniform(0.5, 1.5) for i in range(len(song_list))]
            random.shuffle(base_weights)
            total_weight = sum(base_weights)
            shares = [int(streams_to_add * (w / total_weight)) for w in base_weights]
            
            for i, song_name in enumerate(song_list):
                add_song_streams(songs, song_name, shares[i], current_week)
    
    user_stream_counts.setdefault(user_id, {})
    user_stream_counts[user_id].setdefault(group_name, 0)
    user_stream_counts[user_id][group_name] += 1

    if current_album_data.get('first_24h_tracking'):
        tracking = current_album_data['first_24h_tracking']
        if not tracking.get('ended', False):
            tracking['streams'] = tracking.get('streams', 0) + streams_to_add

    company_name = group_entry.get('company')
    royalty_rate = 0.003
    royalties_earned = int(streams_to_add * royalty_rate)
    if company_name and company_name in company_funds and not is_disbanded:
        company_funds[company_name] += royalties_earned

    update_cooldown(user_id, "streams")
    save_data() 
    
    viral_text = " 🔥 VIRAL!" if went_viral else ""
    embed = discord.Embed(
        title=album_name, 
        description=f"**{group_name}**{viral_text}" + (" (inactive)" if is_disbanded else ""),
        color=discord.Color.gold() if went_viral else (discord.Color.pink() if group_entry.get('is_nations_group') else discord.Color.from_rgb(255, 105, 180))
    )
    embed.set_thumbnail(url=sanitize_url(current_album_data.get('image_url')))
    embed.add_field(name="Streams", value=f"+{format_number(streams_to_add)}", inline=True)
    embed.set_footer(text=f"Total: {format_number(current_album_data['streams'])} | {remaining_uses} uses left today")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Make your group perform to gain popularity!")
@app_commands.describe(group_name="The name of your group.")
@app_commands.autocomplete(group_name=user_group_autocomplete)
async def perform(interaction: discord.Interaction, group_name: str):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()

    is_limited, remaining_uses = check_daily_limit(user_id, "perform", 10) # Increased to 10 uses
    if is_limited:
        await interaction.response.send_message(f"❌ You have reached your daily limit of 10 performances. Remaining uses today: {remaining_uses}.", ephemeral=True)
        return

    if group_name_upper not in group_data:
        await interaction.response.send_message(f"❌ Group `{group_name}` not found.", ephemeral=True)
        return

    if not is_user_group_owner(user_id, group_name_upper):
        await interaction.response.send_message(f"❌ You do not manage the company that owns '{group_name}'.", ephemeral=True)
        return

    if group_data[group_name_upper].get('is_disbanded'):
        await interaction.response.send_message(f"❌ Cannot perform with {group_name_upper} as they are disbanded.", ephemeral=True)
        return

    group_entry = group_data[group_name_upper]
    pop = get_group_derived_popularity(group_entry)
    fanbase = group_entry.get('fanbase', 50)
    gp = group_entry.get('gp', 30)
    
    # Dynamic popularity gain with variance (15-60 range based on stats)
    base_pop_gain = 20 + int((fanbase + gp) / 20)
    variance = random.uniform(0.5, 1.5)
    popularity_gain = max(10, int(base_pop_gain * variance))
    
    # Chance for exceptional performance (5% chance for 2-3x boost)
    went_exceptional = random.random() < 0.05
    if went_exceptional:
        popularity_gain = int(popularity_gain * random.uniform(2.0, 3.0))
    
    # Small GP and fanbase gains with variance
    gp_gain = random.randint(0, 3) if random.random() < 0.4 else 0
    fanbase_gain = random.randint(0, 2) if random.random() < 0.3 else 0
    
    group_entry['gp'] = group_entry.get('gp', 30) + gp_gain
    group_entry['fanbase'] = group_entry.get('fanbase', 50) + fanbase_gain
    distribute_stat_gain_to_members(group_name_upper, 'popularity', popularity_gain)
    save_data()

    exceptional_text = " ✨ **EXCEPTIONAL PERFORMANCE!**" if went_exceptional else ""
    bonus_text = ""
    if gp_gain > 0 or fanbase_gain > 0:
        bonus_text = f" (+{gp_gain} GP, +{fanbase_gain} fanbase)"
    
    await interaction.response.send_message(
        f"🎤 **{group_name_upper}** performed live!{exceptional_text}\n"
        f"Popularity: **+{popularity_gain}** (Total: {get_group_derived_popularity(group_entry)}){bonus_text}\n"
        f"_{remaining_uses} performances remaining today_",
        ephemeral=False
    )


# === MEMBER MANAGEMENT COMMANDS ===

@bot.tree.command(description="Add members to your group (comma-separated for multiple).")
@app_commands.describe(group_name="The name of your group.", member_names="Member name(s) - separate multiple with commas (e.g. 'Lisa, Jisoo, Rose')")
@app_commands.autocomplete(group_name=user_group_autocomplete)
async def addmember(interaction: discord.Interaction, group_name: str, member_names: str):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()
    
    if group_name_upper not in group_data:
        await interaction.response.send_message(f"Group `{group_name}` not found.", ephemeral=True)
        return
    
    if not is_user_group_owner(user_id, group_name_upper):
        await interaction.response.send_message(f"You do not manage the company that owns '{group_name}'.", ephemeral=True)
        return
    
    group_entry = group_data[group_name_upper]
    
    if group_entry.get('is_disbanded'):
        await interaction.response.send_message(f"Cannot add members to a disbanded group.", ephemeral=True)
        return
    
    if group_entry.get('is_subunit'):
        await interaction.response.send_message(f"Cannot add members directly to subunits. Add them to the parent group first.", ephemeral=True)
        return
    
    members = group_entry.get('members', [])
    
    names_to_add = [n.strip().title() for n in member_names.split(',') if n.strip()]
    
    if not names_to_add:
        await interaction.response.send_message("Please provide at least one member name.", ephemeral=True)
        return
    
    added = []
    errors = []
    
    for member_name_clean in names_to_add:
        if len(member_name_clean) < 2 or len(member_name_clean) > 20:
            errors.append(f"{member_name_clean}: name must be 2-20 characters")
            continue
        
        if member_name_clean in members:
            errors.append(f"{member_name_clean}: already a member")
            continue
        
        if len(members) >= 20:
            errors.append(f"{member_name_clean}: group at max capacity (20)")
            break
        
        members.append(member_name_clean)
        added.append(member_name_clean)
        
        group_entry.setdefault('recent_events', [])
        group_entry['recent_events'].append({
            'type': 'member_added',
            'member': member_name_clean,
            'date': datetime.now().isoformat()
        })
    
    if len(group_entry.get('recent_events', [])) > 20:
        group_entry['recent_events'] = group_entry['recent_events'][-20:]
    
    group_entry['members'] = members
    save_data()
    
    if not added and errors:
        await interaction.response.send_message(f"No members added:\n" + "\n".join(errors), ephemeral=True)
        return
    
    embed = discord.Embed(
        title=f"Members Updated - {group_name_upper}",
        description=f"Added: **{', '.join(added)}**" if added else "No new members added",
        color=discord.Color.from_rgb(255, 105, 180)
    )
    embed.add_field(name="Total Members", value=f"{len(members)}/20", inline=True)
    
    if errors:
        embed.add_field(name="Skipped", value="\n".join(errors), inline=False)
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Remove a member from your group.")
@app_commands.describe(group_name="The name of your group.", member_name="The name of the member to remove.")
@app_commands.autocomplete(group_name=user_group_autocomplete)
async def removemember(interaction: discord.Interaction, group_name: str, member_name: str):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()
    member_name_clean = member_name.strip().title()
    
    if group_name_upper not in group_data:
        await interaction.response.send_message(f"❌ Group `{group_name}` not found.", ephemeral=True)
        return
    
    if not is_user_group_owner(user_id, group_name_upper):
        await interaction.response.send_message(f"❌ You do not manage the company that owns '{group_name}'.", ephemeral=True)
        return
    
    group_entry = group_data[group_name_upper]
    members = group_entry.get('members', [])
    
    matching_member = None
    matching_index = None
    for i, m in enumerate(members):
        if isinstance(m, dict):
            if m.get('name', '').lower() == member_name_clean.lower():
                matching_member = m.get('name')
                matching_index = i
                break
        elif isinstance(m, str):
            if m.lower() == member_name_clean.lower():
                matching_member = m
                matching_index = i
                break
    
    if matching_member is None:
        await interaction.response.send_message(f"❌ **{member_name_clean}** is not a member of **{group_name_upper}**.", ephemeral=True)
        return
    
    members.pop(matching_index)
    group_entry['members'] = members
    
    group_entry.setdefault('recent_events', [])
    group_entry['recent_events'].append({
        'type': 'member_removed',
        'member': matching_member,
        'date': datetime.now().isoformat()
    })
    if len(group_entry['recent_events']) > 20:
        group_entry['recent_events'] = group_entry['recent_events'][-20:]
    
    save_data()
    
    embed = discord.Embed(
        title=f"👤 Member Removed",
        description=f"**{matching_member}** has left **{group_name_upper}**.",
        color=discord.Color.orange()
    )
    embed.add_field(name="Remaining Members", value=f"{len(members)}", inline=True)
    if members:
        embed.add_field(name="Current Roster", value=", ".join(members) if len(members) <= 10 else f"{len(members)} members", inline=False)
    
    await interaction.response.send_message(embed=embed)


# === BIRTHDAY SYSTEM ===

@bot.tree.command(description="Set a member's birthday")
@app_commands.describe(
    member="Select a member (format: GROUP|Member)",
    month="Birthday month (1-12)",
    day="Birthday day (1-31)"
)
@app_commands.autocomplete(member=user_member_autocomplete)
async def setbirthday(interaction: discord.Interaction, member: str, month: int, day: int):
    """Set a member's birthday for automatic announcements."""
    user_id = str(interaction.user.id)
    
    if '|' not in member:
        await interaction.response.send_message("Please select a member from the autocomplete.", ephemeral=True)
        return
    
    group_name, member_name = member.split('|', 1)
    group_name_upper = group_name.upper()
    
    if group_name_upper not in group_data:
        await interaction.response.send_message("Group not found.", ephemeral=True)
        return
    
    if not is_user_group_owner(user_id, group_name_upper):
        await interaction.response.send_message("You don't manage this group's company.", ephemeral=True)
        return
    
    if month < 1 or month > 12:
        await interaction.response.send_message("Month must be between 1 and 12.", ephemeral=True)
        return
    
    days_in_month = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if day < 1 or day > days_in_month[month - 1]:
        await interaction.response.send_message(f"Invalid day for month {month}.", ephemeral=True)
        return
    
    group_entry = group_data[group_name_upper]
    members = group_entry.get('members', [])
    
    found = False
    for i, m in enumerate(members):
        if isinstance(m, dict):
            if m.get('name', '').lower() == member_name.lower():
                m['birthday'] = f"{month:02d}-{day:02d}"
                found = True
                break
        elif isinstance(m, str):
            if m.lower() == member_name.lower():
                members[i] = {
                    'name': m,
                    'popularity': 100,
                    'level': 1,
                    'exp': 0,
                    'skills': {'vocal': 50, 'dance': 50, 'rap': 50, 'visual': 50},
                    'fan_ratios': {'teen': 0.5, 'adult': 0.5, 'female': 0.5, 'male': 0.5},
                    'birthday': f"{month:02d}-{day:02d}"
                }
                found = True
                break
    
    if not found:
        await interaction.response.send_message(f"Member **{member_name}** not found in **{group_name_upper}**.", ephemeral=True)
        return
    
    group_entry['members'] = members
    save_data()
    
    month_names = ['January', 'February', 'March', 'April', 'May', 'June', 
                   'July', 'August', 'September', 'October', 'November', 'December']
    
    await interaction.response.send_message(
        f"🎂 **{member_name}**'s birthday set to **{month_names[month-1]} {day}**!\n"
        f"They'll get a special announcement on their birthday."
    )


@bot.tree.command(description="View upcoming birthdays for all members")
@app_commands.describe(group_name="Optional: filter by group")
@app_commands.autocomplete(group_name=group_autocomplete)
async def birthdays(interaction: discord.Interaction, group_name: str = None):
    """View upcoming member birthdays."""
    now = datetime.now(ARG_TZ)
    today_mmdd = now.strftime("%m-%d")
    
    birthdays_list = []
    
    groups_to_check = {}
    if group_name:
        group_name_upper = group_name.upper()
        if group_name_upper in group_data:
            groups_to_check[group_name_upper] = group_data[group_name_upper]
    else:
        groups_to_check = group_data
    
    for grp_name, grp_entry in groups_to_check.items():
        if grp_entry.get('is_disbanded'):
            continue
        
        members = grp_entry.get('members', [])
        for m in members:
            if not isinstance(m, dict):
                continue
            birthday = m.get('birthday')
            if not birthday:
                continue
            
            member_name = m.get('name', 'Unknown')
            
            try:
                bday_month, bday_day = map(int, birthday.split('-'))
                bday_this_year = now.replace(month=bday_month, day=bday_day, hour=0, minute=0, second=0, microsecond=0)
                
                if bday_this_year.date() < now.date():
                    bday_this_year = bday_this_year.replace(year=now.year + 1)
                
                days_until = (bday_this_year.date() - now.date()).days
                
                birthdays_list.append({
                    'member': member_name,
                    'group': grp_name,
                    'birthday': birthday,
                    'days_until': days_until,
                    'is_today': birthday == today_mmdd
                })
            except (ValueError, AttributeError):
                continue
    
    birthdays_list.sort(key=lambda x: x['days_until'])
    
    if not birthdays_list:
        await interaction.response.send_message(
            "No birthdays set yet! Use `/setbirthday` to add member birthdays.",
            ephemeral=True
        )
        return
    
    embed = discord.Embed(
        title="🎂 Upcoming Birthdays",
        color=discord.Color.from_rgb(255, 182, 193)
    )
    
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    
    lines = []
    for bday in birthdays_list[:15]:
        month, day = map(int, bday['birthday'].split('-'))
        date_str = f"{month_names[month-1]} {day}"
        
        if bday['is_today']:
            lines.append(f"🎉 **{bday['member']}** ({bday['group']}) - **TODAY!**")
        elif bday['days_until'] <= 7:
            lines.append(f"🎈 **{bday['member']}** ({bday['group']}) - {date_str} ({bday['days_until']} days)")
        else:
            lines.append(f"**{bday['member']}** ({bday['group']}) - {date_str}")
    
    embed.description = "\n".join(lines) if lines else "No upcoming birthdays"
    
    if len(birthdays_list) > 15:
        embed.set_footer(text=f"Showing 15 of {len(birthdays_list)} birthdays")
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="View the members of a group.")
@app_commands.describe(group_name="The name of the group.")
@app_commands.autocomplete(group_name=group_autocomplete)
async def groupmembers(interaction: discord.Interaction, group_name: str):
    group_name_upper = group_name.upper()
    
    if group_name_upper not in group_data:
        await interaction.response.send_message(f"❌ Group `{group_name}` not found.", ephemeral=True)
        return
    
    group_entry = group_data[group_name_upper]
    members = group_entry.get('members', [])
    
    embed = discord.Embed(
        title=f"👥 {group_name_upper} - Members",
        color=discord.Color.purple()
    )
    
    if group_entry.get('is_subunit'):
        parent = group_entry.get('parent_group', 'Unknown')
        embed.description = f"Subunit of **{parent}**"
    
    if members:
        member_list = "\n".join([f"• {m}" for m in members])
        embed.add_field(name=f"Roster ({len(members)} members)", value=member_list, inline=False)
    else:
        embed.add_field(name="Roster", value="No members added yet. Use `/addmember` to add members!", inline=False)
    
    embed.add_field(name="Company", value=group_entry.get('company', 'Unknown'), inline=True)
    embed.add_field(name="Status", value="Disbanded" if group_entry.get('is_disbanded') else "Active", inline=True)
    
    await interaction.response.send_message(embed=embed)


# --- Sponsorship Gamble Logic ---

SPONSORSHIP_DEALS = {
    "COCA_COLA": {
        "min_popularity": 150,
        "base_amount": 350_000,
        "popularity_gain": (5, 25),
        "demo_category": "energy_drink",
        "demo_description": "Male ↑ Teen ↑",
        "description": "A refreshing partnership for rising stars!"
    },
    "MIU_MIU": {
        "min_popularity": 300,
        "base_amount": 1_400_000,
        "popularity_gain": (20, 40),
        "demo_category": "luxury_fashion",
        "demo_description": "Adult ↑ Female ↑",
        "description": "Elegance meets artistry in this high-end collaboration."
    },
    "SAMSUNG": {
        "min_popularity": 500,
        "base_amount": 3_500_000,
        "popularity_gain": (40, 70),
        "demo_category": "gaming",
        "demo_description": "Male ↑ Teen ↑",
        "description": "Innovate your image with a leading tech brand."
    },
    "PEPSI": {
        "min_popularity": 200,
        "base_amount": 500_000,
        "popularity_gain": (10, 30),
        "demo_category": "energy_drink",
        "demo_description": "Male ↑ Teen ↑",
        "description": "A new generation of pop with an iconic beverage brand."
    },
    "SKYY": {
        "min_popularity": 250,
        "base_amount": 700_000,
        "popularity_gain": (15, 35),
        "demo_category": "luxury_fashion",
        "demo_description": "Adult ↑ Female ↑",
        "description": "Shine brighter with this premium spirit partnership."
    },
    "ALLURE": {
        "min_popularity": 400,
        "base_amount": 2_000_000,
        "popularity_gain": (25, 45),
        "demo_category": "cosmetics",
        "demo_description": "Female ↑ Adult ↑",
        "description": "Capture the essence of beauty and trendsetting."
    },
    "INNISFREE": {
        "min_popularity": 450,
        "base_amount": 2_500_000,
        "popularity_gain": (30, 50),
        "demo_category": "skincare",
        "demo_description": "Female ↑ Adult ↑",
        "description": "Natural beauty, global appeal. A perfect skincare match."
    },
    "PRADA": {
        "min_popularity": 600,
        "base_amount": 5_000_000,
        "popularity_gain": (50, 80),
        "demo_category": "luxury_fashion",
        "demo_description": "Adult ↑ Female ↑",
        "description": "Define luxury. A prestigious collaboration."
    },
    "GIVENCHY": {
        "min_popularity": 650,
        "base_amount": 5_200_000,
        "popularity_gain": (55, 85),
        "demo_category": "luxury_fashion",
        "demo_description": "Adult ↑ Female ↑",
        "description": "Elegance and edge combined in high fashion."
    },
    "GUCCI": {
        "min_popularity": 700,
        "base_amount": 5_500_000,
        "popularity_gain": (60, 90),
        "demo_category": "luxury_fashion",
        "demo_description": "Adult ↑ Female ↑",
        "description": "Iconic, daring, and universally desired."
    },
    "CHANEL": {
        "min_popularity": 750,
        "base_amount": 6_000_000,
        "popularity_gain": (65, 95),
        "demo_category": "cosmetics",
        "demo_description": "Female ↑ Adult ↑",
        "description": "Timeless sophistication meets modern artistry."
    },
    "BULGARI": {
        "min_popularity": 800,
        "base_amount": 6_500_000,
        "popularity_gain": (70, 100),
        "demo_category": "luxury_fashion",
        "demo_description": "Adult ↑ Female ↑",
        "description": "Italian craftsmanship, global glamour."
    },
    "TIFFANY_AND_CO": {
        "min_popularity": 850,
        "base_amount": 7_000_000,
        "popularity_gain": (75, 105),
        "demo_category": "luxury_fashion",
        "demo_description": "Adult ↑ Female ↑",
        "description": "The ultimate symbol of luxury and refinement."
    },
    "APPLE": {
        "min_popularity": 1000,
        "base_amount": 8_000_000,
        "popularity_gain": (100, 150),
        "demo_category": "gaming",
        "demo_description": "Male ↑ Teen ↑",
        "description": "Innovate. Elevate. Dominate. The peak of global influence."
    },
    "POKEMON_KIDS": {
        "min_popularity": 100,
        "base_amount": 200_000,
        "popularity_gain": (3, 10),
        "demo_category": "kids_brand",
        "demo_description": "Teen ↑",
        "description": "Fun and colorful partnership for younger audiences!"
    },
    "CAPCOM_GAMING": {
        "min_popularity": 350,
        "base_amount": 1_000_000,
        "popularity_gain": (15, 30),
        "demo_category": "gaming",
        "demo_description": "Male ↑ Teen ↑",
        "description": "Level up your image with a gaming giant."
    },
    "RED_BULL": {
        "min_popularity": 300,
        "base_amount": 800_000,
        "popularity_gain": (12, 28),
        "demo_category": "energy_drink",
        "demo_description": "Male ↑ Teen ↑",
        "description": "Gives you wings! High energy partnership."
    },
    "LANEIGE": {
        "min_popularity": 350,
        "base_amount": 1_200_000,
        "popularity_gain": (18, 35),
        "demo_category": "skincare",
        "demo_description": "Female ↑ Adult ↑",
        "description": "K-beauty excellence meets global reach."
    }
}

class SponsorshipDealView(ui.View):
    def __init__(self, original_interaction: discord.Interaction, group_name: str, investment: int, available_deals: list):
        super().__init__(timeout=60)
        self.original_interaction = original_interaction
        self.group_name = group_name.upper()
        self.investment = investment
        self.chosen_brand_name = None

        for brand_name in available_deals:
            details = SPONSORSHIP_DEALS[brand_name]
            button = ui.Button(
                label=f"{brand_name.replace('_', ' ').title()} (Pop: {details['min_popularity']}+)",
                style=discord.ButtonStyle.blurple,
                custom_id=f"sponsorship_{brand_name}"
            )
            button.callback = self.button_callback
            self.add_item(button)

        self.add_item(ui.Button(label="Cancel", style=discord.ButtonStyle.red, custom_id="sponsorship_cancel"))

    async def button_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_interaction.user.id:
            await interaction.response.send_message("❌ This is not your sponsorship selection!", ephemeral=True)
            return

        self.chosen_brand_name = '_'.join(interaction.data['custom_id'].split('_')[1:])

        if self.chosen_brand_name == "cancel":
            await interaction.response.edit_message(content="Sponsorship selection cancelled.", view=None)
            self.stop()
            return

        await interaction.response.defer()

        group_entry = group_data.get(self.group_name)
        if not group_entry:
            await self.original_interaction.edit_original_response(content="❌ Group not found during processing. Please try again.", view=None)
            self.stop()
            return

        if group_entry.get('is_disbanded'):
            await self.original_interaction.edit_original_response(content=f"❌ Cannot seek sponsorship for {self.group_name} as they are disbanded.", view=None)
            self.stop()
            return

        deal_details = SPONSORSHIP_DEALS.get(self.chosen_brand_name)
        if not deal_details:
            await self.original_interaction.edit_original_response(content="❌ Selected brand not found. Please try again.", view=None)
            self.stop()
            return

        group_popularity_val = group_entry.get('popularity', 0)
        base_success_chance = 0.4
        popularity_factor = (group_popularity_val / deal_details["min_popularity"])
        investment_bonus = self.investment / 500_000

        update_nations_group()
        nations_bonus = 0.5 if group_entry.get('is_nations_group') else 0

        success_chance = min(0.95, base_success_chance * popularity_factor + investment_bonus + nations_bonus)

        rep_info = get_reputation_level(group_entry)
        success_chance = success_chance * rep_info.get('sponsorship_mult', 1.0)
        success_chance = max(0.0, min(0.95, success_chance))

        outcome_embed = discord.Embed(
            title="🤝 Sponsorship Outcome",
            color=discord.Color.light_grey()
        )

        if random.random() < success_chance:
            outcome_embed.color = discord.Color.green()
            outcome_embed.title = f"🎉 Sponsorship Deal Secured with {self.chosen_brand_name.replace('_', ' ').title()}!"
            outcome_embed.description = f"{self.group_name} has successfully landed the deal!"

            sponsorship_amount = deal_details["base_amount"]
            popularity_gain = random.randint(*deal_details["popularity_gain"])
            distribute_stat_gain_to_members(self.group_name, 'popularity', popularity_gain)

            demo_category = deal_details.get("demo_category", "luxury_fashion")
            shift_demographics(group_entry, demo_category)

            company_name = group_entry.get('company')
            if company_name and company_name in company_funds:
                company_funds[company_name] = company_funds.get(company_name, 0) + sponsorship_amount
                outcome_embed.add_field(name="Funds Gained", value=f"<:MonthlyPeso:1338642658436059239>{format_number(sponsorship_amount)} (New company funds: <:MonthlyPeso:1338642658436059239>{format_number(company_funds[company_name])})", inline=False)
            else:
                outcome_embed.add_field(name="Funds Gained", value=f"<:MonthlyPeso:1338642658436059239>{format_number(sponsorship_amount)} (Company funds not tracked)", inline=False)

            recalc_group_from_members(self.group_name)
            new_pop = get_group_derived_popularity(group_entry)
            outcome_embed.add_field(name="Popularity Gained", value=f"+{popularity_gain} (New popularity: {new_pop})", inline=False)

        else:
            outcome_embed.color = discord.Color.red()
            outcome_embed.title = f"💔 Sponsorship Deal Failed with {self.chosen_brand_name.replace('_', ' ').title()}"
            outcome_embed.description = f"Unfortunately, {self.group_name} couldn't secure the deal this time. Better luck next time!"
            outcome_embed.add_field(name="Chance of Success", value=f"{success_chance * 100:.2f}%", inline=False)
            if self.investment > 0:
                outcome_embed.add_field(name="Investment Cost", value=f"<:MonthlyPeso:1338642658436059239>{format_number(self.investment)}", inline=False)

        save_data()

        await self.original_interaction.edit_original_response(embed=outcome_embed, view=None)
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        await self.original_interaction.edit_original_response(content="Sponsorship selection timed out.", view=self)


@bot.tree.command(description="Seek a new sponsorship deal for your group!")
@app_commands.describe(
    group_name="The name of your group.",
    investment="Optional: Funds to invest for better chances. Will be deducted from company funds."
)
@app_commands.autocomplete(group_name=user_group_autocomplete)
async def sponsorship(interaction: discord.Interaction, group_name: str, investment: int = 0):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()

    # Apply daily limit for sponsorship
    is_limited, remaining_uses = check_daily_limit(user_id, "sponsorship", 3) # Increased to 3 uses
    if is_limited:
        await interaction.response.send_message(f"❌ You have reached your daily limit of 3 sponsorship attempts. Remaining uses today: {remaining_uses}.", ephemeral=True)
        return

    if not is_user_group_owner(user_id, group_name_upper):
        await interaction.response.send_message(f"❌ Group `{group_name}` not found or does not belong to your company.", ephemeral=True)
        return

    group_entry = group_data.get(group_name_upper, {})
    
    if group_data[group_name_upper].get('is_disbanded'):
        await interaction.response.send_message(f"❌ Cannot seek sponsorship for {group_name_upper} as they are disbanded.", ephemeral=True)
        return

    if group_data[group_name_upper].get('active_hate_train'):
        await interaction.response.send_message(f"❌ **{group_name_upper}** has an active hate train! Brands are avoiding them. Use `/charity` to improve their image first.", ephemeral=True)
        return

    company_name = get_group_owner_company(group_name_upper)
    current_company_funds = company_funds.get(company_name, 0)

    if investment < 0:
        await interaction.response.send_message("❌ Investment cannot be negative.", ephemeral=True)
        return
    if investment > 0:
        if current_company_funds < investment:
            await interaction.response.send_message(f"❌ Your company `{company_name}` only has <:MonthlyPeso:1338642658436059239>{format_number(current_company_funds)}. Not enough funds for that investment.", ephemeral=True)
            return
        company_funds[company_name] -= investment
        save_data() 

    sponsorship_embed = discord.Embed(
        title=f"✨ Sponsorship Opportunities for {group_name_upper} ✨",
        description="Select a brand below to try and secure a sponsorship deal!",
        color=discord.Color.gold()
    )
    sponsorship_embed.add_field(name="Current Popularity", value=group_data[group_name_upper].get('popularity', 0), inline=True)
    if investment > 0:
        sponsorship_embed.add_field(name="Investment in Deal", value=f"<:MonthlyPeso:1338642658436059239>{format_number(investment)}", inline=True)
        sponsorship_embed.set_footer(text=f"You have {remaining_uses} sponsorship attempts left today. Your investment will increase your chances!")
    else:
        sponsorship_embed.set_footer(text=f"You have {remaining_uses} sponsorship attempts left today. No investment made for this attempt.")


    # Filter eligible deals based on group popularity
    eligible_deals_pool = [
        brand_name for brand_name, details in SPONSORSHIP_DEALS.items() 
        if group_data[group_name_upper].get('popularity', 0) >= details["min_popularity"]
    ]

    # Select a random subset of eligible deals, up to a maximum of 5
    num_to_display = min(5, len(eligible_deals_pool))
    random_deals_to_display = random.sample(eligible_deals_pool, num_to_display)

    eligible_deals_str = ""
    # Sort selected random deals by min_popularity for better display order
    sorted_random_deals = sorted(random_deals_to_display, key=lambda brand_name: SPONSORSHIP_DEALS[brand_name]['min_popularity'])


    for brand_name in sorted_random_deals:
        details = SPONSORSHIP_DEALS[brand_name]
        eligible_deals_str += (
            f"**{brand_name.replace('_', ' ').title()}** (Target Pop: {details['min_popularity']}+)\n"
            f"  - *{details['description']}*\n"
            f"  - Potential Earnings: <:MonthlyPeso:1338642658436059239>{format_number(details['base_amount'])}\n"
            f"  - Pop Gain: {details['popularity_gain'][0]}-{details['popularity_gain'][1]}\n\n"
        )

    if len(eligible_deals_str) > 1024:
        eligible_deals_str = eligible_deals_str[:1021] + "..." # Truncate and add ellipsis


    view = SponsorshipDealView(interaction, group_name, investment, sorted_random_deals)
    if not eligible_deals_str:
        sponsorship_embed.add_field(
            name="No Eligible Deals Currently", 
            value=f"Your group's popularity ({group_data[group_name_upper].get('popularity', 0)}) is currently too low for any available sponsorships. Keep working on boosting their popularity!", 
            inline=False
        )

        for item in view.children:
            if item.custom_id and item.custom_id.startswith("sponsorship_") and item.custom_id != "sponsorship_cancel":
                item.disabled = True
    else:
        sponsorship_embed.add_field(name="Available Deals", value=eligible_deals_str, inline=False)

    await interaction.response.send_message(embed=sponsorship_embed, view=view, ephemeral=False)

@bot.tree.command(description="Announce an upcoming concert!")
@app_commands.describe(
    group_name="The name of your group.",
    city="The city where the concert will be held."
)
@app_commands.autocomplete(group_name=user_group_autocomplete, city=city_autocomplete)
async def concert(interaction: discord.Interaction, group_name: str, city: str):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()

    # Apply daily limit for concert
    is_limited, remaining_uses = check_daily_limit(user_id, "concert", 1)
    if is_limited:
        await interaction.response.send_message(f"❌ You have reached your daily limit of 1 concert announcement. Remaining uses today: {remaining_uses}.", ephemeral=True)
        return

    if group_name_upper not in group_data:
        await interaction.response.send_message(f"❌ Group `{group_name}` not found.")
        return

    if city not in CONCERT_CITIES:
        await interaction.response.send_message(f"❌ Invalid city. Please choose from: {', '.join(CONCERT_CITIES)}")
        return

    if group_data[group_name_upper].get('is_disbanded'):
        await interaction.response.send_message(f"❌ Cannot announce a concert for {group_name_upper} as they are disbanded.", ephemeral=True)
        return

    group_entry = group_data[group_name_upper]
    pop = get_group_derived_popularity(group_entry)
    fanbase = group_entry.get('fanbase', 50)
    gp = group_entry.get('gp', 30)
    company_name = group_entry.get('company')

    import math
    
    # Get tier bounds for concert
    tier_floor, tier_cap, tier_name = get_tier_bounds(pop, 'concert')
    
    # Calculate venue and tickets with variance
    log_pop = math.log10(max(1, pop) + 1)
    log_fanbase = math.log10(max(1, fanbase) + 1)
    
    venue_capacity = min(50000, int(1000 + log_pop * 5000 + log_fanbase * 3000))
    base_fill_rate = min(1.0, 0.4 + log_pop * 0.15 + log_fanbase * 0.1)
    
    # Wide variance for tickets (0.5-1.3x) - sometimes great turnout, sometimes poor
    fill_variance = random.uniform(0.5, 1.3)
    tickets_sold = max(500, int(venue_capacity * base_fill_rate * fill_variance))

    base_ticket_price = 50
    ticket_price = min(200, int(base_ticket_price + log_fanbase * 30))
    ticket_revenue = tickets_sold * ticket_price
    
    # Merch with variance
    merch_mult = random.uniform(2, 10)
    merch_sales = int(tickets_sold * merch_mult)
    total_revenue = ticket_revenue + merch_sales
    
    # Apply variance to total revenue
    revenue_variance = random.uniform(0.7, 1.3)
    total_revenue = int(total_revenue * revenue_variance)
    
    CONCERT_REVENUE_CAP = 15_000_000
    total_revenue = max(tier_floor, min(tier_cap, total_revenue))
    total_revenue = min(total_revenue, CONCERT_REVENUE_CAP)
    
    # Rare sold-out bonus (8% chance)
    went_soldout = random.random() < 0.08
    if went_soldout:
        total_revenue = int(total_revenue * 1.5)
        total_revenue = min(total_revenue, CONCERT_REVENUE_CAP)
    
    update_nations_group()
    if group_entry.get('is_nations_group'):
        total_revenue = min(int(total_revenue * 1.1), CONCERT_REVENUE_CAP)
    
    if company_name and company_name in company_funds:
        company_funds[company_name] += total_revenue

    # Dynamic popularity boost with variance
    base_pop_boost = max(5, tickets_sold // 8000)
    pop_variance = random.uniform(0.5, 1.5)
    popularity_boost = max(3, int(base_pop_boost * pop_variance))
    if went_soldout:
        popularity_boost = int(popularity_boost * 1.5)
    
    fanbase_gain = random.randint(1, 5) if random.random() < 0.6 else 0
    gp_gain = random.randint(1, 3) if random.random() < 0.4 else 0
    
    distribute_stat_gain_to_members(group_name_upper, 'popularity', popularity_boost)
    group_entry['fanbase'] = group_entry.get('fanbase', 50) + fanbase_gain
    group_entry['gp'] = group_entry.get('gp', 30) + gp_gain

    save_data()

    soldout_text = " 🎫 **SOLD OUT!**" if went_soldout else ""
    embed = discord.Embed(
        title=f"🎤 {group_name_upper} Concert in {city}!",
        description=f"**{group_name_upper}** performed a concert in **{city}**!{soldout_text}",
        color=discord.Color.gold() if went_soldout else (discord.Color.pink() if group_entry.get('is_nations_group') else discord.Color.purple())
    )
    embed.add_field(name="Tickets Sold", value=f"{format_number(tickets_sold)}", inline=True)
    embed.add_field(name="Ticket Price", value=f"<:MonthlyPeso:1338642658436059239>{ticket_price}", inline=True)
    embed.add_field(name="Ticket Revenue", value=f"<:MonthlyPeso:1338642658436059239>{format_number(ticket_revenue)}", inline=True)
    embed.add_field(name="Merch Sales", value=f"<:MonthlyPeso:1338642658436059239>{format_number(merch_sales)}", inline=True)
    embed.add_field(name="💰 Total Earned", value=f"<:MonthlyPeso:1338642658436059239>{format_number(total_revenue)}", inline=True)
    embed.add_field(name="Popularity", value=f"+{popularity_boost}" + (f" (+{fanbase_gain} fans, +{gp_gain} GP)" if fanbase_gain or gp_gain else ""), inline=True)
    embed.set_footer(text=f"You have {remaining_uses} concert announcements left today.")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(description="Start a world tour! Multi-city performance tour.")
@app_commands.describe(
    group_name="Your group",
    countries="Comma-separated list of countries (e.g., 'Japan, Thailand, USA')"
)
@app_commands.autocomplete(group_name=user_group_autocomplete)
async def worldtour(interaction: discord.Interaction, group_name: str, countries: str):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()
    
    if group_name_upper not in group_data:
        await interaction.response.send_message("❌ Group not found.", ephemeral=True)
        return
    
    if not is_user_group_owner(user_id, group_name_upper):
        await interaction.response.send_message("❌ You don't manage this group.", ephemeral=True)
        return
    
    group_entry = group_data[group_name_upper]
    
    # Weekly limit check (1 per week)
    current_week = get_current_week_key()
    last_tour_week = group_entry.get('last_worldtour_week')
    if last_tour_week == current_week:
        await interaction.response.send_message("❌ You can only do 1 world tour per week!", ephemeral=True)
        return
    
    company_name = (group_entry.get('company') or "").upper()
    if not company_name:
        await interaction.response.send_message("❌ This group has no company assigned.", ephemeral=True)
        return
    if company_name not in company_funds:
        await interaction.response.send_message("❌ Company not found.", ephemeral=True)
        return
    if group_entry.get('is_disbanded'):
        await interaction.response.send_message("❌ Cannot tour with a disbanded group.", ephemeral=True)
        return
    
    # Parse countries
    country_list = [c.strip().title() for c in countries.split(',') if c.strip()]
    
    if len(country_list) < 2:
        await interaction.response.send_message("❌ World tour requires at least 2 countries.", ephemeral=True)
        return
    
    if len(country_list) > 10:
        await interaction.response.send_message("❌ Maximum 10 stops per tour.", ephemeral=True)
        return
    
    # Validate countries and check requirements
    invalid_countries = []
    valid_stops = []
    total_cost = 0
    
    group_pop = get_group_derived_popularity(group_entry)
    
    for country in country_list:
        if country not in TOUR_COUNTRIES:
            invalid_countries.append(country)
            continue
        
        country_info = TOUR_COUNTRIES[country]
        
        if group_pop < country_info['popularity_req']:
            invalid_countries.append(f"{country} (need {country_info['popularity_req']} popularity)")
            continue
        
        valid_stops.append(country)
        total_cost += country_info['venue_cost']
    
    if invalid_countries:
        await interaction.response.send_message(
            f"❌ Invalid/unavailable countries:\n" + "\n".join(invalid_countries) +
            f"\n\nAvailable countries: {', '.join(TOUR_COUNTRIES.keys())}",
            ephemeral=True
        )
        return
    
    if not valid_stops:
        await interaction.response.send_message("❌ No valid tour stops.", ephemeral=True)
        return

    # Check company funds
    if company_funds.get(company_name, 0) < total_cost:
        await interaction.response.send_message(
            f"❌ Not enough funds! Tour costs <:MonthlyPeso:1338642658436059239>{format_number(total_cost)}.",
            ephemeral=True
        )
        return
    
    # Deduct cost
    company_funds[company_name] -= total_cost
    
    # Execute tour
    fanbase = group_entry.get('fanbase', 50)
    gp = group_entry.get('gp', 30)
    
    tour_results = []
    total_revenue = 0
    total_attendance = 0
    countries_charted = []
    flop_stops = []
    
    for country in valid_stops:
        country_info = TOUR_COUNTRIES[country]
        
        # Calculate attendance with variance and flop chance (HARDER now)
        base_attendance = country_info['base_attendance']
        popularity_factor = min(1.5, (group_pop / country_info['popularity_req']) * 0.7)  # Reduced from 2.0
        fanbase_factor = fanbase / 100
        gp_factor = gp / 100  # GP matters now
        
        # Attendance harder to achieve (0.2x to 1.0x base, reduced from 0.3-1.5)
        attendance_mult = random.uniform(0.2, 1.0) * popularity_factor * (0.3 + fanbase_factor * 0.4 + gp_factor * 0.3)
        attendance = int(base_attendance * attendance_mult)
        
        # Cap at 100% capacity - no overselling
        capacity = base_attendance
        attendance = min(attendance, capacity)
        attendance_rate = attendance / capacity
        
        if attendance_rate < 0.3:
            flop_stops.append(country)
            # Flopped shows have reduced revenue
            revenue = int(attendance * 50 * country_info['revenue_mult'] * 0.5)
        elif attendance_rate >= 0.9:
            # Sold out bonus
            revenue = int(attendance * 100 * country_info['revenue_mult'] * 1.3)
        else:
            revenue = int(attendance * 80 * country_info['revenue_mult'])
        
        total_attendance += attendance
        total_revenue += revenue
        
        # Track international presence
        group_entry.setdefault('countries_performed', [])
        if country not in group_entry['countries_performed']:
            countries_charted.append(country)
            group_entry['countries_performed'].append(country)

        tour_results.append({
            'country': country,
            'attendance': attendance,
            'attendance_rate': attendance_rate,
            'revenue': revenue,
            'flopped': attendance_rate < 0.3
        })
    
    # Add revenue
    company_funds[company_name] += total_revenue
    net_profit = total_revenue - total_cost
    
    # Stat gains
    pop_gain = random.randint(20, 50) * len(valid_stops)
    fanbase_gain = random.randint(5, 15)
    gp_gain = random.randint(3, 10)
    
    # Reduce gains if tour had flops
    if flop_stops:
        flop_penalty = len(flop_stops) / len(valid_stops)
        pop_gain = int(pop_gain * (1 - flop_penalty * 0.5))
        fanbase_gain = max(1, int(fanbase_gain * (1 - flop_penalty * 0.7)))
        gp_gain = max(1, int(gp_gain * (1 - flop_penalty * 0.6)))
    
    distribute_stat_gain_to_members(group_name_upper, 'popularity', pop_gain)
    group_entry['fanbase'] = min(100, group_entry.get('fanbase', 50) + fanbase_gain)
    group_entry['gp'] = min(100, group_entry.get('gp', 30) + gp_gain)
    
    # Track weekly limit
    group_entry['last_worldtour_week'] = current_week
    
    save_data()
    
    # Create embed
    embed = discord.Embed(
        title=f"🌍 {group_name_upper} World Tour Complete!",
        description=f"{len(valid_stops)} stops across {len(set([c for c in valid_stops]))} countries",
        color=discord.Color.red() if flop_stops else discord.Color.gold()
    )
    
    # Show tour stops
    stops_text = []
    for result in tour_results:
        status = "❌ FLOPPED" if result['flopped'] else "✅" if result['attendance_rate'] >= 0.9 else "📊"
        stops_text.append(
            f"{status} **{result['country']}**\n"
            f"   {format_number(result['attendance'])} fans ({result['attendance_rate']*100:.0f}% capacity)\n"
            f"   Revenue: <:MonthlyPeso:1338642658436059239>{format_number(result['revenue'])}"
        )
    
    embed.add_field(name="Tour Stops", value="\n".join(stops_text), inline=False)
    
    embed.add_field(name="💰 Total Revenue", value=f"<:MonthlyPeso:1338642658436059239>{format_number(total_revenue)}", inline=True)
    embed.add_field(name="💸 Tour Costs", value=f"<:MonthlyPeso:1338642658436059239>{format_number(total_cost)}", inline=True)
    embed.add_field(name="📊 Net Profit", value=f"<:MonthlyPeso:1338642658436059239>{format_number(net_profit)}", inline=True)
    
    embed.add_field(name="📈 Stats", value=f"+{pop_gain} Popularity\n+{fanbase_gain} Fanbase\n+{gp_gain} GP", inline=True)
    embed.add_field(name="👥 Total Fans", value=f"{format_number(total_attendance)}", inline=True)
    
    if countries_charted:
        embed.add_field(name="🗺️ New Markets", value=", ".join(countries_charted), inline=False)
    
    if flop_stops:
        embed.add_field(
            name="⚠️ Warning",
            value=f"These stops had poor attendance:\n{', '.join(flop_stops)}",
            inline=False
        )
        embed.set_footer(text="Low attendance reduces stat gains and damages reputation")
    
    await interaction.response.send_message(embed=embed)


# === FANDOM & REPUTATION SYSTEM ===

@bot.tree.command(description="Set your group's official fandom name and color!")
@app_commands.describe(
    group_name="Your group",
    fandom_name="Official fandom name (e.g., ARMY, ONCE, BLINK)",
    fandom_color="Hex color code (e.g., #FF1493 for hot pink)"
)
@app_commands.autocomplete(group_name=user_group_autocomplete)
async def setfandom(interaction: discord.Interaction, group_name: str, fandom_name: str, fandom_color: str):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()
    
    if not is_user_group_owner(user_id, group_name_upper):
        await interaction.response.send_message("❌ You don't manage this group.", ephemeral=True)
        return
    
    if group_name_upper not in group_data:
        await interaction.response.send_message("❌ Group not found.", ephemeral=True)
        return
    
    # Validate color
    if not fandom_color.startswith('#') or len(fandom_color) != 7:
        await interaction.response.send_message("❌ Invalid color! Use hex format like #FF1493", ephemeral=True)
        return
    
    try:
        # Test if valid hex
        int(fandom_color[1:], 16)
    except ValueError:
        await interaction.response.send_message("❌ Invalid hex color code!", ephemeral=True)
        return
    
    group_entry = group_data[group_name_upper]
    group_entry['fandom_name'] = fandom_name.strip()
    group_entry['fandom_color'] = fandom_color.upper()
    
    save_data()
    
    # Convert hex to RGB for embed
    hex_color = fandom_color.lstrip('#')
    rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    embed = discord.Embed(
        title=f"💜 Fandom Established!",
        description=f"**{group_name_upper}**'s official fandom: **{fandom_name}**",
        color=discord.Color.from_rgb(*rgb)
    )
    embed.add_field(name="Fandom Color", value=f"{fandom_color}", inline=True)
    embed.set_footer(text="Stronger fandoms = more loyal streaming & better merch sales!")
    
    await interaction.response.send_message(embed=embed)


def get_fandom_power_multiplier(group_entry: dict) -> float:
    """Calculate fandom power multiplier based on fanbase and loyalty."""
    fanbase = group_entry.get('fanbase', 50)
    has_fandom_name = bool(group_entry.get('fandom_name'))
    
    base_mult = 1.0 + (fanbase / 200)  # Max +0.5 from fanbase
    
    if has_fandom_name:
        base_mult += 0.1  # +10% for having official fandom
    
    return base_mult


# Add reputation tracking
REPUTATION_LEVELS = {
    "PRISTINE": {"min": 80, "desc": "Pristine Image", "sponsorship_mult": 1.5, "scandal_resist": 0.3},
    "CLEAN": {"min": 60, "desc": "Clean Image", "sponsorship_mult": 1.2, "scandal_resist": 0.15},
    "NEUTRAL": {"min": 40, "desc": "Neutral Image", "sponsorship_mult": 1.0, "scandal_resist": 0.0},
    "CONTROVERSIAL": {"min": 20, "desc": "Controversial", "sponsorship_mult": 0.7, "scandal_resist": -0.1, "viral_boost": 0.15},
    "SCANDAL_RIDDEN": {"min": 0, "desc": "Scandal-Ridden", "sponsorship_mult": 0.3, "scandal_resist": -0.2, "viral_boost": 0.25}
}


def get_reputation_level(group_entry: dict) -> dict:
    """Get current reputation level and its effects."""
    reputation = group_entry.get('reputation', 50)
    
    for level_name, level_info in sorted(REPUTATION_LEVELS.items(), key=lambda x: x[1]['min'], reverse=True):
        if reputation >= level_info['min']:
            return {
                'name': level_name,
                'desc': level_info['desc'],
                'value': reputation,
                **level_info
            }
    
    return {
        'name': 'NEUTRAL',
        'desc': 'Neutral Image',
        'value': reputation,
        **REPUTATION_LEVELS['NEUTRAL']
    }


def apply_reputation_change(group_name: str, change: int, reason: str = None):
    """Apply reputation change with reason tracking."""
    if group_name not in group_data:
        return
    
    group_entry = group_data[group_name]
    old_rep = group_entry.get('reputation', 50)
    new_rep = max(0, min(100, old_rep + change))
    
    group_entry['reputation'] = new_rep
    
    # Track history
    group_entry.setdefault('reputation_history', [])
    group_entry['reputation_history'].append({
        'change': change,
        'reason': reason or 'Unknown',
        'timestamp': datetime.now().isoformat(),
        'old': old_rep,
        'new': new_rep
    })
    
    # Keep last 20 events
    if len(group_entry['reputation_history']) > 20:
        group_entry['reputation_history'] = group_entry['reputation_history'][-20:]
    
    save_data()
    
    return old_rep, new_rep


@bot.tree.command(description="View your group's reputation and fandom power")
@app_commands.autocomplete(group_name=group_autocomplete)
async def reputation(interaction: discord.Interaction, group_name: str):
    group_name_upper = group_name.upper()
    
    if group_name_upper not in group_data:
        await interaction.response.send_message("❌ Group not found.", ephemeral=True)
        return
    
    group_entry = group_data[group_name_upper]
    
    # Get reputation info
    rep_info = get_reputation_level(group_entry)
    
    # Get fandom info
    fandom_name = group_entry.get('fandom_name', 'No Official Fandom')
    fandom_color = group_entry.get('fandom_color', '#FF69B4')
    fandom_power = get_fandom_power_multiplier(group_entry)
    
    # Convert hex to RGB
    try:
        hex_color = fandom_color.lstrip('#')
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        embed_color = discord.Color.from_rgb(*rgb)
    except:
        embed_color = discord.Color.from_rgb(255, 105, 180)
    
    embed = discord.Embed(
        title=f"{group_name_upper} - Reputation & Fandom",
        color=embed_color
    )
    
    # Reputation section
    rep_bar_filled = int((rep_info['value'] / 100) * 10)
    rep_bar = "█" * rep_bar_filled + "░" * (10 - rep_bar_filled)
    
    embed.add_field(
        name=f"📊 Reputation: {rep_info['desc']}",
        value=f"{rep_bar} {rep_info['value']}/100",
        inline=False
    )
    
    # Reputation effects
    effects = []
    if rep_info.get('sponsorship_mult', 1.0) != 1.0:
        mult_text = f"{int((rep_info['sponsorship_mult'] - 1) * 100):+}%"
        effects.append(f"Sponsorship deals: {mult_text}")
    if rep_info.get('viral_boost', 0) > 0:
        effects.append(f"Viral chance: +{int(rep_info['viral_boost'] * 100)}%")
    if rep_info.get('scandal_resist', 0) != 0:
        resist_text = f"{int(rep_info['scandal_resist'] * 100):+}%"
        effects.append(f"Scandal resistance: {resist_text}")
    
    if effects:
        embed.add_field(name="Effects", value="\n".join(effects), inline=False)
    
    # Fandom section
    embed.add_field(
        name=f"💜 Fandom: {fandom_name}",
        value=f"Power Multiplier: **{fandom_power:.2f}x**\n"
              f"Color: {fandom_color if fandom_name != 'No Official Fandom' else 'Not set'}",
        inline=False
    )
    
    embed.set_footer(text="Use /setfandom to establish your official fandom!")
    
    await interaction.response.send_message(embed=embed)

# Add after the fandom system

# === BOYCOTT SYSTEM ===

BOYCOTT_TYPES = {
    "MISTREATMENT": {
        "name": "Mistreatment Boycott",
        "description": "Fans boycott to protest company mistreatment of the group",
        "is_fan_action": True,
        "effects": {
            "company_funds": (-500000, -2000000),  # Hurts company
            "group_sales": -0.3,  # Sales drop 30%
            "group_streams": -0.2,  # Streams drop 20%
            "fanbase_loyalty": (5, 15),  # Fans MORE loyal after
            "gp": (-5, 5),  # Can go either way
            "reputation": (3, 10)  # Group reputation improves (they're victims)
        },
        "duration_days": 7
    },
        "OVERWORK": {
        "name": "Overwork Boycott",
        "description": "Fans demand the group get proper rest",
        "is_fan_action": True,
        "effects": {
            "company_funds": (-400000, -1500000),
            "group_sales": -0.25,
            "group_streams": -0.15,
            "fanbase_loyalty": (3, 10),
            "gp": (5, 15),  # GP likes caring fans
            "reputation": (8, 15)
        },
        "duration_days": 5
    },
    "SCANDAL_BOYCOTT": {
        "name": "Scandal Boycott",
        "description": "Antis and disappointed fans boycott over scandal",
        "is_fan_action": False,
        "effects": {
            "company_funds": (-300000, -1000000),
            "group_sales": -0.5,
            "group_streams": -0.4,
            "group_popularity": (-50, -20),
            "fanbase_loyalty": (-10, -3),  # Lose casual fans
            "gp": (-20, -10),
            "reputation": (-15, -8)
        },
        "duration_days": 10
    },
        "PROBLEMATIC_BEHAVIOR": {
        "name": "Behavior Boycott",
        "description": "Mass boycott over problematic behavior or statements",
        "is_fan_action": False,
        "effects": {
            "company_funds": (-600000, -2000000),
            "group_sales": -0.6,
            "group_streams": -0.5,
            "group_popularity": (-80, -40),
            "fanbase_loyalty": (-15, -5),
            "gp": (-25, -15),
            "reputation": (-20, -12)
        },
        "duration_days": 14
    },
    "CHART_MANIPULATION": {
        "name": "Chart Manipulation Boycott",
        "description": "Boycott over suspected chart/streaming manipulation",
        "is_fan_action": False,
        "effects": {
            "company_funds": (-500000, -1800000),
            "group_sales": -0.4,
            "group_streams": -0.3,
            "group_popularity": (-40, -20),
            "gp": (-18, -10),
            "reputation": (-15, -8)
        },
        "duration_days": 7
    }
}


def start_boycott(group_name: str, boycott_type: str, initiator_id: str = None) -> dict:
    """Start a boycott against a group/company."""
    if group_name not in group_data:
        return None

    group_entry = group_data[group_name]

    # Check if already boycotted
    active_boycotts = group_entry.get('active_boycotts', [])
    for boycott in active_boycotts:
        if not boycott.get('ended', False):
            return {'error': 'Group already has an active boycott'}

    boycott_info = BOYCOTT_TYPES.get(boycott_type)
    if not boycott_info:
        return None

    # Create boycott
    boycott = {
        'type': boycott_type,
        'name': boycott_info['name'],
        'started_at': datetime.now().isoformat(),
        'ends_at': (datetime.now() + timedelta(days=boycott_info['duration_days'])).isoformat(),
        'duration_days': boycott_info['duration_days'],
        'is_fan_action': boycott_info['is_fan_action'],
        'effects': boycott_info['effects'],
        'initiator_id': initiator_id,
        'ended': False
    }

    group_entry.setdefault('active_boycotts', [])
    group_entry['active_boycotts'].append(boycott)

    save_data()
    return boycott


def check_and_apply_boycott_effects(group_name: str, sync_only: bool = True):
    """Check for active boycotts and apply their effects (sync version for commands)."""
    if group_name not in group_data:
        return None

    group_entry = group_data[group_name]
    active_boycotts = group_entry.get('active_boycotts', [])

    active_effects = {
        'sales_mult': 1.0,
        'streams_mult': 1.0,
        'has_active_boycott': False,
        'expired_boycotts': []
    }

    now = datetime.now()

    for boycott in active_boycotts:
        if boycott.get('ended', False):
            continue

        # Check if expired
        ends_at = datetime.fromisoformat(boycott['ends_at'])
        if now >= ends_at:
            # Mark for async processing
            boycott['ended'] = True
            active_effects['expired_boycotts'].append((group_name, boycott))
            continue

        # Apply ongoing effects
        effects = boycott['effects']
        if 'group_sales' in effects:
            active_effects['sales_mult'] *= (1 + effects['group_sales'])
        if 'group_streams' in effects:
            active_effects['streams_mult'] *= (1 + effects['group_streams'])

        active_effects['has_active_boycott'] = True

    save_data()
    return active_effects


@tasks.loop(hours=1)
async def check_expired_boycotts():
    """Check and end expired boycotts with notifications."""
    for group_name in list(group_data.keys()):
        group_entry = group_data.get(group_name, {})
        active_boycotts = group_entry.get('active_boycotts', [])
        
        now = datetime.now()
        
        for boycott in active_boycotts:
            if boycott.get('ended', False):
                continue
            
            ends_at = datetime.fromisoformat(boycott['ends_at'])
            if now >= ends_at:
                boycott['ended'] = True
                await end_boycott_effects(group_name, boycott)
    
    save_data()


@tasks.loop(hours=24)
async def decay_company_pressure():
    """Slowly reduce company pressure over time."""
    for group_name, group_entry in group_data.items():
        pressure = group_entry.get('company_pressure', 0)
        if pressure > 0:
            decay = random.randint(5, 10)
            group_entry['company_pressure'] = max(0, pressure - decay)
    save_data()


async def end_boycott_effects(group_name: str, boycott: dict):
    """Apply final effects when boycott ends and notify owner."""
    if group_name not in group_data:
        return

    group_entry = group_data[group_name]
    effects = boycott['effects']

    # Apply lasting effects
    if 'fanbase_loyalty' in effects:
        change = random.randint(*effects['fanbase_loyalty'])
        group_entry['fanbase'] = max(0, min(100, group_entry.get('fanbase', 50) + change))

    if 'gp' in effects:
        change = random.randint(*effects['gp'])
        group_entry['gp'] = max(0, min(100, group_entry.get('gp', 30) + change))

    if 'reputation' in effects:
        change = random.randint(*effects['reputation'])
        apply_reputation_change(group_name, change, f"Boycott ended: {boycott['name']}")

    if 'group_popularity' in effects:
        change = random.randint(*effects['group_popularity'])
        distribute_stat_gain_to_members(group_name, 'popularity', change)

    if 'company_funds' in effects:
        company_name = group_entry.get('company')
        if company_name and company_name in company_funds:
            loss = random.randint(*effects['company_funds'])
            company_funds[company_name] = max(0, company_funds[company_name] + loss)

    # Notify company owner
    owner_id = get_group_owner_user_id(group_name)
    if owner_id and events_channel_id:
        channel = bot.get_channel(events_channel_id)
        if channel:
            is_fan = boycott.get('is_fan_action', False)
            
            embed = discord.Embed(
                title="📢 Boycott Ended",
                description=f"**{boycott['name']}** against **{group_name}** has ended",
                color=discord.Color.green() if is_fan else discord.Color.orange()
            )
            
            if is_fan:
                embed.add_field(
                    name="Results",
                    value="Fanbase loyalty increased\nGroup reputation improved\nCompany funds affected",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Results",
                    value="Popularity decreased\nGP interest down\nSome fans left",
                    inline=False
                )
            
            try:
                await channel.send(f"<@{owner_id}>", embed=embed)
            except:
                pass


@bot.tree.command(description="Start a boycott! Can be protective fans OR antis.")
@app_commands.describe(
    group_name="The group to boycott",
    boycott_type="Type of boycott",
    reason="Optional: Explain why (will be shown publicly)"
)
@app_commands.choices(boycott_type=[
    app_commands.Choice(name="💔 Mistreatment (Fans protecting group)", value="MISTREATMENT"),
    app_commands.Choice(name="😴 Overwork (Fans demand rest)", value="OVERWORK"),
    app_commands.Choice(name="🚫 Scandal Boycott (Antis)", value="SCANDAL_BOYCOTT"),
    app_commands.Choice(name="⚠️ Problematic Behavior (Antis)", value="PROBLEMATIC_BEHAVIOR"),
    app_commands.Choice(name="📊 Chart Manipulation (Antis)", value="CHART_MANIPULATION")
])
@app_commands.autocomplete(group_name=group_autocomplete)
async def boycott(interaction: discord.Interaction, group_name: str, boycott_type: str, reason: str = None):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()
    
    # Daily limit check (1 per day per user)
    today = get_today_str()
    user_daily_limits.setdefault(user_id, {})
    boycott_uses = user_daily_limits[user_id].get('boycott', {})
    if boycott_uses.get('date') == today and boycott_uses.get('count', 0) >= 1:
        await interaction.response.send_message("❌ You can only start 1 boycott per day!", ephemeral=True)
        return

    if group_name_upper not in group_data:
        await interaction.response.send_message("❌ Group not found.", ephemeral=True)
        return

    group_entry = group_data[group_name_upper]

    if group_entry.get('is_disbanded'):
        await interaction.response.send_message("❌ Cannot boycott a disbanded group.", ephemeral=True)
        return

    # Start boycott
    boycott_result = start_boycott(group_name_upper, boycott_type, user_id)

    if not boycott_result:
        await interaction.response.send_message("❌ Invalid boycott type.", ephemeral=True)
        return

    if boycott_result.get('error'):
        await interaction.response.send_message(f"❌ {boycott_result['error']}", ephemeral=True)
        return

    boycott_info = BOYCOTT_TYPES[boycott_type]
    is_fan_action = boycott_info['is_fan_action']

    # Create announcement
    emoji = "💔" if is_fan_action else "🚫"
    action_by = "Fans" if is_fan_action else "Public/Antis"

    embed = discord.Embed(
        title=f"{emoji} BOYCOTT ANNOUNCED",
        description=f"**{boycott_result['name']}** against **{group_name_upper}**",
        color=discord.Color.orange() if is_fan_action else discord.Color.dark_red()
    )

    embed.add_field(name="Initiated By", value=action_by, inline=True)
    embed.add_field(name="Duration", value=f"{boycott_result['duration_days']} days", inline=True)
    embed.add_field(name="Type", value="Protective Action" if is_fan_action else "Public Backlash", inline=True)

    embed.add_field(
        name="📢 Statement",
        value=boycott_info['description'] + (f"\n\n*\"{reason}\"*" if reason else ""),
        inline=False
    )

    # Show expected effects
    effects_text = []
    effects = boycott_info['effects']

    if 'group_sales' in effects:
        effects_text.append(f"📉 Sales: {int(effects['group_sales'] * 100)}%")
    if 'group_streams' in effects:
        effects_text.append(f"📉 Streams: {int(effects['group_streams'] * 100)}%")
    if 'company_funds' in effects:
        loss_range = effects['company_funds']
        effects_text.append(f"💸 Company losses: <:MonthlyPeso:1338642658436059239>{format_number(abs(loss_range[0]))}-{format_number(abs(loss_range[1]))}")

    if is_fan_action:
        effects_text.append("💜 After boycott: Fanbase loyalty increases")
        effects_text.append("📈 Group reputation may improve")
    else:
        effects_text.append("📉 Popularity will drop")
        effects_text.append("💔 Fanbase loyalty decreases")

    embed.add_field(name="Expected Impact", value="\n".join(effects_text), inline=False)

    # Get owner to notify
    owner_id = get_group_owner_user_id(group_name_upper)
    if owner_id:
        embed.set_footer(text=f"Company owner: <@{owner_id}>")

    # Track daily usage
    if boycott_uses.get('date') != today:
        user_daily_limits[user_id]['boycott'] = {'date': today, 'count': 1}
    else:
        user_daily_limits[user_id]['boycott']['count'] = boycott_uses.get('count', 0) + 1
    save_data()
    
    await interaction.response.send_message(embed=embed)

    # Send DM to owner if possible
    if owner_id:
        try:
            owner = await bot.fetch_user(int(owner_id))
            await owner.send(
                f"⚠️ **BOYCOTT ALERT**\n\n"
                f"A boycott has been started against **{group_name_upper}**!\n"
                f"Type: {boycott_result['name']}\n"
                f"Duration: {boycott_result['duration_days']} days\n\n"
                f"{'Fans are protecting your group - this may actually help long-term!' if is_fan_action else 'Public backlash - expect serious losses.'}"
            )
        except:
            pass


# === TRUCK PROTEST SYSTEM ===

TRUCK_TYPES = {
    "SUPPORT": {
        "name": "Support Truck",
        "description": "Fans send support trucks with encouraging messages",
        "cost": 300_000,
        "is_positive": True,
        "effects": {
            "fanbase": (5, 12),
            "group_morale": (10, 20),
            "reputation": (3, 8)
        },
        "messages": [
            "We love you! Stay strong! 💜",
            "Your fans will always support you! 💪",
            "Take care of your health! We'll wait for you! 💕",
            "You're doing amazing! Keep going! ⭐"
        ]
    },
    "CONTRACT": {
        "name": "Contract Protest Truck",
        "description": "Fans demand fair treatment and better contracts",
        "cost": 500_000,
        "is_positive": True,
        "effects": {
            "company_pressure": (10, 25),
            "fanbase": (8, 15),
            "reputation": (5, 12),
            "company_funds": (-200000, -500000)
        },
        "messages": [
            "Fair contracts for [GROUP]! 📄",
            "Treat them better! ⚖️",
            "[COMPANY] - Listen to the fans! 📢",
            "Respect your artists! 💼"
        ]
    },
    "APOLOGY_DEMAND": {
        "name": "Apology Demand Truck",
        "description": "Antis demand public apology",
        "cost": 400_000,
        "is_positive": False,
        "effects": {
            "reputation": (-8, -3),
            "gp": (-5, -2),
            "company_pressure": (15, 30)
        },
        "messages": [
            "Apologize NOW! 🚫",
            "Accountability matters! ⚠️",
            "We won't forget! 📢",
            "Actions have consequences! ❌"
        ]
    },
    "DISBANDMENT": {
        "name": "Disbandment Demand Truck",
        "description": "Extreme antis demand group disbandment",
        "cost": 600_000,
        "is_positive": False,
        "effects": {
            "reputation": (-15, -8),
            "group_popularity": (-30, -15),
            "fanbase_rally": (10, 20),  # Fans rally in defense!
            "company_pressure": (20, 40)
        },
        "messages": [
            "[GROUP] should disband! 🚫",
            "Cancel [GROUP]! ❌",
            "Unacceptable behavior! 🛑",
            "We won't support this! 💢"
        ]
    },
    "OVERWORK": {
        "name": "Rest Demand Truck",
        "description": "Fans demand the group get proper rest",
        "cost": 350_000,
        "is_positive": True,
        "effects": {
            "fanbase": (6, 13),
            "reputation": (8, 15),
            "gp": (5, 10),
            "company_pressure": (8, 15)
        },
        "messages": [
            "Let them rest! 😴",
            "Health before schedules! 💚",
            "Stop overworking them! ⚠️",
            "Idols are human too! 💜"
        ]
    }
}


@bot.tree.command(description="Send a protest truck! Fans support, antis attack.")
@app_commands.describe(
    target="Group name OR company name",
    truck_type="Type of truck protest",
    custom_message="Optional: Custom message for the truck (max 100 chars)"
)
@app_commands.choices(truck_type=[
    app_commands.Choice(name="💜 Support Truck (Fans)", value="SUPPORT"),
    app_commands.Choice(name="📄 Contract Protest (Fans)", value="CONTRACT"),
    app_commands.Choice(name="😴 Rest Demand (Fans)", value="OVERWORK"),
    app_commands.Choice(name="🚫 Apology Demand (Antis)", value="APOLOGY_DEMAND"),
    app_commands.Choice(name="❌ Disbandment Demand (Antis)", value="DISBANDMENT")
])
async def truck(interaction: discord.Interaction, target: str, truck_type: str, custom_message: str = None):
    user_id = str(interaction.user.id)
    target_upper = target.upper()
    
    # Daily limit check (1 per day per user)
    today = get_today_str()
    user_daily_limits.setdefault(user_id, {})
    truck_uses = user_daily_limits[user_id].get('truck', {})
    if truck_uses.get('date') == today and truck_uses.get('count', 0) >= 1:
        await interaction.response.send_message("❌ You can only send 1 truck per day!", ephemeral=True)
        return

    truck_info = TRUCK_TYPES.get(truck_type)
    if not truck_info:
        await interaction.response.send_message("❌ Invalid truck type.", ephemeral=True)
        return

    # Check if target is group or company
    is_group = target_upper in group_data
    is_company = target_upper in company_funds

    if not is_group and not is_company:
        await interaction.response.send_message("❌ Target not found. Must be a group or company name.", ephemeral=True)
        return

    # Check user funds
    user_balance = user_balances.get(user_id, 0)
    if user_balance < truck_info['cost']:
        await interaction.response.send_message(
            f"❌ Not enough funds! Trucks cost <:MonthlyPeso:1338642658436059239>{format_number(truck_info['cost'])}.",
            ephemeral=True
        )
        return

    # Deduct cost
    user_balances[user_id] = user_balance - truck_info['cost']

    # Determine message
    if custom_message:
        message = custom_message[:100]
    else:
        message = random.choice(truck_info['messages'])
        if is_group:
            message = message.replace('[GROUP]', target_upper)
        else:
            message = message.replace('[COMPANY]', target_upper)

    # Apply effects
    if is_group:
        group_entry = group_data[target_upper]
        effects = truck_info['effects']

        changes = {}

        if 'fanbase' in effects:
            change = random.randint(*effects['fanbase'])
            old_fanbase = group_entry.get('fanbase', 50)
            group_entry['fanbase'] = max(0, min(100, old_fanbase + change))
            changes['fanbase'] = change

        if 'reputation' in effects:
            change = random.randint(*effects['reputation'])
            apply_reputation_change(target_upper, change, f"Truck protest: {truck_info['name']}")
            changes['reputation'] = change

        if 'gp' in effects:
            change = random.randint(*effects['gp'])
            group_entry['gp'] = max(0, min(100, group_entry.get('gp', 30) + change))
            changes['gp'] = change

        if 'group_popularity' in effects:
            change = random.randint(*effects['group_popularity'])
            distribute_stat_gain_to_members(target_upper, 'popularity', change)
            changes['popularity'] = change

        if 'fanbase_rally' in effects:
            # Fans rally in defense
            rally = random.randint(*effects['fanbase_rally'])
            group_entry['fanbase'] = min(100, group_entry.get('fanbase', 50) + rally)
            changes['fanbase_rally'] = rally

        if 'company_funds' in effects:
            company_name = group_entry.get('company')
            if company_name and company_name in company_funds:
                loss = random.randint(*effects['company_funds'])
                company_funds[company_name] = max(0, company_funds[company_name] + loss)

        # Track pressure
        if 'company_pressure' in effects:
            group_entry.setdefault('company_pressure', 0)
            pressure = random.randint(*effects['company_pressure'])
            group_entry['company_pressure'] += pressure
            changes['pressure'] = pressure

    else:  # Company target
        # Affect all groups under company
        affected_groups = [g for g, gd in group_data.items() if gd.get('company') == target_upper]
        changes = {'affected_groups': len(affected_groups)}

        if 'company_funds' in truck_info['effects']:
            loss = random.randint(*truck_info['effects']['company_funds'])
            company_funds[target_upper] = max(0, company_funds.get(target_upper, 0) + loss)
            changes['funds_lost'] = abs(loss)

    save_data()

    # Create announcement
    is_positive = truck_info['is_positive']

    embed = discord.Embed(
        title=f"🚛 {truck_info['name']} Spotted!",
        description=f"A protest truck has been sent to **{target_upper}**!",
        color=discord.Color.green() if is_positive else discord.Color.red()
    )

    embed.add_field(
        name="📢 Message",
        value=f"*\"{message}\"*",
        inline=False
    )

    # Show effects
    effects_text = []
    if 'fanbase' in changes:
        effects_text.append(f"Fanbase: {changes['fanbase']:+}")
    if 'reputation' in changes:
        effects_text.append(f"Reputation: {changes['reputation']:+}")
    if 'gp' in changes:
        effects_text.append(f"GP: {changes['gp']:+}")
    if 'popularity' in changes:
        effects_text.append(f"Popularity: {changes['popularity']:+}")
    if 'fanbase_rally' in changes:
        effects_text.append(f"💪 Fans rallied in defense! Fanbase +{changes['fanbase_rally']}")
    if 'pressure' in changes:
        effects_text.append(f"⚠️ Company pressure increased")
    if 'affected_groups' in changes:
        effects_text.append(f"Affected {changes['affected_groups']} group(s) under {target_upper}")

    if effects_text:
        embed.add_field(name="Impact", value="\n".join(effects_text), inline=False)

    embed.add_field(name="Cost", value=f"<:MonthlyPeso:1338642658436059239>{format_number(truck_info['cost'])}", inline=True)
    embed.add_field(name="Sent by", value=interaction.user.display_name, inline=True)

    if is_positive:
        embed.set_footer(text="💜 Fans showing their support!")
    else:
        embed.set_footer(text="The controversy continues...")

    # Track daily usage
    if truck_uses.get('date') != today:
        user_daily_limits[user_id]['truck'] = {'date': today, 'count': 1}
    else:
        user_daily_limits[user_id]['truck']['count'] = truck_uses.get('count', 0) + 1
    save_data()

    await interaction.response.send_message(embed=embed)


# === SONG QUALITY SYSTEM ===

def calculate_song_quality(group_name: str, production_investment: int) -> dict:
    """Calculate song quality based on production investment and studio level."""
    if group_name not in group_data:
        return {'quality': 50, 'tier': 'Average'}
    
    group_entry = group_data[group_name]
    company_name = group_entry.get('company')
    
    # Base quality from investment (0-100 scale)
    base_quality = min(100, (production_investment / 50000) * 20)  # 50k = 20 quality
    
    # Recording studio bonus
    studio_bonus = 0
    if company_name:
        studio_bonus = get_company_building_bonus(company_name, 'song_quality_boost')
    
    # Member skill average affects quality
    members = group_entry.get('members', [])
    avg_skill = 30  # Default
    if members:
        vocal_avg = 0
        count = 0
        for m in members:
            if isinstance(m, dict):
                vocal_avg += m.get('skills', {}).get('vocal', {}).get('value', 30)
                count += 1
        if count > 0:
            avg_skill = vocal_avg / count
    
    skill_bonus = (avg_skill - 30) / 2  # Max +35 from skills
    
    total_quality = min(100, base_quality + studio_bonus + skill_bonus)
    
    # Determine tier
    if total_quality >= 85:
        tier = 'Masterpiece'
        longevity_mult = 1.5
    elif total_quality >= 70:
        tier = 'Excellent'
        longevity_mult = 1.3
    elif total_quality >= 55:
        tier = 'Good'
        longevity_mult = 1.15
    elif total_quality >= 40:
        tier = 'Average'
        longevity_mult = 1.0
    else:
        tier = 'Below Average'
        longevity_mult = 0.85
    
    return {
        'quality': int(total_quality),
        'tier': tier,
        'longevity_mult': longevity_mult,
        'investment': production_investment,
        'studio_bonus': studio_bonus,
        'skill_bonus': skill_bonus
    }


@bot.tree.command(description="View your group's international presence")
@app_commands.autocomplete(group_name=group_autocomplete)
async def international_presence(interaction: discord.Interaction, group_name: str):
    group_name_upper = group_name.upper()
    
    if group_name_upper not in group_data:
        await interaction.response.send_message("❌ Group not found.", ephemeral=True)
        return
    
    group_entry = group_data[group_name_upper]
    countries_performed = group_entry.get('countries_performed', [])
    
    if isinstance(countries_performed, set):
        countries_performed = list(countries_performed)
        group_entry['countries_performed'] = countries_performed
        save_data()
    
    embed = discord.Embed(
        title=f"🌍 {group_name_upper} - International Presence",
        description=f"Performed in {len(countries_performed)} countries",
        color=discord.Color.blue()
    )
    
    if countries_performed:
        # Group by region
        asia = [c for c in countries_performed if c in ["South Korea", "Japan", "China", "Thailand", "Philippines", "Indonesia", "Singapore"]]
        americas = [c for c in countries_performed if c in ["United States", "Mexico", "Brazil", "Argentina"]]
        europe = [c for c in countries_performed if c in ["United Kingdom", "France", "Germany"]]
        oceania = [c for c in countries_performed if c in ["Australia"]]
        
        if asia:
            embed.add_field(name="🌏 Asia", value=", ".join(asia), inline=False)
        if americas:
            embed.add_field(name="🌎 Americas", value=", ".join(americas), inline=False)
        if europe:
            embed.add_field(name="🌍 Europe", value=", ".join(europe), inline=False)
        if oceania:
            embed.add_field(name="🌏 Oceania", value=", ".join(oceania), inline=False)
    else:
        embed.add_field(name="No International Tours Yet", value="Use `/worldtour` to expand globally!", inline=False)
    
    await interaction.response.send_message(embed=embed)

# 🏢 COMPANY & GROUP MANAGEMENT:
@bot.tree.command(description="Register a new company.")
async def addcompany(interaction: discord.Interaction, name: str):
    company_name_upper = name.strip().upper()
    user_id = str(interaction.user.id)

    if company_name_upper in company_funds:
        await interaction.response.send_message(f"❌ Company `{name}` already exists.")
        return

    # User can now own multiple companies
    if user_id not in user_companies:
        user_companies[user_id] = []

    if company_name_upper in user_companies[user_id]:
        await interaction.response.send_message(f"❌ You already own a company named `{name}`.", ephemeral=True)
        return

    # Create company document
    company_funds[company_name_upper] = 0
    user_companies[user_id].append(company_name_upper) # Add to list of owned companies
    save_data() # Save data after modification

    embed = discord.Embed(
        title=f"🏢 Company Registered: {name}",
        description=f"Congratulations, {interaction.user.display_name}! You are now the CEO of **{name}**!",
        color=discord.Color.dark_green()
    )
    embed.add_field(name="Initial Funds", value=f"<:MonthlyPeso:1338642658436059239>0", inline=False)
    embed.set_footer(text="Start debuting groups and earning money!")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Add a new group to an existing company.")
async def addgroup(
    interaction: discord.Interaction, 
    group_name: str, 
    korean_name: str, 
    company_name: str, # Now explicitly pass company name
    initial_wins: int = 0
):
    user_id = str(interaction.user.id)
    company_name_upper = company_name.upper()

    if not is_user_company_owner(user_id, company_name_upper):
        await interaction.response.send_message(f"❌ You do not own the company `{company_name}`.", ephemeral=True)
        return

    group_name_upper = group_name.upper()
    if group_name_upper in group_data:
        await interaction.response.send_message(f"❌ Group `{group_name}` already exists. Please choose a different name.")
        return

    if initial_wins < 0:
        await interaction.response.send_message("❌ Initial wins cannot be negative.")
        return

    # Create group entry
    new_group_data = {
        'company': company_name_upper,
        'albums': [], 
        'korean_name': korean_name,
        'wins': initial_wins, 
        'popularity': 100, 
        'fanbase': 50,
        'gp': 30,
        'payola_suspicion': 0,
        'debut_date': datetime.now().strftime("%Y-%m-%d"),
        'is_disbanded': False
    }
    group_data[group_name_upper] = new_group_data
    group_popularity[group_name_upper] = new_group_data['popularity']
    save_data()

    embed = discord.Embed(
        title=f"🎤 New Group Added: {group_name}",
        description=f"**{group_name}** ({korean_name}) has been added to **{company_name_upper}**!",
        color=discord.Color.dark_teal()
    )
    embed.add_field(name="Initial Wins", value=initial_wins, inline=True)
    embed.add_field(name="Initial Popularity", value=new_group_data['popularity'], inline=True)
    embed.add_field(name="Fanbase", value=f"{new_group_data['fanbase']}", inline=True)
    embed.add_field(name="GP Interest", value=f"{new_group_data['gp']}", inline=True)
    embed.set_footer(text=f"Ready for their debut!")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Debut a new group with their first album.")
@app_commands.describe(
    album_type="Album type: full, mini, or single",
    album_format="Album format: digital or physical"
)
@app_commands.choices(
    album_type=[
        app_commands.Choice(name="Full Album", value="full"),
        app_commands.Choice(name="Mini Album", value="mini"),
        app_commands.Choice(name="Single", value="single")
    ],
    album_format=[
        app_commands.Choice(name="Digital", value="digital"),
        app_commands.Choice(name="Physical", value="physical")
    ]
)
async def debut(
    interaction: discord.Interaction, 
    group_name: str, 
    korean_name: str, 
    album_name: str, 
    company_name: str,
    investment: int,
    album_type: str = "mini",
    album_format: str = "physical",
    image_url: str = DEFAULT_ALBUM_IMAGE
):
    user_id = str(interaction.user.id)
    company_name_upper = company_name.upper()

    if not is_user_company_owner(user_id, company_name_upper):
        await interaction.response.send_message(f"❌ You do not own the company `{company_name}`.", ephemeral=True)
        return

    group_name_upper = group_name.upper()
    if group_name_upper in group_data:
        await interaction.response.send_message(f"❌ Group `{group_name}` already exists. Please choose a different name or use `/comeback`.")
        return

    if album_name in album_data:
        await interaction.response.send_message(f"❌ Album `{album_name}` already exists. Please choose a different name.")
        return

    current_company_funds = company_funds.get(company_name_upper, 0)

    if investment <= 0:
        await interaction.response.send_message("❌ Investment must be a positive number.")
        return
    if current_company_funds < investment:
        await interaction.response.send_message(f"❌ Your company `{company_name_upper}` only has <:MonthlyPeso:1338642658436059239>{current_company_funds:,}. Not enough funds.")
        return

    # Deduct investment from company funds
    company_funds[company_name_upper] = current_company_funds - investment

    # Create group entry with fanbase/gp based on investment
    base_fanbase = 50 + min(30, investment // 200000)
    base_gp = 30 + min(20, investment // 300000)
    
    new_group_data = {
        'company': company_name_upper,
        'albums': [album_name],
        'korean_name': korean_name,
        'wins': 0,
        'popularity': 100 + (investment // 100000), 
        'fanbase': base_fanbase,
        'gp': base_gp,
        'payola_suspicion': 0,
        'debut_date': datetime.now(ARG_TZ).strftime("%Y-%m-%d"),
        'is_disbanded': False,
        'profile_picture': None,
        'banner_url': None,
        'description': None,
        'all_kills': 0
    }
    group_data[group_name_upper] = new_group_data
    group_popularity[group_name_upper] = new_group_data['popularity']

    initial_stock = random.randint(500000, 1500000) if album_format == "physical" else 0
    
    new_album_data = {
        'group': group_name_upper,
        'wins': 0,
        'release_date': datetime.now(ARG_TZ).strftime("%Y-%m-%d"),
        'streams': 0, 
        'sales': 0,
        'views': 0,
        'image_url': image_url,
        'is_active_promotion': False,
        'promotion_end_date': None,
        'first_24h_tracking': None,
        'album_type': album_type,
        'album_format': album_format,
        'stock': initial_stock,
        'charts_info': {
            "MelOn": {'rank': None, 'peak': None, 'prev_rank': None},
            "Genie": {'rank': None, 'peak': None, 'prev_rank': None},
            "Bugs": {'rank': None, 'peak': None, 'prev_rank': None},
            "FLO": {'rank': None, 'peak': None, 'prev_rank': None}
        }
    }
    album_data[album_name] = new_album_data
    save_data()

    type_display = {"full": "Full Album", "mini": "Mini Album", "single": "Single"}.get(album_type, album_type)
    format_icon = "💿" if album_format == "physical" else "🎵"
    
    embed = discord.Embed(
        title=f"DEBUT - {group_name}",
        description=f"**{group_name}** ({korean_name}) debuts under **{company_name_upper}**",
        color=discord.Color.from_rgb(255, 105, 180)
    )
    embed.set_thumbnail(url=image_url)
    embed.add_field(name="Album", value=f"{format_icon} {album_name}", inline=True)
    embed.add_field(name="Type", value=type_display, inline=True)
    embed.add_field(name="Format", value=album_format.title(), inline=True)
    if album_format == "physical":
        embed.add_field(name="Stock", value=f"{initial_stock:,} copies", inline=True)
    embed.add_field(name="Popularity", value=new_group_data['popularity'], inline=True)
    embed.add_field(name="Investment", value=f"<:MonthlyPeso:1338642658436059239>{investment:,}", inline=True)
    embed.set_footer(text=new_group_data['debut_date'])
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Announce a group's comeback with a new album.")
@app_commands.describe(
    album_type="Album type: full, mini, or single",
    album_format="Album format: digital or physical"
)
@app_commands.choices(
    album_type=[
        app_commands.Choice(name="Full Album", value="full"),
        app_commands.Choice(name="Mini Album", value="mini"),
        app_commands.Choice(name="Single", value="single")
    ],
    album_format=[
        app_commands.Choice(name="Digital", value="digital"),
        app_commands.Choice(name="Physical", value="physical")
    ]
)
async def comeback(
    interaction: discord.Interaction, 
    group_name: str, 
    album_name: str, 
    investment: int,
    album_type: str = "mini",
    album_format: str = "physical",
    image_url: str = DEFAULT_ALBUM_IMAGE
):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()

    if not is_user_group_owner(user_id, group_name_upper):
        await interaction.response.send_message(f"❌ Group `{group_name}` not found or does not belong to your company.", ephemeral=True)
        return

    if group_data[group_name_upper].get('is_disbanded'):
        await interaction.response.send_message(f"❌ This group is disbanded and cannot make a comeback.", ephemeral=True)
        return

    if album_name in album_data:
        await interaction.response.send_message(f"❌ Album `{album_name}` already exists. Please choose a different name.")
        return

    company_name = get_group_owner_company(group_name_upper)
    current_company_funds = company_funds.get(company_name, 0)

    if investment <= 0:
        await interaction.response.send_message("❌ Investment must be a positive number.")
        return
    if current_company_funds < investment:
        await interaction.response.send_message(f"❌ Your company `{company_name}` only has <:MonthlyPeso:1338642658436059239>{current_company_funds:,}. Not enough funds.")
        return

    # Deduct investment from company funds
    company_funds[company_name] = current_company_funds - investment

    group_entry = group_data[group_name_upper]
    group_entry['albums'].append(album_name)
    group_entry['popularity'] = group_entry.get('popularity', 0) + (investment // 200000) 

    recent_albums = group_entry.get('albums', [])[-4:]
    recent_types = [album_data.get(a, {}).get('album_type', 'mini') for a in recent_albums if a in album_data]
    
    fanbase_change = 0
    fanbase_note = ""
    
    if album_type == "full":
        singles_minis_streak = sum(1 for t in recent_types if t in ['single', 'mini'])
        if singles_minis_streak >= 2:
            fanbase_change = random.randint(8, 15)
            fanbase_note = "Fans excited for full album!"
        else:
            fanbase_change = random.randint(3, 8)
            fanbase_note = "Full album boosts loyalty"
    elif album_type == "single":
        single_count = sum(1 for t in recent_types if t == 'single')
        if single_count >= 2:
            fanbase_change = random.randint(-8, -3)
            fanbase_note = "Too many singles, fans disappointed"
        else:
            fanbase_change = random.randint(1, 3)
    elif album_type == "mini":
        mini_count = sum(1 for t in recent_types if t == 'mini')
        if mini_count >= 3:
            fanbase_change = random.randint(-5, -2)
            fanbase_note = "Fans want a full album"
        else:
            fanbase_change = random.randint(2, 5)
    
    investment_boost = min(5, investment // 500000)
    total_fanbase_change = fanbase_change + investment_boost
    group_entry['fanbase'] = max(0, min(100, group_entry.get('fanbase', 50) + total_fanbase_change))
    
    initial_stock = random.randint(500000, 1500000) if album_format == "physical" else 0
    
    new_album_data = {
        'group': group_name_upper,
        'wins': 0,
        'release_date': datetime.now(ARG_TZ).strftime("%Y-%m-%d"),
        'streams': 0, 
        'sales': 0,
        'views': 0,
        'image_url': image_url,
        'is_active_promotion': False,
        'promotion_end_date': None,
        'first_24h_tracking': None,
        'album_type': album_type,
        'album_format': album_format,
        'stock': initial_stock,
        'charts_info': {
            "MelOn": {'rank': None, 'peak': None, 'prev_rank': None},
            "Genie": {'rank': None, 'peak': None, 'prev_rank': None},
            "Bugs": {'rank': None, 'peak': None, 'prev_rank': None},
            "FLO": {'rank': None, 'peak': None, 'prev_rank': None}
        }
    }
    album_data[album_name] = new_album_data
    save_data()

    type_display = {"full": "Full Album", "mini": "Mini Album", "single": "Single"}.get(album_type, album_type)
    format_icon = "💿" if album_format == "physical" else "🎵"
    
    embed = discord.Embed(
        title=f"COMEBACK - {group_name_upper}",
        description=f"**{group_name_upper}** returns with '{album_name}'",
        color=discord.Color.from_rgb(255, 105, 180)
    )
    embed.set_thumbnail(url=image_url)
    embed.add_field(name="Type", value=f"{format_icon} {type_display}", inline=True)
    embed.add_field(name="Format", value=album_format.title(), inline=True)
    if album_format == "physical":
        embed.add_field(name="Stock", value=f"{initial_stock:,}", inline=True)
    
    fanbase_display = f"{group_entry['fanbase']}"
    if total_fanbase_change > 0:
        fanbase_display += f" (+{total_fanbase_change})"
    elif total_fanbase_change < 0:
        fanbase_display += f" ({total_fanbase_change})"
    embed.add_field(name="Fanbase", value=fanbase_display, inline=True)
    embed.add_field(name="Popularity", value=group_entry['popularity'], inline=True)
    if fanbase_note:
        embed.set_footer(text=fanbase_note)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(description="Disband a group (requires confirmation).")
@app_commands.autocomplete(group_name=user_group_autocomplete)
async def disband(interaction: discord.Interaction, group_name: str):
    group_name_upper = group_name.upper()
    user_id = str(interaction.user.id)

    if group_name_upper not in group_data:
        await interaction.response.send_message(f"❌ Group `{group_name}` not found.")
        return

    group_entry = group_data[group_name_upper]
    company_name_of_group = group_entry.get('company')

    if not is_user_company_owner(user_id, company_name_of_group):
        await interaction.response.send_message(f"❌ You can only disband groups belonging to your company `{company_name_of_group}`.", ephemeral=True)
        return

    if group_entry.get('is_disbanded'):
        await interaction.response.send_message(f"❌ Group `{group_name_upper}` is already disbanded.", ephemeral=True)
        return

    class DisbandConfirmView(ui.View):
        def __init__(self, group_name_to_disband, interaction_original):
            super().__init__()
            self.group_name_to_disband = group_name_to_disband
            self.original_interaction = interaction_original # Correctly store the original interaction

        @ui.button(label="Confirm Disband", style=discord.ButtonStyle.red)
        async def confirm_callback(self, interaction: discord.Interaction, button: ui.Button):
            if interaction.user.id != self.original_interaction.user.id: # Check against original interaction user
                await interaction.response.send_message("❌ This confirmation is not for you.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=False) 

            # Mark group as disbanded
            if self.group_name_to_disband in group_data:
                group_data[self.group_name_to_disband]['is_disbanded'] = True
                group_data[self.group_name_to_disband]['popularity'] = 0 # Set popularity to 0 upon disbandment

            # Albums remain, but are no longer actively promoted and won't chart.
            # No need to delete album data, just deactivate promotions.
            for album_name in group_data[self.group_name_to_disband].get('albums', []):
                if album_name in album_data:
                    album_data[album_name]['is_active_promotion'] = False
                    album_data[album_name]['promotion_end_date'] = None
                    for chart_key in album_data[album_name]['charts_info']:
                        album_data[album_name]['charts_info'][chart_key] = {'rank': None, 'peak': None, 'prev_rank': None}

            save_data() # Save data after modifications

            await self.original_interaction.edit_original_response(content=f"💀 Group **{self.group_name_to_disband}** has been disbanded. Their albums are no longer actively promoted.", view=None)
            self.stop() 

        @ui.button(label="Cancel", style=discord.ButtonStyle.grey)
        async def cancel_callback(self, interaction: discord.Interaction, button: ui.Button):
            if interaction.user.id != self.original_interaction.user.id: # Check against original interaction user
                await interaction.response.send_message("❌ This cancellation is not for you.", ephemeral=True)
                return
            await self.original_interaction.edit_original_response(content=f"Disbanding of **{self.group_name_to_disband}** cancelled.", view=None)
            self.stop() 

    view = DisbandConfirmView(group_name_upper, interaction)
    await interaction.response.send_message(
        f"Are you sure you want to disband **{group_name}**? This action will mark the group as inactive and prevent future activities, but will **not** delete their historical data.",
        view=view,
        ephemeral=True
    )


@bot.tree.command(description="Show the leaderboard of most popular groups.")
async def groups(interaction: discord.Interaction):
    if not group_data:
        await interaction.response.send_message("No groups registered yet.")
        return

    # Only include valid dict entries (prevents unexpected crashes)
    active_groups = {
        name: data
        for name, data in group_data.items()
        if isinstance(data, dict)
    }

    sorted_groups = sorted(
        active_groups.items(),
        key=lambda item: item[1].get('popularity', 0),
        reverse=True
    )

    embed = discord.Embed(
        title="Most Popular Groups",
        color=discord.Color.from_rgb(255, 105, 180)
    )

    leaderboard_lines = []
    for i, (group_name, data) in enumerate(sorted_groups[:10]):
        company = data.get('company', 'N/A')
        popularity = data.get('popularity', 0)
        nations_tag = " 🩷" if data.get('is_nations_group') else ""
        leaderboard_lines.append(
            f"**{i+1}. [{group_name}]** — {popularity} pts{nations_tag}\n`{company}`"
        )

    embed.description = "\n\n".join(leaderboard_lines) if leaderboard_lines else "No groups available."
    embed.set_footer(text="Use /view_group <name> to see full profile")

    await interaction.response.send_message(embed=embed)

@bot.tree.command(description="Show leaderboards for companies (richest).")
async def companies(interaction: discord.Interaction):
    if not company_funds:
        await interaction.response.send_message("No companies registered yet.")
        return

    # Richest Companies
    richest_companies = sorted(company_funds.items(), key=lambda item: item[1], reverse=True)
    company_embed = discord.Embed(title="Richest Companies", color=discord.Color.from_rgb(255, 105, 180))
    if richest_companies:
        for i, (company_name, funds) in enumerate(richest_companies[:10]):
            company_embed.add_field(name=f"{i+1}. {company_name}", value=f"Funds: <:MonthlyPeso:1338642658436059239>{funds:,}", inline=False)
    else:
        company_embed.add_field(name="No companies", value="No companies registered yet.", inline=False)

    await interaction.response.send_message(embed=company_embed) # Changed 'embed' to 'company_embed'


# === Chart Logic and Command ===

# CHART_CONFIG for realism - each chart has different difficulty levels
# streams_for_top_10: streams needed to potentially reach top 10
# streams_for_top_50: streams needed to potentially reach top 50
# streams_for_charting: minimum streams to appear on chart at all
CHART_CONFIG = {
    "MelOn": {
        "charting_threshold": 100,
        "streams_for_top_10": 8_000_000,
        "streams_for_top_50": 2_000_000,
        "streams_for_charting": 500_000,
    },
    "Genie": {
        "charting_threshold": 100,
        "streams_for_top_10": 5_000_000,
        "streams_for_top_50": 1_000_000,
        "streams_for_charting": 300_000,
    },
    "Bugs": {
        "charting_threshold": 100,
        "streams_for_top_10": 3_000_000,
        "streams_for_top_50": 500_000,
        "streams_for_charting": 150_000,
    }, 
    "FLO": {
        "charting_threshold": 100,
        "streams_for_top_10": 2_000_000,
        "streams_for_top_50": 400_000,
        "streams_for_charting": 100_000,
    },
}


# How quickly an album's chart standing fades. Lifetime streams are halved
# every CHART_HALF_LIFE_DAYS since release, so a record slides off the chart
# instead of holding a position forever, while recent streaming pushes back
# against the decay. Raise it to keep older albums around longer.
CHART_HALF_LIFE_DAYS = 60
CHART_RECENT_DAYS = 7
CHART_RECENT_WEIGHT = 5 # Recent plays count for more than lifetime totals


def _chart_score(album_entry: dict):
    """An album's chart standing: lifetime streams decayed by age, plus recent plays.

    Using lifetime streams alone made every album chart forever - 96 of 174
    albums qualified, filling almost every position and leaving no room for the
    rest of the industry. Decay is what lets a song chart after its promotion
    ends and then fade naturally once people stop playing it.
    """
    lifetime = album_entry.get('streams', 0)

    release_date = album_entry.get('release_date', '')
    try:
        age_days = (datetime.now(ARG_TZ).date() - datetime.fromisoformat(release_date).date()).days
    except (ValueError, TypeError):
        age_days = 0
    age_days = max(0, age_days)

    decayed = lifetime * (0.5 ** (age_days / CHART_HALF_LIFE_DAYS))

    recent = 0
    daily = album_entry.get('daily_streams')
    if isinstance(daily, dict):
        today = datetime.now(ARG_TZ).date()
        for offset in range(CHART_RECENT_DAYS):
            recent += daily.get((today - timedelta(days=offset)).strftime("%Y-%m-%d"), 0)

    return int(decayed + recent * CHART_RECENT_WEIGHT)


def _get_all_active_albums():
    """Albums eligible to chart.

    Deliberately not restricted to actively promoted albums: a song keeps
    charting while people are still playing it, and _chart_score's decay is
    what removes the ones nobody is listening to.
    """
    active_albums = []
    for album_name, album_entry in album_data.items():
        group_name = album_entry.get('group')
        if group_name and group_data.get(group_name, {}).get('is_disbanded'):
            continue
        active_albums.append((album_name, album_entry))
    return active_albums


def _calculate_base_rank(streams: int, chart_settings: dict):
    """
    Calculates what rank an album DESERVES based on its streams alone.
    Returns a base rank (1-100+) or None if not enough streams to chart.
    """
    streams_for_charting = chart_settings['streams_for_charting']
    streams_for_top_50 = chart_settings['streams_for_top_50']
    streams_for_top_10 = chart_settings['streams_for_top_10']
    threshold = chart_settings['charting_threshold']
    
    if streams < streams_for_charting:
        return None
    
    # Deterministic: the same score always yields the same rank, and a higher
    # score always ranks better. Random jitter here used to invent movement
    # between two views of an unchanged chart, and could place a
    # lower-streaming album above a higher-streaming one.
    if streams >= streams_for_top_10:
        ratio = streams / streams_for_top_10
        base_rank = max(1, int(11 - (ratio * 2)))
        return max(1, min(10, base_rank))
    elif streams >= streams_for_top_50:
        ratio = (streams - streams_for_top_50) / (streams_for_top_10 - streams_for_top_50)
        base_rank = int(50 - (ratio * 40))
        return max(11, min(50, base_rank))
    elif streams >= streams_for_charting:
        ratio = (streams - streams_for_charting) / (streams_for_top_50 - streams_for_charting)
        base_rank = int(threshold - (ratio * (threshold - 51)))
        return max(51, min(threshold, base_rank))
    
    return None


def _calculate_all_chart_ranks(chart_name: str, chart_settings: dict):
    """
    Calculates unique chart ranks for all active albums on a specific chart.
    Albums get ranks based on their streams (absolute), then adjusted to ensure uniqueness.
    Returns a dict mapping album_name -> rank (or None if not charting).
    """
    active_albums = _get_all_active_albums()
    
    album_base_ranks = []
    for album_name, album_entry in active_albums:
        streams = _chart_score(album_entry)
        base_rank = _calculate_base_rank(streams, chart_settings)
        if base_rank is not None:
            album_base_ranks.append((album_name, base_rank, streams))
    
    album_base_ranks.sort(key=lambda x: (x[1], -x[2]))
    
    ranks = {}
    used_ranks = set()
    
    for album_name, base_rank, streams in album_base_ranks:
        final_rank = base_rank
        while final_rank in used_ranks:
            final_rank += 1
        
        if final_rank > chart_settings['charting_threshold']:
            ranks[album_name] = None
        else:
            ranks[album_name] = final_rank
            used_ranks.add(final_rank)
    
    return ranks


def _get_chart_info(album_entry: dict, chart_type: str):
    """Retrieves chart information for a specific album and chart type, ensuring structure exists."""
    if 'charts_info' not in album_entry:
        album_entry['charts_info'] = {}

    if chart_type not in album_entry['charts_info']:
        album_entry['charts_info'][chart_type] = {'rank': None, 'peak': None, 'prev_rank': None}

    return album_entry['charts_info'][chart_type]

def _update_and_format_chart_line(album_entry: dict, chart_name: str, calculated_rank: int):
    """Updates chart info for an album and returns a formatted string for the report."""
    chart_info = _get_chart_info(album_entry, chart_name)

    # Store current rank as previous for the next update
    chart_info['prev_rank'] = chart_info['rank'] 
    chart_info['rank'] = calculated_rank

    # Update peak rank (lower number is better)
    if chart_info['peak'] is None or (calculated_rank is not None and calculated_rank < chart_info['peak']):
        chart_info['peak'] = calculated_rank

    # --- Formatting the line ---
    rank_str = f"#{calculated_rank}" if calculated_rank is not None else "N/A"

    rank_change_text = ""
    is_new_entry = (chart_info['prev_rank'] is None and calculated_rank is not None)

    if is_new_entry:
        rank_change_text = "(NEW)"
    elif calculated_rank is not None and chart_info['prev_rank'] is not None:
        change = chart_info['prev_rank'] - calculated_rank # Positive if rank improved (lower number)
        if change > 0:
            rank_change_text = f"(+{change})"
        elif change < 0:
            rank_change_text = f"({change})" # Already has a minus sign
        else:
            rank_change_text = "(=)"

    new_peak_text = ""
    # Check for new peak: if current rank is the lowest (best) rank achieved so far, and it's charting
    if calculated_rank is not None and calculated_rank == chart_info['peak']:
        # Only mark as "new peak" if it's actually an improvement or the first recorded rank that's charting
        if chart_info['prev_rank'] is None or calculated_rank < chart_info['prev_rank']:
            new_peak_text = "*new peak"

    return f"{rank_str} {chart_name} {rank_change_text} {new_peak_text}".strip()


CHARTS_ENTRIES_SHOWN = 10 # Per platform, on the overall chart view


@bot.tree.command(description="Show the current music charts, or one group's chart run.")
@app_commands.describe(
    group_name="Optional: a single group's chart information. Omit to see the overall charts."
)
@app_commands.autocomplete(group_name=group_autocomplete)
async def charts(interaction: discord.Interaction, group_name: str = None):
    # No group given: show the overall charts across every platform.
    #
    # This branch is READ ONLY. The per-group view below records prev_rank and
    # peak as it goes, so if browsing the overall chart did the same, simply
    # looking at it would manufacture movement in every group's next report.
    if group_name is None:
        current_date_formatted = f"{datetime.now(ARG_TZ).strftime('%B')} {ordinal(datetime.now(ARG_TZ).day)}"
        embed = discord.Embed(
            title=f"📊 Music Charts — {current_date_formatted}",
            color=discord.Color.blurple(),
        )

        charting_anywhere = False
        for platform_name, settings in CHART_CONFIG.items():
            all_ranks = _calculate_all_chart_ranks(platform_name, settings)
            ranked = sorted(
                ((rank, name) for name, rank in all_ranks.items() if rank is not None)
            )
            if not ranked:
                embed.add_field(name=platform_name, value="*No albums charting.*", inline=False)
                continue

            charting_anywhere = True

            # Only real albums are listed. The positions in between belong to
            # the rest of the industry, which is never named or shown - the gaps
            # in the numbering are what make this read as a public chart.
            lines = [
                f"`#{rank}` **{album_data.get(name, {}).get('group', '?')}** — {name}"
                for rank, name in ranked[:CHARTS_ENTRIES_SHOWN]
            ]
            if len(ranked) > CHARTS_ENTRIES_SHOWN:
                lines.append(f"*…and {len(ranked) - CHARTS_ENTRIES_SHOWN} more charting below.*")

            # Stay inside Discord's 1024 character limit for an embed field.
            value = "\n".join(lines)
            if len(value) > 1024:
                value = value[:1010].rsplit("\n", 1)[0] + "\n*…*"
            embed.add_field(name=platform_name, value=value, inline=False)

        if not charting_anywhere:
            embed.description = "Nothing is charting right now."
        embed.set_footer(text="Use /charts <group> for one group's chart run.")

        await interaction.response.send_message(embed=embed)
        return

    group_name_upper = group_name.upper()

    if group_name_upper not in group_data:
        await interaction.response.send_message(f"❌ Group `{group_name}` not found. Please check the name.", ephemeral=True)
        return

    if group_data[group_name_upper].get('is_disbanded'):
        await interaction.response.send_message(f"❌ Cannot show charts for {group_name_upper} as they are disbanded.", ephemeral=True)
        return

    # Find the active album for the group
    active_album_name = None
    group_albums = group_data[group_name_upper].get('albums', [])

    for album_name in group_albums:
        album_entry = album_data.get(album_name)
        if album_entry and album_entry.get('is_active_promotion'):
            # Now, album_entry['promotion_end_date'] is either a datetime object or None
            promo_end_date_obj = album_entry.get('promotion_end_date')

            # If promo_end_date_obj exists AND the current time is past it
            if promo_end_date_obj and datetime.now() > promo_end_date_obj:
                # Promotion has ended, deactivate this album
                album_entry['is_active_promotion'] = False
                album_entry['promotion_end_date'] = None # Set to None, will be saved as null by DateTimeEncoder
                # Reset chart info for deactivated album
                for chart_key in album_entry['charts_info']:
                    album_entry['charts_info'][chart_key] = {'rank': None, 'peak': None, 'prev_rank': None}
                save_data() # Save the change
                continue # Skip to next album

            # If it's active AND (no end date or current time is within the period)
            if album_entry.get('is_active_promotion') and (not promo_end_date_obj or datetime.now() <= promo_end_date_obj):
                active_album_name = album_name
                break # Found the active album

    if not active_album_name:
        # A song can still chart after its promotion period ends, so fall back to
        # the group's most recent release rather than refusing to show anything.
        released = [a for a in group_albums if a in album_data]
        if not released:
            await interaction.response.send_message(f"❌ `{group_name}` has no albums yet.", ephemeral=True)
            return
        active_album_name = max(released, key=lambda a: album_data[a].get('release_date', ''))

    album_entry = album_data[active_album_name]
    album_streams = album_entry.get('streams', 0)
    group_korean_name = group_data[group_name_upper].get('korean_name', '')

    report_lines = []

    current_date_formatted = f"{datetime.now().strftime('%B')} {ordinal(datetime.now().day)}"

    report_lines.append(f"📊 **{group_name_upper} {active_album_name} {current_date_formatted} Update**\n")


    final_chart_display = []

    for platform_name, settings in CHART_CONFIG.items():
        all_ranks = _calculate_all_chart_ranks(platform_name, settings)
        calculated_rank = all_ranks.get(active_album_name)
        
        chart_info = _get_chart_info(album_entry, platform_name)
        chart_info['prev_rank'] = chart_info.get('rank')
        chart_info['rank'] = calculated_rank
        
        if calculated_rank is not None:
            if chart_info['peak'] is None or calculated_rank < chart_info['peak']:
                chart_info['peak'] = calculated_rank
        
        current_rank = chart_info.get('rank')

        if current_rank is not None:
            rank_str = f"#{current_rank}"
            prev_rank = chart_info.get('prev_rank')
            peak_rank = chart_info.get('peak')

            rank_change_text = ""
            is_new_entry = (prev_rank is None)
            if is_new_entry:
                rank_change_text = "(NEW)"
            elif current_rank < prev_rank:
                rank_change_text = f"(+{prev_rank - current_rank})"
            elif current_rank > prev_rank:
                rank_change_text = f"(-{current_rank - prev_rank})"
            else:
                rank_change_text = "(=)"

            new_peak_text = ""
            if current_rank == peak_rank and (prev_rank is None or current_rank < prev_rank):
                 new_peak_text = "*new peak"

            final_chart_display.append((current_rank, f"{rank_str} {platform_name} {rank_change_text} {new_peak_text}".strip()))

    final_chart_display.sort(key=lambda x: x[0])

    if final_chart_display:
        report_lines.extend([line for rank, line in final_chart_display])
    else:
        report_lines.append(f"*{active_album_name} by {group_name_upper} is not currently charting on any major platform.*")

    all_kill = False
    chart_info_data = album_entry.get('charts_info', {})
    if len(chart_info_data) == 4:
        ranks = [chart_info_data.get(chart, {}).get('rank') for chart in ["MelOn", "Genie", "Bugs", "FLO"]]
        if all(r == 1 for r in ranks):
            all_kill = True
            report_lines.append("\n👑 **ALL KILL** 👑")
            report_lines.append("*#1 on all major charts!*")
            
            group_entry = group_data.get(group_name_upper, {})
            group_entry['all_kills'] = group_entry.get('all_kills', 0) + 1
            
            gp_boost = random.randint(3, 8)
            fanbase_boost = random.randint(2, 5)
            group_entry['gp'] = group_entry.get('gp', 30) + gp_boost
            group_entry['fanbase'] = group_entry.get('fanbase', 50) + fanbase_boost
            
            report_lines.append(f"*GP +{gp_boost} | Fanbase +{fanbase_boost}*")

    group_hashtag_main = f"#{group_name_upper.replace(' ', '')}"
    group_korean_hashtag = f"#{group_korean_name.replace(' ', '')}" if group_korean_name else ""
    album_hashtag = f"#{active_album_name.replace(' ', '')}"

    final_hashtags_block = []
    if group_korean_hashtag:
        final_hashtags_block.append(f"**{group_hashtag_main} {group_korean_hashtag}**")
    else:
        final_hashtags_block.append(f"**{group_hashtag_main}**")
    final_hashtags_block.append(f"**{album_hashtag}**")

    report_lines.append("\n" + "\n".join(final_hashtags_block))

    save_data()

    await interaction.response.send_message("\n".join(report_lines))

# --- New Command: View Group Details ---
@bot.tree.command(description="View detailed information about a group.")
@app_commands.autocomplete(group_name=group_autocomplete)
async def view_group(interaction: discord.Interaction, group_name: str):
    group_name_upper = group_name.upper()
    if group_name_upper not in group_data:
        await interaction.response.send_message(f"Group `{group_name}` not found.", ephemeral=True)
        return

    backfill_prereleases()
    
    group_info = group_data[group_name_upper]

    update_nations_group()
    
    status_tags = []
    if group_info.get('is_disbanded'):
        status_tags.append("Disbanded")
    
    if group_info.get('is_subunit'):
        parent = group_info.get('parent_group', 'Unknown')
        status_tags.append(f"Subunit of {parent}")
    
    if group_info.get('is_nations_group'):
        status_tags.append("🩷 NATION'S GROUP")
    
    if group_info.get('active_hate_train'):
        status_tags.append("🔥 HATE TRAIN")
    
    all_kills = group_info.get('all_kills', 0)
    if all_kills > 0:
        status_tags.append(f"👑 {all_kills} ALL KILL{'S' if all_kills > 1 else ''}")

    embed_color = discord.Color.from_rgb(255, 105, 180)
    if group_info.get('active_hate_train'):
        embed_color = discord.Color.from_rgb(255, 69, 100)

    bio = group_info.get('description') or "*No bio set. Use /editprofile to add one.*"
    
    embed = discord.Embed(
        title=f"{group_name_upper}",
        description=f"**@{group_info.get('korean_name', group_name_upper)}** · {group_info.get('company', 'Independent')}\n\n{bio}",
        color=embed_color
    )
    
    if group_info.get('banner_url'):
        embed.set_image(url=group_info['banner_url'])
    
    if group_info.get('profile_picture'):
        embed.set_thumbnail(url=group_info['profile_picture'])
    
    if status_tags:
        embed.add_field(name="Status", value=" · ".join(status_tags), inline=False)

    stats_line = f"**{group_info.get('popularity', 0)}** Popularity · **{group_info.get('fanbase', 50)}** Fanbase · **{group_info.get('gp', 30)}** GP"
    embed.add_field(name="Stats", value=stats_line, inline=False)
    
    total_streams = 0
    total_sales = 0
    total_mv_views = 0
    for alb_name in group_info.get('albums', []):
        if alb_name in album_data:
            total_streams += album_data[alb_name].get('streams', 0)
            total_sales += album_data[alb_name].get('sales', 0)
            total_mv_views += album_data[alb_name].get('views', 0)
    
    career_line = f"**{format_number(total_streams)}** Streams · **{format_number(total_sales)}** Sales · **{format_number(total_mv_views)}** MV Views"
    embed.add_field(name="Career", value=career_line, inline=False)
    
    wins_count = group_info.get('wins', 0)
    achievements_parts = []
    if wins_count > 0:
        achievements_parts.append(f"**{wins_count}** Music Show Win{'s' if wins_count != 1 else ''}")
    if all_kills > 0:
        achievements_parts.append(f"**{all_kills}** All Kill{'s' if all_kills != 1 else ''}")
    
    if achievements_parts:
        embed.add_field(name="Achievements", value=" · ".join(achievements_parts), inline=False)
    else:
        embed.add_field(name="Achievements", value="*No achievements yet — keep promoting!*", inline=False)
    
    if group_info.get('is_nations_group'):
        embed.add_field(name="Nation's Perks", value="+25% streams/views, +20% sales", inline=True)

    albums_list = group_info.get('albums', [])
    view = None
    
    if albums_list:
        albums_str = []
        for album in albums_list[:5]:
            album_detail = album_data.get(album, {})
            streams = format_number(album_detail.get('streams', 0))
            is_active = " 🔴" if album_detail.get('is_active_promotion') else ""
            albums_str.append(f"**{album}**{is_active} — {streams} streams")
        
        if len(albums_list) > 5:
            class ExpandDiscographyView(ui.View):
                def __init__(self, all_albums, group_name):
                    super().__init__(timeout=120)
                    self.all_albums = all_albums
                    self.group_name = group_name
                    self.expanded = False
                
                @ui.button(label=f"Show all ({len(albums_list)})", style=discord.ButtonStyle.secondary)
                async def expand_btn(self, interaction: discord.Interaction, button: ui.Button):
                    if self.expanded:
                        short_list = []
                        for album in self.all_albums[:5]:
                            album_detail = album_data.get(album, {})
                            streams = format_number(album_detail.get('streams', 0))
                            is_active = " 🔴" if album_detail.get('is_active_promotion') else ""
                            short_list.append(f"**{album}**{is_active} — {streams} streams")
                        button.label = f"Show all ({len(self.all_albums)})"
                        await interaction.response.edit_message(content=f"**{self.group_name} Discography**\n" + "\n".join(short_list), view=self)
                        self.expanded = False
                    else:
                        full_list = []
                        for album in self.all_albums:
                            album_detail = album_data.get(album, {})
                            streams = format_number(album_detail.get('streams', 0))
                            is_active = " 🔴" if album_detail.get('is_active_promotion') else ""
                            full_list.append(f"**{album}**{is_active} — {streams} streams")
                        button.label = "Show less"
                        await interaction.response.edit_message(content=f"**{self.group_name} Full Discography**\n" + "\n".join(full_list), view=self)
                        self.expanded = True
            
            view = ExpandDiscographyView(albums_list, group_name_upper)
            albums_str.append(f"*...and {len(albums_list) - 5} more*")
        
        embed.add_field(name="Discography", value="\n".join(albums_str), inline=False)
    else:
        embed.add_field(name="Discography", value="No albums yet", inline=False)
    
    prereleases_list = group_info.get('prereleases', [])
    active_preorders = []
    for pr_name in prereleases_list:
        pr_entry = preorder_data.get(pr_name) or album_data.get(pr_name, {})
        if pr_entry.get('status') == 'open' or pr_entry.get('is_preorder'):
            preorder_count = pr_entry.get('preorders', 0)
            active_preorders.append(f"**{pr_name}** — {format_number(preorder_count)} pre-orders")
    
    if active_preorders:
        embed.add_field(name="📦 Pre-Orders", value="\n".join(active_preorders[:3]), inline=False)

    embed.set_footer(text=f"Debut: {group_info.get('debut_date', 'N/A')}")
    
    if view:
        await interaction.response.send_message(embed=embed, view=view)
    else:
        await interaction.response.send_message(embed=embed)


@bot.tree.command(name="editprofile", description="Edit your group's profile picture, banner, or bio")
@app_commands.describe(
    group_name="The group to edit",
    description="Group bio/description (max 200 chars)",
    profile_url="Profile picture URL (permanent image link)",
    banner_url="Banner image URL (permanent image link)"
)
@app_commands.autocomplete(group_name=user_group_autocomplete)
async def editprofile(
    interaction: discord.Interaction, 
    group_name: str,
    description: str = None,
    profile_url: str = None,
    banner_url: str = None
):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()
    
    if not is_user_group_owner(user_id, group_name_upper):
        await interaction.response.send_message("You don't manage this group.", ephemeral=True)
        return
    
    if group_name_upper not in group_data:
        await interaction.response.send_message("Group not found.", ephemeral=True)
        return
    
    group_entry = group_data[group_name_upper]
    changes = []
    
    pfp_url = None
    new_banner_url = None
    
    if profile_url:
        if profile_url.startswith('http'):
            pfp_url = profile_url
            group_entry['profile_picture'] = pfp_url
            changes.append("profile picture")
        else:
            await interaction.response.send_message("Profile URL must start with http:// or https://", ephemeral=True)
            return
    
    if banner_url:
        if banner_url.startswith('http'):
            new_banner_url = banner_url
            group_entry['banner_url'] = new_banner_url
            changes.append("banner")
        else:
            await interaction.response.send_message("Banner URL must start with http:// or https://", ephemeral=True)
            return
    
    if description:
        if len(description) > 200:
            description = description[:200]
        group_entry['description'] = description
        changes.append("bio")
    
    if not changes:
        await interaction.response.send_message("No changes made. Attach images or add a description.", ephemeral=True)
        return
    
    save_data()
    
    embed = discord.Embed(
        title=f"Profile Updated",
        description=f"**{group_name_upper}**'s profile has been updated!\nChanged: {', '.join(changes)}",
        color=discord.Color.from_rgb(255, 105, 180)
    )
    if pfp_url:
        embed.set_thumbnail(url=pfp_url)
    if new_banner_url:
        embed.set_image(url=new_banner_url)
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Edit an album's cover image")
@app_commands.describe(
    album_name="The album to edit",
    image="The new album cover image (attach an image file)"
)
@app_commands.autocomplete(album_name=user_album_autocomplete)
async def editalbum(
    interaction: discord.Interaction, 
    album_name: str,
    image: discord.Attachment
):
    user_id = str(interaction.user.id)
    
    if album_name not in album_data:
        await interaction.response.send_message("Album not found.", ephemeral=True)
        return
    
    album_entry = album_data[album_name]
    group_name = album_entry.get('group')
    
    if not group_name or not is_user_group_owner(user_id, group_name):
        await interaction.response.send_message("You don't manage this album's group.", ephemeral=True)
        return
    
    if not image.content_type or not image.content_type.startswith('image/'):
        await interaction.response.send_message("Please attach a valid image file.", ephemeral=True)
        return
    
    album_entry['image_url'] = image.url
    save_data()
    
    embed = discord.Embed(
        title="Album Cover Updated",
        description=f"**{album_name}** now has a new cover!",
        color=discord.Color.from_rgb(255, 105, 180)
    )
    embed.set_thumbnail(url=image.url)
    
    await interaction.response.send_message(embed=embed)


# --- New Command: Set Promotion Period ---
@bot.tree.command(description="Set or change the active promotion period for an album.")
@app_commands.describe(
    group_name="The group that owns the album.",
    album_name="The album to set as active for promotion.",
    duration_days="How many days the album will be actively promoted (charts, etc.). Set to 0 to deactivate."
)
@app_commands.autocomplete(group_name=user_group_autocomplete, album_name=user_album_autocomplete)
async def promoperiod(interaction: discord.Interaction, group_name: str, album_name: str, duration_days: int):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()

    # Check ownership
    if not is_user_group_owner(user_id, group_name_upper):
        await interaction.response.send_message(f"❌ You do not manage the company that owns '{group_name}'.", ephemeral=True)
        return

    if group_data[group_name_upper].get('is_disbanded'):
        await interaction.response.send_message(f"❌ Cannot set promotion period for {group_name_upper} as they are disbanded.", ephemeral=True)
        return
    if album_name not in album_data or album_data[album_name].get('group') != group_name_upper:
        await interaction.response.send_message(f"❌ Album `{album_name}` not found or does not belong to `{group_name}`.", ephemeral=True)
        return

    # Deactivate any other active album for this group
    for alb_name in group_data[group_name_upper].get('albums', []):
        if alb_name != album_name and album_data.get(alb_name, {}).get('is_active_promotion'):
            album_data[alb_name]['is_active_promotion'] = False
            album_data[alb_name]['promotion_end_date'] = None
            # Reset chart info for deactivated album
            for chart_key in album_data[alb_name]['charts_info']:
                album_data[alb_name]['charts_info'][chart_key] = {'rank': None, 'peak': None, 'prev_rank': None}
            print(f"Deactivated promotion for {alb_name}")

    current_album_entry = album_data[album_name]
    korean_name = group_data[group_name_upper].get('korean_name', '')
    korean_name_display = f"({korean_name})" if korean_name else ""


    if duration_days > 0:
        current_album_entry['is_active_promotion'] = True
        current_album_entry['promotion_end_date'] = datetime.now() + timedelta(days=duration_days)

        start_date_str = datetime.now().strftime("%Y.%m.%d")
        end_date_str = current_album_entry['promotion_end_date'].strftime("%Y.%m.%d")

        message = (
            f"**{group_name_upper} {korean_name_display} '{album_name}'**\n"
            f"Inicio de promoción: {start_date_str}\n"
            f"Final de promoción:{end_date_str}"
        )

        # Reset charts info when a new promo period starts
        for chart_key in current_album_entry['charts_info']:
            current_album_entry['charts_info'][chart_key] = {'rank': None, 'peak': None, 'prev_rank': None}

    else: # duration_days <= 0 means deactivate
        current_album_entry['is_active_promotion'] = False
        current_album_entry['promotion_end_date'] = None

        message = (
            f"**{group_name_upper} {korean_name_display} '{album_name}'**\n"
            f"Promoción: No activo"
        )
        # Reset chart info when promotion ends
        for chart_key in current_album_entry['charts_info']:
            current_album_entry['charts_info'][chart_key] = {'rank': None, 'peak': None, 'prev_rank': None}

    save_data()
    await interaction.response.send_message(message)


# --- PAYOLA SHOP ---
PAYOLA_SHOP_ITEMS = {
    "POP POTION": {
        "cost": 500000,
        "popularity_boost_range": (50, 150),
        "description": "Give your group a sudden surge in popularity!"
    },
    "MEDIA BUY": {
        "cost": 1_000_000,
        "streams_to_add_range": (100_000, 500_000),
        "sales_to_add_range": (1000, 5000),
        "description": "Purchase direct streams and sales for an album. No revenue generated for your company."
    },
    "SCANDAL MACHINE": {
        "cost": 2_500_000,
        "popularity_reduction_range": (100, 300),
        "backfire_chance": 0.20,
        "description": "Attempt to create a scandal for another group, reducing their popularity. May backfire!"
    },
    "ADS": {
        "cost": 750_000,
        "views_to_add_range": (200_000, 800_000),
        "gp_reduction_chance": 0.25,
        "gp_reduction_range": (3, 8),
        "description": "Run MV ads on YouTube to boost views. Overusing may annoy the general public!"
    },
    "PLAYLISTING": {
        "cost": 1_200_000,
        "streams_to_add_range": (300_000, 900_000),
        "gp_reduction_chance": 0.30,
        "gp_reduction_range": (5, 12),
        "description": "Pay for playlist placement to boost streams. Overusing damages authenticity!"
    },
    "BOTTING": {
        "cost": 300_000,
        "views_to_add_range": (500_000, 1_500_000),
        "streams_to_add_range": (400_000, 1_200_000),
        "exposure_chance": 0.40,
        "popularity_loss_on_exposure": (100, 250),
        "gp_loss_on_exposure": (15, 30),
        "description": "RISKY! Cheap bot farms for views/streams. High chance of exposure and severe consequences!"
    },
    "EXTRA STREAMS": {
        "cost": 500_000,
        "extra_command": "streams",
        "description": "Buy +1 daily /streams use. Price doubles after 5 purchases."
    },
    "EXTRA SALES": {
        "cost": 500_000,
        "extra_command": "sales",
        "description": "Buy +1 daily /sales use. Price doubles after 5 purchases."
    },
    "EXTRA VIEWS": {
        "cost": 500_000,
        "extra_command": "views",
        "description": "Buy +1 daily /views use. Price doubles after 5 purchases."
    },
    "EXTRA STREAMSONG": {
        "cost": 500_000,
        "extra_command": "streamsong",
        "description": "Buy +1 daily /streamsong use. Price doubles after 5 purchases."
    }
}
    # === COMPANY BUILDINGS SYSTEM ===

COMPANY_BUILDINGS = {
    "PRACTICE_ROOM": {
        "name": "Practice Room",
        "description": "Professional training facilities - reduces training costs",
        "cost": 2_000_000,
        "max_level": 5,
        "upgrade_multiplier": 1.5,
        "benefits": {
            "training_discount": 0.15  # 15% per level, max 75%
        }
    },
    "RECORDING_STUDIO": {
        "name": "Recording Studio",
        "description": "State-of-the-art recording equipment - songs have better quality",
        "cost": 3_000_000,
        "max_level": 5,
        "upgrade_multiplier": 1.8,
        "benefits": {
            "song_quality_boost": 10  # +10% per level, max 50%
        }
    },
    "MARKETING_DEPT": {
        "name": "Marketing Department",
        "description": "Professional marketing team - increases viral chance",
        "cost": 2_500_000,
        "max_level": 5,
        "upgrade_multiplier": 1.6,
        "benefits": {
            "viral_chance_boost": 0.03  # +3% per level, max 15%
        }
    },
    "DANCE_STUDIO": {
        "name": "Dance Studio",
        "description": "Specialized choreography space - members gain dance skill faster",
        "cost": 1_800_000,
        "max_level": 5,
        "upgrade_multiplier": 1.5,
        "benefits": {
            "dance_training_boost": 0.3  # +30% dance skill gains per level
        }
    },
    "VOCAL_BOOTH": {
        "name": "Vocal Booth",
        "description": "Professional vocal training - members gain vocal skill faster",
        "cost": 1_800_000,
        "max_level": 5,
        "upgrade_multiplier": 1.5,
        "benefits": {
            "vocal_training_boost": 0.3  # +30% vocal skill gains per level
        }
    },
    "CAFETERIA": {
        "name": "Cafeteria",
        "description": "Healthy meals for artists - boosts member stamina",
        "cost": 1_500_000,
        "max_level": 5,
        "upgrade_multiplier": 1.4,
        "benefits": {
            "stamina_boost": 0.1  # +10% activity efficiency per level
        }
    },
    "GYM": {
        "name": "Fitness Center",
        "description": "Physical training facilities - boosts performance capacity",
        "cost": 2_200_000,
        "max_level": 5,
        "upgrade_multiplier": 1.6,
        "benefits": {
            "concert_capacity_boost": 0.05  # +5% concert attendance per level
        }
    }
}

def get_building_cost(building_id: str, current_level: int = 0) -> int:
    """Calculate cost for building/upgrading."""
    if building_id not in COMPANY_BUILDINGS:
        return 0
    
    building = COMPANY_BUILDINGS[building_id]
    base_cost = building['cost']
    multiplier = building['upgrade_multiplier']
    
    if current_level == 0:
        return base_cost
    
    return int(base_cost * (multiplier ** current_level))


def get_company_building_bonus(company_name: str, bonus_type: str) -> float:
    """Get total bonus from all company buildings."""
    if company_name not in company_funds:
        return 0.0
    
    # Buildings stored in company_data
    company_data.setdefault(company_name, {})
    buildings = company_data[company_name].get('buildings', {})
    
    total_bonus = 0.0
    
    for building_id, level in buildings.items():
        if building_id not in COMPANY_BUILDINGS or level <= 0:
            continue
        
        building = COMPANY_BUILDINGS[building_id]
        benefits = building.get('benefits', {})
        
        if bonus_type in benefits:
            bonus_per_level = benefits[bonus_type]
            total_bonus += bonus_per_level * level
    
    return total_bonus


@bot.tree.command(description="Build or upgrade company facilities!")
@app_commands.describe(
    company_name="Your company",
    building="Building to construct/upgrade"
)
@app_commands.choices(building=[
    app_commands.Choice(name="Practice Room", value="PRACTICE_ROOM"),
    app_commands.Choice(name="Recording Studio", value="RECORDING_STUDIO"),
    app_commands.Choice(name="Marketing Department", value="MARKETING_DEPT"),
    app_commands.Choice(name="Dance Studio", value="DANCE_STUDIO"),
    app_commands.Choice(name="Vocal Booth", value="VOCAL_BOOTH"),
    app_commands.Choice(name="Cafeteria", value="CAFETERIA"),
    app_commands.Choice(name="Fitness Center", value="GYM")
])
@app_commands.autocomplete(company_name=user_company_autocomplete)
async def build(interaction: discord.Interaction, company_name: str, building: str):
    user_id = str(interaction.user.id)
    company_name_upper = company_name.upper()
    
    if not is_user_company_owner(user_id, company_name_upper):
        await interaction.response.send_message("❌ You don't own this company.", ephemeral=True)
        return
    
    if building not in COMPANY_BUILDINGS:
        await interaction.response.send_message("❌ Invalid building.", ephemeral=True)
        return
    
    building_info = COMPANY_BUILDINGS[building]
    
    # Initialize company data
    company_data.setdefault(company_name_upper, {})
    company_data[company_name_upper].setdefault('buildings', {})
    
    current_level = company_data[company_name_upper]['buildings'].get(building, 0)
    
    if current_level >= building_info['max_level']:
        await interaction.response.send_message(
            f"❌ **{building_info['name']}** is already at max level ({building_info['max_level']})!",
            ephemeral=True
        )
        return
    
    cost = get_building_cost(building, current_level)
    
    if company_funds.get(company_name_upper, 0) < cost:
        await interaction.response.send_message(
            f"❌ Not enough funds! Need <:MonthlyPeso:1338642658436059239>{format_number(cost)}.",
            ephemeral=True
        )
        return
    
    # Deduct cost
    company_funds[company_name_upper] -= cost
    
    # Upgrade building
    company_data[company_name_upper]['buildings'][building] = current_level + 1
    new_level = current_level + 1
    
    save_data()
    
    action = "Built" if current_level == 0 else f"Upgraded to Level {new_level}"
    
    embed = discord.Embed(
        title=f"🏢 {action}: {building_info['name']}",
        description=building_info['description'],
        color=discord.Color.blue()
    )
    embed.add_field(name="Company", value=company_name_upper, inline=True)
    embed.add_field(name="Level", value=f"{new_level}/{building_info['max_level']}", inline=True)
    embed.add_field(name="Cost", value=f"<:MonthlyPeso:1338642658436059239>{format_number(cost)}", inline=True)
    
    # Show benefits
    benefits_text = []
    for benefit_type, benefit_value in building_info['benefits'].items():
        if benefit_type == "training_discount":
            total_discount = benefit_value * new_level
            benefits_text.append(f"Training costs: -{int(total_discount * 100)}%")
        elif benefit_type == "song_quality_boost":
            total_boost = benefit_value * new_level
            benefits_text.append(f"Song quality: +{int(total_boost)}%")
        elif benefit_type == "viral_chance_boost":
            total_boost = benefit_value * new_level
            benefits_text.append(f"Viral chance: +{int(total_boost * 100)}%")
        elif benefit_type.endswith("_training_boost"):
            skill_name = benefit_type.replace("_training_boost", "")
            total_boost = benefit_value * new_level
            benefits_text.append(f"{skill_name.title()} training: +{int(total_boost * 100)}%")
    
    if benefits_text:
        embed.add_field(name="Active Benefits", value="\n".join(benefits_text), inline=False)
    
    if new_level < building_info['max_level']:
        next_cost = get_building_cost(building, new_level)
        embed.set_footer(text=f"Next upgrade: 💰{format_number(next_cost)}")
    else:
        embed.set_footer(text="✅ Max level reached!")
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="View your company's buildings and facilities")
@app_commands.autocomplete(company_name=user_company_autocomplete)
async def buildings(interaction: discord.Interaction, company_name: str):
    company_name_upper = company_name.upper()
    
    if company_name_upper not in company_funds:
        await interaction.response.send_message("❌ Company not found.", ephemeral=True)
        return
    
    company_data.setdefault(company_name_upper, {})
    buildings_owned = company_data[company_name_upper].get('buildings', {})
    
    embed = discord.Embed(
        title=f"🏢 {company_name_upper} - Facilities",
        description="Company buildings and upgrades",
        color=discord.Color.blue()
    )
    
    if not buildings_owned:
        embed.add_field(
            name="No Buildings Yet",
            value="Use `/build` to construct your first facility!",
            inline=False
        )
    else:
        for building_id, level in buildings_owned.items():
            if building_id not in COMPANY_BUILDINGS:
                continue
            
            building_info = COMPANY_BUILDINGS[building_id]
            status = f"Level {level}/{building_info['max_level']}"
            
            # Calculate total benefits
            benefits = []
            for benefit_type, benefit_value in building_info['benefits'].items():
                total = benefit_value * level
                if benefit_type == "training_discount":
                    benefits.append(f"-{int(total * 100)}% training costs")
                elif benefit_type == "song_quality_boost":
                    benefits.append(f"+{int(total)}% song quality")
                elif benefit_type == "viral_chance_boost":
                    benefits.append(f"+{int(total * 100)}% viral chance")
                elif benefit_type.endswith("_training_boost"):
                    skill = benefit_type.replace("_training_boost", "")
                    benefits.append(f"+{int(total * 100)}% {skill} training")
            
            value_text = f"{status}\n" + " • ".join(benefits)
            
            if level < building_info['max_level']:
                next_cost = get_building_cost(building_id, level)
                value_text += f"\nUpgrade: 💰{format_number(next_cost)}"
            
            embed.add_field(
                name=f"{building_info['name']}",
                value=value_text,
                inline=False
            )
    
    embed.add_field(
        name="Company Funds",
        value=f"<:MonthlyPeso:1338642658436059239>{format_number(company_funds.get(company_name_upper, 0))}",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed)

SPECIAL_DISCOUNT_USER = "979346606233104415"

def get_extra_use_cost(user_id: str) -> int:
    """Get the cost for the next extra use purchase based on total purchases."""
    total_purchased = get_total_extras_purchased(user_id)
    if user_id == SPECIAL_DISCOUNT_USER:
        return 500_000 if total_purchased >= 5 else 100_000
    return 1_000_000 if total_purchased >= 5 else 500_000

class PayolaShopView(ui.View):
    def __init__(self, original_interaction: discord.Interaction, item_name: str, group_name: str | None, user_id: str, target_album_name: str = None, target_group_name: str = None):
        super().__init__(timeout=30)
        self.original_interaction = original_interaction
        self.item_name = item_name.upper()
        # Safely handle group_name being None
        self.group_name = group_name.upper() if group_name else "" 
        self.user_id = user_id
        self.target_album_name = target_album_name
        self.target_group_name = target_group_name # For sabotage


    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("❌ This purchase confirmation is not for you.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.original_interaction.edit_original_response(content="Purchase timed out.", view=self)
        except discord.NotFound:
            pass # Message might have been deleted

    @ui.button(label="Confirm Purchase", style=discord.ButtonStyle.green, custom_id="confirm_payola_purchase")
    async def confirm_payola_purchase_callback(self, interaction: discord.Interaction, button: ui.Button):
        item_details = PAYOLA_SHOP_ITEMS.get(self.item_name)
        if not item_details:
            await interaction.response.edit_message(content="❌ Item not found.", view=None)
            self.stop()
            return

        # Ensure latest data
        load_data() 

        user_bal = user_balances.get(self.user_id, 0)

        # Handle extra use items with dynamic pricing
        if self.item_name.startswith("EXTRA "):
            actual_cost = get_extra_use_cost(self.user_id)
            if user_bal < actual_cost:
                await interaction.response.edit_message(content=f"❌ You don't have enough <:MonthlyPeso:1338642658436059239> to purchase this. You need {format_number(actual_cost)}.", view=None)
                self.stop()
                return
            
            extra_command = item_details.get('extra_command')
            if extra_command:
                user_balances[self.user_id] = user_bal - actual_cost
                add_extra_use(self.user_id, extra_command)
                
                new_total = get_extra_uses(self.user_id, extra_command)
                next_cost = get_extra_use_cost(self.user_id)
                
                outcome_message = (
                    f"✅ Purchased **+1 daily /{extra_command} use**!\n"
                    f"You now have **{new_total}** extra daily uses for /{extra_command}.\n"
                    f"Next extra purchase will cost: <:MonthlyPeso:1338642658436059239>{format_number(next_cost)}"
                )
                outcome_message += f"\nYour balance is now <:MonthlyPeso:1338642658436059239>{format_number(user_balances[self.user_id])}."
                save_data()
                await interaction.response.edit_message(content=outcome_message, view=None)
                self.stop()
                return

        if user_bal < item_details['cost']:
            await interaction.response.edit_message(content=f"❌ You don't have enough <:MonthlyPeso:1338642658436059239> to purchase '{self.item_name}'. You need {format_number(item_details['cost'])}.", view=None)
            self.stop()
            return

        # Deduct cost immediately
        user_balances[self.user_id] -= item_details['cost']

        outcome_message = f"✅ You successfully purchased **'{self.item_name}'**!\n"

        # --- Apply item effects ---
        if self.item_name == "POP POTION":
            if not self.group_name or self.group_name not in group_data:
                await interaction.response.edit_message(content=f"❌ Group '{self.group_name}' not found or not specified for Pop Potion.", view=None)
                user_balances[self.user_id] += item_details['cost'] # Refund if group is invalid
                save_data()
                self.stop()
                return
            if group_data[self.group_name].get('is_disbanded'):
                await interaction.response.edit_message(content=f"❌ Cannot use Pop Potion on disbanded group ({self.group_name}).", view=None)
                user_balances[self.user_id] += item_details['cost'] # Refund
                save_data()
                self.stop()
                return

            # Removed the ownership check for Pop Potion
            # if not is_user_group_owner(self.user_id, self.group_name):
            #      await interaction.response.edit_message(content=f"❌ You do not manage the company that owns '{self.group_name}'.", view=None)
            #      user_balances[self.user_id] += item_details['cost'] # Refund
            #      save_data()
            #      self.stop()
            #      return


            group_entry = group_data.get(self.group_name)
            popularity_boost = random.randint(*item_details['popularity_boost_range'])
            group_entry['popularity'] = group_entry.get('popularity', 0) + popularity_boost
            outcome_message += (
                f"**{self.group_name}**'s popularity increased by **{popularity_boost}** "
                f"(New popularity: {group_entry['popularity']})."
            )

        elif self.item_name == "MEDIA BUY":
            if not self.target_album_name or self.target_album_name not in album_data:
                await interaction.response.edit_message(content=f"❌ Album '{self.target_album_name}' not found or not specified for Media Buy.", view=None)
                user_balances[self.user_id] += item_details['cost'] # Refund
                save_data()
                self.stop()
                return

            target_album_entry = album_data.get(self.target_album_name)
            target_group_name_for_album = target_album_entry.get('group') # Renamed to avoid clash

            if target_group_name_for_album and group_data[target_group_name_for_album].get('is_disbanded'):
                await interaction.response.edit_message(content=f"❌ Cannot use Media Buy on an album of a disbanded group ({target_group_name_for_album}).", view=None)
                user_balances[self.user_id] += item_details['cost'] # Refund
                save_data()
                self.stop()
                return

            # Removed the ownership check for Media Buy
            # if not is_user_group_owner(self.user_id, target_group_name_for_album):
            #      await interaction.response.edit_message(content=f"❌ You do not manage the company that owns the group for '{self.target_album_name}'.", view=None)
            #      user_balances[self.user_id] += item_details['cost'] # Refund
            #      save_data()
            #      self.stop()
            #      return


            streams_added = random.randint(*item_details['streams_to_add_range'])
            sales_added = random.randint(*item_details['sales_to_add_range'])

            target_album_entry['streams'] = target_album_entry.get('streams', 0) + streams_added
            target_album_entry['sales'] = target_album_entry.get('sales', 0) + sales_added

            outcome_message += (
                f"Added {format_number(streams_added)} streams and {format_number(sales_added)} sales to album "
                f"**'{self.target_album_name}'**. (No revenue for company from these sales/streams)."
            )

        elif self.item_name == "SCANDAL MACHINE":
            if not self.target_group_name or self.target_group_name not in group_data:
                await interaction.response.edit_message(content=f"❌ Target group '{self.target_group_name}' not found or not specified for Scandal Machine.", view=None)
                user_balances[self.user_id] += item_details['cost'] # Refund
                save_data()
                self.stop()
                return

            target_group_entry = group_data.get(self.target_group_name)
            if target_group_entry.get('is_disbanded'):
                await interaction.response.edit_message(content=f"❌ Cannot sabotage disbanded group ({self.target_group_name}).", view=None)
                user_balances[self.user_id] += item_details['cost'] # Refund
                save_data()
                self.stop()
                return

            # Prevent sabotaging one's own group
            if is_user_group_owner(self.user_id, self.target_group_name):
                await interaction.response.edit_message(content=f"❌ You cannot sabotage your own group '{self.target_group_name}'.", view=None)
                user_balances[self.user_id] += item_details['cost'] # Refund
                save_data()
                self.stop()
                return

            # Check for backfire
            if random.random() < item_details['backfire_chance']:
                popularity_reduction = random.randint(*item_details['popularity_reduction_range'])
                # If backfire, reduce user's own group's popularity (if specified) or a random one from their company
                user_company_list = get_user_companies(self.user_id)
                affected_group_for_backfire = None # Initialize to None

                if user_company_list:
                    # Collect all active groups owned by the user's companies
                    user_owned_active_groups = []
                    for company in user_company_list:
                        for g_name, g_data in group_data.items():
                            if g_data.get('company') == company and not g_data.get('is_disbanded'):
                                user_owned_active_groups.append(g_name)

                    if user_owned_active_groups:
                        affected_group_for_backfire = random.choice(user_owned_active_groups)
                        group_data[affected_group_for_backfire]['popularity'] = max(0, group_data[affected_group_for_backfire].get('popularity', 0) - popularity_reduction)
                        group_data[affected_group_for_backfire]['has_scandal'] = True
                        # Reputation damage from backfired scandal machine
                        apply_reputation_change(affected_group_for_backfire, random.randint(-15, -8), "Scandal Machine Backfire")
                        outcome_message = (
                            f"💔 Oh no! The **Scandal Machine** backfired!\n"
                            f"Your group **{affected_group_for_backfire}**'s popularity decreased by **{popularity_reduction}** "
                            f"(New popularity: {group_data[affected_group_for_backfire]['popularity']}).\n"
                            f"Their reputation has been damaged!"
                        )
                        # Public message for backfire
                        try:
                            await self.original_interaction.channel.send(
                                f"🚨 A scandal has hit **{affected_group_for_backfire}**! Their popularity has decreased by {popularity_reduction}."
                            )
                        except discord.errors.Forbidden:
                            print(f"ERROR: Missing permissions to send public scandal message in channel {self.original_interaction.channel.id}")
                    else:
                        outcome_message = "💔 Oh no! The **Scandal Machine** backfired, but you have no active groups to affect!"
                else:
                    outcome_message = "💔 Oh no! The **Scandal Machine** backfired, but you don't own a company to affect!"
            else:
                popularity_reduction = random.randint(*item_details['popularity_reduction_range'])
                target_group_entry['popularity'] = max(0, target_group_entry.get('popularity', 0) - popularity_reduction)
                target_group_entry['has_scandal'] = True
                target_group_entry['gp'] = max(0, target_group_entry.get('gp', 30) - random.randint(5, 15))
                # Reputation damage from scandal machine attack
                apply_reputation_change(self.target_group_name, random.randint(-12, -5), "Scandal Attack")
                outcome_message += (
                    f"**{self.target_group_name}**'s popularity decreased by **{popularity_reduction}** "
                    f"(New popularity: {target_group_entry['popularity']}).\n"
                    f"Their reputation has been damaged!\n"
                    f"They can use `/publicapology` to try to recover."
                )
                # Public message for successful sabotage
                try:
                    await self.original_interaction.channel.send(
                        f"📰 Breaking News! A scandal has hit **{self.target_group_name}**! Their popularity has decreased by {popularity_reduction}."
                    )
                except discord.errors.Forbidden:
                    print(f"ERROR: Missing permissions to send public scandal message in channel {self.original_interaction.channel.id}")

        elif self.item_name == "ADS":
            if not self.target_album_name or self.target_album_name not in album_data:
                await interaction.response.edit_message(content=f"❌ Album '{self.target_album_name}' not found or not specified for Ads.", view=None)
                user_balances[self.user_id] += item_details['cost']
                save_data()
                self.stop()
                return

            target_album_entry = album_data.get(self.target_album_name)
            target_group_name_for_album = target_album_entry.get('group')

            if target_group_name_for_album and group_data[target_group_name_for_album].get('is_disbanded'):
                await interaction.response.edit_message(content=f"❌ Cannot run ads for an album of a disbanded group.", view=None)
                user_balances[self.user_id] += item_details['cost']
                save_data()
                self.stop()
                return

            views_added = random.randint(*item_details['views_to_add_range'])
            target_album_entry['views'] = target_album_entry.get('views', 0) + views_added

            if target_album_entry.get('first_24h_tracking'):
                tracking = target_album_entry['first_24h_tracking']
                if not tracking.get('ended', False):
                    tracking['views'] = tracking.get('views', 0) + views_added

            outcome_message += f"Added **{format_number(views_added)}** MV views to **'{self.target_album_name}'**!"

            if random.random() < item_details['gp_reduction_chance']:
                gp_loss = random.randint(*item_details['gp_reduction_range'])
                if target_group_name_for_album:
                    group_data[target_group_name_for_album]['gp'] = max(0, group_data[target_group_name_for_album].get('gp', 30) - gp_loss)
                    outcome_message += f"\n⚠️ The public is getting annoyed by your ads! GP interest decreased by **{gp_loss}**."

        elif self.item_name == "PLAYLISTING":
            if not self.target_album_name or self.target_album_name not in album_data:
                await interaction.response.edit_message(content=f"❌ Album '{self.target_album_name}' not found or not specified for Playlisting.", view=None)
                user_balances[self.user_id] += item_details['cost']
                save_data()
                self.stop()
                return

            target_album_entry = album_data.get(self.target_album_name)
            target_group_name_for_album = target_album_entry.get('group')

            if target_group_name_for_album and group_data[target_group_name_for_album].get('is_disbanded'):
                await interaction.response.edit_message(content=f"❌ Cannot playlist for an album of a disbanded group.", view=None)
                user_balances[self.user_id] += item_details['cost']
                save_data()
                self.stop()
                return

            streams_added = random.randint(*item_details['streams_to_add_range'])
            target_album_entry['streams'] = target_album_entry.get('streams', 0) + streams_added

            if target_album_entry.get('first_24h_tracking'):
                tracking = target_album_entry['first_24h_tracking']
                if not tracking.get('ended', False):
                    tracking['streams'] = tracking.get('streams', 0) + streams_added

            outcome_message += f"Added **{format_number(streams_added)}** streams to **'{self.target_album_name}'** through playlist placement!"

            if random.random() < item_details['gp_reduction_chance']:
                gp_loss = random.randint(*item_details['gp_reduction_range'])
                if target_group_name_for_album:
                    group_data[target_group_name_for_album]['gp'] = max(0, group_data[target_group_name_for_album].get('gp', 30) - gp_loss)
                    outcome_message += f"\n⚠️ People are noticing the artificial playlist placements! GP interest decreased by **{gp_loss}**."

        elif self.item_name == "BOTTING":
            if not self.target_album_name or self.target_album_name not in album_data:
                await interaction.response.edit_message(content=f"❌ Album '{self.target_album_name}' not found or not specified for Botting.", view=None)
                user_balances[self.user_id] += item_details['cost']
                save_data()
                self.stop()
                return

            target_album_entry = album_data.get(self.target_album_name)
            target_group_name_for_album = target_album_entry.get('group')

            if target_group_name_for_album and group_data[target_group_name_for_album].get('is_disbanded'):
                await interaction.response.edit_message(content=f"❌ Cannot bot for an album of a disbanded group.", view=None)
                user_balances[self.user_id] += item_details['cost']
                save_data()
                self.stop()
                return

            views_added = random.randint(*item_details['views_to_add_range'])
            streams_added = random.randint(*item_details['streams_to_add_range'])

            if random.random() < item_details['exposure_chance']:
                pop_loss = random.randint(*item_details['popularity_loss_on_exposure'])
                gp_loss = random.randint(*item_details['gp_loss_on_exposure'])
                
                if target_group_name_for_album:
                    group_data[target_group_name_for_album]['popularity'] = max(0, group_data[target_group_name_for_album].get('popularity', 0) - pop_loss)
                    group_data[target_group_name_for_album]['gp'] = max(0, group_data[target_group_name_for_album].get('gp', 30) - gp_loss)
                    group_data[target_group_name_for_album]['payola_suspicion'] = group_data[target_group_name_for_album].get('payola_suspicion', 0) + 25
                    group_data[target_group_name_for_album]['has_scandal'] = True
                    group_data[target_group_name_for_album]['active_hate_train'] = True
                    # Major reputation damage for botting scandal
                    apply_reputation_change(target_group_name_for_album, random.randint(-25, -15), "Botting Scandal Exposed")
                
                outcome_message = (
                    f"🚨 **EXPOSED!** Your botting has been detected!\n"
                    f"The fake views and streams have been **deleted**!\n"
                    f"**{target_group_name_for_album}** lost **{pop_loss}** popularity and **{gp_loss}** GP interest!\n"
                    f"🔥 **HATE TRAIN ACTIVATED** - Reputation severely damaged!\n"
                    f"The public is outraged! Use `/publicapology` to try to recover."
                )
                
                try:
                    await self.original_interaction.channel.send(
                        f"🚨 **BOTTING SCANDAL!** **{target_group_name_for_album}**'s streaming numbers have been exposed as fake! "
                        f"Their reputation has taken a massive hit! 📉"
                    )
                except discord.errors.Forbidden:
                    pass
            else:
                target_album_entry['views'] = target_album_entry.get('views', 0) + views_added
                target_album_entry['streams'] = target_album_entry.get('streams', 0) + streams_added

                if target_album_entry.get('first_24h_tracking'):
                    tracking = target_album_entry['first_24h_tracking']
                    if not tracking.get('ended', False):
                        tracking['views'] = tracking.get('views', 0) + views_added
                        tracking['streams'] = tracking.get('streams', 0) + streams_added
                
                if target_group_name_for_album:
                    group_data[target_group_name_for_album]['payola_suspicion'] = group_data[target_group_name_for_album].get('payola_suspicion', 0) + 10
                
                outcome_message += (
                    f"Successfully added **{format_number(views_added)}** views and **{format_number(streams_added)}** streams "
                    f"to **'{self.target_album_name}'**!\n"
                    f"⚠️ Be careful... the more you bot, the higher the risk of exposure!"
                )

        outcome_message += f"\nYour balance is now <:MonthlyPeso:1338642658436059239>{format_number(user_balances[self.user_id])}."
        save_data()

        await interaction.response.edit_message(content=outcome_message, view=None)
        self.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.red, custom_id="cancel_payola_purchase")
    async def cancel_payola_purchase_callback(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(content="Purchase cancelled.", view=None)
        self.stop()


@bot.tree.command(description="Visit the Payola Shop to buy special items!")
@app_commands.describe(
    item_name="The name of the item you want to buy (optional, shows menu if empty).",
    group_name="Your group (for Pop Potion).",
    album_name="Your album (for Media Buy).",
    target_group_name="The group to target (for Scandal Machine)."
)
async def payolashop(
    interaction: discord.Interaction, 
    item_name: str = None, 
    group_name: str = None, 
    album_name: str = None, 
    target_group_name: str = None
):
    user_id = str(interaction.user.id)

    if item_name is None:
        if not PAYOLA_SHOP_ITEMS:
            await interaction.response.send_message("Shop empty.", ephemeral=True)
            return

        embed = discord.Embed(title="Payola Shop", color=discord.Color.from_rgb(180, 80, 150))
        for name, details in PAYOLA_ITEMS.items():
            cost = format_number(details['cost'])
            embed.add_field(
                name=f"{name.title()} - {cost}",
                value=details['description'],
                inline=True
            )
        embed.set_footer(text="Use /payolashop item_name:<item>")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # If an item_name is provided, proceed with the purchase logic
    item_name_upper = item_name.upper()
    item_details = PAYOLA_SHOP_ITEMS.get(item_name_upper)

    if not item_details:
        available_items = "\n".join([f"- **{name.title()}**: {details['description']} (Cost: <:MonthlyPeso:1338642658436059239>{format_number(details['cost'])})" for name, details in PAYOLA_SHOP_ITEMS.items()])
        await interaction.response.send_message(
            f"❌ Item '{item_name}' not found. Available items:\n{available_items}",
            ephemeral=True
        )
        return

    user_bal = user_balances.get(user_id, 0)

    if not item_name_upper.startswith("EXTRA "):
        if user_bal < item_details['cost']:
            await interaction.response.send_message(
                f"❌ You need <:MonthlyPeso:1338642658436059239>{format_number(item_details['cost'])} to buy '{item_name}'. You only have <:MonthlyPeso:1338642658436059239>{format_number(user_bal)}.",
                ephemeral=True
            )
            return

    # Validate arguments based on item type
    if item_name_upper == "POP POTION":
        if not group_name:
            await interaction.response.send_message(f"❌ '{item_name}' requires a `group_name`.", ephemeral=True)
            return
        group_name_upper = group_name.upper()
        if group_name_upper not in group_data or group_data[group_name_upper].get('is_disbanded'):
            await interaction.response.send_message(f"❌ Group '{group_name}' not found or is disbanded.", ephemeral=True)
            return

        # Removed ownership check here

        purchase_message = (
            f"Are you sure you want to purchase **'{item_name}'** for **{group_name}** "
            f"for <:MonthlyPeso:1338642658436059239>{format_number(item_details['cost'])}?\n"
            f"This will: {item_details['description']}"
        )
        view = PayolaShopView(interaction, item_name, group_name, user_id)

    elif item_name_upper == "MEDIA BUY":
        if not album_name:
            await interaction.response.send_message(f"❌ '{item_name}' requires an `album_name`.", ephemeral=True)
            return

        if album_name not in album_data:
            await interaction.response.send_message(f"❌ Album '{album_name}' not found.", ephemeral=True)
            return

        album_group = album_data[album_name].get('group')
        if album_group and group_data[album_group].get('is_disbanded'):
            await interaction.response.send_message(f"❌ Cannot buy media for an album of a disbanded group ({album_group}).", ephemeral=True)
            return

        # Removed ownership check here

        purchase_message = (
            f"Are you sure you want to purchase **'{item_name}'** for album **'{album_name}'** "
            f"for <:MonthlyPeso:1338642658436059239>{format_number(item_details['cost'])}?\n"
            f"This will: {item_details['description']}"
        )
        view = PayolaShopView(interaction, item_name, None, user_id, target_album_name=album_name)

    elif item_name_upper == "SCANDAL MACHINE":
        if not target_group_name:
            await interaction.response.send_message(f"❌ '{item_name}' requires a `target_group_name`.", ephemeral=True)
            return

        target_group_name_upper = target_group_name.upper()
        if target_group_name_upper not in group_data or group_data[target_group_name_upper].get('is_disbanded'):
            await interaction.response.send_message(f"❌ Target group '{target_group_name}' not found or is disbanded.", ephemeral=True)
            return

        # Prevent sabotaging one's own group
        user_company_list = get_user_companies(user_id)
        target_group_company = get_group_owner_company(target_group_name_upper)
        if user_company_list and target_group_company in user_company_list:
            await interaction.response.send_message(f"❌ You cannot sabotage your own group '{target_group_name}'.", ephemeral=True)
            return

        purchase_message = (
            f"Are you sure you want to purchase **'{item_name}'** to target **{target_group_name}** "
            f"for <:MonthlyPeso:1338642658436059239>{format_number(item_details['cost'])}?\n"
            f"This will: {item_details['description']}"
        )
        view = PayolaShopView(interaction, item_name, None, user_id, target_group_name=target_group_name_upper)

    elif item_name_upper == "ADS":
        if not album_name:
            await interaction.response.send_message(f"❌ '{item_name}' requires an `album_name`.", ephemeral=True)
            return

        if album_name not in album_data:
            await interaction.response.send_message(f"❌ Album '{album_name}' not found.", ephemeral=True)
            return

        album_group = album_data[album_name].get('group')
        if album_group and group_data[album_group].get('is_disbanded'):
            await interaction.response.send_message(f"❌ Cannot run ads for an album of a disbanded group.", ephemeral=True)
            return

        purchase_message = (
            f"Are you sure you want to purchase **'{item_name}'** for album **'{album_name}'** "
            f"for <:MonthlyPeso:1338642658436059239>{format_number(item_details['cost'])}?\n"
            f"This will: {item_details['description']}\n"
            f"⚠️ Warning: {int(item_details['gp_reduction_chance'] * 100)}% chance of annoying the GP!"
        )
        view = PayolaShopView(interaction, item_name, None, user_id, target_album_name=album_name)

    elif item_name_upper == "PLAYLISTING":
        if not album_name:
            await interaction.response.send_message(f"❌ '{item_name}' requires an `album_name`.", ephemeral=True)
            return

        if album_name not in album_data:
            await interaction.response.send_message(f"❌ Album '{album_name}' not found.", ephemeral=True)
            return

        album_group = album_data[album_name].get('group')
        if album_group and group_data[album_group].get('is_disbanded'):
            await interaction.response.send_message(f"❌ Cannot playlist for an album of a disbanded group.", ephemeral=True)
            return

        purchase_message = (
            f"Are you sure you want to purchase **'{item_name}'** for album **'{album_name}'** "
            f"for <:MonthlyPeso:1338642658436059239>{format_number(item_details['cost'])}?\n"
            f"This will: {item_details['description']}\n"
            f"⚠️ Warning: {int(item_details['gp_reduction_chance'] * 100)}% chance of damaging authenticity!"
        )
        view = PayolaShopView(interaction, item_name, None, user_id, target_album_name=album_name)

    elif item_name_upper == "BOTTING":
        if not album_name:
            await interaction.response.send_message(f"❌ '{item_name}' requires an `album_name`.", ephemeral=True)
            return

        if album_name not in album_data:
            await interaction.response.send_message(f"❌ Album '{album_name}' not found.", ephemeral=True)
            return

        album_group = album_data[album_name].get('group')
        if album_group and group_data[album_group].get('is_disbanded'):
            await interaction.response.send_message(f"❌ Cannot bot for an album of a disbanded group.", ephemeral=True)
            return

        purchase_message = (
            f"🚨 **RISKY PURCHASE!** 🚨\n"
            f"Are you sure you want to purchase **'{item_name}'** for album **'{album_name}'** "
            f"for <:MonthlyPeso:1338642658436059239>{format_number(item_details['cost'])}?\n"
            f"This will: {item_details['description']}\n"
            f"⚠️ **{int(item_details['exposure_chance'] * 100)}% CHANCE OF EXPOSURE!** "
            f"If caught: streams/views deleted + major popularity loss!"
        )
        view = PayolaShopView(interaction, item_name, None, user_id, target_album_name=album_name)

    elif item_name_upper.startswith("EXTRA "):
        extra_command = item_details.get('extra_command')
        if not extra_command:
            await interaction.response.send_message(f"❌ Invalid extra use item.", ephemeral=True)
            return
        
        actual_cost = get_extra_use_cost(user_id)
        current_extras = get_extra_uses(user_id, extra_command)
        total_purchased = get_total_extras_purchased(user_id)
        
        if user_bal < actual_cost:
            await interaction.response.send_message(
                f"❌ You need <:MonthlyPeso:1338642658436059239>{format_number(actual_cost)} to buy '{item_name}'. You only have <:MonthlyPeso:1338642658436059239>{format_number(user_bal)}.",
                ephemeral=True
            )
            return
        
        purchase_message = (
            f"Are you sure you want to purchase **+1 daily /{extra_command} use** "
            f"for <:MonthlyPeso:1338642658436059239>{format_number(actual_cost)}?\n"
            f"You currently have **{current_extras}** extra uses for this command.\n"
            f"Base daily limit: {DAILY_LIMITS.get(extra_command, 10)} | Your total: {DAILY_LIMITS.get(extra_command, 10) + current_extras}"
        )
        view = PayolaShopView(interaction, item_name, None, user_id)

    else:
        await interaction.response.send_message(f"❌ The item '{item_name}' could not be processed. Please check arguments.", ephemeral=True)
        return


    await interaction.response.send_message(purchase_message, view=view, ephemeral=True)

PAYOLA_ITEMS = {
    "POP POTION": {
        "cost": 500000,
        "description": "Boost popularity",
        "popularity_boost_range": (50, 150)
    },
    "MEDIA BUY": { 
        "cost": 1_000_000,
        "description": "Buy streams + sales",
        "streams_to_add_range": (100_000, 500_000),
        "sales_to_add_range": (1000, 5000)
    },
    "SCANDAL MACHINE": {
        "cost": 2_500_000,
        "description": "Sabotage a rival (20% backfire)",
        "popularity_reduction_range": (100, 300),
        "backfire_chance": 0.20
    },
    "ADS": {
        "cost": 750_000,
        "description": "MV ads, 25% GP risk",
        "views_to_add_range": (200_000, 800_000),
        "gp_reduction_chance": 0.25,
        "gp_reduction_range": (3, 8)
    },
    "PLAYLISTING": {
        "cost": 1_200_000,
        "description": "Playlist push, 30% GP risk",
        "streams_to_add_range": (300_000, 900_000),
        "gp_reduction_chance": 0.30,
        "gp_reduction_range": (5, 12)
    },
    "BOTTING": {
        "cost": 300_000,
        "description": "Cheap bots, 40% exposure risk!",
        "views_to_add_range": (500_000, 1_500_000),
        "streams_to_add_range": (400_000, 1_200_000),
        "exposure_chance": 0.40,
        "popularity_loss_on_exposure": (100, 250),
        "gp_loss_on_exposure": (15, 30)
    },
    "EXTRA STREAMS": {
        "cost": 500_000,
        "description": "+1 daily /streams (500K, 1M after 5)"
    },
    "EXTRA SALES": {
        "cost": 500_000,
        "description": "+1 daily /sales (500K, 1M after 5)"
    },
    "EXTRA VIEWS": {
        "cost": 500_000,
        "description": "+1 daily /views (500K, 1M after 5)"
    },
    "EXTRA STREAMSONG": {
        "cost": 500_000,
        "description": "+1 daily /streamsong (500K, 1M after 5)"
    }
}


# === NEW COMMANDS: Views, 24hs, Compare ===

@bot.tree.command(description="Watch the MV to add YouTube views. Views scale with popularity, fanbase, and GP interest.")
@app_commands.autocomplete(album_name=album_autocomplete)
async def views(interaction: discord.Interaction, album_name: str):
    user_id = str(interaction.user.id)
    
    is_limited, remaining_uses = check_daily_limit(user_id, "views", DAILY_LIMITS["views"])
    if is_limited:
        await interaction.response.send_message(f"❌ You've reached your daily views limit! (0 uses remaining)", ephemeral=True)
        return
    
    if album_name not in album_data:
        await interaction.response.send_message(f"❌ Album `{album_name}` not found.", ephemeral=True)
        return
    
    album_entry = album_data[album_name]
    group_name = album_entry.get('group')
    
    if not group_name or group_name not in group_data:
        await interaction.response.send_message(f"❌ Group for album `{album_name}` not found.", ephemeral=True)
        return
    
    if group_data[group_name].get('is_disbanded'):
        await interaction.response.send_message(f"❌ Cannot add views for a disbanded group.", ephemeral=True)
        return
    
    group_entry = group_data[group_name]
    pop = get_group_derived_popularity(group_entry)
    fanbase = group_entry.get('fanbase', 50)
    gp = group_entry.get('gp', 30)
    
    import math
    
    # Get tier bounds for views
    tier_floor, tier_cap, tier_name = get_tier_bounds(pop, 'views')
    
    # Calculate base views
    effective_pop = pop + (fanbase * 0.5) + (gp * 0.4)
    soft_pop = math.sqrt(effective_pop)
    base_views = int(soft_pop * (tier_cap / math.sqrt(tier_cap)))
    base_views = max(tier_floor, min(tier_cap, base_views))
    
    # Apply demographic multiplier (teen fans boost views)
    demo_mults = get_demographic_multipliers(group_entry)
    base_views = int(base_views * demo_mults['streams'])
    
    # Viral chance (rare: 3-10% based on GP)
    viral_chance = min(0.10, max(0.03, (gp - 30) / 400)) * demo_mults['viral']
    
    # Use dynamic result system for variance
    result = calculate_dynamic_result(
        base_value=base_views,
        tier_floor=tier_floor,
        tier_cap=tier_cap,
        variance_range=(0.4, 1.6),
        viral_chance=viral_chance,
        viral_mult_range=(1.4, 2.5)
    )
    
    total_views_added = result['final']
    went_viral = result['went_viral']
    total_views_added = int(total_views_added * _get_hidden_bonus(group_name))
    
    if group_entry.get('active_hate_train'):
        hate_boost = group_entry.get('hate_train_fanbase_boost', 0)
        total_views_added = int(total_views_added * (1 + hate_boost / 200))
    
    update_nations_group()
    if group_entry.get('is_nations_group'):
        total_views_added = int(total_views_added * 1.10)
    
    ABSOLUTE_MAX_VIEWS = 150000
    total_views_added = min(total_views_added, ABSOLUTE_MAX_VIEWS)
    
    album_entry['views'] = album_entry.get('views', 0) + total_views_added
    
    if album_entry.get('first_24h_tracking'):
        tracking = album_entry['first_24h_tracking']
        if not tracking.get('ended', False):
            tracking['views'] = tracking.get('views', 0) + total_views_added
    
    update_cooldown(user_id, "views")
    save_data()
    
    viral_text = " 🔥 VIRAL!" if went_viral else ""
    embed = discord.Embed(
        title=f"📺 MV Views - {album_name}",
        description=f"**{group_name}**{viral_text} • Music Video",
        color=discord.Color.gold() if went_viral else (discord.Color.pink() if group_entry.get('is_nations_group') else discord.Color.red())
    )
    embed.set_thumbnail(url=sanitize_url(album_entry.get('image_url')))
    embed.add_field(name="Views Added", value=f"+{format_number(total_views_added)}", inline=True)
    if went_viral:
        embed.add_field(name="🔥 Viral Bonus", value=f"+{format_number(result['viral_bonus'])}", inline=True)
    embed.set_footer(text=f"Total MV Views: {album_entry['views']:,} | {remaining_uses} uses left today")
    
    await interaction.response.send_message(embed=embed)
    
    if total_views_added < 8000:
        try:
            await interaction.channel.send("this MV is flopping harder than a fish out of water <:lmfaooo:1162576419486974022>")
        except discord.errors.Forbidden:
            pass


TRACKING_DURATION_MINUTES = 60

@bot.tree.command(description="Start tracking first 24h performance for an album (1 hour simulation).")
@app_commands.autocomplete(album_name=user_album_autocomplete)
async def start24h(interaction: discord.Interaction, album_name: str):
    if album_name not in album_data:
        await interaction.response.send_message(f"❌ Album `{album_name}` not found.", ephemeral=True)
        return
    
    album_entry = album_data[album_name]
    
    if album_entry.get('first_24h_tracking') and not album_entry['first_24h_tracking'].get('ended', False):
        await interaction.response.send_message(f"❌ 24h tracking is already active for `{album_name}`.", ephemeral=True)
        return
    
    album_entry['first_24h_tracking'] = {
        'start_time': datetime.now().isoformat(),
        'streams': 0,
        'sales': 0,
        'views': 0,
        'ended': False
    }
    save_data()
    
    await interaction.response.send_message(
        f"⏱️ **24H Tracking Started for '{album_name}'!**\n"
        f"Stats will be tracked for the next {TRACKING_DURATION_MINUTES} minutes (simulating 24 hours).\n"
        f"Use `/24hs {album_name}` to check progress!"
    )


@bot.tree.command(name="24hs", description="View the first 24-hour performance stats for an album.")
@app_commands.autocomplete(album_name=active_24h_album_autocomplete)
async def first_24_hours(interaction: discord.Interaction, album_name: str):
    user_id = str(interaction.user.id)
    
    if album_name not in album_data:
        await interaction.response.send_message("Album not found.", ephemeral=True)
        return
    
    album_entry = album_data[album_name]
    tracking = album_entry.get('first_24h_tracking')
    
    if not tracking:
        await interaction.response.send_message(
            f"No 24h tracking. Use `/start24h {album_name}` first.",
            ephemeral=True
        )
        return
    
    group_name = album_entry.get('group', 'Unknown')
    start_time = datetime.fromisoformat(tracking['start_time'])
    end_time = start_time + timedelta(minutes=TRACKING_DURATION_MINUTES)
    now = datetime.now()
    
    records_broken = []
    
    if not tracking.get('ended') and now >= end_time:
        tracking['ended'] = True
        tracking['end_time'] = end_time.isoformat()
        
        current_streams = tracking.get('streams', 0)
        current_sales = tracking.get('sales', 0)
        current_views = tracking.get('views', 0)
        
        global_records = records_24h.get('global', {"streams": 0, "sales": 0, "views": 0})
        if current_streams > global_records.get('streams', 0):
            global_records['streams'] = current_streams
            records_broken.append(f"NEW GLOBAL STREAM RECORD!")
        if current_sales > global_records.get('sales', 0):
            global_records['sales'] = current_sales
            records_broken.append(f"NEW GLOBAL SALES RECORD!")
        if current_views > global_records.get('views', 0):
            global_records['views'] = current_views
            records_broken.append(f"NEW GLOBAL VIEWS RECORD!")
        records_24h['global'] = global_records
        
        records_24h.setdefault('personal', {})
        records_24h['personal'].setdefault(user_id, {"streams": 0, "sales": 0, "views": 0})
        personal = records_24h['personal'][user_id]
        
        if current_streams > personal.get('streams', 0):
            personal['streams'] = current_streams
            if "STREAM RECORD" not in str(records_broken):
                records_broken.append("Personal best streams!")
        if current_sales > personal.get('sales', 0):
            personal['sales'] = current_sales
            if "SALES RECORD" not in str(records_broken):
                records_broken.append("Personal best sales!")
        if current_views > personal.get('views', 0):
            personal['views'] = current_views
            if "VIEWS RECORD" not in str(records_broken):
                records_broken.append("Personal best views!")
        
        save_data()
    
    is_active = not tracking.get('ended', False)
    
    if is_active:
        time_remaining = end_time - now
        minutes_left = int(time_remaining.total_seconds() / 60)
        seconds_left = int(time_remaining.total_seconds() % 60)
        status_text = f"LIVE - {minutes_left}m {seconds_left}s left"
        color = discord.Color.green()
    else:
        status_text = "COMPLETED"
        color = discord.Color.gold()
    
    embed = discord.Embed(
        title=f"24H - {album_name}",
        description=f"**{group_name}** | {status_text}",
        color=color
    )
    embed.add_field(name="Streams", value=f"{tracking.get('streams', 0):,}", inline=True)
    embed.add_field(name="Sales", value=f"{tracking.get('sales', 0):,}", inline=True)
    embed.add_field(name="Views", value=f"{tracking.get('views', 0):,}", inline=True)
    
    if records_broken:
        embed.add_field(name="Records", value="\n".join(records_broken), inline=False)
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Compare two groups' success metrics.")
@app_commands.autocomplete(group1=group_autocomplete, group2=group_autocomplete)
async def compare(interaction: discord.Interaction, group1: str, group2: str):
    group1_upper = group1.upper()
    group2_upper = group2.upper()
    
    if group1_upper not in group_data:
        await interaction.response.send_message(f"❌ Group `{group1}` not found.", ephemeral=True)
        return
    if group2_upper not in group_data:
        await interaction.response.send_message(f"❌ Group `{group2}` not found.", ephemeral=True)
        return
    
    g1 = group_data[group1_upper]
    g2 = group_data[group2_upper]
    
    g1_streams = sum(album_data[a].get('streams', 0) for a in g1.get('albums', []) if a in album_data)
    g2_streams = sum(album_data[a].get('streams', 0) for a in g2.get('albums', []) if a in album_data)
    
    g1_sales = sum(album_data[a].get('sales', 0) for a in g1.get('albums', []) if a in album_data)
    g2_sales = sum(album_data[a].get('sales', 0) for a in g2.get('albums', []) if a in album_data)
    
    g1_views = sum(album_data[a].get('views', 0) for a in g1.get('albums', []) if a in album_data)
    g2_views = sum(album_data[a].get('views', 0) for a in g2.get('albums', []) if a in album_data)
    
    def compare_stat(v1, v2):
        if v1 > v2:
            return "🏆", ""
        elif v2 > v1:
            return "", "🏆"
        return "🤝", "🤝"
    
    stats = [
        ("Popularity", g1.get('popularity', 0), g2.get('popularity', 0)),
        ("Fanbase", g1.get('fanbase', 0), g2.get('fanbase', 0)),
        ("GP Interest", g1.get('gp', 0), g2.get('gp', 0)),
        ("Total Wins", g1.get('wins', 0), g2.get('wins', 0)),
        ("Total Streams", g1_streams, g2_streams),
        ("Total Sales", g1_sales, g2_sales),
        ("Total MV Views", g1_views, g2_views),
        ("Albums", len(g1.get('albums', [])), len(g2.get('albums', []))),
    ]
    
    g1_wins_count = 0
    g2_wins_count = 0
    
    comparison_lines = []
    for stat_name, v1, v2 in stats:
        icon1, icon2 = compare_stat(v1, v2)
        if icon1 == "🏆":
            g1_wins_count += 1
        elif icon2 == "🏆":
            g2_wins_count += 1
        comparison_lines.append(f"**{stat_name}**: {icon1}{v1:,} vs {v2:,}{icon2}")
    
    if g1_wins_count > g2_wins_count:
        winner = group1_upper
        verdict = f"🥇 **{group1_upper}** is more successful overall!"
    elif g2_wins_count > g1_wins_count:
        winner = group2_upper
        verdict = f"🥇 **{group2_upper}** is more successful overall!"
    else:
        verdict = f"🤝 **It's a tie!** Both groups are equally matched!"
    
    embed = discord.Embed(
        title=f"⚔️ {group1_upper} vs {group2_upper}",
        description="\n".join(comparison_lines),
        color=discord.Color.from_rgb(255, 105, 180)
    )
    embed.add_field(name="Verdict", value=verdict, inline=False)
    embed.set_footer(text=f"Categories won: {group1_upper}: {g1_wins_count} | {group2_upper}: {g2_wins_count}")
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="View active groups and their promotion end dates.")
async def schedule(interaction: discord.Interaction):
    active_groups = []
    
    for group_name, group_entry in group_data.items():
        if group_entry.get('is_disbanded'):
            continue
        
        for album_name in group_entry.get('albums', []):
            if album_name in album_data:
                album = album_data[album_name]
                if album.get('is_active_promotion'):
                    promo_end = album.get('promotion_end_date')
                    if promo_end:
                        if isinstance(promo_end, str):
                            promo_end = datetime.fromisoformat(promo_end)
                        if promo_end > datetime.now():
                            days_left = (promo_end - datetime.now()).days
                            active_groups.append({
                                'group': group_name,
                                'album': album_name,
                                'ends': promo_end.strftime("%m/%d"),
                                'days': days_left
                            })
    
    if not active_groups:
        await interaction.response.send_message("No groups currently promoting.", ephemeral=True)
        return
    
    active_groups.sort(key=lambda x: x['days'])
    
    embed = discord.Embed(title="Active Promotions", color=discord.Color.from_rgb(255, 105, 180))
    for item in active_groups[:15]:
        embed.add_field(
            name=item['group'],
            value=f"{item['album']} | ends {item['ends']} ({item['days']}d)",
            inline=True
        )
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="View your most-streamed groups.")
async def favs(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    
    user_streams = user_stream_counts.get(user_id, {})
    if not user_streams:
        await interaction.response.send_message("You haven't streamed any groups yet!", ephemeral=True)
        return
    
    sorted_groups = sorted(user_streams.items(), key=lambda x: x[1], reverse=True)
    top_groups = sorted_groups[:min(10, len(sorted_groups))]
    
    embed = discord.Embed(
        title=f"{interaction.user.display_name}'s Favorites",
        color=discord.Color.pink()
    )
    
    for i, (group_name, stream_count) in enumerate(top_groups, 1):
        embed.add_field(
            name=f"{i}. {group_name}",
            value=f"Streamed {stream_count:,}x",
            inline=True
        )
    
    total_streams = sum(user_streams.values())
    embed.set_footer(text=f"Total streams: {total_streams:,}")
    
    await interaction.response.send_message(embed=embed)


# === GP AND SCANDAL MANAGEMENT COMMANDS ===

@bot.tree.command(description="Issue a public apology after a scandal. Risky - GP might forgive or turn against you!")
@app_commands.autocomplete(group_name=user_group_autocomplete)
async def publicapology(interaction: discord.Interaction, group_name: str):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()
    
    if group_name_upper not in group_data:
        await interaction.response.send_message(f"❌ Group `{group_name}` not found.", ephemeral=True)
        return
    
    if not is_user_group_owner(user_id, group_name_upper):
        await interaction.response.send_message(f"❌ You do not manage the company that owns '{group_name}'.", ephemeral=True)
        return
    
    group_entry = group_data[group_name_upper]
    
    if group_entry.get('is_disbanded'):
        await interaction.response.send_message(f"❌ Cannot issue apology for a disbanded group.", ephemeral=True)
        return
    
    if not group_entry.get('has_scandal') and group_entry.get('gp', 30) >= 25:
        await interaction.response.send_message(f"❌ **{group_name_upper}** doesn't have any scandal to apologize for!", ephemeral=True)
        return
    
    current_gp = group_entry.get('gp', 30)
    current_fanbase = group_entry.get('fanbase', 50)
    
    forgiveness_chance = 0.5
    if current_gp < 20:
        forgiveness_chance = 0.3
    elif current_gp < 10:
        forgiveness_chance = 0.15
    
    if random.random() < forgiveness_chance:
        gp_recovery = random.randint(8, 20)
        group_entry['gp'] = current_gp + gp_recovery
        group_entry['has_scandal'] = False
        group_entry['active_hate_train'] = False
        group_entry['hate_train_fanbase_boost'] = 0
        
        update_nations_group()
        update_cooldown(user_id, f"apology_{group_name_upper}")
        save_data()
        
        embed = discord.Embed(
            title=f"🙏 Public Apology - {group_name_upper}",
            description=f"**The public has accepted the apology!**",
            color=discord.Color.green()
        )
        embed.add_field(name="GP Recovery", value=f"+{gp_recovery}", inline=True)
        embed.add_field(name="New GP", value=f"{group_entry['gp']}", inline=True)
        embed.add_field(name="Scandal Status", value="✅ Cleared", inline=True)
        
        await interaction.response.send_message(embed=embed)
        
        try:
            await interaction.channel.send(f"📰 **{group_name_upper}** has issued a sincere public apology and the public has forgiven them! 💕")
        except discord.errors.Forbidden:
            pass
    else:
        gp_loss = random.randint(5, 15)
        fanbase_boost = random.randint(10, 25)
        group_entry['gp'] = max(0, current_gp - gp_loss)
        group_entry['active_hate_train'] = True
        group_entry['hate_train_fanbase_boost'] = min(50, group_entry.get('hate_train_fanbase_boost', 0) + fanbase_boost)
        group_entry['fanbase'] = current_fanbase + random.randint(3, 8)
        # Reputation damage from failed apology triggering hate train
        apply_reputation_change(group_name_upper, random.randint(-10, -5), "Failed Public Apology")
        
        update_nations_group()
        update_cooldown(user_id, f"apology_{group_name_upper}")
        save_data()
        
        embed = discord.Embed(
            title=f"😡 Public Apology BACKFIRED - {group_name_upper}",
            description=f"**The public rejected the apology! A hate train has started!**\nReputation damaged!",
            color=discord.Color.dark_red()
        )
        embed.add_field(name="GP Lost", value=f"-{gp_loss}", inline=True)
        embed.add_field(name="New GP", value=f"{group_entry['gp']}", inline=True)
        embed.add_field(name="🔥 Hate Train", value="ACTIVE", inline=True)
        embed.add_field(name="💪 Fanbase Rally", value=f"+{fanbase_boost}% stream/view bonus", inline=True)
        embed.add_field(name="Fanbase Loyalty", value=f"Increased to {group_entry['fanbase']}", inline=True)
        embed.set_footer(text="Your core fans are rallying behind you! They'll stream and view harder to support you.")
        
        await interaction.response.send_message(embed=embed)
        
        try:
            await interaction.channel.send(f"🔥 **{group_name_upper}**'s apology has BACKFIRED! The public is furious! But their loyal fans are rallying in support! 💪")
        except discord.errors.Forbidden:
            pass


VARIETY_ACTIVITIES = {
    'variety_show': {'name': 'Variety Show', 'demo_shift': 'variety_show', 'description': 'Male ↑ Teen ↑', 'shows': ['Running Man', 'Knowing Bros', 'Amazing Saturday']},
    'music_show_mc': {'name': 'Music Show MC', 'demo_shift': 'music_show_mc', 'description': 'Female ↑ Teen ↑', 'shows': ['Music Bank MC', 'Inkigayo MC', 'M Countdown MC']},
    'drama_acting': {'name': 'Drama Acting', 'demo_shift': 'drama_acting', 'description': 'Adult ↑ Female ↑', 'shows': ['K-Drama Role', 'Web Drama', 'Movie Cameo']},
    'radio_podcast': {'name': 'Radio/Podcast', 'demo_shift': 'radio_podcast', 'description': 'Adult ↑', 'shows': ['Kiss the Radio', 'Cultwo Show', 'Podcast Guest']},
    'fashion_magazine': {'name': 'Fashion Magazine', 'demo_shift': 'fashion_magazine', 'description': 'Female ↑ Adult ↑', 'shows': ['Vogue Korea', 'Elle Korea', 'Harper\'s Bazaar']},
    'sports_event': {'name': 'Sports Event', 'demo_shift': 'sports_event', 'description': 'Male ↑', 'shows': ['ISAC', 'Baseball First Pitch', 'Sports Ambassador']},
    'university_festival': {'name': 'University Festival', 'demo_shift': 'university_festival', 'description': 'Teen ↑ Male ↑', 'shows': ['University Festival', 'Campus Concert', 'College Event']},
}

@bot.tree.command(description="Book variety activities to increase GP interest. Costs company funds.")
@app_commands.describe(
    group_name="Your group",
    activity_type="Type of activity",
    members="Optional: Member name(s) participating (comma-separated). If blank, whole group participates."
)
@app_commands.choices(activity_type=[
    app_commands.Choice(name="Variety Show", value="variety_show"),
    app_commands.Choice(name="Music Show MC", value="music_show_mc"),
    app_commands.Choice(name="Drama Acting", value="drama_acting"),
    app_commands.Choice(name="Radio/Podcast", value="radio_podcast"),
    app_commands.Choice(name="Fashion Magazine", value="fashion_magazine"),
    app_commands.Choice(name="Sports Event", value="sports_event"),
    app_commands.Choice(name="University Festival", value="university_festival"),
])
@app_commands.autocomplete(group_name=user_group_autocomplete)
async def variety(interaction: discord.Interaction, group_name: str, activity_type: str = "variety_show", members: str = None):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()
    
    if group_name_upper not in group_data:
        await interaction.response.send_message(f"❌ Group `{group_name}` not found.", ephemeral=True)
        return
    
    if not is_user_group_owner(user_id, group_name_upper):
        await interaction.response.send_message(f"❌ You do not manage the company that owns '{group_name}'.", ephemeral=True)
        return
    
    group_entry = group_data[group_name_upper]
    
    if group_entry.get('is_disbanded'):
        await interaction.response.send_message(f"❌ Cannot book activities for a disbanded group.", ephemeral=True)
        return
    
    if group_entry.get('active_hate_train'):
        await interaction.response.send_message(f"❌ **{group_name_upper}** has an active hate train! Activities are rejecting them. Use `/charity` to improve their image first.", ephemeral=True)
        return
    
    company_name = group_entry.get('company')
    cost = 200_000
    
    if company_name not in company_funds or company_funds[company_name] < cost:
        await interaction.response.send_message(f"❌ Not enough company funds! Need <:MonthlyPeso:1338642658436059239>{format_number(cost)}.", ephemeral=True)
        return
    
    company_funds[company_name] -= cost
    
    activity_info = VARIETY_ACTIVITIES.get(activity_type, VARIETY_ACTIVITIES['variety_show'])
    show = random.choice(activity_info['shows'])
    
    demo_mults = get_demographic_multipliers(group_entry)
    
    base_gp = random.randint(3, 10)
    gp_variance = random.uniform(0.6, 1.5)
    gp_gain = max(2, int(base_gp * gp_variance * demo_mults['gp']))
    
    base_pop = random.randint(5, 15)
    pop_variance = random.uniform(0.5, 1.5)
    pop_gain = max(3, int(base_pop * pop_variance))
    
    went_viral_moment = random.random() < 0.08
    if went_viral_moment:
        gp_gain = int(gp_gain * 2.0)
        pop_gain = int(pop_gain * 1.8)
    
    group_entry['gp'] = group_entry.get('gp', 30) + gp_gain
    
    participating_members = []
    members_text = ""
    if members:
        member_names = [m.strip().upper() for m in members.split(',')]
        for m in group_entry.get('members', []):
            if isinstance(m, dict) and m.get('name', '').upper() in member_names:
                participating_members.append(m)
    
    if participating_members:
        pop_per_member = max(1, pop_gain // len(participating_members))
        for m in participating_members:
            m['popularity'] = m.get('popularity', 50) + pop_per_member
        shift_demographics_for_members(participating_members, activity_info['demo_shift'])
        recalc_group_from_members(group_name_upper)
        members_text = f"\n**Participating:** {', '.join([m.get('name', '?') for m in participating_members])}"
    else:
        distribute_stat_gain_to_members(group_name_upper, 'popularity', pop_gain)
        shift_demographics(group_entry, activity_info['demo_shift'])
    
    update_nations_group()
    update_cooldown(user_id, f"variety_{group_name_upper}")
    save_data()
    
    viral_text = " 🎬 **VIRAL MOMENT!**" if went_viral_moment else ""
    embed = discord.Embed(
        title=f"📺 {activity_info['name']} - {group_name_upper}",
        description=f"**{group_name_upper}** appeared on **{show}**!{viral_text}{members_text}",
        color=discord.Color.gold() if went_viral_moment else discord.Color.orange()
    )
    embed.add_field(name="GP Interest", value=f"+{gp_gain} (Now: {group_entry['gp']})", inline=True)
    embed.add_field(name="Popularity", value=f"+{pop_gain}", inline=True)
    embed.add_field(name="Cost", value=f"<:MonthlyPeso:1338642658436059239>{format_number(cost)}", inline=True)
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Do charity work to boost GP interest and public image. Costs company funds.")
@app_commands.autocomplete(group_name=user_group_autocomplete)
async def charity(interaction: discord.Interaction, group_name: str):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()
    
    is_limited, remaining_uses = check_daily_limit(user_id, "charity", DAILY_LIMITS["charity"])
    if is_limited:
        await interaction.response.send_message(f"❌ You've reached your daily charity limit! (0 uses remaining)", ephemeral=True)
        return
    
    if group_name_upper not in group_data:
        await interaction.response.send_message(f"❌ Group `{group_name}` not found.", ephemeral=True)
        return
    
    if not is_user_group_owner(user_id, group_name_upper):
        await interaction.response.send_message(f"❌ You do not manage the company that owns '{group_name}'.", ephemeral=True)
        return
    
    group_entry = group_data[group_name_upper]
    
    if group_entry.get('is_disbanded'):
        await interaction.response.send_message(f"❌ Cannot do charity for a disbanded group.", ephemeral=True)
        return
    
    company_name = group_entry.get('company')
    cost = 500_000
    
    if company_name not in company_funds or company_funds[company_name] < cost:
        await interaction.response.send_message(f"❌ Not enough company funds! Need <:MonthlyPeso:1338642658436059239>{format_number(cost)}.", ephemeral=True)
        return
    
    company_funds[company_name] -= cost
    
    charities = ["children's hospital", "disaster relief fund", "animal shelter", "education foundation", "environmental organization", "food bank"]
    charity_type = random.choice(charities)
    
    demo_mults = get_demographic_multipliers(group_entry)
    
    # Dynamic GP and fanbase gains with variance
    base_gp = random.randint(8, 18)
    gp_variance = random.uniform(0.6, 1.5)
    gp_gain = max(5, int(base_gp * gp_variance * demo_mults['gp']))
    
    base_fanbase = random.randint(2, 5)
    fanbase_variance = random.uniform(0.5, 1.5)
    fanbase_gain = max(1, int(base_fanbase * fanbase_variance))
    
    # Rare exceptional charity event (5% chance)
    went_exceptional = random.random() < 0.05
    if went_exceptional:
        gp_gain = int(gp_gain * 2.5)
        fanbase_gain = int(fanbase_gain * 2)
    
    group_entry['gp'] = group_entry.get('gp', 30) + gp_gain
    group_entry['fanbase'] = group_entry.get('fanbase', 50) + fanbase_gain
    
    if group_entry.get('active_hate_train') and group_entry['gp'] >= 40:
        group_entry['active_hate_train'] = False
        group_entry['hate_train_fanbase_boost'] = 0
        embed_note = "\n🎉 **The hate train has ended!** Public sentiment has recovered."
    else:
        embed_note = ""
    
    update_nations_group()
    update_cooldown(user_id, f"charity_{group_name_upper}")
    save_data()
    
    exceptional_text = " ✨ **HEARTWARMING IMPACT!**" if went_exceptional else ""
    embed = discord.Embed(
        title=f"💝 Charity Work - {group_name_upper}",
        description=f"**{group_name_upper}** donated to a **{charity_type}**!{exceptional_text}{embed_note}",
        color=discord.Color.gold() if went_exceptional else discord.Color.pink()
    )
    embed.add_field(name="GP Interest", value=f"+{gp_gain} (Now: {group_entry['gp']})", inline=True)
    embed.add_field(name="Fanbase", value=f"+{fanbase_gain} (Now: {group_entry['fanbase']})", inline=True)
    embed.add_field(name="Donation", value=f"<:MonthlyPeso:1338642658436059239>{format_number(cost)}", inline=True)
    embed.set_footer(text=f"{remaining_uses} charity uses left today")
    
    await interaction.response.send_message(embed=embed)


# === PRESS/MEDIA MECHANICS ===

ARTICLE_TEMPLATES = {
    'positive': [
        "📰 **{outlet}**: \"{group} eats and leaves no crumbs. Stan Twitter is absolutely losing it.\"",
        "📰 **{outlet}**: \"Scientists confirm: {group}'s latest comeback is clinically proven to cause serotonin overload\"",
        "📰 **{outlet}**: \"BREAKING: {group} casually ended every other group's career with one performance\"",
        "📰 **{outlet}**: \"{group} just dropped something so legendary that even antis are quietly streaming\"",
        "📰 **{outlet}**: \"Not {group} serving visuals so hard the camera operators needed therapy\"",
        "📰 **{outlet}**: \"POV: You're watching {group} absolutely demolish the charts AGAIN\"",
        "📰 **{outlet}**: \"{group}'s fancam has more views than some groups' entire discographies...\"",
        "📰 **{outlet}**: \"CEO confirmed sobbing tears of joy after seeing {group}'s album sales\"",
        "📰 **{outlet}**: \"The way {group} just casually invented music. No big deal.\"",
        "📰 **{outlet}**: \"{group} said 'flop era? don't know her' and proceeded to break 17 records\"",
    ],
    'neutral': [
        "📰 **{outlet}**: \"{group} continues their promotional activities\"",
        "📰 **{outlet}**: \"A look at {group}'s musical journey so far\"",
        "📰 **{outlet}**: \"{group} announces new content for fans\"",
        "📰 **{outlet}**: \"Behind the scenes with {group}\"",
    ],
    'negative': [
        "📰 **{outlet}**: \"Not to be dramatic but {group}'s latest stage had the energy of a Tuesday morning meeting\"",
        "📰 **{outlet}**: \"Pann users are FERAL right now: '{group} fell off harder than my WiFi during a comeback'\"",
        "📰 **{outlet}**: \"TheQoo in shambles after {group}'s recent performance... and not in a good way\"",
        "📰 **{outlet}**: \"Industry insider: 'We're worried about {group}. Someone check on their streaming numbers.'\"",
        "📰 **{outlet}**: \"Is {group} giving Renaissance or giving Renaissance fair? Netizens debate.\"",
        "📰 **{outlet}**: \"Antis celebrating as {group}'s momentum slows down. Fans in denial.\"",
        "📰 **{outlet}**: \"PANNCHOA: '{group} is serving... but what exactly? The fans need answers.'\"",
        "📰 **{outlet}**: \"K-netz concerned: '{group} giving very much 2019 energy in 2024'\"",
        "📰 **{outlet}**: \"The company needs to fire {group}'s stylist IMMEDIATELY. This is criminal.\"",
        "📰 **{outlet}**: \"'{group} used to eat with no crumbs, now they're just... eating' - Netizen reactions\"",
    ],
    'scandal': [
        "📰 **{outlet}**: \"DISPATCH WINS AGAIN: {member} from {group} caught at Han River at 2AM... with coffee\"",
        "📰 **{outlet}**: \"The timeline is in FLAMES after {member}'s alleged 'friendship' surfaces\"",
        "📰 **{outlet}**: \"{member} from {group} just liked a post and stans are writing 47-page analysis threads\"",
    ],
    'viral': [
        "📰 **{outlet}**: \"VIRAL: {group}'s fancam just ended all other fancams. Literally no competition.\"",
        "📰 **{outlet}**: \"{group} went viral and now everyone's pretending they were day-one fans\"",
        "📰 **{outlet}**: \"That moment when {group} did THAT. You know exactly what we're talking about.\"",
    ]
}

MEDIA_OUTLETS = ["AllKPop", "Soompi", "Koreaboo", "Pannchoa", "TheQoo", "Naver News", "Dispatch", "Sports Seoul"]


class ArticleView(ui.View):
    def __init__(self, group_name: str):
        super().__init__(timeout=60)
        self.group_name = group_name
    
    @ui.button(label="Positive Article", style=discord.ButtonStyle.green)
    async def positive_article(self, interaction: discord.Interaction, button: ui.Button):
        await self.release_article(interaction, "positive")
    
    @ui.button(label="Negative Article", style=discord.ButtonStyle.red)
    async def negative_article(self, interaction: discord.Interaction, button: ui.Button):
        await self.release_article(interaction, "negative")
    
    async def release_article(self, interaction: discord.Interaction, article_type: str):
        group_name_upper = self.group_name
        
        if group_name_upper not in group_data:
            await interaction.response.send_message("Group no longer exists.", ephemeral=True)
            return
        
        group_entry = group_data[group_name_upper]
        members = group_entry.get('members', [])
        member = random.choice(members) if members else "a member"
        outlet = random.choice(MEDIA_OUTLETS)
        
        if article_type == "positive":
            template = random.choice(ARTICLE_TEMPLATES['positive'])
            headline = template.format(outlet=outlet, group=group_name_upper, member=member)
            
            gp_change = random.randint(5, 15)
            fanbase_change = random.randint(2, 8)
            pop_change = random.randint(10, 30)
            
            group_entry['gp'] = group_entry.get('gp', 30) + gp_change
            group_entry['fanbase'] = group_entry.get('fanbase', 50) + fanbase_change
            group_entry['popularity'] = group_entry.get('popularity', 0) + pop_change
            
            effect_text = f"+{gp_change} GP | +{fanbase_change} Fanbase | +{pop_change} Popularity"
            embed_color = discord.Color.green()
        else:
            template = random.choice(ARTICLE_TEMPLATES['negative'])
            headline = template.format(outlet=outlet, group=group_name_upper, member=member)
            
            gp_change = random.randint(-15, -5)
            fanbase_change = random.randint(-5, -1)
            pop_change = random.randint(-20, -5)
            
            group_entry['gp'] = max(0, group_entry.get('gp', 30) + gp_change)
            group_entry['fanbase'] = max(0, group_entry.get('fanbase', 50) + fanbase_change)
            group_entry['popularity'] = max(0, group_entry.get('popularity', 0) + pop_change)
            
            effect_text = f"{gp_change} GP | {fanbase_change} Fanbase | {pop_change} Popularity"
            embed_color = discord.Color.red()
        
        update_nations_group()
        save_data()
        
        self.stop()
        for child in self.children:
            child.disabled = True
        
        await interaction.response.edit_message(content="Article released!", view=self)
        
        try:
            await interaction.channel.send(f"{headline}\n\n*{effect_text}*")
        except discord.errors.Forbidden:
            pass


@bot.tree.command(description="Release an article about a group (anonymous, public).")
@app_commands.describe(group_name="The group to generate an article about.")
@app_commands.autocomplete(group_name=group_autocomplete)
async def article(interaction: discord.Interaction, group_name: str):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()
    
    # Daily limit check (5 per day per user)
    today = get_today_str()
    user_daily_limits.setdefault(user_id, {})
    article_uses = user_daily_limits[user_id].get('article', {})
    if article_uses.get('date') == today and article_uses.get('count', 0) >= 5:
        await interaction.response.send_message("❌ You can only release 5 articles per day!", ephemeral=True)
        return
    
    if group_name_upper not in group_data:
        await interaction.response.send_message(f"Group `{group_name}` not found.", ephemeral=True)
        return
    
    group_entry = group_data[group_name_upper]
    
    # Track daily usage
    if article_uses.get('date') != today:
        user_daily_limits[user_id]['article'] = {'date': today, 'count': 1}
    else:
        user_daily_limits[user_id]['article']['count'] = article_uses.get('count', 0) + 1
    save_data()

    remaining = 5 - user_daily_limits[user_id]['article']['count']
    
    embed = discord.Embed(
        title=f"📰 Release Article - {group_name_upper}",
        description="Choose what type of article to release. This will be posted publicly and anonymously.",
        color=discord.Color.dark_gray()
    )
    embed.add_field(name="Positive", value="Boosts GP, Fanbase, Popularity", inline=True)
    embed.add_field(name="Negative", value="Damages GP, Fanbase, Popularity", inline=True)
    embed.set_footer(text=f"Articles remaining today: {remaining}")
    
    view = ArticleView(group_name_upper)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(description="Open preorders for an upcoming album release.")
@app_commands.describe(album_name="The name of the upcoming album.", group_name="The group releasing the album.", stock="Initial stock amount (1000-100000).")
@app_commands.autocomplete(group_name=user_group_autocomplete)
async def openpreorder(interaction: discord.Interaction, album_name: str, group_name: str, stock: int = 10000):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()
    album_name_clean = album_name.strip()
    
    if group_name_upper not in group_data:
        await interaction.response.send_message(f"❌ Group `{group_name}` not found.", ephemeral=True)
        return
    
    if not is_user_group_owner(user_id, group_name_upper):
        await interaction.response.send_message(f"❌ You do not manage the company that owns '{group_name}'.", ephemeral=True)
        return
    
    group_entry = group_data[group_name_upper]
    
    if group_entry.get('is_disbanded'):
        await interaction.response.send_message(f"❌ Cannot open preorders for a disbanded group.", ephemeral=True)
        return
    
    if stock < 1000 or stock > 100000:
        await interaction.response.send_message(f"❌ Stock must be between 1,000 and 100,000.", ephemeral=True)
        return
    
    preorder_key = f"{group_name_upper}_{album_name_clean}"
    
    if preorder_key in preorder_data:
        await interaction.response.send_message(f"❌ Preorders for `{album_name_clean}` by {group_name_upper} are already open!", ephemeral=True)
        return
    
    if album_name_clean not in album_data:
        album_data[album_name_clean] = {
            'group': group_name_upper,
            'album_type': 'preorder',
            'album_format': 'physical',
            'streams': 0,
            'sales': 0,
            'views': 0,
            'songs': {},
            'release_date': None,
            'is_active_promotion': False,
            'preorder_sales': 0,
            'weekly_streams': {},
            'weekly_sales': {},
            'weekly_views': {}
        }
        
        if 'albums' not in group_entry:
            group_entry['albums'] = []
        if album_name_clean not in group_entry['albums']:
            group_entry['albums'].append(album_name_clean)
    
    preorder_data[preorder_key] = {
        'album_name': album_name_clean,
        'group': group_name_upper,
        'stock': stock,
        'preordered': 0,
        'opened_at': datetime.now().isoformat(),
        'status': 'open'
    }
    
    save_data()
    
    embed = discord.Embed(
        title=f"📦 Preorders Now Open!",
        description=f"**{album_name_clean}** by **{group_name_upper}**\nAlbum added to group profile!",
        color=discord.Color.blue()
    )
    embed.add_field(name="Available Stock", value=f"{format_number(stock)}", inline=True)
    embed.add_field(name="Preordered", value="0", inline=True)
    embed.set_footer(text="Fans can use /preorder to secure their copy! Use /releasepreorder when ready.")
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Preorder an upcoming album release.")
@app_commands.describe(group_name="The group's name.", album_name="The album to preorder.")
@app_commands.autocomplete(group_name=preorder_group_autocomplete, album_name=preorder_album_autocomplete)
async def preorder(interaction: discord.Interaction, group_name: str, album_name: str):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()
    album_name_clean = album_name.strip()
    
    preorder_key = f"{group_name_upper}_{album_name_clean}"
    
    if preorder_key not in preorder_data:
        await interaction.response.send_message(f"❌ No active preorders found for `{album_name_clean}` by `{group_name_upper}`.", ephemeral=True)
        return
    
    preorder_entry = preorder_data[preorder_key]
    
    if preorder_entry['status'] != 'open':
        await interaction.response.send_message(f"❌ Preorders for this album are closed.", ephemeral=True)
        return
    
    remaining_stock = preorder_entry['stock'] - preorder_entry['preordered']
    if remaining_stock <= 0:
        await interaction.response.send_message(f"❌ Preorders are sold out!", ephemeral=True)
        return
    
    group_entry = group_data.get(group_name_upper, {})
    fanbase = group_entry.get('fanbase', 50)
    pop = get_group_derived_popularity(group_entry)
    
    demo_mults = get_demographic_multipliers(group_entry)
    base_preorder = max(50, int(pop * 0.5 + fanbase * 2))
    base_preorder = int(base_preorder * demo_mults['fandom'])  # Female fans boost preorders
    preorder_amount = min(remaining_stock, int(random.gauss(base_preorder, base_preorder * 0.3)))
    preorder_amount = max(10, preorder_amount)
    
    preorder_entry['preordered'] += preorder_amount
    save_data()
    
    embed = discord.Embed(
        title=f"📦 Preorder Placed!",
        description=f"**{preorder_entry['album_name']}** by **{preorder_entry['group']}**",
        color=discord.Color.teal()
    )
    embed.add_field(name="Your Preorder", value=f"+{format_number(preorder_amount)}", inline=True)
    embed.add_field(name="Total Preorders", value=f"{format_number(preorder_entry['preordered'])}", inline=True)
    embed.add_field(name="Remaining", value=f"{format_number(remaining_stock - preorder_amount)}", inline=True)
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="View current preorder status for albums.")
async def preorders_list(interaction: discord.Interaction):
    if not preorder_data:
        await interaction.response.send_message("📦 No active preorders at the moment.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="📦 Active Preorders",
        color=discord.Color.blue()
    )
    
    for key, entry in list(preorder_data.items())[:10]:
        remaining = entry['stock'] - entry['preordered']
        status = "🟢 Open" if entry['status'] == 'open' and remaining > 0 else "🔴 Sold Out"
        embed.add_field(
            name=f"{entry['album_name']} - {entry['group']}",
            value=f"Preordered: {format_number(entry['preordered'])} | Remaining: {format_number(remaining)} | {status}",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(description="Close preorders and release the album (converts preorders to sales).")
@app_commands.describe(group_name="The group's name.", album_name="The album to release.")
@app_commands.autocomplete(group_name=user_group_autocomplete)
async def releasealbum(interaction: discord.Interaction, group_name: str, album_name: str, image_url: str = None):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()
    album_name_clean = album_name.strip()
    
    if group_name_upper not in group_data:
        await interaction.response.send_message(f"❌ Group `{group_name}` not found.", ephemeral=True)
        return
    
    if not is_user_group_owner(user_id, group_name_upper):
        await interaction.response.send_message(f"❌ You do not manage the company that owns '{group_name}'.", ephemeral=True)
        return
    
    preorder_key = f"{group_name_upper}_{album_name_clean}"
    
    if preorder_key not in preorder_data:
        await interaction.response.send_message(f"❌ No preorders found for `{album_name_clean}`. Use `/addalbum` instead for direct releases.", ephemeral=True)
        return
    
    preorder_entry = preorder_data[preorder_key]
    preorder_sales = preorder_entry['preordered']
    remaining_stock = preorder_entry['stock'] - preorder_sales
    
    if album_name_clean in album_data:
        album_entry = album_data[album_name_clean]
        album_entry['sales'] = album_entry.get('sales', 0) + preorder_sales
        album_entry['preorder_sales'] = preorder_sales
        album_entry['stock'] = remaining_stock
        album_entry['release_date'] = datetime.now().isoformat()
        album_entry['album_type'] = 'full'
        if image_url:
            album_entry['image_url'] = image_url
    else:
        album_data[album_name_clean] = {
            'group': group_name_upper,
            'sales': preorder_sales,
            'streams': 0,
            'views': 0,
            'stock': remaining_stock,
            'image_url': image_url or DEFAULT_ALBUM_IMAGE,
            'release_date': datetime.now().isoformat(),
            'preorder_sales': preorder_sales,
            'weekly_streams': {}
        }
    
    group_entry = group_data[group_name_upper]
    group_entry.setdefault('albums', [])
    if album_name_clean not in group_entry['albums']:
        group_entry['albums'].append(album_name_clean)
    
    if album_name_clean in group_entry.get('prereleases', []):
        group_entry['prereleases'].remove(album_name_clean)
    
    album_data[album_name_clean]['status'] = 'released'
    album_data[album_name_clean]['is_preorder'] = False
    
    company_name = group_entry.get('company')
    if company_name and company_name in company_funds:
        revenue = int(preorder_sales * 10)
        company_funds[company_name] += revenue
    
    del preorder_data[preorder_key]
    save_data()
    
    embed = discord.Embed(
        title=f"🎉 Album Released!",
        description=f"**{album_name_clean}** by **{group_name_upper}** is now available!",
        color=discord.Color.gold()
    )
    embed.add_field(name="Preorder Sales", value=f"{format_number(preorder_sales)}", inline=True)
    embed.add_field(name="Remaining Stock", value=f"{format_number(remaining_stock)}", inline=True)
    if preorder_sales > 0:
        embed.add_field(name="Revenue from Preorders", value=f"<:MonthlyPeso:1338642658436059239>{format_number(preorder_sales * 10)}", inline=True)
    embed.set_thumbnail(url=sanitize_url(image_url))
    
    await interaction.response.send_message(embed=embed)


# === WEEKLY CHARTS SYSTEM (SONG-BASED) ===

def _calculate_song_rank(song_streams: int, chart_settings: dict) -> int:
    """Calculate a song's rank on a platform based on streams.
    Higher streams = lower rank number (better position).
    Returns None if below charting threshold.
    """
    if song_streams < chart_settings['streams_for_charting']:
        return None
    
    if song_streams >= chart_settings['streams_for_top_10']:
        excess_ratio = min(1.0, (song_streams - chart_settings['streams_for_top_10']) / chart_settings['streams_for_top_10'])
        rank = int(10 - excess_ratio * 9)
        return max(1, rank)
    elif song_streams >= chart_settings['streams_for_top_50']:
        ratio = (song_streams - chart_settings['streams_for_top_50']) / (chart_settings['streams_for_top_10'] - chart_settings['streams_for_top_50'])
        rank = int(50 - ratio * 39)
        return max(11, min(50, rank))
    else:
        ratio = (song_streams - chart_settings['streams_for_charting']) / (chart_settings['streams_for_top_50'] - chart_settings['streams_for_charting'])
        rank = int(100 - ratio * 49)
        return max(51, min(100, rank))


def _get_all_songs_weekly_data(group_name: str) -> list:
    """Get all songs from a group with their weekly streams across all albums."""
    current_week = get_current_week_key()
    songs_data = []
    
    group_albums = group_data.get(group_name, {}).get('albums', [])
    for album_name in group_albums:
        album_entry = album_data.get(album_name)
        if not album_entry:
            continue
        songs = album_entry.get('songs', {})
        if not isinstance(songs, dict):
            continue
        for song_name, song_info in songs.items():
            if not isinstance(song_info, dict):
                continue
            weekly_streams = song_info.get('weekly_streams', {}).get(current_week, 0)
            if weekly_streams > 0:
                songs_data.append({
                    'song_name': song_name,
                    'album_name': album_name,
                    'weekly_streams': weekly_streams,
                    'is_title': song_info.get('is_title', False),
                    'song_data': song_info
                })
    
    songs_data.sort(key=lambda x: x['weekly_streams'], reverse=True)
    return songs_data


@bot.tree.command(description="View a group's songs charting on weekly charts (all albums).")
@app_commands.describe(group_name="The name of the group whose weekly chart positions you want to see.")
@app_commands.autocomplete(group_name=group_autocomplete)
async def weeklychart(interaction: discord.Interaction, group_name: str):
    group_name_upper = group_name.upper()
    
    if group_name_upper not in group_data:
        await interaction.response.send_message(f"Group `{group_name}` not found.", ephemeral=True)
        return
    
    if group_data[group_name_upper].get('is_disbanded'):
        await interaction.response.send_message(f"Cannot show charts for {group_name_upper} as they are disbanded.", ephemeral=True)
        return
    
    group_korean_name = group_data[group_name_upper].get('korean_name', '')
    current_week = get_current_week_key()
    
    songs_data = _get_all_songs_weekly_data(group_name_upper)
    
    if not songs_data:
        await interaction.response.send_message(f"No songs from {group_name_upper} have weekly streams this week.", ephemeral=True)
        return
    
    report_lines = [f"📊 **Weekly Chart Update - {group_name_upper}**\n"]
    
    charting_songs = []
    for song_entry in songs_data:
        song_name = song_entry['song_name']
        album_name = song_entry['album_name']
        weekly_streams = song_entry['weekly_streams']
        song_info = song_entry['song_data']
        
        song_chart_lines = []
        best_rank = 999
        
        song_info.setdefault('weekly_chart_info', {})
        
        for platform_name, settings in CHART_CONFIG.items():
            rank = _calculate_song_rank(weekly_streams, settings)
            if rank is None:
                continue
            
            chart_key = f"weekly_{platform_name}"
            chart_info = song_info['weekly_chart_info'].setdefault(chart_key, {'rank': None, 'peak': None, 'prev_rank': None})
            chart_info['prev_rank'] = chart_info.get('rank')
            chart_info['rank'] = rank
            
            if chart_info['peak'] is None or rank < chart_info['peak']:
                chart_info['peak'] = rank
            
            prev_rank = chart_info.get('prev_rank')
            if prev_rank is None:
                change_text = "(NEW)"
            elif rank < prev_rank:
                change_text = f"(+{prev_rank - rank})"
            elif rank > prev_rank:
                change_text = f"(-{rank - prev_rank})"
            else:
                change_text = "(=)"
            
            song_chart_lines.append((rank, f"#{rank} {platform_name} {change_text}"))
            if rank < best_rank:
                best_rank = rank
        
        if song_chart_lines:
            song_chart_lines.sort(key=lambda x: x[0])
            charting_songs.append({
                'song_name': song_name,
                'album_name': album_name,
                'best_rank': best_rank,
                'chart_lines': [line for _, line in song_chart_lines]
            })
    
    if not charting_songs:
        await interaction.response.send_message(f"No songs from {group_name_upper} are currently charting on weekly charts.", ephemeral=True)
        return
    
    charting_songs.sort(key=lambda x: x['best_rank'])
    
    for song in charting_songs:
        report_lines.append(f"**{song['song_name']}** - {song['album_name']}")
        for chart_line in song['chart_lines']:
            report_lines.append(chart_line)
        report_lines.append("")
    
    group_hashtag = f"#{group_name_upper.replace(' ', '')}"
    korean_hashtag = f"#{group_korean_name.replace(' ', '')}" if group_korean_name else ""
    if korean_hashtag:
        report_lines.append(f"**{group_hashtag} {korean_hashtag}**")
    else:
        report_lines.append(f"**{group_hashtag}**")
    
    save_data()
    await interaction.response.send_message("\n".join(report_lines))


@bot.tree.command(description="View group rankings based on combined weekly album performance.")
async def groupchart(interaction: discord.Interaction):
    current_week = get_current_week_key()
    
    group_weekly_totals = {}
    
    for album_name, album_entry in album_data.items():
        group_name = album_entry.get('group', 'Unknown')
        weekly_streams = album_entry.get('weekly_streams', {})
        this_week_streams = weekly_streams.get(current_week, 0)
        
        if group_name not in group_weekly_totals:
            group_weekly_totals[group_name] = {
                'weekly_streams': 0,
                'album_count': 0
            }
        
        group_weekly_totals[group_name]['weekly_streams'] += this_week_streams
        if this_week_streams > 0:
            group_weekly_totals[group_name]['album_count'] += 1
    
    sorted_groups = sorted(
        [(g, data) for g, data in group_weekly_totals.items() if data['weekly_streams'] > 0],
        key=lambda x: x[1]['weekly_streams'],
        reverse=True
    )
    
    if not sorted_groups:
        await interaction.response.send_message("No group streaming data for this week yet!", ephemeral=True)
        return
    
    current_date_formatted = f"{datetime.now().strftime('%B')} {ordinal(datetime.now().day)}"
    report_lines = [f"📊 **Group Chart Update - {current_date_formatted}**\n"]
    
    for i, (group_name, data) in enumerate(sorted_groups[:10], 1):
        rank_str = f"#{i}"
        group_entry = group_data.get(group_name, {})
        is_nations = group_entry.get('is_nations_group', False)
        prefix = "🩷 " if is_nations else ""
        weekly = format_number(data['weekly_streams'])
        albums = data['album_count']
        report_lines.append(f"{rank_str} {prefix}**{group_name}** - {weekly} ({albums} albums)")
    
    report_lines.append(f"\n*Week {current_week} • Combined album performance*")
    
    await interaction.response.send_message("\n".join(report_lines))


# === SUBUNIT SYSTEM ===

@bot.tree.command(description="Create a subunit with debut album. Members must be from parent group.")
@app_commands.describe(
    parent_group="The main group to create a subunit from.",
    subunit_name="The name of the new subunit.",
    members="Comma-separated list of members for the subunit (from parent group).",
    album_name="The debut album name for this subunit.",
    album_type="Album type: full, mini, or single",
    album_format="Album format: digital or physical",
    image_url="Album cover image URL (optional)"
)
@app_commands.choices(
    album_type=[
        app_commands.Choice(name="Full Album", value="full"),
        app_commands.Choice(name="Mini Album", value="mini"),
        app_commands.Choice(name="Single", value="single")
    ],
    album_format=[
        app_commands.Choice(name="Digital", value="digital"),
        app_commands.Choice(name="Physical", value="physical")
    ]
)
@app_commands.autocomplete(parent_group=user_group_autocomplete)
async def createsubunit(
    interaction: discord.Interaction, 
    parent_group: str, 
    subunit_name: str, 
    members: str,
    album_name: str,
    album_type: str = "mini",
    album_format: str = "physical",
    image_url: str = DEFAULT_ALBUM_IMAGE
):
    user_id = str(interaction.user.id)
    parent_group_upper = parent_group.upper()
    subunit_name_upper = subunit_name.upper().strip()
    
    if parent_group_upper not in group_data:
        await interaction.response.send_message(f"❌ Parent group `{parent_group}` not found.", ephemeral=True)
        return
    
    if not is_user_group_owner(user_id, parent_group_upper):
        await interaction.response.send_message(f"❌ You do not manage the company that owns '{parent_group}'.", ephemeral=True)
        return
    
    parent_entry = group_data[parent_group_upper]
    
    if parent_entry.get('is_disbanded'):
        await interaction.response.send_message(f"❌ Cannot create subunit from a disbanded group.", ephemeral=True)
        return
    
    if parent_entry.get('is_subunit'):
        await interaction.response.send_message(f"❌ Cannot create a subunit from another subunit.", ephemeral=True)
        return
    
    if subunit_name_upper in group_data:
        await interaction.response.send_message(f"❌ A group/subunit named `{subunit_name}` already exists.", ephemeral=True)
        return
    
    if album_name in album_data:
        await interaction.response.send_message(f"❌ Album `{album_name}` already exists. Please choose a different name.", ephemeral=True)
        return
    
    parent_members = parent_entry.get('members', [])
    if not parent_members:
        await interaction.response.send_message(f"❌ Parent group has no members. Add members first with `/addmember`.", ephemeral=True)
        return
    
    member_list = [m.strip().title() for m in members.split(',')]
    
    invalid_members = []
    valid_members = []
    for m in member_list:
        found = False
        for pm in parent_members:
            if pm.lower() == m.lower():
                valid_members.append(pm)
                found = True
                break
        if not found:
            invalid_members.append(m)
    
    if invalid_members:
        await interaction.response.send_message(
            f"❌ These members are not in **{parent_group_upper}**: {', '.join(invalid_members)}\n"
            f"Valid members: {', '.join(parent_members)}",
            ephemeral=True
        )
        return
    
    if len(valid_members) < 1:
        await interaction.response.send_message(f"❌ Subunit must have at least 1 member.", ephemeral=True)
        return
    
    company_name = parent_entry.get('company')
    
    inherited_pop = int(parent_entry.get('popularity', 100) * 0.5)
    inherited_fanbase = int(parent_entry.get('fanbase', 50) * 0.6)
    inherited_gp = int(parent_entry.get('gp', 30) * 0.7)
    
    group_data[subunit_name_upper] = {
        'company': company_name,
        'albums': [album_name],
        'popularity': inherited_pop,
        'fanbase': inherited_fanbase,
        'gp': inherited_gp,
        'members': valid_members,
        'is_subunit': True,
        'parent_group': parent_group_upper,
        'is_disbanded': False,
        'recent_events': [],
        'wins': 0,
        'all_kills': 0,
        'payola_suspicion': 0,
        'debut_date': datetime.now(ARG_TZ).strftime("%Y-%m-%d"),
        'profile_picture': None,
        'banner_url': None,
        'description': None
    }
    group_popularity[subunit_name_upper] = inherited_pop
    
    initial_stock = random.randint(500000, 1500000) if album_format == "physical" else 0
    
    album_data[album_name] = {
        'group': subunit_name_upper,
        'wins': 0,
        'release_date': datetime.now(ARG_TZ).strftime("%Y-%m-%d"),
        'streams': 0,
        'sales': 0,
        'views': 0,
        'image_url': image_url,
        'is_active_promotion': False,
        'promotion_end_date': None,
        'first_24h_tracking': None,
        'album_type': album_type,
        'album_format': album_format,
        'stock': initial_stock,
        'charts_info': {
            "MelOn": {'rank': None, 'peak': None, 'prev_rank': None},
            "Genie": {'rank': None, 'peak': None, 'prev_rank': None},
            "Bugs": {'rank': None, 'peak': None, 'prev_rank': None},
            "FLO": {'rank': None, 'peak': None, 'prev_rank': None}
        }
    }
    
    parent_entry.setdefault('subunits', [])
    if subunit_name_upper not in parent_entry['subunits']:
        parent_entry['subunits'].append(subunit_name_upper)
    
    save_data()
    
    type_display = {"full": "Full Album", "mini": "Mini Album", "single": "Single"}.get(album_type, album_type)
    format_icon = "💿" if album_format == "physical" else "🎵"
    
    embed = discord.Embed(
        title=f"🌟 Subunit Debut - {subunit_name_upper}",
        description=f"**{subunit_name_upper}** debuts as a subunit of **{parent_group_upper}**!",
        color=discord.Color.from_rgb(255, 105, 180)
    )
    embed.set_thumbnail(url=image_url)
    embed.add_field(name="Members", value=", ".join(valid_members), inline=False)
    embed.add_field(name="Album", value=f"{format_icon} {album_name}", inline=True)
    embed.add_field(name="Type", value=type_display, inline=True)
    embed.add_field(name="Format", value=album_format.title(), inline=True)
    if album_format == "physical":
        embed.add_field(name="Stock", value=f"{initial_stock:,} copies", inline=True)
    embed.add_field(name="Popularity", value=str(inherited_pop), inline=True)
    embed.add_field(name="Fanbase", value=str(inherited_fanbase), inline=True)
    embed.add_field(name="GP Interest", value=str(inherited_gp), inline=True)
    embed.set_footer(text=f"Inherits stats from {parent_group_upper} • {datetime.now(ARG_TZ).strftime('%Y-%m-%d')}")
    
    await interaction.response.send_message(embed=embed)


# === SONG-LEVEL TRACKING SYSTEM ===

@bot.tree.command(description="Add songs to an album. Designate one as the title track.")
@app_commands.describe(
    album_name="The album to add songs to.",
    songs="Comma-separated list of song names.",
    title_track="Which song is the title track (must be in the songs list)."
)
@app_commands.autocomplete(album_name=user_album_autocomplete)
async def addsongs(interaction: discord.Interaction, album_name: str, songs: str, title_track: str):
    user_id = str(interaction.user.id)
    
    if album_name not in album_data:
        await interaction.response.send_message(f"❌ Album `{album_name}` not found.", ephemeral=True)
        return
    
    album_entry = album_data[album_name]
    group_name = album_entry.get('group')
    
    if not group_name or not is_user_group_owner(user_id, group_name):
        await interaction.response.send_message(f"❌ You do not manage the company that owns this album.", ephemeral=True)
        return
    
    if album_entry.get('songs'):
        await interaction.response.send_message(f"❌ This album already has songs. Use `/albumsongs` to view them.", ephemeral=True)
        return
    
    song_list = [s.strip() for s in songs.split(',') if s.strip()]
    title_track_clean = title_track.strip()
    
    if len(song_list) < 1:
        await interaction.response.send_message(f"❌ Please provide at least one song.", ephemeral=True)
        return
    
    if len(song_list) > 15:
        await interaction.response.send_message(f"❌ Maximum 15 songs per album.", ephemeral=True)
        return
    
    title_found = False
    normalized_title = None
    for s in song_list:
        if s.lower() == title_track_clean.lower():
            title_found = True
            normalized_title = s
            break
    
    if not title_found:
        await interaction.response.send_message(f"❌ Title track `{title_track}` must be in the songs list.", ephemeral=True)
        return
    
    existing_streams = album_entry.get('streams', 0)
    other_songs = [s for s in song_list if s != normalized_title]
    
    songs_data = {}
    
    if existing_streams > 0 and len(song_list) > 0:
        if len(other_songs) > 0:
            title_share = int(existing_streams * 0.6)
            remaining = existing_streams - title_share
            base_weights = [(0.3 ** i) * random.uniform(0.5, 1.5) for i in range(len(other_songs))]
            random.shuffle(base_weights)
            total_weight = sum(base_weights)
            bside_shares = [int(remaining * (w / total_weight)) for w in base_weights]
        else:
            title_share = existing_streams
            bside_shares = []
        
        for i, song in enumerate(song_list):
            if song == normalized_title:
                songs_data[song] = {
                    'streams': title_share,
                    'weekly_streams': {},
                    'is_title': True
                }
            else:
                bside_index = other_songs.index(song)
                songs_data[song] = {
                    'streams': bside_shares[bside_index] if bside_shares else 0,
                    'weekly_streams': {},
                    'is_title': False
                }
    else:
        for song in song_list:
            songs_data[song] = {
                'streams': 0,
                'weekly_streams': {},
                'is_title': song == normalized_title
            }
    
    album_entry['songs'] = songs_data
    album_entry['title_track'] = normalized_title
    save_data()
    
    embed = discord.Embed(
        title=f"🎵 Songs Added to {album_name}!",
        description=f"**{group_name}** • {len(song_list)} tracks",
        color=discord.Color.green()
    )
    
    song_display = []
    for song in song_list:
        song_streams = songs_data[song]['streams']
        if song == normalized_title:
            if song_streams > 0:
                song_display.append(f"⭐ **{song}** (Title Track) - {format_number(song_streams)} streams")
            else:
                song_display.append(f"⭐ **{song}** (Title Track)")
        else:
            if song_streams > 0:
                song_display.append(f"• {song} - {format_number(song_streams)} streams")
            else:
                song_display.append(f"• {song}")
    
    embed.add_field(name="Tracklist", value="\n".join(song_display), inline=False)
    
    if existing_streams > 0:
        embed.set_footer(text=f"📊 {format_number(existing_streams)} existing streams distributed to songs!")
    
    embed.set_thumbnail(url=sanitize_url(album_entry.get('image_url')))
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="View all songs in an album with their individual streams.")
@app_commands.describe(album_name="The album to view songs from.")
@app_commands.autocomplete(album_name=album_autocomplete)
async def albumsongs(interaction: discord.Interaction, album_name: str):
    if album_name not in album_data:
        await interaction.response.send_message(f"❌ Album `{album_name}` not found.", ephemeral=True)
        return
    
    album_entry = album_data[album_name]
    songs = album_entry.get('songs', {})
    group_name = album_entry.get('group', 'Unknown')
    title_track = album_entry.get('title_track')
    
    if not songs:
        await interaction.response.send_message(f"📋 **{album_name}** has no individual songs tracked. The owner can add them with `/addsongs`.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title=f"🎵 {album_name} - Tracklist",
        description=f"**{group_name}**",
        color=discord.Color.blue()
    )
    
    current_week = get_current_week_key()
    sorted_songs = sorted(songs.items(), key=lambda x: x[1].get('streams', 0), reverse=True)
    
    for i, (song_name, song_data) in enumerate(sorted_songs, 1):
        is_title = song_data.get('is_title', False)
        streams = song_data.get('streams', 0)
        weekly = song_data.get('weekly_streams', {}).get(current_week, 0)
        
        prefix = "⭐ " if is_title else f"{i}. "
        suffix = " **(Title Track)**" if is_title else ""
        
        embed.add_field(
            name=f"{prefix}{song_name}{suffix}",
            value=f"Total: {format_number(streams)} | This Week: {format_number(weekly)}",
            inline=False
        )
    
    embed.set_thumbnail(url=sanitize_url(album_entry.get('image_url')))
    embed.set_footer(text=f"Album Total Streams: {format_number(album_entry.get('streams', 0))}")
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="view_album", description="View complete album details including streams, sales, MV views, and all songs.")
@app_commands.describe(album_name="The album to view.")
@app_commands.autocomplete(album_name=album_autocomplete)
async def view_album(interaction: discord.Interaction, album_name: str):
    if album_name not in album_data:
        await interaction.response.send_message(f"Album `{album_name}` not found.", ephemeral=True)
        return
    
    album_entry = album_data[album_name]
    group_name = album_entry.get('group', 'Unknown')
    group_info = group_data.get(group_name, {})
    
    songs = album_entry.get('songs', {})
    current_week = get_current_week_key()
    
    if songs and isinstance(songs, dict):
        total_streams = sum(s.get('streams', 0) for s in songs.values())
        weekly_streams = sum(s.get('weekly_streams', {}).get(current_week, 0) for s in songs.values())
    else:
        total_streams = album_entry.get('streams', 0)
        weekly_streams = album_entry.get('weekly_streams', {}).get(current_week, 0)
    
    total_sales = album_entry.get('sales', 0)
    mv_views = album_entry.get('views', 0)
    album_type = album_entry.get('album_type', album_entry.get('type', 'Album'))
    format_type = album_entry.get('album_format', album_entry.get('format', 'Digital'))
    release_date = album_entry.get('release_date', 'Unknown')
    is_active = album_entry.get('is_active_promotion', False)
    
    type_display = {"full": "Full Album", "mini": "Mini Album", "single": "Single"}.get(album_type, album_type)
    format_display = format_type.title() if format_type else "Digital"
    
    embed = discord.Embed(
        title=f"{album_name}",
        description=f"by **{group_name}**" + (f" ({group_info.get('korean_name', '')})" if group_info.get('korean_name') else ""),
        color=discord.Color.from_rgb(255, 105, 180)
    )
    
    embed.add_field(name="Type", value=f"{type_display} • {format_display}", inline=True)
    embed.add_field(name="Release", value=release_date, inline=True)
    embed.add_field(name="Status", value="🔴 Active Promotion" if is_active else "Inactive", inline=True)
    
    embed.add_field(name="Total Streams", value=format_number(total_streams), inline=True)
    embed.add_field(name="Weekly Streams", value=format_number(weekly_streams), inline=True)
    embed.add_field(name="Total Sales", value=format_number(total_sales), inline=True)
    embed.add_field(name="MV Views", value=format_number(mv_views), inline=True)
    
    if format_type == 'physical':
        current_stock = album_entry.get('stock', 0)
        stock_display = format_number(current_stock) if current_stock > 0 else "SOLD OUT"
        embed.add_field(name="Stock", value=stock_display, inline=True)
    
    if songs and isinstance(songs, dict):
        sorted_songs = sorted(songs.items(), key=lambda x: x[1].get('streams', 0), reverse=True)
        
        song_lines = []
        for song_name, song_data in sorted_songs:
            is_title = song_data.get('is_title', False)
            streams = song_data.get('streams', 0)
            prefix = "⭐" if is_title else "•"
            song_lines.append(f"{prefix} {song_name} — {format_number(streams)}")
        
        if len(song_lines) > 10:
            embed.add_field(name=f"Songs ({len(songs)})", value="\n".join(song_lines[:10]) + f"\n*...and {len(songs) - 10} more*", inline=False)
        else:
            embed.add_field(name=f"Songs ({len(songs)})", value="\n".join(song_lines) if song_lines else "No songs", inline=False)
    else:
        embed.add_field(name="Songs", value="No individual song tracking. Owner can add with `/addsongs`", inline=False)
    
    first_24h = album_entry.get('first_24h_tracking')
    if first_24h:
        ended = first_24h.get('ended', False)
        h24_streams = first_24h.get('streams', 0)
        h24_sales = first_24h.get('sales', 0)
        h24_views = first_24h.get('views', 0)
        status = "Ended" if ended else "Tracking"
        embed.add_field(
            name=f"First 24H ({status})",
            value=f"Streams: {format_number(h24_streams)} | Sales: {format_number(h24_sales)} | Views: {format_number(h24_views)}",
            inline=False
        )
    
    embed.set_thumbnail(url=sanitize_url(album_entry.get('image_url')))
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="editalbum_songs", description="Add or remove songs from an existing album.")
@app_commands.describe(
    album_name="The album to edit",
    action="Add or remove songs",
    songs="Comma-separated song names to add/remove",
    new_title="(Optional) Set a new title track"
)
@app_commands.choices(action=[
    app_commands.Choice(name="Add Songs", value="add"),
    app_commands.Choice(name="Remove Songs", value="remove")
])
@app_commands.autocomplete(album_name=user_album_autocomplete)
async def editalbum_songs(
    interaction: discord.Interaction,
    album_name: str,
    action: str,
    songs: str,
    new_title: str = None
):
    user_id = str(interaction.user.id)
    
    if album_name not in album_data:
        await interaction.response.send_message("Album not found.", ephemeral=True)
        return
    
    album_entry = album_data[album_name]
    group_name = album_entry.get('group')
    
    if not group_name or not is_user_group_owner(user_id, group_name):
        await interaction.response.send_message("You don't manage this album's group.", ephemeral=True)
        return
    
    existing_songs = album_entry.get('songs', {})
    if not isinstance(existing_songs, dict):
        existing_songs = {}
    
    song_list = [s.strip() for s in songs.split(',') if s.strip()]
    
    if not song_list:
        await interaction.response.send_message("Please provide at least one song name.", ephemeral=True)
        return
    
    changes = []
    
    if action == "add":
        for song in song_list:
            if song not in existing_songs:
                existing_songs[song] = {
                    'streams': 0,
                    'weekly_streams': {},
                    'is_title': False
                }
                changes.append(f"+ {song}")
        
        if new_title:
            new_title_clean = new_title.strip()
            if new_title_clean in existing_songs:
                for s in existing_songs:
                    existing_songs[s]['is_title'] = (s == new_title_clean)
                album_entry['title_track'] = new_title_clean
                changes.append(f"⭐ Set title: {new_title_clean}")
    
    elif action == "remove":
        for song in song_list:
            matched = None
            for s in existing_songs:
                if s.lower() == song.lower():
                    matched = s
                    break
            if matched:
                if existing_songs[matched].get('is_title'):
                    await interaction.response.send_message(f"Cannot remove title track `{matched}`. Set a new title track first.", ephemeral=True)
                    return
                del existing_songs[matched]
                changes.append(f"- {matched}")
    
    if not changes:
        if action == "add":
            await interaction.response.send_message("All specified songs already exist in the album.", ephemeral=True)
        else:
            await interaction.response.send_message("None of the specified songs were found in the album.", ephemeral=True)
        return
    
    album_entry['songs'] = existing_songs
    
    if len(existing_songs) > 15:
        await interaction.response.send_message("Maximum 15 songs per album.", ephemeral=True)
        return
    
    save_data()
    
    embed = discord.Embed(
        title=f"Album Songs Updated",
        description=f"**{album_name}** by **{group_name}**",
        color=discord.Color.green()
    )
    embed.add_field(name="Changes", value="\n".join(changes), inline=False)
    embed.add_field(name="Total Songs", value=str(len(existing_songs)), inline=True)
    embed.set_thumbnail(url=sanitize_url(album_entry.get('image_url')))
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Redistribute an album's streams properly (50% title, 50% randomized to b-sides).")
@app_commands.describe(album_name="The album to fix stream distribution for.")
@app_commands.autocomplete(album_name=user_album_autocomplete)
async def fixalbumstreams(interaction: discord.Interaction, album_name: str):
    user_id = str(interaction.user.id)
    
    if album_name not in album_data:
        await interaction.response.send_message(f"❌ Album `{album_name}` not found.", ephemeral=True)
        return
    
    album_entry = album_data[album_name]
    group_name = album_entry.get('group')
    
    if not group_name or not is_user_group_owner(user_id, group_name):
        await interaction.response.send_message("❌ You don't manage this album's group.", ephemeral=True)
        return
    
    songs = album_entry.get('songs', {})
    if not songs:
        await interaction.response.send_message(f"❌ This album has no songs to redistribute. Add songs first with `/addsongs`.", ephemeral=True)
        return
    
    total_streams = album_entry.get('streams', 0)
    if total_streams == 0:
        await interaction.response.send_message(f"❌ This album has no streams to redistribute.", ephemeral=True)
        return
    
    title_track = None
    other_songs = []
    for song_name, song_data in songs.items():
        if song_data.get('is_title', False):
            title_track = song_name
        else:
            other_songs.append(song_name)
    
    if not title_track:
        await interaction.response.send_message(f"❌ No title track found in this album.", ephemeral=True)
        return
    
    if other_songs:
        title_share = int(total_streams * 0.6)
        remaining = total_streams - title_share
        base_weights = [(0.3 ** i) * random.uniform(0.5, 1.5) for i in range(len(other_songs))]
        random.shuffle(base_weights)
        total_weight = sum(base_weights)
        bside_shares = [int(remaining * (w / total_weight)) for w in base_weights]
    else:
        title_share = total_streams
        bside_shares = []
    
    songs[title_track]['streams'] = title_share
    songs[title_track].setdefault('weekly_streams', {})
    
    for i, song_name in enumerate(other_songs):
        songs[song_name]['streams'] = bside_shares[i] if bside_shares else 0
        songs[song_name].setdefault('weekly_streams', {})
    
    save_data()
    
    embed = discord.Embed(
        title=f"🔧 Streams Redistributed!",
        description=f"**{album_name}** by **{group_name}**",
        color=discord.Color.green()
    )
    
    song_display = []
    sorted_songs = sorted(songs.items(), key=lambda x: x[1].get('streams', 0), reverse=True)
    for song_name, song_data in sorted_songs:
        is_title = song_data.get('is_title', False)
        streams = song_data.get('streams', 0)
        prefix = "⭐ " if is_title else "• "
        song_display.append(f"{prefix}{song_name} - {format_number(streams)} streams")
    
    embed.add_field(name="New Distribution", value="\n".join(song_display), inline=False)
    embed.set_footer(text=f"Total: {format_number(total_streams)} streams | Title gets 60%, b-sides share the rest")
    embed.set_thumbnail(url=sanitize_url(album_entry.get('image_url')))
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Stream a specific song from an album.")
@app_commands.describe(album_name="The album containing the song.", song_name="The specific song to stream.")
@app_commands.autocomplete(album_name=album_autocomplete, song_name=song_autocomplete)
async def streamsong(interaction: discord.Interaction, album_name: str, song_name: str):
    user_id = str(interaction.user.id)
    
    is_limited, remaining_uses = check_daily_limit(user_id, "streamsong", DAILY_LIMITS["streamsong"])
    if is_limited:
        await interaction.response.send_message(f"You've reached your daily song streaming limit! (0 uses remaining)", ephemeral=True)
        return
    
    if album_name not in album_data:
        await interaction.response.send_message(f"❌ Album `{album_name}` not found.", ephemeral=True)
        return
    
    album_entry = album_data[album_name]
    songs = album_entry.get('songs', {})
    group_name = album_entry.get('group')
    
    if not group_name or group_name not in group_data:
        await interaction.response.send_message("Album group not found.", ephemeral=True)
        return
    
    if not songs:
        await interaction.response.send_message(f"❌ This album doesn't have individual song tracking. Use `/streams` instead.", ephemeral=True)
        return
    
    matched_song = None
    for s in songs.keys():
        if s.lower() == song_name.strip().lower():
            matched_song = s
            break
    
    if not matched_song:
        await interaction.response.send_message(f"❌ Song `{song_name}` not found in this album.", ephemeral=True)
        return
    
    group_entry = group_data[group_name]
    is_disbanded = group_entry.get('is_disbanded', False)
    group_current_popularity = get_group_derived_popularity(group_entry)
    fanbase = group_entry.get('fanbase', 50)
    gp = group_entry.get('gp', 30)
    
    import math
    
    # Get tier bounds for streamsong
    tier_floor, tier_cap, tier_name = get_tier_bounds(group_current_popularity, 'streamsong')
    
    # Calculate base streams
    effective_pop = group_current_popularity + (fanbase * 0.3) + (gp * 0.2)
    soft_pop = math.sqrt(effective_pop)
    base_streams = int(soft_pop * (tier_cap / math.sqrt(tier_cap)))
    base_streams = max(tier_floor, min(tier_cap, base_streams))
    
    is_title = songs[matched_song].get('is_title', False)
    if is_title:
        base_streams = int(base_streams * 1.2)
    
    # Age curve
    release_date = album_entry.get('release_date')
    if release_date:
        try:
            release_dt = datetime.fromisoformat(release_date)
            days_since = (datetime.now(ARG_TZ) - release_dt.replace(tzinfo=ARG_TZ)).days
            weeks_since = days_since / 7
            if weeks_since <= 1:
                age_curve = 1.35
            elif weeks_since <= 3:
                age_curve = 1.15
            elif weeks_since <= 7:
                age_curve = 1.0
            elif weeks_since <= 15:
                age_curve = 0.85
            elif weeks_since <= 51:
                age_curve = 0.65
            else:
                age_curve = 0.45
        except:
            age_curve = 1.0
    else:
        age_curve = 1.0
    
    age_multiplier = 0.3 + 0.7 * age_curve
    scaled_base = int(base_streams * age_multiplier)
    
    # Apply demographic multiplier
    demo_mults = get_demographic_multipliers(group_entry)
    scaled_base = int(scaled_base * demo_mults['streams'])
    
    # Viral chance (rare: 2-6%)
    viral_chance = min(0.06, max(0.02, (gp - 30) / 600)) * demo_mults['viral']
    
    # Use dynamic result system for variance
    result = calculate_dynamic_result(
        base_value=scaled_base,
        tier_floor=tier_floor,
        tier_cap=tier_cap,
        variance_range=(0.6, 1.4),
        viral_chance=viral_chance,
        viral_mult_range=(1.3, 1.8)
    )
    
    streams_to_add = result['final']
    went_viral = result['went_viral']
    streams_to_add = int(streams_to_add * _get_hidden_bonus(group_name))
    
    if group_entry.get('active_hate_train'):
        hate_boost = group_entry.get('hate_train_fanbase_boost', 0)
        streams_to_add = int(streams_to_add * (1 + hate_boost / 200))
    
    update_nations_group()
    if group_entry.get('is_nations_group'):
        streams_to_add = int(streams_to_add * 1.10)
    
    ABSOLUTE_MAX_STREAMS = 100000
    streams_to_add = min(streams_to_add, ABSOLUTE_MAX_STREAMS)
    
    current_week = get_current_week_key()
    
    title_track = None
    for s, sd in songs.items():
        if sd.get('is_title', False):
            title_track = s
            break
    
    add_song_streams(songs, matched_song, streams_to_add, current_week)
    
    album_entry['streams'] = album_entry.get('streams', 0) + streams_to_add
    album_entry.setdefault('weekly_streams', {})
    album_entry['weekly_streams'][current_week] = album_entry['weekly_streams'].get(current_week, 0) + streams_to_add
    
    if album_entry.get('first_24h_tracking'):
        tracking = album_entry['first_24h_tracking']
        if not tracking.get('ended', False):
            tracking['streams'] = tracking.get('streams', 0) + streams_to_add
    
    company_name = group_entry.get('company')
    royalty_rate = 0.003
    royalties_earned = int(streams_to_add * royalty_rate)
    if company_name and company_name in company_funds and not is_disbanded:
        company_funds[company_name] += royalties_earned
    
    save_data()
    
    viral_text = " 🔥 VIRAL!" if went_viral else ""
    embed = discord.Embed(
        title=f"{matched_song}" + (" ⭐" if is_title else ""),
        description=f"from **{album_name}** • **{group_name}**{viral_text}" + (" (Title Track)" if is_title else ""),
        color=discord.Color.gold() if went_viral else (discord.Color.pink() if group_entry.get('is_nations_group') else discord.Color.from_rgb(255, 105, 180))
    )
    embed.set_thumbnail(url=sanitize_url(album_entry.get('image_url')))
    embed.add_field(name="Streams", value=f"+{format_number(streams_to_add)}", inline=True)
    embed.add_field(name="Song Total", value=f"{format_number(songs[matched_song]['streams'])}", inline=True)
    embed.set_footer(text=f"Album Total: {format_number(album_entry['streams'])} | {remaining_uses} uses left today")
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Start a viral challenge on social media. Free but success varies with fanbase!")
@app_commands.autocomplete(group_name=user_group_autocomplete, album_name=user_album_autocomplete)
async def viralchallenge(interaction: discord.Interaction, group_name: str, album_name: str):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()
    
    if group_name_upper not in group_data:
        await interaction.response.send_message(f"❌ Group `{group_name}` not found.", ephemeral=True)
        return
    
    if not is_user_group_owner(user_id, group_name_upper):
        await interaction.response.send_message(f"❌ You do not manage the company that owns '{group_name}'.", ephemeral=True)
        return
    
    if album_name not in album_data:
        await interaction.response.send_message(f"❌ Album `{album_name}` not found.", ephemeral=True)
        return
    
    group_entry = group_data[group_name_upper]
    album_entry = album_data[album_name]
    
    if album_entry.get('group') != group_name_upper:
        await interaction.response.send_message(f"❌ Album `{album_name}` doesn't belong to `{group_name}`.", ephemeral=True)
        return
    
    if group_entry.get('is_disbanded'):
        await interaction.response.send_message(f"❌ Cannot start challenges for a disbanded group.", ephemeral=True)
        return
    
    fanbase = group_entry.get('fanbase', 50)
    gp = group_entry.get('gp', 30)
    
    viral_chance = (fanbase + gp) / 200

    rep_info = get_reputation_level(group_entry)
    if rep_info.get('viral_boost'):
        viral_chance = viral_chance * (1 + rep_info['viral_boost'])

    viral_chance = max(0.0, min(1.0, viral_chance))

    challenges = [
        "dance challenge",
        "lip sync challenge",
        "outfit challenge",
        "lyrics challenge",
        "reaction challenge"
    ]
    challenge_type = random.choice(challenges)
    
    if random.random() < viral_chance:
        gp_gain = random.randint(5, 15)
        views_gain = random.randint(100000, 500000)
        pop_gain = random.randint(10, 30)
        
        group_entry['gp'] = group_entry.get('gp', 30) + gp_gain
        group_entry['popularity'] = group_entry.get('popularity', 0) + pop_gain
        album_entry['views'] = album_entry.get('views', 0) + views_gain
        
        update_nations_group()
        update_cooldown(user_id, f"viral_{group_name_upper}")
        save_data()
        
        embed = discord.Embed(
            title=f"🔥 VIRAL CHALLENGE SUCCESS! - {group_name_upper}",
            description=f"The **#{group_name_upper}{challenge_type.replace(' ', '')}** is trending!",
            color=discord.Color.orange()
        )
        embed.add_field(name="GP Interest", value=f"+{gp_gain} (Now: {group_entry['gp']})", inline=True)
        embed.add_field(name="Popularity", value=f"+{pop_gain}", inline=True)
        embed.add_field(name="MV Views", value=f"+{views_gain:,}", inline=True)
        
        await interaction.response.send_message(embed=embed)
        
        try:
            await interaction.channel.send(f"🔥 The **#{group_name_upper}{challenge_type.replace(' ', '')}** is going VIRAL! Everyone's joining in!")
        except discord.errors.Forbidden:
            pass
    else:
        gp_gain = random.randint(1, 3)
        views_gain = random.randint(5000, 30000)
        
        group_entry['gp'] = group_entry.get('gp', 30) + gp_gain
        album_entry['views'] = album_entry.get('views', 0) + views_gain
        
        update_nations_group()
        update_cooldown(user_id, f"viral_{group_name_upper}")
        save_data()
        
        embed = discord.Embed(
            title=f"📱 Challenge Posted - {group_name_upper}",
            description=f"The **{challenge_type}** got some attention but didn't go viral.",
            color=discord.Color.light_grey()
        )
        embed.add_field(name="GP Interest", value=f"+{gp_gain}", inline=True)
        embed.add_field(name="MV Views", value=f"+{views_gain:,}", inline=True)
        embed.set_footer(text="Higher fanbase + GP = better chance to go viral!")
        
        await interaction.response.send_message(embed=embed)


# === INCOME SOURCES ===

@bot.tree.command(description="Host a fanmeeting for loyal fans. Cheaper than concerts but great for fanbase!")
@app_commands.autocomplete(group_name=user_group_autocomplete)
async def fanmeeting(interaction: discord.Interaction, group_name: str):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()
    
    if group_name_upper not in group_data:
        await interaction.response.send_message(f"❌ Group `{group_name}` not found.", ephemeral=True)
        return
    
    if not is_user_group_owner(user_id, group_name_upper):
        await interaction.response.send_message(f"❌ You do not manage the company that owns '{group_name}'.", ephemeral=True)
        return
    
    group_entry = group_data[group_name_upper]
    
    if group_entry.get('is_disbanded'):
        await interaction.response.send_message(f"❌ Cannot host fanmeetings for a disbanded group.", ephemeral=True)
        return
    
    company_name = group_entry.get('company')
    venue_cost = 100_000
    
    if company_name not in company_funds or company_funds[company_name] < venue_cost:
        await interaction.response.send_message(f"❌ Not enough for venue costs! Need <:MonthlyPeso:1338642658436059239>{format_number(venue_cost)}.", ephemeral=True)
        return
    
    company_funds[company_name] -= venue_cost
    
    fanbase = group_entry.get('fanbase', 50)
    popularity = group_entry.get('popularity', 0)
    
    base_attendance = fanbase * 20 + popularity * 5
    attendance = max(100, int(random.gauss(base_attendance, base_attendance * 0.2)))
    ticket_price = 80
    
    ticket_revenue = attendance * ticket_price
    exclusive_merch = int(attendance * random.uniform(20, 40))
    total_revenue = ticket_revenue + exclusive_merch
    net_profit = total_revenue - venue_cost
    
    company_funds[company_name] += total_revenue
    
    fanbase_variance = random.uniform(0.6, 1.4)
    fanbase_gain = max(2, int(random.randint(3, 8) * fanbase_variance))
    group_entry['fanbase'] = group_entry.get('fanbase', 50) + fanbase_gain
    
    shift_demographics(group_entry, 'fanmeeting')
    
    activities = ["fansign event", "hi-touch session", "Q&A session", "mini-concert", "birthday celebration"]
    activity = random.choice(activities)
    
    update_cooldown(user_id, f"fanmeet_{group_name_upper}")
    save_data()
    
    embed = discord.Embed(
        title=f"💕 Fanmeeting - {group_name_upper}",
        description=f"**{group_name_upper}** held a **{activity}** for their fans!",
        color=discord.Color.magenta()
    )
    embed.add_field(name="Attendance", value=f"{attendance:,} fans", inline=True)
    embed.add_field(name="Ticket Revenue", value=f"<:MonthlyPeso:1338642658436059239>{format_number(ticket_revenue)}", inline=True)
    embed.add_field(name="Exclusive Merch", value=f"<:MonthlyPeso:1338642658436059239>{format_number(exclusive_merch)}", inline=True)
    embed.add_field(name="Venue Cost", value=f"-<:MonthlyPeso:1338642658436059239>{format_number(venue_cost)}", inline=True)
    embed.add_field(name="Net Profit", value=f"<:MonthlyPeso:1338642658436059239>{format_number(net_profit)}", inline=True)
    embed.add_field(name="💖 Fanbase", value=f"+{fanbase_gain} (Now: {group_entry['fanbase']})", inline=True)
    embed.set_footer(text="Fanmeetings strengthen your core fanbase!")
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Release merchandise to earn passive income! Higher fanbase = more sales.")
@app_commands.autocomplete(group_name=user_group_autocomplete)
async def merchandise(interaction: discord.Interaction, group_name: str):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()
    
    if group_name_upper not in group_data:
        await interaction.response.send_message(f"❌ Group `{group_name}` not found.", ephemeral=True)
        return
    
    if not is_user_group_owner(user_id, group_name_upper):
        await interaction.response.send_message(f"❌ You do not manage the company that owns '{group_name}'.", ephemeral=True)
        return
    
    group_entry = group_data[group_name_upper]
    
    if group_entry.get('is_disbanded'):
        await interaction.response.send_message(f"❌ Cannot release merch for a disbanded group.", ephemeral=True)
        return
    
    company_name = group_entry.get('company')
    production_cost = 50_000
    
    if company_name not in company_funds or company_funds[company_name] < production_cost:
        await interaction.response.send_message(f"❌ Not enough for production costs! Need <:MonthlyPeso:1338642658436059239>{format_number(production_cost)}.", ephemeral=True)
        return
    
    company_funds[company_name] -= production_cost
    
    fanbase = group_entry.get('fanbase', 50)
    popularity = group_entry.get('popularity', 0)
    
    base_units = fanbase * 50 + popularity * 10
    units_sold = max(100, int(random.gauss(base_units, base_units * 0.3)))
    price_per_unit = random.randint(20, 50)
    
    revenue = units_sold * price_per_unit
    net_profit = revenue - production_cost
    
    update_nations_group()
    if group_entry.get('is_nations_group'):
        bonus = int(revenue * 0.25)
        revenue += bonus
        net_profit += bonus
    
    company_funds[company_name] += revenue
    
    merch_types = ["lightstick", "photocard set", "hoodie collection", "poster set", "keychain bundle", "fan kit", "slogan banner"]
    merch = random.choice(merch_types)
    
    shift_demographics(group_entry, 'merchandise')
    
    update_cooldown(user_id, f"merch_{group_name_upper}")
    save_data()
    
    embed = discord.Embed(
        title=f"🛍️ Merch Drop - {group_name_upper}",
        description=f"**{group_name_upper}** released a new **{merch}**!",
        color=discord.Color.pink() if group_entry.get('is_nations_group') else discord.Color.orange()
    )
    embed.add_field(name="Units Sold", value=f"{units_sold:,}", inline=True)
    embed.add_field(name="Price/Unit", value=f"<:MonthlyPeso:1338642658436059239>{price_per_unit}", inline=True)
    embed.add_field(name="Revenue", value=f"<:MonthlyPeso:1338642658436059239>{format_number(revenue)}", inline=True)
    embed.add_field(name="Production", value=f"-<:MonthlyPeso:1338642658436059239>{format_number(production_cost)}", inline=True)
    embed.add_field(name="Net Profit", value=f"<:MonthlyPeso:1338642658436059239>{format_number(net_profit)}", inline=True)
    embed.set_footer(text=f"Fanbase: {fanbase} | Higher fanbase = more sales!")
    
    await interaction.response.send_message(embed=embed)


# === PREDICT COMMAND WITH PILLOW SCOREBOARD ===

def create_predict_scoreboard(albums_scores: list[dict], show_name: str = "Music Bank") -> io.BytesIO:
    """Creates a K-pop award show style scoreboard image using Pillow."""
    
    bg_color = (25, 16, 35)
    header_color = (142, 77, 187)
    row_color_1 = (46, 31, 60)
    row_color_2 = (35, 22, 48)
    text_color = (245, 241, 250)
    gold_color = (255, 215, 0)
    pink_accent = (255, 105, 180)
    
    width = 900
    header_height = 60
    row_height = 45
    num_rows = min(len(albums_scores), 10)
    footer_height = 40
    height = header_height + (row_height * (num_rows + 1)) + footer_height + 20
    
    img = Image.new('RGB', (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    
    try:
        font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
        font_regular = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
    except:
        font_bold = ImageFont.load_default()
        font_regular = ImageFont.load_default()
        font_small = ImageFont.load_default()
        font_title = ImageFont.load_default()
    
    draw.rectangle([(0, 0), (width, header_height)], fill=header_color)
    title = f"{show_name.upper()} PREDICTION"
    title_width = len(title) * 10
    draw.text((width // 2 - title_width // 2, 18), title, fill=text_color, font=font_title)
    
    y = header_height + 5
    col_positions = [15, 60, 220, 370, 450, 540, 630, 720, 810]
    headers = ["#", "ARTIST", "SONG", "TOTAL", "DIG", "PHY", "SNS", "BRD", ""]
    
    draw.rectangle([(0, y), (width, y + row_height)], fill=header_color)
    for i, header in enumerate(headers):
        draw.text((col_positions[i], y + 12), header, fill=text_color, font=font_bold)
    
    y += row_height
    
    winner_idx = 0
    max_total = 0
    for i, album in enumerate(albums_scores[:10]):
        if album['total'] > max_total:
            max_total = album['total']
            winner_idx = i
    
    for i, album in enumerate(albums_scores[:10]):
        row_color = row_color_1 if i % 2 == 0 else row_color_2
        draw.rectangle([(0, y), (width, y + row_height)], fill=row_color)
        
        rank_text = f"#{i + 1}"
        draw.text((col_positions[0], y + 12), rank_text, fill=gold_color if i == 0 else text_color, font=font_bold)
        
        artist = album['group'][:15]
        draw.text((col_positions[1], y + 12), artist, fill=pink_accent, font=font_bold)
        
        song = album['album'][:12]
        draw.text((col_positions[2], y + 12), song, fill=text_color, font=font_regular)
        
        total_color = gold_color if i == winner_idx else text_color
        draw.text((col_positions[3], y + 12), str(album['total']), fill=total_color, font=font_bold)
        
        draw.text((col_positions[4], y + 12), str(album['digital']), fill=text_color, font=font_regular)
        draw.text((col_positions[5], y + 12), str(album['physical']), fill=text_color, font=font_regular)
        draw.text((col_positions[6], y + 12), str(album['sns']), fill=text_color, font=font_regular)
        draw.text((col_positions[7], y + 12), str(album['broadcast']), fill=text_color, font=font_regular)
        
        if i == winner_idx:
            draw.text((col_positions[8], y + 12), "WIN", fill=gold_color, font=font_bold)
        
        y += row_height
    
    y += 10
    disclaimer = "Auto Prediction — Not official"
    draw.text((width // 2 - 80, y), disclaimer, fill=(150, 140, 160), font=font_small)
    
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer


@bot.tree.command(description="Generate a K-pop award show prediction scoreboard image!")
@app_commands.describe(show="The music show to predict for")
@app_commands.autocomplete(show=music_show_autocomplete)
async def predict(interaction: discord.Interaction, show: str = "Music Bank"):
    await interaction.response.defer()
    
    if show not in MUSIC_SHOWS:
        show = "Music Bank"
    
    scoring = MUSIC_SHOWS[show]
    max_digital = scoring["max_digital"]
    max_physical = scoring["max_physical"]
    max_sns = scoring["max_sns"]
    max_broadcast = scoring["max_broadcast"]
    digital_div = scoring["digital_divisor"]
    physical_div = scoring["physical_divisor"]
    sns_div = scoring["sns_divisor"]
    
    active_albums = []
    for album_name, album_entry in album_data.items():
        if not album_entry.get('is_active_promotion'):
            continue
        
        promo_end = album_entry.get('promotion_end_date')
        if promo_end and datetime.now() > promo_end:
            continue
        
        group_name = album_entry.get('group', 'Unknown')
        if group_name in group_data and group_data[group_name].get('is_disbanded'):
            continue
        
        current_week = get_current_week_key()
        weekly_streams = album_entry.get('weekly_streams', {}).get(current_week, 0)
        sales = album_entry.get('sales', 0)
        views = album_entry.get('views', 0)
        sns_posts = album_entry.get('sns_posts', 0)
        is_active = album_entry.get('is_active_promotion', False)
        
        digital = min(max_digital, int(weekly_streams / digital_div))
        physical = min(max_physical, int(sales / physical_div))
        
        if scoring.get('sns_split'):
            max_views_sns = scoring.get('max_sns_views', 1400)
            max_posts_sns = scoring.get('max_sns_posts', 600)
            posts_div = scoring.get('posts_divisor', 5)
            sns_from_views = min(max_views_sns, int(views / sns_div))
            sns_from_posts = min(max_posts_sns, int(sns_posts * posts_div))
            sns = sns_from_views + sns_from_posts
        else:
            sns = min(max_sns, int(views / sns_div))
        
        broadcast = max_broadcast if is_active else 0
        
        voting = 0
        if scoring.get('has_voting') and is_active:
            max_voting = scoring.get('max_voting', 2000)
            grp = group_data.get(group_name, {})
            fanbase = grp.get('fanbase', 50)
            voting = min(max_voting, int(fanbase * 20))
        
        total = digital + physical + sns + broadcast + voting
        
        active_albums.append({
            'album': album_name,
            'group': group_name,
            'digital': digital,
            'physical': physical,
            'sns': sns,
            'broadcast': broadcast,
            'voting': voting,
            'total': total
        })
    
    if not active_albums:
        await interaction.followup.send("No albums currently in promotion to predict!", ephemeral=True)
        return
    
    active_albums.sort(key=lambda x: x['total'], reverse=True)
    
    scoreboard_image = create_predict_scoreboard(active_albums, show)
    
    file = discord.File(scoreboard_image, filename="prediction.png")
    
    embed = discord.Embed(
        title=f"{show} Prediction",
        description="Based on current streams, sales, views, and promotion status",
        color=discord.Color.from_rgb(142, 77, 187)
    )
    embed.set_image(url="attachment://prediction.png")
    embed.set_footer(text="Auto Prediction — Not official results")
    
    await interaction.followup.send(embed=embed, file=file)


@bot.tree.command(description="View Global Top Songs chart for a song.")
@app_commands.describe(song_name="The song to check global charts for")
@app_commands.autocomplete(song_name=song_autocomplete)
async def globalchart(interaction: discord.Interaction, song_name: str):
    found_song = None
    found_album = None
    found_group = None
    
    for album_name, album_entry in album_data.items():
        songs = album_entry.get('songs', {})
        for sname in songs:
            if sname.lower() == song_name.lower():
                found_song = sname
                found_album = album_name
                found_group = album_entry.get('group', 'Unknown')
                break
        if found_song:
            break
    
    if not found_song:
        await interaction.response.send_message(f"Song `{song_name}` not found.", ephemeral=True)
        return
    
    song_data = album_data[found_album]['songs'][found_song]
    total_streams = song_data.get('streams', 0)
    
    song_data.setdefault('global_chart', {})
    
    report_lines = [f'**"{found_song}"** on Global Top Songs:\n']
    
    charted_countries = []
    for emoji, country, weight in GLOBAL_CHART_COUNTRIES:
        threshold = int(500000 / weight)
        
        if total_streams < threshold:
            continue
        
        chart_key = country.replace(" ", "_").lower()
        prev_rank = song_data['global_chart'].get(chart_key, {}).get('rank')
        prev_peak = song_data['global_chart'].get(chart_key, {}).get('peak')
        
        base_rank = max(1, int(200 - (total_streams / threshold) * 50))
        variance = random.randint(-5, 5)
        rank = max(1, min(200, base_rank + variance))
        
        peak = min(rank, prev_peak) if prev_peak else rank
        
        song_data['global_chart'][chart_key] = {'rank': rank, 'peak': peak}
        
        if prev_rank:
            diff = prev_rank - rank
            if diff > 0:
                change = f"(+{diff})"
            elif diff < 0:
                change = f"({diff})"
            else:
                change = "(=)"
        else:
            change = "(NEW)"
        
        peak_note = " *new peak*" if rank == peak and prev_peak and rank < prev_peak else ""
        
        charted_countries.append((rank, f"{emoji} #{rank}. {country} {change}{peak_note}"))
    
    if not charted_countries:
        await interaction.response.send_message(f"'{found_song}' hasn't charted globally yet. Keep streaming!", ephemeral=True)
        return
    
    charted_countries.sort(key=lambda x: x[0])
    
    if len(charted_countries) > 8:
        top_2 = charted_countries[:2]
        bottom_2 = charted_countries[-2:]
        mid_countries = charted_countries[2:-2]
        
        num_mid_to_pick = min(4, len(mid_countries))
        if mid_countries and num_mid_to_pick > 0:
            selected_mid = random.sample(mid_countries, num_mid_to_pick)
            selected_mid.sort(key=lambda x: x[0])
        else:
            selected_mid = []
        
        charted_countries = top_2 + selected_mid + bottom_2
    
    for _, line in charted_countries:
        report_lines.append(line)
    
    report_lines.append(f"\n#{found_song.replace(' ', '')} #{found_group.replace(' ', '')}")
    
    save_data()
    await interaction.response.send_message("\n".join(report_lines))


@bot.tree.command(description="View the top 10 groups leaderboard for this week.")
async def groupweekly(interaction: discord.Interaction):
    current_week = get_current_week_key()
    
    group_scores = []
    
    for group_name, group_entry in group_data.items():
        if group_entry.get('is_disbanded'):
            continue
        
        group_albums = [a for a, ad in album_data.items() if ad.get('group') == group_name]
        
        weekly_streams = 0
        weekly_sales = 0
        weekly_views = 0
        
        for album_name in group_albums:
            album_entry = album_data[album_name]
            
            album_weekly = album_entry.get('weekly_streams', {}).get(current_week, 0)
            weekly_streams += album_weekly
            
            songs = album_entry.get('songs', {})
            if isinstance(songs, dict):
                for song_name, song_data in songs.items():
                    song_weekly = song_data.get('weekly_streams', {}).get(current_week, 0)
                    weekly_streams += song_weekly
            
            album_sales_weekly = album_entry.get('weekly_sales', {}).get(current_week, 0)
            weekly_sales += album_sales_weekly
            
            album_views_weekly = album_entry.get('weekly_views', {}).get(current_week, 0)
            weekly_views += album_views_weekly
        
        raw_score = (weekly_streams / 10000) + (weekly_sales * 2) + (weekly_views / 5000)
        
        group_scores.append({
            'name': group_name,
            'raw_score': raw_score,
            'streams': weekly_streams,
            'sales': weekly_sales,
            'views': weekly_views
        })
    
    group_scores.sort(key=lambda x: x['raw_score'], reverse=True)
    
    max_raw = group_scores[0]['raw_score'] if group_scores and group_scores[0]['raw_score'] > 0 else 1
    
    for g in group_scores:
        g['score'] = int((g['raw_score'] / max_raw) * 10000) if max_raw > 0 else 0
    
    top_10 = group_scores[:10]
    
    if not top_10:
        await interaction.response.send_message("No active groups to rank.", ephemeral=True)
        return
    
    report_lines = [f"🏆 **Weekly Top 10 Groups** — Week {current_week}\n"]
    
    medals = ["🥇", "🥈", "🥉"]
    
    for i, g in enumerate(top_10):
        rank_display = medals[i] if i < 3 else f"**#{i+1}**"
        
        stats_parts = []
        if g['streams'] > 0:
            stats_parts.append(f"{format_number(g['streams'])} streams")
        if g['sales'] > 0:
            stats_parts.append(f"{format_number(g['sales'])} sales")
        if g['views'] > 0:
            stats_parts.append(f"{format_number(g['views'])} views")
        
        stats_line = " | ".join(stats_parts) if stats_parts else "No activity yet"
        
        report_lines.append(f"{rank_display} **{g['name']}** — {g['score']:,}/10,000")
        report_lines.append(f"   {stats_line}")
        report_lines.append("")
    
    await interaction.response.send_message("\n".join(report_lines))


@bot.tree.command(description="View daily Spotify streaming history for a song.")
@app_commands.describe(song_name="The song to check daily streams for")
@app_commands.autocomplete(song_name=song_autocomplete)
async def dailyspotify(interaction: discord.Interaction, song_name: str):
    found_song = None
    found_album = None
    found_group = None
    
    for album_name, album_entry in album_data.items():
        songs = album_entry.get('songs', {})
        for sname in songs:
            if sname.lower() == song_name.lower():
                found_song = sname
                found_album = album_name
                found_group = album_entry.get('group', 'Unknown')
                break
        if found_song:
            break
    
    if not found_song:
        await interaction.response.send_message(f"Song `{song_name}` not found.", ephemeral=True)
        return
    
    song_data = album_data[found_album]['songs'][found_song]
    total_streams = song_data.get('streams', 0)
    
    daily_streams = song_data.get('daily_streams', {})
    
    if not daily_streams:
        await interaction.response.send_message(f"**{found_song}** hasn't been streamed yet! Use `/streamsong` or `/streams` first.", ephemeral=True)
        return
    
    report_lines = [f"**{found_song}** SPOTIFY\n"]
    
    sorted_dates = sorted(daily_streams.keys())[-7:]
    
    biggest_day = 0
    biggest_day_date = None
    prev_streams = None
    
    for date_key in sorted_dates:
        streams = daily_streams[date_key]
        date_obj = datetime.strptime(date_key, "%Y-%m-%d")
        date_str = date_obj.strftime("%d/%m")
        
        if streams > biggest_day:
            biggest_day = streams
            biggest_day_date = date_str
        
        if prev_streams is not None:
            diff = streams - prev_streams
            if prev_streams > 0:
                if diff > 0:
                    indicator = f"(+{format_number(diff)})🔺" if diff > prev_streams * 0.1 else f"(+{format_number(diff)})"
                elif diff < 0:
                    indicator = f"({format_number(diff)})🔻" if abs(diff) > prev_streams * 0.1 else f"({format_number(diff)})"
                    if abs(diff) > prev_streams * 0.2:
                        indicator += "🚨"
                else:
                    indicator = "(=)"
            else:
                indicator = f"(+{format_number(diff)})" if diff > 0 else "(=)"
        else:
            indicator = ""
        
        report_lines.append(f"{date_str} — {format_number(streams)} {indicator}")
        prev_streams = streams
    
    report_lines.append(f"\nTotal: {format_number(total_streams)} streams")
    
    today_key = get_today_str()
    today_streams = daily_streams.get(today_key, 0)
    if biggest_day > 0 and today_streams == biggest_day:
        report_lines.append(f"\n✨ **\"{found_song}\"** by {found_group} earns its biggest streaming day with {format_number(biggest_day)} streams!")
    
    await interaction.response.send_message("\n".join(report_lines))


@bot.tree.command(name="random", description="Trigger a random event for a random group (3-hour global cooldown).")
async def random_event(interaction: discord.Interaction):
    global last_random_timestamp
    
    now = datetime.now(ARG_TZ)
    cooldown_seconds = 3 * 60 * 60
    
    if last_random_timestamp:
        try:
            if isinstance(last_random_timestamp, str):
                last_time = datetime.fromisoformat(last_random_timestamp)
                if last_time.tzinfo is None:
                    last_time = last_time.replace(tzinfo=ARG_TZ)
            else:
                last_time = last_random_timestamp
                if last_time.tzinfo is None:
                    last_time = last_time.replace(tzinfo=ARG_TZ)
            
            time_since = (now - last_time).total_seconds()
            if time_since < cooldown_seconds:
                remaining = int(cooldown_seconds - time_since)
                hours = remaining // 3600
                minutes = (remaining % 3600) // 60
                await interaction.response.send_message(
                    f"⏳ Random event on cooldown! Wait **{hours}h {minutes}m** before anyone can use this again.",
                    ephemeral=True
                )
                return
        except:
            pass
    
    active_groups = [g for g, gd in group_data.items() if not gd.get('is_disbanded')]
    
    if not active_groups:
        await interaction.response.send_message("❌ No active groups to trigger events for.", ephemeral=True)
        return
    
    group_name = random.choice(active_groups)
    group_entry = group_data[group_name]
    is_canonical = group_name.upper() in _CANONICAL_GROUPS
    
    if is_canonical:
        is_good_event = random.random() > 0.15
    else:
        is_good_event = random.random() > 0.4
    
    events_list = RANDOM_EVENTS_GOOD if is_good_event else RANDOM_EVENTS_BAD
    event = random.choice(events_list).copy()
    
    other_group = None
    other_member = None
    if event.get('requires_other_group'):
        other_group = get_random_other_group(group_name)
        if other_group:
            other_member = get_random_member(other_group)
        else:
            # fallback: pick a non-crossover event so formatting won't fail
            non_cross = [e for e in events_list if not e.get('requires_other_group')]
            event = random.choice(non_cross).copy() if non_cross else event

    if not is_good_event and is_canonical:
        if 'popularity' in event:
            event['popularity'] = (event['popularity'][0] // 2, event['popularity'][1] // 2)
        if 'gp' in event:
            event['gp'] = (event['gp'][0] // 2, event['gp'][1] // 2)
        if 'triggers_hate_train' in event:
            event['triggers_hate_train'] = event['triggers_hate_train'] * 0.3
    
    member = get_random_member(group_name)
    
    description = event['description']
    if '{embarrassing_action}' in description:
        action = random.choice(EMBARRASSING_LIVE_ACTIONS)
        description = description.replace('{embarrassing_action}', action)
    
    song_name = None
    album_name_for_song = None
    if event.get('song_boost'):
        song_name, album_name_for_song = get_random_song_from_group(group_name)
        if not song_name:
            await interaction.response.send_message("❌ Couldn't find a song for this event. Try again!", ephemeral=True)
            return
        description = description.replace('{song}', song_name)
    
    description = description.format(
    member=member,
    group=group_name,
    song=song_name or "",
    other_group=other_group or "",
    other_member=other_member or ""
)
    
    event_record = {
        'type': event['type'],
        'title': event['title'],
        'description': description,
        'timestamp': now.isoformat(),
        'is_good': is_good_event
    }
    
    if 'popularity' in event:
        change = random.randint(*event['popularity'])
        group_entry['popularity'] = max(0, group_entry.get('popularity', 0) + change)
        event_record['popularity_change'] = change
    
    if 'gp' in event:
        change = random.randint(*event['gp'])
        group_entry['gp'] = max(0, min(100, group_entry.get('gp', 30) + change))
        event_record['gp_change'] = change
    
    if 'fanbase' in event:
        change = random.randint(*event['fanbase'])
        group_entry['fanbase'] = max(0, min(100, group_entry.get('fanbase', 50) + change))
        event_record['fanbase_change'] = change
    
    if 'views' in event:
        change = random.randint(*event['views'])
        group_entry['views'] = max(0, group_entry.get('views', 0) + change)
        event_record['views_change'] = change
    if 'streams' in event:
        change = random.randint(*event['streams'])
        group_entry['streams'] = max(0, group_entry.get('streams', 0) + change)
        event_record['streams_change'] = change
    if event.get('song_boost') and song_name and album_name_for_song:
        stream_boost = random.randint(100000, 500000)
        current_week = get_current_week_key()
        songs = album_data[album_name_for_song].get('songs', {})
        if song_name in songs:
            add_song_streams(songs, song_name, stream_boost, current_week)
        album_data[album_name_for_song]['streams'] = album_data[album_name_for_song].get('streams', 0) + stream_boost
        album_data[album_name_for_song].setdefault('weekly_streams', {})
        album_data[album_name_for_song]['weekly_streams'][current_week] = album_data[album_name_for_song]['weekly_streams'].get(current_week, 0) + stream_boost
        event_record['song_boost'] = stream_boost
        event_record['boosted_song'] = song_name
    
    if event.get('triggers_hate_train') and random.random() < event['triggers_hate_train']:
        group_entry['active_hate_train'] = True
        group_entry['has_scandal'] = True
        event_record['triggered_hate_train'] = True

    if event.get('triggers_hate_train') or 'scandal' in event.get('type', '').lower():
        rep_change = random.randint(-15, -5)
        apply_reputation_change(group_name, rep_change, event['title'])
        event_record['reputation_change'] = rep_change

    recent_events = group_entry.get('recent_events', [])
    recent_events.append(event_record)
    group_entry['recent_events'] = recent_events[-10:]
    
    random_events_log.setdefault(group_name, []).append(event_record)
    
    last_random_timestamp = now.isoformat()
    save_data()
    
    emoji = "✨" if event_record['is_good'] else "⚠️"
    owner_id = get_group_owner_user_id(group_name)
    mention = f"<@{owner_id}>" if owner_id else ""
    
    msg = f"{emoji} **{event_record['title']}** {emoji}\n{event_record['description']}"
    if mention:
        msg += f"\n\n{mention}"
    
    if event_record.get('triggered_hate_train'):
        msg += "\n🔥 **HATE TRAIN ACTIVATED**"
    
    if event_record.get('song_boost'):
        msg += f"\n📈 **+{format_number(event_record['song_boost'])} streams** to \"{event_record['boosted_song']}\""
    if event_record.get('views_change'):
        msg += f"\n📺 **+{format_number(event_record['views_change'])} views**"
    if event_record.get('streams_change'):
        msg += f"\n🎧 **+{format_number(event_record['streams_change'])} streams**"
    
    await interaction.response.send_message(msg)


# === MEMBER SYSTEM ===

def get_group_derived_popularity(group_entry: dict) -> int:
    """Calculate group popularity as SUM of member popularities if members exist."""
    members = group_entry.get('members', [])
    if not members:
        return group_entry.get('popularity', 100)
    member_pops = [m.get('popularity', 0) for m in members if isinstance(m, dict)]
    if not member_pops:
        return group_entry.get('popularity', 100)
    # Group popularity = SUM of all member popularities
    return sum(member_pops)


def get_demographic_multipliers(group_entry: dict) -> dict:
    """Calculate multipliers based on average fan demographics across all members.
    Returns: {streams_mult, sales_mult, fandom_mult, gp_mult, viral_mult}
    - teen fans → streams + viral chance
    - adult fans → sales + stability
    - female fans → fandom power (preorders, merch)
    - male fans → GP (passive streams, longevity)
    """
    members = group_entry.get('members', [])
    
    if not members:
        return {'streams': 1.0, 'sales': 1.0, 'fandom': 1.0, 'gp': 1.0, 'viral': 1.0}
    
    total_teen = total_adult = total_female = total_male = 0.0
    count = 0
    
    for m in members:
        if isinstance(m, dict):
            ratios = m.get('fan_ratios', {'teen': 0.5, 'adult': 0.5, 'female': 0.5, 'male': 0.5})
            if ratios:
                total_teen += ratios.get('teen', 0.5)
                total_adult += ratios.get('adult', 0.5)
                total_female += ratios.get('female', 0.5)
                total_male += ratios.get('male', 0.5)
                count += 1
    
    if count == 0:
        return {'streams': 1.0, 'sales': 1.0, 'fandom': 1.0, 'gp': 1.0, 'viral': 1.0}
    
    avg_teen = total_teen / count
    avg_adult = total_adult / count
    avg_female = total_female / count
    avg_male = total_male / count
    
    streams_mult = 0.8 + (avg_teen * 0.4)
    viral_mult = 0.7 + (avg_teen * 0.6)
    sales_mult = 0.8 + (avg_adult * 0.4)
    fandom_mult = 0.8 + (avg_female * 0.4)
    gp_mult = 0.8 + (avg_male * 0.4)
    
    return {
        'streams': streams_mult,
        'sales': sales_mult,
        'fandom': fandom_mult,
        'gp': gp_mult,
        'viral': viral_mult
    }


def distribute_stat_gain_to_members(group_name: str, stat_type: str, amount: int):
    """Distribute a stat gain among members randomly (some get more, some less).
    
    With the SUM model: the amount is distributed across members so that
    group total increases by the full amount.
    """
    if group_name not in group_data:
        return
    
    group_entry = group_data[group_name]
    members = group_entry.get('members', [])
    if not members:
        if stat_type == 'popularity':
            group_entry['popularity'] = group_entry.get('popularity', 0) + amount
        return
    
    # Convert string members if needed, giving them a fair share of current group pop
    current_group_pop = group_entry.get('popularity', 100)
    num_members = len(members)
    base_member_pop = max(10, current_group_pop // num_members) if num_members > 0 else 50
    
    for i, m in enumerate(members):
        if isinstance(m, str):
            members[i] = ensure_member_schema({'name': m, 'group': group_name}, base_pop=base_member_pop)
    
    dict_members = [m for m in members if isinstance(m, dict)]
    if not dict_members:
        if stat_type == 'popularity':
            group_entry['popularity'] = group_entry.get('popularity', 0) + amount
        return
    
    num_members = len(dict_members)
    base_share = amount // num_members
    remainder = amount % num_members
    
    shares = []
    for i in range(num_members):
        variation = random.uniform(0.6, 1.4)
        share = int(base_share * variation)
        if i < remainder:
            share += 1
        shares.append(max(1, share) if amount > 0 else min(-1, share) if amount < 0 else 0)
    
    total_distributed = sum(shares)
    if total_distributed != amount and shares:
        diff = amount - total_distributed
        shares[0] += diff
    
    for i, m in enumerate(dict_members):
        if stat_type == 'popularity':
            m['popularity'] = max(0, m.get('popularity', 50) + shares[i])
    
    if stat_type == 'popularity':
        recalc_group_from_members(group_name)

def redistribute_popularity_to_members(group_name: str, group_entry: dict, member_names: list):
    """Redistribute group popularity evenly across new members and sync back."""
    current_pop = group_entry.get('popularity', 100)
    num_members = len(member_names)
    per_member = max(10, current_pop // num_members)
    remainder = current_pop - (per_member * num_members)
    
    members = []
    for i, name in enumerate(member_names):
        pop = per_member + (1 if i < remainder else 0)
        members.append({
            'name': name,
            'popularity': pop,
            'level': 1,
            'exp': 0,
            'exp_to_next': 100,
            'fan_ratios': {
                'teen': 0.5,
                'adult': 0.5,
                'female': 0.5,
                'male': 0.5
            },
            'fan_multipliers': {
                'teen': 1.0,
                'adult': 1.0,
                'female': 1.0,
                'male': 1.0
            },
            'skills': {
                'vocal': {'value': 30, 'cap': 100},
                'dance': {'value': 30, 'cap': 100},
                'stage': {'value': 30, 'cap': 100}
            },
            'history': [],
            'group': group_name,
            'image_url': None,
            'bio': ''
        })
    group_entry['members'] = members
    group_entry['has_members'] = True
    
    total_pop = sum(m['popularity'] for m in members)
    group_entry['popularity'] = total_pop
    group_popularity[group_name] = total_pop

class MemberView(ui.View):
    def __init__(self, group_name: str, member_data: dict, is_owner: bool, original_user_id: int):
        super().__init__(timeout=120)
        self.group_name = group_name
        self.member_data = member_data
        self.is_owner = is_owner
        self.original_user_id = original_user_id
        
        if not is_owner:
            for item in self.children:
                if hasattr(item, 'label') and item.label in ['Edit', 'Train']:
                    item.disabled = True

    @ui.button(label="Train", style=discord.ButtonStyle.green, emoji="💪")
    async def train_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("❌ This is not your member view!", ephemeral=True)
            return
        
        if not self.is_owner:
            await interaction.response.send_message("❌ You don't own this group!", ephemeral=True)
            return
        
        group_entry = group_data.get(self.group_name)
        if not group_entry:
            await interaction.response.send_message("❌ Group not found.", ephemeral=True)
            return
        
        company_name = group_entry.get('company')
        if not company_name or company_name not in company_funds:
            await interaction.response.send_message("❌ Company not found.", ephemeral=True)
            return
        
        member_level = self.member_data.get('level', 1)

        base_training_cost = get_training_cost(member_level)
        training_discount = get_company_building_bonus(company_name, 'training_discount') or 0.0

        # Clamp discount so it can’t go negative or hit 100%+
        training_discount = min(max(training_discount, 0.0), 0.9)

        training_cost = max(1, int(base_training_cost * (1 - training_discount)))
        if company_funds[company_name] < training_cost:
            await interaction.response.send_message(f"❌ Not enough funds! Training costs <:MonthlyPeso:1338642658436059239>{training_cost:,}.", ephemeral=True)
            return
        
        members = group_entry.get('members', [])
        member = None
        member_name_to_find = self.member_data.get('name', '')
        for i, m in enumerate(members):
            if isinstance(m, dict):
                if m.get('name') == member_name_to_find:
                    member = m
                    break
            elif isinstance(m, str):
                if m == member_name_to_find:
                    member = {
                        'name': m,
                        'popularity': 50,
                        'level': 1,
                        'exp': 0,
                        'exp_to_next': 100,
                        'fan_multipliers': {'teen': 1.0, 'adult': 1.0, 'female': 1.0, 'male': 1.0},
                        'skills': {'vocal': {'value': 30, 'cap': 100}, 'dance': {'value': 30, 'cap': 100}, 'stage': {'value': 30, 'cap': 100}},
                        'image_url': None,
                        'bio': ''
                    }
                    members[i] = member
                    break
        
        if not member:
            await interaction.response.send_message("❌ Member not found.", ephemeral=True)
            return
        
        company_funds[company_name] -= training_cost
        
        exp_gain = random.randint(15, 35)
        member['exp'] = member.get('exp', 0) + exp_gain
        
        old_level = member.get('level', 1)
        level_up = False
        level_up_bonuses = None
        while member['exp'] >= member.get('exp_to_next', 100):
            member['exp'] -= member['exp_to_next']
            member['level'] = member.get('level', 1) + 1
            member['exp_to_next'] = int(member['exp_to_next'] * 1.5)
            level_up = True
            
            skill_choice = random.choice(['vocal', 'dance', 'stage'])
            skill = member['skills'][skill_choice]
            if skill['value'] < skill['cap']:
                boost = random.randint(2, 5)  # Increased from 1-3
                skill['value'] = min(skill['cap'], skill['value'] + boost)
        
        # Apply meaningful level-up bonuses (popularity, GP, fanbase)
        if level_up:
            level_up_bonuses = apply_level_up_bonuses(self.group_name, member, old_level, member['level'])
        
        save_data()
        
        msg = f"💪 **{member['name']}** trained! +{exp_gain} EXP"
        if level_up and level_up_bonuses:
            msg += f"\n🎉 **LEVEL UP!** Now Level {member['level']}"
            msg += f"\n📈 Bonuses: +{level_up_bonuses['pop']} pop, +{level_up_bonuses['gp']} GP, +{level_up_bonuses['fanbase']} fanbase"
        msg += f"\n💰 Cost: <:MonthlyPeso:1338642658436059239>{training_cost:,}"
        next_cost = get_training_cost(member['level'])
        msg += f"\n📈 Next training: <:MonthlyPeso:1338642658436059239>{next_cost:,}"
        
        await interaction.response.send_message(msg, ephemeral=True)

    @ui.button(label="Edit", style=discord.ButtonStyle.blurple, emoji="✏️")
    async def edit_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.original_user_id:
            await interaction.response.send_message("❌ This is not your member view!", ephemeral=True)
            return
        
        if not self.is_owner:
            await interaction.response.send_message("❌ You don't own this group!", ephemeral=True)
            return
        
        await interaction.response.send_message(
            f"To edit **{self.member_data.get('name')}**, use:\n"
            f"`/editmember group:{self.group_name} member:{self.member_data.get('name')} [options]`\n\n"
            f"Options: `image_url`, `bio`",
            ephemeral=True
        )

@bot.tree.command(description="View a member's profile and stats.")
@app_commands.describe(member="Select a member to view")
@app_commands.autocomplete(member=member_autocomplete)
async def member(interaction: discord.Interaction, member: str):
    if '|' not in member:
        await interaction.response.send_message("❌ Invalid member format. Please use autocomplete.", ephemeral=True)
        return
    
    group_name, member_name = member.split('|', 1)
    group_name = group_name.upper()
    
    if group_name not in group_data:
        await interaction.response.send_message("❌ Group not found.", ephemeral=True)
        return
    
    group_entry = group_data[group_name]
    members = group_entry.get('members', [])
    
    member_data = None
    for m in members:
        if isinstance(m, dict):
            if m.get('name', '').lower() == member_name.lower():
                member_data = m
                break
        elif isinstance(m, str):
            if m.lower() == member_name.lower():
                member_data = {
                    'name': m,
                    'popularity': 50,
                    'level': 1,
                    'exp': 0,
                    'exp_to_next': 100,
                    'fan_multipliers': {'teen': 1.0, 'adult': 1.0, 'female': 1.0, 'male': 1.0},
                    'skills': {'vocal': {'value': 30, 'cap': 100}, 'dance': {'value': 30, 'cap': 100}, 'stage': {'value': 30, 'cap': 100}},
                    'image_url': None,
                    'bio': ''
                }
                break
    
    if not member_data:
        await interaction.response.send_message(f"❌ Member `{member_name}` not found in {group_name}. Use `/addmembers` to add members with full profiles.", ephemeral=True)
        return
    
    user_id = str(interaction.user.id)
    owned_companies = get_user_companies(user_id)
    is_owner = group_entry.get('company') in owned_companies
    
    embed = discord.Embed(
        title=f"{member_data.get('name')}",
        description=f"**{group_name}** • {group_entry.get('korean_name', '')}",
        color=discord.Color.pink()
    )
    
    if member_data.get('image_url'):
        embed.set_thumbnail(url=member_data['image_url'])
    
    if member_data.get('bio'):
        embed.add_field(name="Bio", value=member_data['bio'][:200], inline=False)
    
    embed.add_field(name="Popularity", value=f"**{member_data.get('popularity', 0):,}**", inline=True)
    embed.add_field(name="Level", value=f"**{member_data.get('level', 1)}** ({member_data.get('exp', 0)}/{member_data.get('exp_to_next', 100)} EXP)", inline=True)
    
    skills = member_data.get('skills', {})
    skill_text = (
        f"🎤 Vocal: **{skills.get('vocal', {}).get('value', 30)}** / {skills.get('vocal', {}).get('cap', 100)}\n"
        f"💃 Dance: **{skills.get('dance', {}).get('value', 30)}** / {skills.get('dance', {}).get('cap', 100)}\n"
        f"🎭 Stage: **{skills.get('stage', {}).get('value', 30)}** / {skills.get('stage', {}).get('cap', 100)}"
    )
    embed.add_field(name="Skills", value=skill_text, inline=False)
    
    fan_ratios = member_data.get('fan_ratios', {'teen': 0.5, 'adult': 0.5, 'female': 0.5, 'male': 0.5})
    if not fan_ratios:
        fan_ratios = {'teen': 0.5, 'adult': 0.5, 'female': 0.5, 'male': 0.5}
    
    group_fanbase = group_entry.get('fanbase', 100)
    teen_count = int(group_fanbase * fan_ratios.get('teen', 0.5))
    adult_count = int(group_fanbase * fan_ratios.get('adult', 0.5))
    female_count = int(group_fanbase * fan_ratios.get('female', 0.5))
    male_count = int(group_fanbase * fan_ratios.get('male', 0.5))
    
    fan_text = (
        f"**Age Distribution** ({fan_ratios.get('teen', 0.5)*100:.0f}% teen / {fan_ratios.get('adult', 0.5)*100:.0f}% adult)\n"
        f"👶 Teen: **{teen_count:,}** | 👤 Adult: **{adult_count:,}**\n\n"
        f"**Gender Distribution** ({fan_ratios.get('female', 0.5)*100:.0f}% F / {fan_ratios.get('male', 0.5)*100:.0f}% M)\n"
        f"♀️ Female: **{female_count:,}** | ♂️ Male: **{male_count:,}**"
    )
    embed.add_field(name=f"Fan Demographics (Group Fanbase: {group_fanbase:,})", value=fan_text, inline=False)
    
    embed.set_footer(text="Train to level up and improve skills!")
    
    view = MemberView(group_name, member_data, is_owner, interaction.user.id)
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(description="Add members to a group (comma-separated names).")
@app_commands.describe(
    group_name="The group to add members to",
    members="Comma-separated member names (max 20)"
)
@app_commands.autocomplete(group_name=user_group_autocomplete)
async def addmembers(interaction: discord.Interaction, group_name: str, members: str):
    user_id = str(interaction.user.id)
    group_name_upper = group_name.upper()
    
    if group_name_upper not in group_data:
        await interaction.response.send_message("❌ Group not found.", ephemeral=True)
        return
    
    group_entry = group_data[group_name_upper]
    owned_companies = get_user_companies(user_id)
    
    if group_entry.get('company') not in owned_companies:
        await interaction.response.send_message("❌ You don't own this group.", ephemeral=True)
        return
    
    if group_entry.get('members'):
        await interaction.response.send_message(
            f"❌ This group already has members. Use `/removemember` first if you want to reset.",
            ephemeral=True
        )
        return
    
    member_names = [name.strip() for name in members.split(',') if name.strip()]
    
    if len(member_names) == 0:
        await interaction.response.send_message("❌ Please provide at least one member name.", ephemeral=True)
        return
    
    if len(member_names) > 20:
        await interaction.response.send_message("❌ Maximum 20 members per group.", ephemeral=True)
        return
    
    redistribute_popularity_to_members(group_name_upper, group_entry, member_names)
    save_data()
    
    embed = discord.Embed(
        title=f"👥 Members Added to {group_name_upper}",
        description=f"Added **{len(member_names)}** members",
        color=discord.Color.green()
    )
    
    member_list = "\n".join([f"• {name}" for name in member_names])
    embed.add_field(name="Members", value=member_list[:1000], inline=False)
    embed.add_field(
        name="Popularity Distribution",
        value=f"Each member started with **{group_entry['members'][0]['popularity']:,}** popularity (redistributed from group total)",
        inline=False
    )
    embed.set_footer(text="Use /member to view individual profiles • Group popularity now derived from members")
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Edit a member's profile.")
@app_commands.describe(
    member="Select a member to edit",
    image_url="URL for member's profile image",
    bio="Member bio/description"
)
@app_commands.autocomplete(member=user_member_autocomplete)
async def editmember(interaction: discord.Interaction, member: str, image_url: str = None, bio: str = None):
    user_id = str(interaction.user.id)
    
    if '|' not in member:
        await interaction.response.send_message("❌ Invalid member format. Please use autocomplete.", ephemeral=True)
        return
    
    group_name, member_name = member.split('|', 1)
    group_name = group_name.upper()
    
    if group_name not in group_data:
        await interaction.response.send_message("❌ Group not found.", ephemeral=True)
        return
    
    group_entry = group_data[group_name]
    owned_companies = get_user_companies(user_id)
    
    if group_entry.get('company') not in owned_companies:
        await interaction.response.send_message("❌ You don't own this group.", ephemeral=True)
        return
    
    members = group_entry.get('members', [])
    member_data = None
    member_index = None
    for i, m in enumerate(members):
        if isinstance(m, dict):
            if m.get('name', '').lower() == member_name.lower():
                member_data = m
                member_index = i
                break
        elif isinstance(m, str):
            if m.lower() == member_name.lower():
                member_data = {
                    'name': m,
                    'popularity': 50,
                    'level': 1,
                    'exp': 0,
                    'exp_to_next': 100,
                    'fan_multipliers': {'teen': 1.0, 'adult': 1.0, 'female': 1.0, 'male': 1.0},
                    'skills': {'vocal': {'value': 30, 'cap': 100}, 'dance': {'value': 30, 'cap': 100}, 'stage': {'value': 30, 'cap': 100}},
                    'image_url': None,
                    'bio': ''
                }
                members[i] = member_data
                member_index = i
                break
    
    if not member_data:
        await interaction.response.send_message(f"❌ Member `{member_name}` not found. Use `/addmembers` to add members with full profiles.", ephemeral=True)
        return
    
    changes = []
    if image_url:
        member_data['image_url'] = image_url
        changes.append("profile image")
    if bio:
        member_data['bio'] = bio[:500]
        changes.append("bio")
    
    if not changes:
        await interaction.response.send_message("❌ Please provide at least one field to update.", ephemeral=True)
        return
    
    save_data()
    
    await interaction.response.send_message(
        f"✅ Updated **{member_data['name']}**'s {', '.join(changes)}!",
        ephemeral=True
    )


# === ADMIN COMMANDS ===
@bot.tree.command(description="Admin commands for game balancing (restricted)")
@app_commands.describe(
    category="Category: group, album, member, migrate",
    action="Action: set, add, transfer, redistribute_popularity",
    field="Field to modify (popularity, streams, sales, views, stock, weekly_streams, skill, fanbase)",
    target="Target name (group, album, or member|group format)",
    value="Value to set or add"
)
async def admin(interaction: discord.Interaction, category: str, action: str, field: str = None, target: str = None, value: str = None):
    if interaction.user.id != ADMIN_USER_ID:
        await interaction.response.send_message("❌ This command is restricted to administrators.", ephemeral=True)
        return
    
    category = category.lower()
    action = action.lower()
    admin_id = str(interaction.user.id)
    
    # GROUP COMMANDS
    if category == "group":
        if not target or target.upper() not in group_data:
            await interaction.response.send_message(f"❌ Group `{target}` not found.", ephemeral=True)
            return
        
        group_name = target.upper()
        group_entry = group_data[group_name]
        
        if field == "popularity":
            before = group_entry.get('popularity', 0)
            try:
                val = int(value)
            except:
                await interaction.response.send_message("❌ Invalid value.", ephemeral=True)
                return
            
            if action == "set":
                group_entry['popularity'] = val
                if group_name in group_popularity:
                    group_popularity[group_name] = val
            elif action == "add":
                group_entry['popularity'] = before + val
                if group_name in group_popularity:
                    group_popularity[group_name] = before + val
            else:
                await interaction.response.send_message("❌ Invalid action. Use 'set' or 'add'.", ephemeral=True)
                return
            
            after = group_entry['popularity']
            add_audit_log(admin_id, f"group_{action}_popularity", group_name, before, after)
            save_data()
            
            await interaction.response.send_message(
                f"✅ **{group_name}** popularity: {before:,} → {after:,}",
                ephemeral=True
            )
        
        elif field == "fanbase":
            before = group_entry.get('fanbase', 50)
            try:
                val = int(value)
            except:
                await interaction.response.send_message("❌ Invalid value.", ephemeral=True)
                return
            
            if action == "set":
                group_entry['fanbase'] = val
            elif action == "add":
                group_entry['fanbase'] = before + val
            
            after = group_entry['fanbase']
            add_audit_log(admin_id, f"group_{action}_fanbase", group_name, before, after)
            save_data()
            
            await interaction.response.send_message(
                f"✅ **{group_name}** fanbase: {before:,} → {after:,}",
                ephemeral=True
            )
        
        elif field == "gp":
            before = group_entry.get('gp', 30)
            try:
                val = int(value)
            except:
                await interaction.response.send_message("❌ Invalid value.", ephemeral=True)
                return
            
            if action == "set":
                group_entry['gp'] = val
            elif action == "add":
                group_entry['gp'] = before + val
            
            after = group_entry['gp']
            add_audit_log(admin_id, f"group_{action}_gp", group_name, before, after)
            save_data()
            
            await interaction.response.send_message(
                f"✅ **{group_name}** GP: {before:,} → {after:,}",
                ephemeral=True
            )
        else:
            await interaction.response.send_message("❌ Invalid field. Use 'popularity', 'fanbase', or 'gp'.", ephemeral=True)
    
    # ALBUM COMMANDS
    elif category == "album":
        if not target or target not in album_data:
            await interaction.response.send_message(f"❌ Album `{target}` not found.", ephemeral=True)
            return
        
        album_entry = album_data[target]
        field_map = {
            "streams": "streams",
            "sales": "sales",
            "views": "views",
            "mv_views": "views",
            "stock": "stock",
            "weekly_streams": "weekly_streams"
        }
        
        if field not in field_map:
            await interaction.response.send_message("❌ Invalid field. Use: streams, sales, views, mv_views, stock, weekly_streams.", ephemeral=True)
            return
        
        actual_field = field_map[field]
        
        if actual_field == "weekly_streams":
            current_week = get_current_week_key()
            album_entry.setdefault('weekly_streams', {})
            before = album_entry['weekly_streams'].get(current_week, 0)
            try:
                val = int(value)
            except:
                await interaction.response.send_message("❌ Invalid value.", ephemeral=True)
                return
            
            if action == "set":
                album_entry['weekly_streams'][current_week] = val
            elif action == "add":
                album_entry['weekly_streams'][current_week] = before + val
            
            after = album_entry['weekly_streams'][current_week]
            add_audit_log(admin_id, f"album_{action}_weekly_streams", target, before, after)
            save_data()
            
            await interaction.response.send_message(
                f"✅ **{target}** weekly streams ({current_week}): {before:,} → {after:,}",
                ephemeral=True
            )
        else:
            before = album_entry.get(actual_field, 0)
            try:
                val = int(value)
            except:
                await interaction.response.send_message("❌ Invalid value.", ephemeral=True)
                return
            
            if action == "set":
                album_entry[actual_field] = val
            elif action == "add":
                album_entry[actual_field] = before + val
            else:
                await interaction.response.send_message("❌ Invalid action. Use 'set' or 'add'.", ephemeral=True)
                return
            
            after = album_entry[actual_field]
            add_audit_log(admin_id, f"album_{action}_{actual_field}", target, before, after)
            save_data()
            
            await interaction.response.send_message(
                f"✅ **{target}** {actual_field}: {before:,} → {after:,}",
                ephemeral=True
            )
    
    # MEMBER COMMANDS
    elif category == "member":
        if action == "transfer":
            if not target or '|' not in target:
                await interaction.response.send_message("❌ Use format: member_name|old_group for target, new_group for value.", ephemeral=True)
                return
            
            member_name, old_group = target.split('|', 1)
            new_group = value.upper() if value else None
            old_group = old_group.upper()
            
            if old_group not in group_data:
                await interaction.response.send_message(f"❌ Source group `{old_group}` not found.", ephemeral=True)
                return
            if not new_group or new_group not in group_data:
                await interaction.response.send_message(f"❌ Target group `{new_group}` not found.", ephemeral=True)
                return
            
            old_members = group_data[old_group].get('members', [])
            member_to_transfer = None
            member_index = None
            
            for i, m in enumerate(old_members):
                if isinstance(m, dict):
                    if m.get('name', '').lower() == member_name.lower():
                        member_to_transfer = m
                        member_index = i
                        break
                elif isinstance(m, str):
                    if m.lower() == member_name.lower():
                        member_to_transfer = ensure_member_schema({'name': m})
                        old_members[i] = member_to_transfer
                        member_index = i
                        break
            
            if not member_to_transfer:
                await interaction.response.send_message(f"❌ Member `{member_name}` not found in {old_group}.", ephemeral=True)
                return
            
            old_members.pop(member_index)
            
            member_to_transfer.setdefault('history', [])
            member_to_transfer['history'].append({
                'group': old_group,
                'start_date': None,
                'end_date': datetime.now().isoformat(),
                'note': f'Transferred to {new_group}'
            })
            member_to_transfer['group'] = new_group
            
            group_data[new_group].setdefault('members', [])
            group_data[new_group]['members'].append(member_to_transfer)
            
            recalc_group_from_members(old_group)
            recalc_group_from_members(new_group)
            
            add_audit_log(admin_id, "member_transfer", f"{member_name}|{old_group}->{new_group}", old_group, new_group)
            save_data()
            
            await interaction.response.send_message(
                f"✅ **{member_to_transfer['name']}** transferred: {old_group} → {new_group}\n"
                f"Stats preserved. Group popularities recalculated.",
                ephemeral=True
            )
        
        elif field == "skill":
            if not target or '|' not in target:
                await interaction.response.send_message("❌ Use format: member_name|group for target.", ephemeral=True)
                return
            
            member_name, group_name = target.split('|', 1)
            group_name = group_name.upper()
            
            if group_name not in group_data:
                await interaction.response.send_message(f"❌ Group `{group_name}` not found.", ephemeral=True)
                return
            
            parts = value.split(':') if value else []
            if len(parts) != 2:
                await interaction.response.send_message("❌ Use format: skill_name:value (e.g., vocal:80).", ephemeral=True)
                return
            
            skill_name, skill_val = parts[0].lower(), int(parts[1])
            if skill_name not in ['vocal', 'dance', 'stage']:
                await interaction.response.send_message("❌ Invalid skill. Use: vocal, dance, stage.", ephemeral=True)
                return
            
            members = group_data[group_name].get('members', [])
            member = None
            for i, m in enumerate(members):
                if isinstance(m, dict) and m.get('name', '').lower() == member_name.lower():
                    member = m
                    break
                elif isinstance(m, str) and m.lower() == member_name.lower():
                    member = ensure_member_schema({'name': m})
                    members[i] = member
                    break
            
            if not member:
                await interaction.response.send_message(f"❌ Member `{member_name}` not found.", ephemeral=True)
                return
            
            member.setdefault('skills', {})
            member['skills'].setdefault(skill_name, {'value': 30, 'cap': 100})
            before = member['skills'][skill_name]['value']
            
            if action == "set":
                member['skills'][skill_name]['value'] = min(100, max(0, skill_val))
            elif action == "add":
                member['skills'][skill_name]['value'] = min(100, max(0, before + skill_val))
            
            after = member['skills'][skill_name]['value']
            add_audit_log(admin_id, f"member_{action}_skill_{skill_name}", target, before, after)
            save_data()
            
            await interaction.response.send_message(
                f"✅ **{member['name']}** {skill_name}: {before} → {after}",
                ephemeral=True
            )
        
        elif field == "popularity":
            if not target or '|' not in target:
                await interaction.response.send_message("❌ Use format: member_name|group for target.", ephemeral=True)
                return
            
            member_name, group_name = target.split('|', 1)
            group_name = group_name.upper()
            
            if group_name not in group_data:
                await interaction.response.send_message(f"❌ Group `{group_name}` not found.", ephemeral=True)
                return
            
            try:
                val = int(value)
            except:
                await interaction.response.send_message("❌ Invalid value.", ephemeral=True)
                return
            
            members = group_data[group_name].get('members', [])
            member = None
            for i, m in enumerate(members):
                if isinstance(m, dict) and m.get('name', '').lower() == member_name.lower():
                    member = m
                    break
                elif isinstance(m, str) and m.lower() == member_name.lower():
                    member = ensure_member_schema({'name': m})
                    members[i] = member
                    break
            
            if not member:
                await interaction.response.send_message(f"❌ Member `{member_name}` not found.", ephemeral=True)
                return
            
            before = member.get('popularity', 50)
            
            if action == "set":
                member['popularity'] = val
            elif action == "add":
                member['popularity'] = before + val
            
            after = member['popularity']
            recalc_group_from_members(group_name)
            add_audit_log(admin_id, f"member_{action}_popularity", target, before, after)
            save_data()
            
            await interaction.response.send_message(
                f"✅ **{member['name']}** popularity: {before:,} → {after:,}\n"
                f"Group popularity recalculated.",
                ephemeral=True
            )
        
        elif field == "fanbase":
            if not target or '|' not in target:
                await interaction.response.send_message("❌ Use format: member_name|group for target.", ephemeral=True)
                return
            
            member_name, group_name = target.split('|', 1)
            group_name = group_name.upper()
            
            if group_name not in group_data:
                await interaction.response.send_message(f"❌ Group `{group_name}` not found.", ephemeral=True)
                return
            
            parts = value.split(':') if value else []
            if len(parts) != 2:
                await interaction.response.send_message("❌ Use format: demo:value (e.g., teen:0.7 or female:0.6).", ephemeral=True)
                return
            
            demo_name, demo_val = parts[0].lower(), float(parts[1])
            demo_val = max(0.0, min(1.0, demo_val))
            
            members = group_data[group_name].get('members', [])
            member = None
            for i, m in enumerate(members):
                if isinstance(m, dict) and m.get('name', '').lower() == member_name.lower():
                    member = m
                    break
                elif isinstance(m, str) and m.lower() == member_name.lower():
                    member = ensure_member_schema({'name': m})
                    members[i] = member
                    break
            
            if not member:
                await interaction.response.send_message(f"❌ Member `{member_name}` not found.", ephemeral=True)
                return
            
            member.setdefault('fan_ratios', {'teen': 0.5, 'adult': 0.5, 'female': 0.5, 'male': 0.5})
            
            if demo_name == 'teen':
                before = member['fan_ratios'].get('teen', 0.5)
                member['fan_ratios']['teen'] = demo_val
                member['fan_ratios']['adult'] = 1.0 - demo_val
            elif demo_name == 'adult':
                before = member['fan_ratios'].get('adult', 0.5)
                member['fan_ratios']['adult'] = demo_val
                member['fan_ratios']['teen'] = 1.0 - demo_val
            elif demo_name == 'female':
                before = member['fan_ratios'].get('female', 0.5)
                member['fan_ratios']['female'] = demo_val
                member['fan_ratios']['male'] = 1.0 - demo_val
            elif demo_name == 'male':
                before = member['fan_ratios'].get('male', 0.5)
                member['fan_ratios']['male'] = demo_val
                member['fan_ratios']['female'] = 1.0 - demo_val
            else:
                await interaction.response.send_message("❌ Invalid demo. Use: teen, adult, female, male.", ephemeral=True)
                return
            
            after = member['fan_ratios'][demo_name]
            add_audit_log(admin_id, f"member_{action}_fanbase_{demo_name}", target, before, after)
            save_data()
            
            ratios = member['fan_ratios']
            await interaction.response.send_message(
                f"✅ **{member['name']}** fan demographics updated:\n"
                f"Teen: {ratios['teen']*100:.0f}% | Adult: {ratios['adult']*100:.0f}%\n"
                f"Female: {ratios['female']*100:.0f}% | Male: {ratios['male']*100:.0f}%",
                ephemeral=True
            )
        else:
            await interaction.response.send_message("❌ Invalid field. Use: skill, popularity, fanbase, or action 'transfer'.", ephemeral=True)
    
    # MIGRATE COMMANDS
    elif category == "migrate":
        if action == "redistribute_popularity":
            if not target or target.upper() not in group_data:
                await interaction.response.send_message(f"❌ Group `{target}` not found.", ephemeral=True)
                return
            
            group_name = target.upper()
            group_entry = group_data[group_name]
            members = group_entry.get('members', [])
            
            if not members:
                await interaction.response.send_message(f"❌ {group_name} has no members to redistribute to.", ephemeral=True)
                return
            
            before_pop = group_entry.get('popularity', 100)
            before_member_pops = []
            for m in members:
                if isinstance(m, dict):
                    before_member_pops.append(m.get('popularity', 50))
                else:
                    before_member_pops.append(50)
            
            redistribute_popularity(group_name)
            
            after_member_pops = []
            for m in group_data[group_name]['members']:
                if isinstance(m, dict):
                    after_member_pops.append(m.get('popularity', 50))
            
            add_audit_log(admin_id, "migrate_redistribute_popularity", group_name, before_member_pops, after_member_pops)
            
            member_list = []
            for m in group_data[group_name]['members']:
                if isinstance(m, dict):
                    member_list.append(f"• {m['name']}: {m.get('popularity', 0):,}")
            
            await interaction.response.send_message(
                f"✅ Redistributed **{before_pop:,}** popularity across {len(members)} members:\n" + 
                "\n".join(member_list[:10]),
                ephemeral=True
            )
        else:
            await interaction.response.send_message("❌ Invalid migrate action. Use 'redistribute_popularity'.", ephemeral=True)
    
    else:
        await interaction.response.send_message("❌ Invalid category. Use: group, album, member, migrate.", ephemeral=True)


@bot.tree.command(description="Admin command usage examples and documentation")
async def helpadmin(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_USER_ID:
        await interaction.response.send_message("❌ This command is restricted to administrators.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="Admin Command Guide",
        description="Use `/admin category action field target value`",
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name="GROUP Commands",
        value=(
            "**Set popularity:**\n"
            "`/admin group set popularity TWICE 500`\n\n"
            "**Add popularity:**\n"
            "`/admin group add popularity TWICE 100`\n\n"
            "**Set fanbase:**\n"
            "`/admin group set fanbase TWICE 80`\n\n"
            "**Set GP (general public):**\n"
            "`/admin group set gp TWICE 60`"
        ),
        inline=False
    )
    
    embed.add_field(
        name="ALBUM Commands",
        value=(
            "**Set streams:**\n"
            "`/admin album set streams Formula of Love 5000000`\n\n"
            "**Add sales:**\n"
            "`/admin album add sales Formula of Love 100000`\n\n"
            "**Set views:**\n"
            "`/admin album set views Formula of Love 2000000`\n\n"
            "**Set stock:**\n"
            "`/admin album set stock Formula of Love 500000`\n\n"
            "**Set weekly_streams:**\n"
            "`/admin album set weekly_streams Formula of Love 100000`"
        ),
        inline=False
    )
    
    embed.add_field(
        name="MEMBER Commands",
        value=(
            "**Set skill (vocal/dance/stage):**\n"
            "`/admin member set skill Nayeon|TWICE vocal:85`\n\n"
            "**Add popularity:**\n"
            "`/admin member add popularity Nayeon|TWICE 50`\n\n"
            "**Set fan demographics:**\n"
            "`/admin member set fanbase Nayeon|TWICE female:0.7`\n"
            "(Options: teen, adult, female, male - value 0.0-1.0)\n\n"
            "**Transfer member:**\n"
            "`/admin member transfer - Nayeon|TWICE MISAMO`"
        ),
        inline=False
    )
    
    embed.add_field(
        name="MIGRATE Commands",
        value=(
            "**Redistribute popularity to members:**\n"
            "`/admin migrate redistribute_popularity - TWICE`\n"
            "(Sets each member's popularity to the group average)"
        ),
        inline=False
    )
    
    embed.set_footer(text="All admin actions are logged for auditing.")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


# === MUSIC SHOW BOARDS ===
#
# Each show scores on the categories printed on its own template, so the numbers
# on the board always match the artwork.
#
# Categories with no gameplay system behind them yet use a flat placeholder
# share rather than an invented mechanic. They are kept as separate categories
# so each can be replaced individually later without touching the show
# definitions or the templates.

SHOW_SCORING_DAYS = 7 # Music shows score on the promotional week

# Categories the game cannot model yet. Each scores a flat share of its
# allocation so the row is visibly filled but obviously not earned.
SHOW_PLACEHOLDER_CATEGORIES = {"sns", "social", "broadcast", "onair",
                               "viewer_committee", "prevote", "fanvote"}
SHOW_PLACEHOLDER_SHARE = 0.5

SHOW_BOARDS = {
    "music_core": {
        "display": "Show! Music Core",
        "template": "music_core",
        "panels": 3,
        "total_points": 10000,
        "categories": {
            "digital": 0.50,
            "physical": 0.10,
            "sns": 0.10,
            "broadcast": 0.05,
            "viewer_committee": 0.10,
            "live_vote": 0.15,
        },
        # The board shows four rows; several categories share a row.
        "live_vote_category": "live_vote",
        "display_rows": {
            "score_sound": ["digital", "physical"],
            "score_video": ["sns", "broadcast"],
            "score_prevote": ["viewer_committee"],
            "score_livevote": ["live_vote"],
        },
    },
    "inkigayo": {
        "display": "Inkigayo",
        "template": "inkigayo",
        "panels": 3,
        "total_points": 10000,
        # Weights taken from the legend printed on the template itself, which
        # sums to exactly 100 and needs no normalisation.
        "categories": {
            "physical": 0.10,
            "sns": 0.20,
            "prevote": 0.05,
            "onair": 0.10,
            "live_vote": 0.05,
            "digital": 0.50,
        },
        "live_vote_category": "live_vote",
        "display_rows": {
            "score_physical": ["physical"],
            "score_sns": ["sns"],
            "score_prevote": ["prevote"],
            "score_onair": ["onair"],
            "score_livevote": ["live_vote"],
            "score_digital": ["digital"],
        },
    },
    "mcountdown": {
        "display": "M Countdown",
        "template": "mcountdown",
        "panels": 2, # Head-to-head: exactly two nominees
        "total_points": 10000,
        "categories": {
            "digital": 0.50,
            "physical": 0.20,
            "social": 0.10,
            "fanvote": 0.15,
            "broadcast": 0.05,
        },
        # M Countdown's global fan vote is where the live vote lands.
        "live_vote_category": "fanvote",
    },
}


def _sum_recent_days(daily_dict: dict, days: int = SHOW_SCORING_DAYS):
    """Total of a daily_streams / daily_sales style dict over the last N days."""
    if not isinstance(daily_dict, dict):
        return 0
    today = datetime.now(ARG_TZ).date()
    total = 0
    for offset in range(days):
        day = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        total += daily_dict.get(day, 0)
    return total


def get_show_album(group_name: str):
    """The album a group competes with: the promoted one, else its latest."""
    group_entry = group_data.get(group_name)
    if not group_entry:
        return None
    albums = [a for a in group_entry.get('albums', []) if a in album_data]
    if not albums:
        return None
    for album_name in albums:
        if album_data[album_name].get('is_active_promotion'):
            return album_name
    return max(albums, key=lambda a: album_data[a].get('release_date', ''))


def calculate_show_board(show_key: str, album_names: list, live_votes: dict = None):
    """Score nominees for one show, relative to the strongest in each category."""
    show = SHOW_BOARDS[show_key]
    live_votes = live_votes or {}

    contexts = []
    for album_name in album_names:
        album_entry = album_data.get(album_name, {})
        group_entry = group_data.get(album_entry.get('group'), {})
        contexts.append({
            'album': album_name,
            'group': album_entry.get('group', '?'),
            'digital': _sum_recent_days(album_entry.get('daily_streams', {})),
            'physical': _sum_recent_days(album_entry.get('daily_sales', {})) or album_entry.get('sales', 0),
            'live_vote': live_votes.get(album_name, 0),
        })

    live_category = show.get('live_vote_category')
    votes_were_cast = any(c['live_vote'] for c in contexts)

    results = []
    for index, ctx in enumerate(contexts):
        breakdown = {}
        for category, weight in show['categories'].items():
            allocation = show['total_points'] * weight

            # The live vote category is real whenever anyone actually voted,
            # even if it would otherwise be a placeholder for this show.
            if category == live_category and votes_were_cast:
                values = [c['live_vote'] for c in contexts]
                best = max(values)
                breakdown[category] = int(round(allocation * (values[index] / best))) if best else 0
                continue

            if category in SHOW_PLACEHOLDER_CATEGORIES:
                # No system behind this yet: flat share, not an invented mechanic.
                breakdown[category] = int(round(allocation * SHOW_PLACEHOLDER_SHARE))
                continue

            values = [c.get(category, 0) for c in contexts]
            best = max(values) if values else 0
            share = (values[index] / best) if best > 0 else 0
            breakdown[category] = int(round(allocation * share))

        results.append({
            'album': ctx['album'],
            'group': ctx['group'],
            'breakdown': breakdown,
            'total': sum(breakdown.values()),
        })

    return results


async def _fetch_show_art(url: str):
    """Best-effort download of era art. Returns None on any failure."""
    if not url:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status == 200:
                    return await response.read()
    except Exception as e:
        print(f"GRAPHICS: failed to fetch {url}: {e}")
    return None


def _local_era_file(group_name: str, album_name: str = None):
    """An era image file named after the album, or failing that the group."""
    normalise = lambda n: ''.join(c for c in n.lower() if c.isalnum())
    wanted = [normalise(n) for n in (album_name, group_name) if n]
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for target in wanted:
        for sub_dir in ('.', 'assets/era'):
            directory = os.path.join(base_dir, sub_dir)
            if not os.path.isdir(directory):
                continue
            for filename in sorted(os.listdir(directory)):
                stem, extension = os.path.splitext(filename)
                if extension.lower() in ('.png', '.jpg', '.jpeg', '.webp') and normalise(stem) == target:
                    return os.path.join(directory, filename)
    return None


async def get_era_art(group_name: str, album_name: str):
    """Era art for a nominee, falling back until something works.

    Older albums predate era images entirely, so this walks a chain rather than
    assuming one exists:
      1. era_image_url on the album      (set with /setera)
      2. a local file named after the album, then after the group
      3. the album cover                 (set with /setcover, or at release)
      4. the group's profile picture, then its banner
    If all of them are missing the slot is simply left empty and the template's
    own artwork shows through.
    """
    album_entry = album_data.get(album_name, {})
    group_entry = group_data.get(group_name, {})

    art = await _fetch_show_art(album_entry.get('era_image_url'))
    if art:
        return art

    local = _local_era_file(group_name, album_name)
    if local:
        try:
            with open(local, 'rb') as f:
                return f.read()
        except OSError as e:
            print(f"GRAPHICS: could not read {local}: {e}")

    for fallback in (album_entry.get('image_url'),
                     group_entry.get('profile_picture'),
                     group_entry.get('banner_url')):
        art = await _fetch_show_art(fallback)
        if art:
            return art

    print(f"GRAPHICS: no era art available for {group_name} - {album_name}")
    return None


class LiveVoteView(ui.View):
    """Button-based live vote, one vote per person, tallied in real time.

    Discord's native polls take a duration in whole hours, which cannot express
    a short live vote, so the show runs its own. That also allows a live tally
    and an immediate close when the timer runs out.
    """

    def __init__(self, nominees: list, duration_seconds: int):
        super().__init__(timeout=duration_seconds)
        self.nominees = nominees  # [{'group':..., 'album':...}]
        self.votes = {}           # user_id -> album_name
        self.message = None

        for index, nominee in enumerate(nominees):
            button = ui.Button(
                label=nominee['group'][:80],
                style=discord.ButtonStyle.blurple,
                custom_id=f"livevote_{index}",
            )
            button.callback = self._make_callback(nominee['album'])
            self.add_item(button)

    def _make_callback(self, album_name):
        async def callback(interaction: discord.Interaction):
            user_id = str(interaction.user.id)
            previous = self.votes.get(user_id)
            self.votes[user_id] = album_name

            if previous == album_name:
                note = f"Your vote for **{album_name}** already counted."
            elif previous:
                note = f"Vote changed to **{album_name}**."
            else:
                note = f"Voted for **{album_name}**!"

            await interaction.response.send_message(note, ephemeral=True)
            if self.message:
                try:
                    await self.message.edit(embed=self.build_embed())
                except discord.HTTPException:
                    pass
        return callback

    def tally(self):
        counts = {n['album']: 0 for n in self.nominees}
        for album_name in self.votes.values():
            if album_name in counts:
                counts[album_name] += 1
        return counts

    def build_embed(self, closed: bool = False):
        counts = self.tally()
        cast = sum(counts.values())
        lines = []
        for nominee in self.nominees:
            count = counts[nominee['album']]
            filled = int(round(12 * count / cast)) if cast else 0
            bar = "█" * filled + "░" * (12 - filled)
            lines.append(f"**{nominee['group']}** — {nominee['album']}\n`{bar}` {count} vote(s)")

        embed = discord.Embed(
            title="🗳️ Live Vote — CLOSED" if closed else "🗳️ Live Vote is OPEN",
            description="\n".join(lines),
            color=discord.Color.greyple() if closed else discord.Color.gold(),
        )
        embed.set_footer(
            text="Voting has ended." if closed
            else "One vote each — press a button below. You can change your vote."
        )
        return embed

    async def close(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(embed=self.build_embed(closed=True), view=self)
            except discord.HTTPException:
                pass


SHOW_BOARD_CHOICES = [
    app_commands.Choice(name=cfg['display'], value=key)
    for key, cfg in SHOW_BOARDS.items()
]


@bot.tree.command(description="Run a music show: announce nominees, hold a live vote, crown a winner.")
@app_commands.describe(
    show="Which music show to run.",
    group1="First nominee.",
    group2="Second nominee.",
    group3="Third nominee (not used by M Countdown).",
    vote_minutes="How long live voting stays open (1-14, default 5). Use 0 to skip.",
)
@app_commands.choices(show=SHOW_BOARD_CHOICES)
@app_commands.autocomplete(group1=group_autocomplete, group2=group_autocomplete, group3=group_autocomplete)
async def musicshow(
    interaction: discord.Interaction,
    show: app_commands.Choice[str],
    group1: str,
    group2: str,
    group3: str = None,
    vote_minutes: int = 5,
):
    show_key = show.value
    show_config = SHOW_BOARDS[show_key]
    max_panels = show_config['panels']

    requested = [g for g in (group1, group2, group3) if g]

    # M Countdown is a head-to-head board with exactly two slots. Rejecting the
    # third nominee outright beats silently dropping someone's group, which
    # would look like a bug from the player's side.
    if len(requested) > max_panels:
        await interaction.response.send_message(
            f"❌ {show_config['display']} is a {max_panels}-nominee show. "
            f"You entered {len(requested)}; please pick {max_panels}.",
            ephemeral=True,
        )
        return

    if len(requested) != len(set(g.upper() for g in requested)):
        await interaction.response.send_message("❌ A group cannot compete against itself.", ephemeral=True)
        return

    nominees = []
    for raw_name in requested:
        group_name = raw_name.upper()
        if group_name not in group_data:
            await interaction.response.send_message(f"❌ Group `{raw_name}` not found.", ephemeral=True)
            return
        if group_data[group_name].get('is_disbanded'):
            await interaction.response.send_message(f"❌ {group_name} is disbanded.", ephemeral=True)
            return
        album_name = get_show_album(group_name)
        if not album_name:
            await interaction.response.send_message(f"❌ {group_name} has no album to compete with.", ephemeral=True)
            return
        nominees.append({'group': group_name, 'album': album_name})

    # --- Pre-show announcement ---
    await interaction.response.send_message(
        f"**{show_config['display']}** is starting!\n"
        + "\n".join(f"• {n['group']} - {n['album']}" for n in nominees)
    )

    # --- Live vote ---
    live_votes = {}
    vote_minutes = max(0, min(14, vote_minutes))  # Interaction tokens expire at 15
    if vote_minutes and show_config.get('live_vote_category'):
        view = LiveVoteView(nominees, vote_minutes * 60)
        view.message = await interaction.followup.send(embed=view.build_embed(), view=view, wait=True)
        await view.wait()   # returns when the timer runs out
        await view.close()
        live_votes = view.tally()

    results = calculate_show_board(show_key, [n['album'] for n in nominees], live_votes)
    winner = max(results, key=lambda r: r['total'])
    winner_index = results.index(winner)

    # --- Board image ---
    file = None
    try:
        if show_key == 'mcountdown':
            left, right = results[0], results[1]
            left_art = await get_era_art(left['group'], left['album'])
            right_art = await get_era_art(right['group'], right['album'])
            buffer = await asyncio.to_thread(
                graphics.render_mcountdown,
                {'group': left['group'], 'song': left['album'],
                 'scores': left['breakdown'], 'total': left['total']},
                {'group': right['group'], 'song': right['album'],
                 'scores': right['breakdown'], 'total': right['total']},
                left_art, right_art,
            )
        else:
            panel_data, images = [], {}
            for index, result in enumerate(results):
                group_entry = group_data.get(result['group'], {})
                korean_name = group_entry.get('korean_name', '')
                panel = {
                    'group_name': f"{result['group']} ({korean_name})" if korean_name else result['group'],
                    'song_title': result['album'],
                    'score_total': f"{result['total']:,}",
                }
                for row_name, categories in show_config.get('display_rows', {}).items():
                    panel[row_name] = f"{sum(result['breakdown'].get(c, 0) for c in categories):,}"
                panel_data.append(panel)

                art = await get_era_art(result['group'], result['album'])
                if art:
                    images[(index, 'era_image')] = art

            buffer = await asyncio.to_thread(
                graphics.render_template,
                show_config['template'],
                panel_data,
                images,
                {(winner_index, 'score_total'): graphics.WINNER_GOLD},
            )
        file = discord.File(buffer, filename=f"{show_key}_results.png")
    except Exception as e:
        print(f"GRAPHICS: {show_key} render failed:")
        traceback.print_exception(type(e), e, e.__traceback__)

    # --- Result: the win line only, no scoreboard dump ---
    message = (
        f"🏆 {winner['group']} wins on {show_config['display']} with {winner['album']}!\n"
        f"Use `/addwin` to record the win."
    )

    if file:
        await interaction.followup.send(message, file=file)
    else:
        await interaction.followup.send(message)


IMAGE_CONTENT_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")


def _resolve_image_input(upload, url, label):
    """Turn an upload or URL into a storable link.

    Discord attachments are already hosted, so the CDN link is stored rather
    than the bytes. Returns (url, error_message).
    """
    if upload and url:
        return None, f"Give either an upload or a URL for the {label}, not both."
    if not upload and not url:
        return None, f"Provide an image for the {label}: upload a file or pass a URL."

    if upload:
        if upload.content_type not in IMAGE_CONTENT_TYPES:
            return None, f"`{upload.filename}` is not a supported image (PNG, JPEG, WEBP or GIF)."
        if upload.size > 8 * 1024 * 1024:
            return None, f"`{upload.filename}` is larger than 8MB."
        return upload.url, None

    if not url.lower().startswith(("http://", "https://")):
        return None, "That does not look like a valid image URL."
    return url, None


@bot.tree.command(description="Set the era image for an album (upload from your gallery, or paste a URL).")
@app_commands.describe(
    album_name="The album this era belongs to.",
    image="Upload an image from your device or gallery.",
    image_url="Alternatively, paste a direct image URL.",
)
@app_commands.autocomplete(album_name=user_album_autocomplete)
async def setera(
    interaction: discord.Interaction,
    album_name: str,
    image: discord.Attachment = None,
    image_url: str = None,
):
    if album_name not in album_data:
        await interaction.response.send_message(f"❌ Album `{album_name}` not found.", ephemeral=True)
        return

    album_entry = album_data[album_name]
    group_name = album_entry.get('group')

    if not is_user_group_owner(str(interaction.user.id), group_name):
        await interaction.response.send_message(
            f"❌ You do not manage the company that owns '{group_name}'.", ephemeral=True)
        return

    resolved_url, error = _resolve_image_input(image, image_url, "era image")
    if error:
        await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        return

    album_entry['era_image_url'] = resolved_url
    save_data()

    embed = discord.Embed(
        title=f"🎬 Era image set for '{album_name}'",
        description=f"**{group_name}** • used on music show boards.",
        color=discord.Color.teal(),
    )
    embed.set_image(url=resolved_url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Set an album's cover image (upload from your gallery, or paste a URL).")
@app_commands.describe(
    album_name="The album to update.",
    image="Upload an image from your device or gallery.",
    image_url="Alternatively, paste a direct image URL.",
)
@app_commands.autocomplete(album_name=user_album_autocomplete)
async def setcover(
    interaction: discord.Interaction,
    album_name: str,
    image: discord.Attachment = None,
    image_url: str = None,
):
    if album_name not in album_data:
        await interaction.response.send_message(f"❌ Album `{album_name}` not found.", ephemeral=True)
        return

    album_entry = album_data[album_name]
    group_name = album_entry.get('group')

    if not is_user_group_owner(str(interaction.user.id), group_name):
        await interaction.response.send_message(
            f"❌ You do not manage the company that owns '{group_name}'.", ephemeral=True)
        return

    resolved_url, error = _resolve_image_input(image, image_url, "album cover")
    if error:
        await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        return

    album_entry['image_url'] = resolved_url
    save_data()

    embed = discord.Embed(
        title=f"💿 Cover updated for '{album_name}'",
        description=f"**{group_name}**",
        color=discord.Color.teal(),
    )
    embed.set_thumbnail(url=resolved_url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="ADMIN: overlay layout guides on a show template for tuning.")
@app_commands.describe(show="Which template to check.")
@app_commands.choices(show=SHOW_BOARD_CHOICES)
async def showlayout(interaction: discord.Interaction, show: app_commands.Choice[str]):
    """Draws every slot as a labelled box so coordinates can be checked by eye."""
    await interaction.response.defer(ephemeral=True)
    template = SHOW_BOARDS[show.value]['template']
    try:
        buffer = await asyncio.to_thread(graphics.render_calibration, template)
    except Exception as e:
        await interaction.followup.send(f"❌ Could not render the guide: {e}", ephemeral=True)
        return
    await interaction.followup.send(
        "Red boxes are image slots, magenta crosshairs are text anchors.\n"
        "Tell me which are off and by how much and I'll adjust `graphics.py`.",
        file=discord.File(buffer, filename=f"{template}_layout.png"),
        ephemeral=True,
    )


# === RUN ===
bot.run(TOKEN)
