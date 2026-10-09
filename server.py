import io

import os

import re

import json

from pathlib import Path

from datetime import datetime, timezone, timedelta

from urllib.parse import quote, urlencode

from urllib.request import Request, urlopen

from urllib.error import URLError, HTTPError

import base64
import secrets

from dotenv import load_dotenv

from flask import Flask, request, Response, jsonify, redirect, session

from openai import OpenAI



# ============================================================

# PATHS / ENVIRONMENT

# ============================================================

BASE_DIR = Path(__file__).resolve().parent

ENV_FILE = BASE_DIR / ".env"

load_dotenv(

    dotenv_path=ENV_FILE,

    override=True

)

API_KEY = os.getenv("OPENAI_API_KEY")

if not API_KEY:

    raise RuntimeError(

        f"OPENAI_API_KEY was not found.\n"

        f"Checked: {ENV_FILE}\n\n"

        f"Your .env file must contain:\n"

        f"OPENAI_API_KEY=your_api_key_here"

    )



# ============================================================

# OPENAI

# ============================================================

client = OpenAI(

    api_key=API_KEY

)



# ============================================================

# CONFIGURATION

# ============================================================

PORT = 5000

STT_MODEL = "gpt-transcribe"

CHAT_MODEL = "gpt-4.1-mini"

TTS_MODEL = "gpt-4o-mini-tts"

TTS_VOICE = "marin"

TTS_SPEED = 0.95

MAX_AUDIO_BYTES = 150_000

CONVERSATION_FILE = (

    BASE_DIR / "conversation_id.txt"

)

# ------------------------------------------------------------

# TIMEZONE

# ------------------------------------------------------------

TIMEZONE = "Europe/Istanbul"



# ------------------------------------------------------------

# WEATHER

# ------------------------------------------------------------

DEFAULT_WEATHER_CITY = ""

DEFAULT_WEATHER_COUNTRY = "Turkey"

GEOCODING_URL = (

    "https://geocoding-api.open-meteo.com/v1/search"

)

WEATHER_URL = (

    "https://api.open-meteo.com/v1/forecast"

)



# ============================================================

# TIMEZONE

# ============================================================

try:

    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:

        TURKEY_TZ = ZoneInfo(

            TIMEZONE

        )

    except ZoneInfoNotFoundError:

        print(

            "[TIME] Europe/Istanbul timezone database "

            "not found."

        )

        print(

            "[TIME] Falling back to UTC+03:00."

        )

        TURKEY_TZ = timezone(

            timedelta(hours=3)

        )

except Exception:

    print(

        "[TIME] zoneinfo unavailable."

    )

    print(

        "[TIME] Falling back to UTC+03:00."

    )

    TURKEY_TZ = timezone(

        timedelta(hours=3)

    )



# ============================================================

# FLASK

# ============================================================

app = Flask(__name__)



# ============================================================

# TIME FUNCTIONS

# ============================================================

def get_time_of_day(hour: int) -> str:

    if 5 <= hour < 12:

        return "Morning"

    if 12 <= hour < 17:

        return "Afternoon"

    if 17 <= hour < 21:

        return "Evening"

    return "Night"



def get_current_time_context() -> dict:

    now = datetime.now(

        TURKEY_TZ

    )

    return {

        "date": now.strftime(

            "%Y-%m-%d"

        ),

        "time": now.strftime(

            "%H:%M:%S"

        ),

        "day": now.strftime(

            "%A"

        ),

        "time_of_day":

            get_time_of_day(

                now.hour

            ),

        "timezone":

            TIMEZONE

    }



def build_time_context() -> str:

    t = get_current_time_context()

    return (

        f"Current local date: {t['date']}\n"

        f"Current local time: {t['time']}\n"

        f"Current day: {t['day']}\n"

        f"Time of day: {t['time_of_day']}\n"

        f"Timezone: {t['timezone']}"

    )



# ============================================================

# WEATHER

# ============================================================

def http_get_json(

    url: str,

    timeout: int = 10

) -> dict:

    request = Request(

        url,

        headers={

            "User-Agent":

                "ESP32-C3-Voice-Assistant/1.0"

        }

    )

    try:

        with urlopen(

            request,

            timeout=timeout

        ) as response:

            data = response.read()

        return json.loads(

            data.decode("utf-8")

        )

    except HTTPError as e:

        raise RuntimeError(

            f"HTTP error {e.code} from weather service"

        )

    except URLError as e:

        raise RuntimeError(

            f"Weather service connection failed: {e.reason}"

        )

    except json.JSONDecodeError:

        raise RuntimeError(

            "Weather service returned invalid JSON"

        )



