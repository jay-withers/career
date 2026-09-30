"""Straight-line distance from a named place, for the "how far from home"
job preference.

No geocoding API: a listing's location is a short free-text string ("Bristol,
UK", "Remote (UK)", "London, UK (Hybrid)"), and this is a personal tool
searching mostly UK listings, so a small hardcoded gazetteer of UK town/city
coordinates is enough to resolve most of them without a new network
dependency or API key — the same trade-off `matching.py` already makes with
plain token overlap instead of a real NLP/geocoding service. A place this
table doesn't know is simply not checked (see `matching.score`): "can't
tell" must not read the same as "too far".

The exception is `OUTSIDE_UK`: countries and major cities that are
certainly nowhere near a UK home, with no coordinates needed. Without
these a Berlin or Zürich listing (common from any board that isn't
UK-only) reads as "unknown place" and sails past any distance limit. It's
the big names only — a small foreign town (Wuppertal, say) still reads as
unknown and isn't excluded.

Coordinates are approximate (town-centre, a handful of decimal places) —
plenty precise for a 0-100 relevance score, not survey-grade.
"""

from __future__ import annotations

import re
import unicodedata
from math import asin, cos, radians, sin, sqrt

# (latitude, longitude). Weighted towards the South/South-East, since that's
# where this profile's `home_location` (Fareham) sits, plus the UK's other
# major cities for everything further afield.
UK_PLACES: dict[str, tuple[float, float]] = {
    "fareham": (50.8523, -1.1780),
    "portsmouth": (50.8198, -1.0880),
    "southampton": (50.9097, -1.4044),
    "gosport": (50.7936, -1.1265),
    "havant": (50.8514, -0.9814),
    "waterlooville": (50.8788, -1.0294),
    "winchester": (51.0632, -1.3080),
    "eastleigh": (50.9690, -1.3510),
    "romsey": (50.9896, -1.4956),
    "chichester": (50.8365, -0.7792),
    "petersfield": (51.0038, -0.9367),
    "basingstoke": (51.2670, -1.0873),
    "guildford": (51.2362, -0.5704),
    "woking": (51.3168, -0.5600),
    "aldershot": (51.2478, -0.7639),
    "bournemouth": (50.7192, -1.8808),
    "poole": (50.7150, -1.9872),
    "salisbury": (51.0688, -1.7943),
    "brighton": (50.8225, -0.1372),
    "reading": (51.4543, -0.9781),
    "oxford": (51.7520, -1.2577),
    "slough": (51.5105, -0.5950),
    "london": (51.5074, -0.1278),
    "cambridge": (52.2053, 0.1218),
    "milton keynes": (52.0406, -0.7594),
    "bristol": (51.4545, -2.5879),
    "cardiff": (51.4816, -3.1791),
    "swansea": (51.6214, -3.9436),
    "exeter": (50.7184, -3.5339),
    "plymouth": (50.3755, -4.1427),
    "birmingham": (52.4862, -1.8904),
    "coventry": (52.4068, -1.5197),
    "leicester": (52.6369, -1.1398),
    "nottingham": (52.9548, -1.1581),
    "derby": (52.9225, -1.4746),
    "sheffield": (53.3811, -1.4701),
    "leeds": (53.8008, -1.5491),
    "manchester": (53.4808, -2.2426),
    "liverpool": (53.4084, -2.9916),
    "york": (53.9600, -1.0873),
    "newcastle": (54.9783, -1.6178),
    "glasgow": (55.8642, -4.2518),
    "edinburgh": (55.9533, -3.1883),
    "aberdeen": (57.1497, -2.0943),
    "belfast": (54.5973, -5.9301),
    "norwich": (52.6309, 1.2974),
    "ipswich": (52.0567, 1.1482),
}