def geocode_city(

    city: str

) -> dict | None:

    """

    Convert a city name into coordinates.

    We first search the requested city in Turkey.

    If nothing is found, we search globally.

    """

    city = city.strip()

    if not city:

        return None

    # --------------------------------------------------------

    # First: Turkey

    # --------------------------------------------------------

    turkey_query = quote(

        city

    )

    turkey_url = (

        f"{GEOCODING_URL}"

        f"?name={turkey_query}"

        f"&count=5"

        f"&language=en"

        f"&countryCode=TR"

        f"&format=json"

    )

    try:

        data = http_get_json(

            turkey_url

        )

        results = data.get(

            "results",

            []

        )

        if results:

            return results[0]

    except Exception as e:

        print(

            f"[WEATHER] Turkey geocoding failed: {e}"

        )

    # --------------------------------------------------------

    # Second: global search

    # --------------------------------------------------------

    global_url = (

        f"{GEOCODING_URL}"

        f"?name={quote(city)}"

        f"&count=5"

        f"&language=en"

        f"&format=json"

    )

    try:

        data = http_get_json(

            global_url

        )

        results = data.get(

            "results",

            []

        )

        if results:

            return results[0]

    except Exception as e:

        print(

            f"[WEATHER] Global geocoding failed: {e}"

        )

    return None



def weather_description(

    weather_code: int,

    is_day: int | None = None

) -> str:

    """

    Convert WMO weather codes into speech-friendly text.

    """

    descriptions = {

        0: "clear sky",

        1: "mainly clear",

        2: "partly cloudy",

        3: "overcast",

        45: "foggy",

        48: "foggy",

        51: "light drizzle",

        53: "moderate drizzle",

        55: "heavy drizzle",

        56: "light freezing drizzle",

        57: "heavy freezing drizzle",

        61: "light rain",

        63: "moderate rain",

        65: "heavy rain",

        66: "light freezing rain",

        67: "heavy freezing rain",

        71: "light snow",

        73: "moderate snow",

        75: "heavy snow",

        77: "snow grains",

        80: "light rain showers",

        81: "moderate rain showers",

        82: "heavy rain showers",

        85: "light snow showers",

        86: "heavy snow showers",

        95: "thunderstorms",

        96: "thunderstorms with light hail",

        99: "thunderstorms with heavy hail",

    }

    return descriptions.get(

        weather_code,

        "unknown conditions"

    )



def get_weather(

    city: str | None = None

) -> dict:

    """

    Get current weather for a city.

    If no city is supplied, İzmir is used.

    """

    requested_city = (

        city.strip()

        if city

        else DEFAULT_WEATHER_CITY

    )

    print(

        f"[WEATHER] Looking up: "

        f"{requested_city}"

    )

    location = geocode_city(

        requested_city

    )

    if not location:

        raise RuntimeError(

            f"Could not find the city: "

            f"{requested_city}"

        )

    latitude = location.get(

        "latitude"

    )

    longitude = location.get(

        "longitude"

    )

    location_name = location.get(

        "name",

        requested_city

    )

    country = location.get(

        "country",

        ""

    )

    location_timezone = location.get(

        "timezone",

        TIMEZONE

    )

    # --------------------------------------------------------

    # Current weather

    # --------------------------------------------------------

    current_variables = (

        "temperature_2m,"

        "relative_humidity_2m,"

        "apparent_temperature,"

        "precipitation,"

        "rain,"

        "showers,"

        "snowfall,"

        "weather_code,"

        "cloud_cover,"

        "wind_speed_10m,"

        "wind_direction_10m,"

        "wind_gusts_10m,"

        "is_day"

    )

    weather_url = (

        f"{WEATHER_URL}"

        f"?latitude={latitude}"

        f"&longitude={longitude}"

        f"&current={current_variables}"

        f"&temperature_unit=celsius"

        f"&wind_speed_unit=kmh"

        f"&precipitation_unit=mm"

        f"&timezone=auto"

    )

    print(

        f"[WEATHER] Coordinates: "

        f"{latitude}, {longitude}"

    )

    data = http_get_json(

        weather_url

    )

    current = data.get(

        "current",

        {}

    )

    if not current:

        raise RuntimeError(

            "Weather response did not contain "

            "current conditions."

        )

    weather_code = int(

        current.get(

            "weather_code",

            0

        )

    )

    result = {

        "city":

            location_name,

        "country":

            country,

        "latitude":

            latitude,

        "longitude":

            longitude,

        "timezone":

            location_timezone,

        "time":

            current.get(

                "time"

            ),

        "temperature_c":

            current.get(

                "temperature_2m"

            ),

        "feels_like_c":

            current.get(

                "apparent_temperature"

            ),

        "humidity_percent":

            current.get(

                "relative_humidity_2m"

            ),

        "precipitation_mm":

            current.get(

                "precipitation"

            ),

        "rain_mm":

            current.get(

                "rain"

            ),

        "showers_mm":

            current.get(

                "showers"

            ),

        "snowfall_cm":

            current.get(

                "snowfall"

            ),

        "weather_code":

            weather_code,

        "condition":

            weather_description(

                weather_code,

                current.get(

                    "is_day"

                )

            ),

        "cloud_cover_percent":

            current.get(

                "cloud_cover"

            ),

        "wind_speed_kmh":

            current.get(

                "wind_speed_10m"

            ),

        "wind_direction":

            current.get(

                "wind_direction_10m"

            ),

        "wind_gusts_kmh":

            current.get(

                "wind_gusts_10m"

            ),

        "is_day":

            current.get(

                "is_day"

            ),

    }

    print(

        f"[WEATHER] "

        f"{location_name}: "

        f"{result['temperature_c']}°C, "

        f"{result['condition']}"

    )

    return result



def build_weather_context(

    weather: dict

) -> str:

    return f"""

Weather for {weather["city"]}, {weather["country"]}:

Temperature: {weather["temperature_c"]} °C

Feels like: {weather["feels_like_c"]} °C

Condition: {weather["condition"]}

Humidity: {weather["humidity_percent"]} %

Precipitation: {weather["precipitation_mm"]} mm

Rain: {weather["rain_mm"]} mm

Snowfall: {weather["snowfall_cm"]} cm

Cloud cover: {weather["cloud_cover_percent"]} %

Wind speed: {weather["wind_speed_kmh"]} km/h

Wind gusts: {weather["wind_gusts_kmh"]} km/h

Wind direction: {weather["wind_direction"]} degrees

Local weather time: {weather["time"]}

Timezone: {weather["timezone"]}

""".strip()



# ============================================================

# WEATHER CITY DETECTION

# ============================================================

def extract_weather_city(

    user_text: str

) -> str | None:

    """

    Try to detect a city mentioned in a weather question.

    Examples:

    "What's the weather in Istanbul?"

    "How hot is Ankara?"

    "Will it rain in Antalya?"

    If no city is found, return None so İzmir is used.

    """

    text = user_text.strip()

    patterns = [

        r"\bweather\s+(?:in|for|at)\s+([A-Za-zÀ-ÿÇĞİÖŞÜçğıöşü .'-]+)",

        r"\btemperature\s+(?:in|for|at)\s+([A-Za-zÀ-ÿÇĞİÖŞÜçğıöşü .'-]+)",

        r"\b(?:hot|cold|rain|raining|snow|snowing)\s+(?:in|at)\s+([A-Za-zÀ-ÿÇĞİÖŞÜçğıöşü .'-]+)",

        r"\b(?:weather|temperature)\s+of\s+([A-Za-zÀ-ÿÇĞİÖŞÜçğıöşü .'-]+)",

        r"\b(?:hows|how's|how is)\s+the\s+weather\s+(?:in|at)\s+([A-Za-zÀ-ÿÇĞİÖŞÜçğıöşü .'-]+)",

        r"\b(?:hava|sıcaklık)\s+(?:İzmir'de|istanbul'da|ankara'da|antalya'da)\b",

    ]

    for pattern in patterns:

        match = re.search(

            pattern,

            text,

            flags=re.IGNORECASE

        )

        if match:

            if match.lastindex:

                city = (

                    match.group(1)

                    .strip()

                    .strip("?.!,")

                )

                # Avoid returning obvious trailing words.

                city = re.split(

                    r"\b(?:today|now|right now|today**\\?**)\b",

                    city,

                    flags=re.IGNORECASE

                )[0].strip()

                if city:

                    return city

    # --------------------------------------------------------

    # Common Turkish phrasing

    # --------------------------------------------------------

    turkish_patterns = [

        r"\b([A-Za-zÀ-ÿÇĞİÖŞÜçğıöşü .'-]+)'(?:de|da)\s+(?:hava|sıcaklık)",

        r"\b([A-Za-zÀ-ÿÇĞİÖŞÜçğıöşü .'-]+)'(?:ta|te)\s+(?:hava|sıcaklık)",

        r"\b([A-Za-zÀ-ÿÇĞİÖŞÜçğıöşü .'-]+)\s+(?:hava nasıl|hava durumu nasıl)",

    ]

    for pattern in turkish_patterns:

        match = re.search(

            pattern,

            text,

            flags=re.IGNORECASE

        )

        if match:

            city = (

                match.group(1)

                .strip()

                .strip("?.!,")

            )

            if city:

                return city

    return None



# ============================================================

# WEATHER INTENT

# ============================================================

def is_weather_request(

    user_text: str

) -> bool:

    text = user_text.lower()

    weather_words = [

        # English

        "weather",

        "temperature",

        "forecast",

        "rain",

        "raining",

        "snow",

        "snowing",

        "hot",

        "cold",

        "humid",

        "humidity",

        "wind",

        "windy",

        "cloudy",

        "sunny",

        # Turkish

        "hava",

        "sıcaklık",

        "yağmur",

        "yağıyor",

        "kar",

        "karlı",

        "sıcak",

        "soğuk",

        "nem",

        "rüzgar",

        "rüzgarlı",

        "bulutlu",

        "güneşli",

    ]

    return any(

        word in text

        for word in weather_words

    )