# Accent-free and lower-case, since location text is matched after
# `_normalise` strips accents ("Zürich" -> "zurich", "München" -> "munchen").
# Names shared with a UK place are left out on purpose — Boston, Perth,
# Richmond, Washington — as is plain "Ireland", which would also match
# "Northern Ireland".
OUTSIDE_UK: frozenset[str] = frozenset(
    {
        # Countries, in English and as the listings themselves write them.
        "germany", "deutschland", "switzerland", "schweiz", "suisse",
        "austria", "osterreich", "france", "netherlands", "belgium", "spain",
        "espana", "portugal", "italy", "italia", "poland", "czechia",
        "czech republic", "denmark", "sweden", "norway", "finland",
        "republic of ireland", "luxembourg", "united states", "usa",
        "canada", "mexico", "brazil", "australia", "new zealand", "india",
        "singapore", "japan", "south korea", "china", "united arab emirates",
        "israel", "south africa",
        # Major cities those countries' listings name without the country.
        "berlin", "munich", "munchen", "muenchen", "hamburg", "frankfurt",
        "cologne", "koln", "dusseldorf", "stuttgart", "leipzig", "dresden",
        "hannover", "nuremberg", "nurnberg", "zurich", "geneva", "geneve",
        "basel", "bern", "lausanne", "vienna", "wien", "paris", "lyon",
        "lille", "marseille", "toulouse", "nantes", "amsterdam", "rotterdam",
        "the hague", "brussels", "madrid", "barcelona", "lisbon", "milan",
        "rome", "warsaw", "krakow", "prague", "copenhagen", "stockholm",
        "oslo", "helsinki", "dublin", "cork", "new york", "new york city",
        "san francisco", "los angeles", "seattle", "chicago", "austin",
        "toronto", "vancouver", "montreal", "sydney", "melbourne",
        "brisbane", "auckland", "bangalore", "bengaluru", "mumbai", "delhi",
        "tokyo", "seoul", "dubai", "tel aviv",
    }
)  # fmt: skip

# Longest names first, so "milton keynes" matches before a hypothetical
# shorter place whose name it contains, and UK and non-UK names share one
# pattern so "New York" is consumed whole rather than matching "york".
# Word-bounded so e.g. "york" doesn't match inside "Yorkshire" — though a
# same-named place outside the UK ("Cambridge, MA") is a false match this
# table has no way to catch.
_PLACE_NAMES = sorted(UK_PLACES.keys() | OUTSIDE_UK, key=len, reverse=True)
_PLACE_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(name) for name in _PLACE_NAMES) + r")\b", re.IGNORECASE
)

EARTH_RADIUS_MILES = 3958.8


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = (radians(v) for v in a)
    lat2, lon2 = (radians(v) for v in b)
    d_lat = lat2 - lat1
    d_lon = lon2 - lon1
    h = sin(d_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * asin(sqrt(h))


def _normalise(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _places_in(text: str) -> list[str]:
    return [m.group(0) for m in _PLACE_PATTERN.finditer(_normalise(text))]


def find_known_place(text: str) -> str | None:
    """The first known UK place name found in `text`, or None."""
    return next((p for p in _places_in(text) if p in UK_PLACES), None)


def find_place_outside_uk(text: str) -> str | None:
    """A non-UK country or city named in `text`, unless it also names a UK place.

    A multi-site listing ("Berlin; London") is treated as UK, since the
    London office may be the one within reach.
    """
    places = _places_in(text)
    if any(p in UK_PLACES for p in places):
        return None
    return next((p for p in places if p in OUTSIDE_UK), None)


def distance_miles(home: str, location_text: str) -> float | None:
    """Distance from `home` to whatever place is named in `location_text`.

    None when either end can't be resolved against `UK_PLACES` — an unknown
    home town, or a listing location (often "Remote (UK)", or a place this
    gazetteer just doesn't have) that names no place this table knows.
    """
    home_place = find_known_place(home)
    listing_place = find_known_place(location_text)
    if home_place is None or listing_place is None:
        return None
    return haversine_miles(UK_PLACES[home_place], UK_PLACES[listing_place])