# ============================================================
# SPOTIFY
# ============================================================

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
SPOTIFY_REDIRECT_URI = os.getenv(
    "SPOTIFY_REDIRECT_URI",
    "http://127.0.0.1:5000/spotify/callback"
).strip()
SPOTIFY_DEVICE_NAME = os.getenv("SPOTIFY_DEVICE_NAME", "").strip()
SPOTIFY_TOKEN_FILE = BASE_DIR / "spotify_token.json"
SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SPOTIFY_SCOPES = (
    "user-read-playback-state "
    "user-modify-playback-state"
)

SPOTIFY_STATE_FILE = BASE_DIR / "spotify_oauth_state.txt"


def spotify_is_configured() -> bool:
    return bool(
        SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET
    )


def spotify_save_token(token: dict) -> None:
    SPOTIFY_TOKEN_FILE.write_text(
        json.dumps(token, indent=2),
        encoding="utf-8"
    )


def spotify_load_token() -> dict | None:
    if not SPOTIFY_TOKEN_FILE.exists():
        return None

    try:
        token = json.loads(
            SPOTIFY_TOKEN_FILE.read_text(
                encoding="utf-8"
            )
        )
        if isinstance(token, dict) and token.get("access_token"):
            return token
    except Exception as e:
        print(
            f"[SPOTIFY] Could not read token file: {e}"
        )

    return None


def spotify_token_request(form_data: dict) -> dict:
    body = urlencode(form_data).encode("utf-8")
    credentials = (
        f"{SPOTIFY_CLIENT_ID}:"
        f"{SPOTIFY_CLIENT_SECRET}"
    )
    encoded = base64.b64encode(
        credentials.encode("utf-8")
    ).decode("ascii")

    req = Request(
        SPOTIFY_TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {encoded}",
            "Content-Type":
                "application/x-www-form-urlencoded"
        },
        method="POST"
    )

    try:
        with urlopen(req, timeout=15) as response:
            payload = response.read()
        return json.loads(
            payload.decode("utf-8")
        )
    except HTTPError as e:
        error_body = e.read().decode(
            "utf-8",
            errors="replace"
        )
        raise RuntimeError(
            f"Spotify token error {e.code}: {error_body}"
        )
    except URLError as e:
        raise RuntimeError(
            f"Spotify token connection failed: {e.reason}"
        )


def spotify_refresh_access_token() -> str | None:
    token = spotify_load_token()
    if not token:
        return None

    refresh_token = token.get("refresh_token")
    if not refresh_token:
        return None

    refreshed = spotify_token_request({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    })

    access_token = refreshed.get("access_token")
    if not access_token:
        return None

    token["access_token"] = access_token
    token["expires_at"] = int(
        datetime.now(timezone.utc).timestamp()
    ) + int(refreshed.get("expires_in", 3600))

    if refreshed.get("refresh_token"):
        token["refresh_token"] = refreshed["refresh_token"]

    spotify_save_token(token)
    print("[SPOTIFY] Access token refreshed.")
    return access_token


def spotify_get_access_token() -> str | None:
    token = spotify_load_token()
    if not token:
        return None

    expires_at = int(token.get("expires_at", 0))
    now = int(
        datetime.now(timezone.utc).timestamp()
    )

    if expires_at > now + 60:
        return token.get("access_token")

    return spotify_refresh_access_token()


def spotify_api_request(
    method: str,
    path: str,
    body: dict | None = None,
    retry_after_refresh: bool = True
) -> dict:
    access_token = spotify_get_access_token()
    if not access_token:
        raise RuntimeError(
            "Spotify is not authorized. Open /spotify/login first."
        )

    data = None
    headers = {
        "Authorization":
            f"Bearer {access_token}",
        "Accept": "application/json"
    }

    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = Request(
        f"{SPOTIFY_API_BASE}{path}",
        data=data,
        headers=headers,
        method=method
    )

    try:
        with urlopen(req, timeout=15) as response:
            payload = response.read()
            if not payload:
                return {}
            return json.loads(
                payload.decode("utf-8")
            )
    except HTTPError as e:
        if e.code == 401 and retry_after_refresh:
            refreshed = spotify_refresh_access_token()
            if refreshed:
                return spotify_api_request(
                    method,
                    path,
                    body,
                    retry_after_refresh=False
                )

        error_body = e.read().decode(
            "utf-8",
            errors="replace"
        )
        raise RuntimeError(
            f"Spotify API error {e.code}: {error_body}"
        )
    except URLError as e:
        raise RuntimeError(
            f"Spotify connection failed: {e.reason}"
        )


def build_spotify_auth_url() -> str:

    state = secrets.token_urlsafe(24)

    SPOTIFY_STATE_FILE.write_text(
        state,
        encoding="utf-8"
    )

    params = {
        "response_type": "code",
        "client_id": SPOTIFY_CLIENT_ID,
        "scope": SPOTIFY_SCOPES,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "state": state
    }

    print(
        f"[SPOTIFY] OAuth state created: {state}"
    )

    return (
        f"{SPOTIFY_AUTH_URL}?"
        f"{urlencode(params)}"
    )


def spotify_search_track(query: str) -> dict | None:
    query = query.strip()
    if not query:
        return None

    params = urlencode({
        "q": query,
        "type": "track",
        "limit": "1",
        "market": "TR"
    })

    data = spotify_api_request(
        "GET",
        f"/search?{params}"
    )

    tracks = data.get(
        "tracks",
        {}
    ).get(
        "items",
        []
    )

    if not tracks:
        return None

    track = tracks[0]
    artists = [
        artist.get("name", "")
        for artist in track.get("artists", [])
        if artist.get("name")
    ]

    return {
        "name": track.get("name", "Unknown song"),
        "artists": artists,
        "uri": track.get("uri", "")
    }


def spotify_get_devices() -> list[dict]:
    data = spotify_api_request(
        "GET",
        "/me/player/devices"
    )
    return data.get("devices", [])


def spotify_select_iphone(
    devices: list[dict]
) -> dict | None:
    candidates = [
        d for d in devices
        if not d.get("is_restricted", False)
    ]

    if SPOTIFY_DEVICE_NAME:
        preferred = SPOTIFY_DEVICE_NAME.lower()
        exact = [
            d for d in candidates
            if d.get("name", "").lower() == preferred
        ]
        if exact:
            return exact[0]

        contains = [
            d for d in candidates
            if preferred in d.get("name", "").lower()
        ]
        if contains:
            return contains[0]

    iphones = [
        d for d in candidates
        if "iphone" in d.get("name", "").lower()
        or "ipad" in d.get("name", "").lower()
    ]

    active_iphone = [
        d for d in iphones
        if d.get("is_active")
    ]
    if active_iphone:
        return active_iphone[0]

    return iphones[0] if iphones else None


def spotify_transfer_to_device(device_id: str) -> None:
    spotify_api_request(
        "PUT",
        "/me/player",
        {
            "device_ids": [device_id],
            "play": False
        }
    )


def detect_spotify_command(user_text: str) -> dict | None:
    text = user_text.strip()
    lower = text.lower().strip()

    pause_phrases = {
        "pause",
        "stop the music",
        "pause the music",
        "müziği durdur",
        "müziği kapat",
        "müzik dur",
        "durdur"
    }
    if lower in pause_phrases:
        return {"action": "pause"}

    next_phrases = {
        "next", "next song", "skip", "skip song",
        "sonraki", "sonraki şarkı", "sıradaki", "sıradaki şarkı"
    }
    if lower in next_phrases:
        return {"action": "next"}

    previous_phrases = {
        "previous", "previous song", "go back", "back",
        "önceki", "önceki şarkı", "bir önceki"
    }
    if lower in previous_phrases:
        return {"action": "previous"}

    resume_phrases = {
        "resume", "resume music", "continue", "continue music",
        "devam et", "müziği devam ettir"
    }
    if lower in resume_phrases:
        return {"action": "resume"}

    play_match = re.match(
        r"^(?:play|çal|spotify'da çal|spotifyda çal)\s+(.+)$",
        text,
        flags=re.IGNORECASE
    )
    if play_match:
        query = play_match.group(1).strip()
        query = re.sub(
            r"\s+(?:on|in)\s+spotify\s*$",
            "",
            query,
            flags=re.IGNORECASE
        ).strip()
        query = re.sub(
            r"^spotify\s+",
            "",
            query,
            flags=re.IGNORECASE
        ).strip()
        if query:
            return {"action": "play", "query": query}

    return None


def handle_spotify_command(command: dict) -> str:
    if not spotify_is_configured():
        return (
            "Spotify is not configured on the laptop server yet."
        )

    if not spotify_get_access_token():
        return (
            "Spotify is not connected yet. "
            "Open the Spotify login page on the laptop first."
        )

    devices = spotify_get_devices()
    device = spotify_select_iphone(devices)

    if not device:
        return (
            "I can't see your iPhone as an available Spotify device. "
            "Open Spotify on the iPhone and try again."
        )

    device_id = device.get("id")
    device_name = device.get("name", "your iPhone")
    action = command.get("action")

    if action == "play":
        track = spotify_search_track(
            command.get("query", "")
        )
        if not track or not track.get("uri"):
            return "I couldn't find that song on Spotify."

        if not device.get("is_active"):
            spotify_transfer_to_device(device_id)

        spotify_api_request(
            "PUT",
            "/me/player/play?" + urlencode({
                "device_id": device_id
            }),
            {"uris": [track["uri"]]}
        )

        artist_text = ", ".join(
            track.get("artists", [])
        ) or "the artist"

        return (
            f"Playing {track['name']} by {artist_text} "
            f"on {device_name}."
        )

    if action == "pause":
        spotify_api_request(
            "PUT",
            "/me/player/pause?" + urlencode({
                "device_id": device_id
            })
        )
        return "Spotify playback is paused."

    if action == "resume":
        spotify_api_request(
            "PUT",
            "/me/player/play?" + urlencode({
                "device_id": device_id
            })
        )
        return "Spotify playback resumed."

    if action == "next":
        spotify_api_request(
            "POST",
            "/me/player/next?" + urlencode({
                "device_id": device_id
            })
        )
        return "Skipped to the next song."

    if action == "previous":
        spotify_api_request(
            "POST",
            "/me/player/previous?" + urlencode({
                "device_id": device_id
            })
        )
        return "Went back to the previous song."

    return "I couldn't understand the Spotify command."


# ============================================================

# CONVERSATION MEMORY

# ============================================================

def get_conversation_id():

    if CONVERSATION_FILE.exists():

        conversation_id = (

            CONVERSATION_FILE

            .read_text(

                encoding="utf-8"

            )

            .strip()

        )

        if conversation_id:

            print(

                f"[MEMORY] Using conversation: "

                f"{conversation_id}"

            )

            return conversation_id

    print(

        "[MEMORY] Creating new conversation..."

    )

    conversation = client.conversations.create(

        metadata={

            "device": "esp32-c3"

        }

    )

    conversation_id = conversation.id

    CONVERSATION_FILE.write_text(

        conversation_id,

        encoding="utf-8"

    )

    print(

        f"[MEMORY] New conversation: "

        f"{conversation_id}"

    )

    return conversation_id



conversation_id = get_conversation_id()



# ============================================================

# HEALTH

# ============================================================

@app.get("/health")

def health():

    try:

        time_info = (

            get_current_time_context()

        )

        return jsonify({

            "status": "ok",

            "conversation_id":

                conversation_id,

            "default_weather_city":

                DEFAULT_WEATHER_CITY,

            "time":

                time_info

        })

    except Exception as e:

        print(

            f"[HEALTH ERROR] {e}"

        )

        return jsonify({

            "status": "error",

            "error": str(e)

        }), 500



# ============================================================
# SPOTIFY LOGIN
# ============================================================
@app.get("/spotify/login")
def spotify_login():
    if not spotify_is_configured():
        return jsonify({
            "status": "error",
            "error": (
                "Set SPOTIFY_CLIENT_ID and "
                "SPOTIFY_CLIENT_SECRET in .env"
            )
        }), 500

    return redirect(
        build_spotify_auth_url()
    )


# ============================================================
# SPOTIFY CALLBACK
# ============================================================
@app.get("/spotify/callback")
def spotify_callback():

    error = request.args.get("error")

    if error:
        return (
            f"Spotify authorization failed: {error}",
            400
        )

    returned_state = request.args.get(
        "state",
        ""
    )

    if not SPOTIFY_STATE_FILE.exists():
        print(
            "[SPOTIFY] No saved OAuth state found."
        )

        return (
            "Spotify authorization state is missing. "
            "Start the Spotify login again.",
            400
        )

    saved_state = (
        SPOTIFY_STATE_FILE
        .read_text(
            encoding="utf-8"
        )
        .strip()
    )

    print(
        f"[SPOTIFY] Saved state:    {saved_state}"
    )

    print(
        f"[SPOTIFY] Returned state: {returned_state}"
    )

    if not saved_state or returned_state != saved_state:

        print(
            "[SPOTIFY] OAuth state mismatch."
        )

        return (
            "Spotify authorization state mismatch. "
            "Start the Spotify login again.",
            400
        )

    # State was valid, so delete it.
    try:
        SPOTIFY_STATE_FILE.unlink()
    except FileNotFoundError:
        pass

    code = request.args.get(
        "code",
        ""
    )

    if not code:
        return (
            "Spotify did not return an authorization code.",
            400
        )

    try:

        print(
            "[SPOTIFY] Exchanging authorization code..."
        )

        token = spotify_token_request({
            "grant_type":
                "authorization_code",

            "code":
                code,

            "redirect_uri":
                SPOTIFY_REDIRECT_URI
        })

        token["expires_at"] = (
            int(
                datetime.now(
                    timezone.utc
                ).timestamp()
            )
            +
            int(
                token.get(
                    "expires_in",
                    3600
                )
            )
        )

        spotify_save_token(
            token
        )

        print(
            "[SPOTIFY] Authorization successful."
        )

        return (
            "Spotify connected successfully. "
            "You can close this page and use the ESP32."
        )

    except Exception as e:

        print(
            "[SPOTIFY CALLBACK ERROR]"
        )

        print(e)

        return (
            f"Spotify connection failed: {e}",
            500
        )



# ============================================================
# SPOTIFY STATUS
# ============================================================
@app.get("/spotify/status")
def spotify_status():
    try:
        configured = spotify_is_configured()
        authorized = spotify_get_access_token() is not None
        devices = []
        selected = None

        if authorized:
            devices = spotify_get_devices()
            selected = spotify_select_iphone(devices)

        return jsonify({
            "configured": configured,
            "authorized": authorized,
            "device_count": len(devices),
            "selected_device": (
                selected.get("name")
                if selected else None
            )
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


# ============================================================
# SPOTIFY DEVICES
# ============================================================
@app.get("/spotify/devices")
def spotify_devices_endpoint():
    try:
        devices = spotify_get_devices()
        return jsonify({
            "status": "ok",
            "devices": devices,
            "selected_device": spotify_select_iphone(devices)
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


# ============================================================

# WEATHER TEST ENDPOINT

# ============================================================

@app.get("/weather")

def weather_endpoint():

    city = request.args.get(

        "city",

        default=DEFAULT_WEATHER_CITY,

        type=str

    )

    print(

        f"[WEATHER API] Request: {city}"

    )

    try:

        weather = get_weather(

            city

        )

        return jsonify({

            "status": "ok",

            "weather": weather

        })

    except Exception as e:

        print(

            f"[WEATHER API ERROR] {e}"

        )

        return jsonify({

            "status": "error",

            "error": str(e)

        }), 500



# ============================================================

# AI

# ============================================================

def get_ai_answer(

    user_text: str,

    weather: dict | None = None

) -> str:

    current_time = (

        build_time_context()

    )

    weather_context = ""

    if weather:

        weather_context = (

            "\n\n"

            + build_weather_context(

                weather

            )

        )

    instructions = f"""

You are the voice assistant inside a small ESP32-C3 device.

Answer naturally and conversationally.

Keep spoken answers reasonably concise.

CURRENT TIME

-------------

{current_time}

Use the current time information when the user asks about:

- the current time

- today's date

- the day of the week

- morning, afternoon, evening, or night

- relative time questions

Do NOT guess the current time or date.

The local timezone is Europe/Istanbul.

WEATHER

-------

{weather_context if weather_context else "No weather data was requested for this turn."}

If weather data is provided above, treat it as the authoritative

current weather information.

Do not invent weather information.

If the user asks about weather and weather data was not provided,

say that you could not retrieve the weather right now.

The default weather location is Izmir, Turkey.

If the user explicitly mentions another city, weather information

for that city takes priority.

You are currently in the basic assistant stage.

Weather is available.

Room humidity, Spotify, timers, and other device features are

not available yet.

Do not invent data for capabilities you do not have.

Do not mention APIs, servers, models, tokens, or implementation

details to the user.

Respond in the language the user is speaking.

"""

    response = client.responses.create(

        model=CHAT_MODEL,

        conversation=conversation_id,

        instructions=instructions,

        input=user_text

    )

    answer = (

        response.output_text or ""

    ).strip()

    if not answer:

        answer = (

            "Sorry, I couldn't come up with an answer."

        )

    return answer



# ============================================================

# VOICE ENDPOINT

# ============================================================

@app.post("/voice")

def voice():

    # --------------------------------------------------------

    # RECEIVE WAV

    # --------------------------------------------------------

    audio_data = request.get_data(

        cache=False,

        as_text=False

    )

    print()

    print("========================================")

    print("[VOICE] New request")

    print(

        f"[VOICE] Received: "

        f"{len(audio_data)} bytes"

    )

    print("========================================")

    if not audio_data:

        return jsonify({

            "error":

                "No audio received"

        }), 400

    if len(audio_data) > MAX_AUDIO_BYTES:

        return jsonify({

            "error":

                "Audio too large"

        }), 413

    if not audio_data.startswith(

        b"RIFF"

    ):

        return jsonify({

            "error":

                "Expected WAV audio"

        }), 400

    # --------------------------------------------------------

    # TIME

    # --------------------------------------------------------

    try:

        time_info = (

            get_current_time_context()

        )

        print(

            f"[TIME] "

            f"{time_info['date']} "

            f"{time_info['time']} "

            f"{time_info['day']} "

            f"{time_info['time_of_day']}"

        )

    except Exception as e:

        print(

            f"[TIME ERROR] {e}"

        )

    # --------------------------------------------------------

    # STT

    # --------------------------------------------------------

    print(

        "[STT] Transcribing..."

    )

    try:

        audio_file = (

            "voice.wav",

            io.BytesIO(audio_data),

            "audio/wav"

        )

        transcription = (

            client.audio.transcriptions.create(

                model=STT_MODEL,

                file=audio_file

            )

        )

        user_text = (

            transcription.text or ""

        ).strip()

    except Exception as e:

        print(

            "[STT ERROR]"

        )

        print(e)

        return jsonify({

            "error":

                "STT failed"

        }), 500

    print(

        f"[STT] User: {user_text}"

    )

    if not user_text:

        return jsonify({

            "error":

                "No speech detected"

        }), 400

    # --------------------------------------------------------

    # --------------------------------------------------------
    # SPOTIFY
    # --------------------------------------------------------
    spotify_command = detect_spotify_command(
        user_text
    )

    if spotify_command:
        print(
            f"[SPOTIFY] Command: {spotify_command}"
        )

        try:
            answer = handle_spotify_command(
                spotify_command
            )
        except Exception as e:
            print(
                "[SPOTIFY ERROR]"
            )
            print(e)
            answer = (
                "I couldn't complete the Spotify command "
                "right now."
            )

        print(
            f"[SPOTIFY] Assistant: {answer}"
        )

        # Direct Spotify commands bypass the normal AI response.
        print(
            "[TTS] Generating speech..."
        )
        try:
            speech = client.audio.speech.create(
                model=TTS_MODEL,
                voice=TTS_VOICE,
                input=answer,
                instructions=(
                    "Speak clearly, naturally, and conversationally. "
                    "Use a relaxed speaking pace."
                ),
                response_format="pcm",
                speed=TTS_SPEED
            )
            pcm_audio = speech.read()
        except Exception as e:
            print(
                "[TTS ERROR]"
            )
            print(e)
            return jsonify({
                "error":
                    "TTS failed"
            }), 500

        return Response(
            pcm_audio,
            status=200,
            mimetype="application/octet-stream",
            headers={
                "Content-Length":
                    str(len(pcm_audio)),
                "X-Audio-Sample-Rate":
                    "24000",
                "X-Audio-Bits":
                    "16",
                "X-Audio-Channels":
                    "1",
                "Connection":
                    "close"
            }
        )

    # WEATHER

    # --------------------------------------------------------

    weather = None

    if is_weather_request(

        user_text

    ):

        print(

            "[WEATHER] Weather request detected."

        )

        requested_city = (

            extract_weather_city(

                user_text

            )

        )

        if requested_city:

            print(

                f"[WEATHER] "

                f"City detected: "

                f"{requested_city}"

            )

        else:

            requested_city = (

                DEFAULT_WEATHER_CITY

            )

            print(

                f"[WEATHER] "

                f"No city detected. "

                f"Using default: "

                f"{DEFAULT_WEATHER_CITY}"

            )

        try:

            weather = get_weather(

                requested_city

            )

        except Exception as e:

            print(

                "[WEATHER ERROR]"

            )

            print(e)

            # Do not immediately fail the voice request.

            # Let the AI tell the user weather could not

            # be retrieved.

            weather = None

    # --------------------------------------------------------

    # AI

    # --------------------------------------------------------

    print(

        "[AI] Thinking..."

    )

    try:

        answer = get_ai_answer(

            user_text,

            weather

        )

    except Exception as e:

        print(

            "[AI ERROR]"

        )

        print(e)

        return jsonify({

            "error":

                "AI failed"

        }), 500

    print(

        f"[AI] Assistant: {answer}"

    )

    # --------------------------------------------------------

    # TTS

    # --------------------------------------------------------

    print(

        "[TTS] Generating speech..."

    )

    try:

        speech = client.audio.speech.create(

            model=TTS_MODEL,

            voice=TTS_VOICE,

            input=answer,

            instructions=(

                "Speak clearly, naturally, and conversationally. "

                "Use a relaxed speaking pace."

            ),

            response_format="pcm",

            speed=TTS_SPEED

        )

        pcm_audio = speech.read()

    except Exception as e:

        print(

            "[TTS ERROR]"

        )

        print(e)

        return jsonify({

            "error":

                "TTS failed"

        }), 500

    print(

        f"[TTS] Generated: "

        f"{len(pcm_audio)} bytes"

    )

    # --------------------------------------------------------

    # RETURN PCM

    #

    # 24 kHz

    # 16-bit

    # mono

    # --------------------------------------------------------

    return Response(

        pcm_audio,

        status=200,

        mimetype="application/octet-stream",

        headers={

            "Content-Length":

                str(len(pcm_audio)),

            "X-Audio-Sample-Rate":

                "24000",

            "X-Audio-Bits":

                "16",

            "X-Audio-Channels":

                "1",

            "Connection":

                "close"

        }

    )



# ============================================================

# START SERVER

# ============================================================

if __name__ == "__main__":

    print()

    print("========================================")

    print("ESP32-C3 AI SERVER")

    print("========================================")

    print(

        f"Timezone: {TIMEZONE}"

    )

    print(

        f"Default weather: "

        f"{DEFAULT_WEATHER_CITY}, "

        f"{DEFAULT_WEATHER_COUNTRY}"

    )

    print(

        f"Port: {PORT}"

    )

    print()

    print(

        "Waiting for ESP32..."

    )

    print()

    app.run(

        host="0.0.0.0",

        port=PORT,

        debug=False,

        threaded=True

    )