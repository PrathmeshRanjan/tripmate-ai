"""
Flight Information Utility 
==============================================
This module integrates with the AviationStack API to retrieve live flight schedules and status.
It provides:
  1. Natural language query parsing (extracting country, city, or IATA airport codes).
  2. Geographic location resolution to 3-letter IATA airport codes using `pycountry` and `airportsdata`.
  3. Predefined alias dictionaries for prominent travel destinations and airport hubs.
  4. Core `search_flights` utility function.
"""

import os
import re
from typing import Optional, Tuple, List, Dict, Any
import airportsdata
import pycountry
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Base URL for the AviationStack Real-Time Flight API
BASE_URL = "https://api.aviationstack.com/v1/flights"

# Load the global IATA airport database (keyed by 3-letter IATA code, e.g. "JFK", "NRT")
AIRPORTS: Dict[str, Dict[str, Any]] = airportsdata.load("IATA")


# ==============================================================================
# 1. GEOGRAPHIC & AIRPORT MAPPINGS
# ==============================================================================

# Common country aliases / colloquial names mapped to ISO 3166-1 alpha-2 codes
COUNTRY_ALIASES: Dict[str, str] = {
    "usa": "US",
    "u.s.a": "US",
    "u.s.": "US",
    "america": "US",
    "united states": "US",
    "united states of america": "US",
    "uk": "GB",
    "u.k.": "GB",
    "britain": "GB",
    "great britain": "GB",
    "england": "GB",
    "uae": "AE",
    "u.a.e.": "AE",
    "dubai": "AE",
    "south korea": "KR",
    "korea": "KR",
    "russia": "RU",
    "vietnam": "VN",
    "bangladesh": "BD",
    "india": "IN",
    "japan": "JP",
    "china": "CN",
    "singapore": "SG",
    "malaysia": "MY",
    "thailand": "TH",
    "indonesia": "ID",
    "nepal": "NP",
    "qatar": "QA",
    "saudi arabia": "SA",
    "turkey": "TR",
    "canada": "CA",
    "australia": "AU",
    "germany": "DE",
    "france": "FR",
    "italy": "IT",
    "spain": "ES",
    "switzerland": "CH",
    "netherlands": "NL",
    "maldives": "MV",
    "sri lanka": "LK",
    "philippines": "PH",
    "mexico": "MX",
    "greece": "GR",
    "portugal": "PT",
    "egypt": "EG",
    "new zealand": "NZ",
}

# Preferred primary international hub airport when a country is searched
COUNTRY_MAIN_AIRPORT: Dict[str, str] = {
    "BD": "DAC",  # Dhaka Hazrat Shahjalal
    "IN": "DEL",  # New Delhi Indira Gandhi
    "JP": "NRT",  # Tokyo Narita
    "US": "JFK",  # New York JFK
    "GB": "LHR",  # London Heathrow
    "AE": "DXB",  # Dubai International
    "SG": "SIN",  # Singapore Changi
    "MY": "KUL",  # Kuala Lumpur International
    "TH": "BKK",  # Bangkok Suvarnabhumi
    "ID": "CGK",  # Jakarta Soekarno-Hatta
    "CN": "PEK",  # Beijing Capital
    "KR": "ICN",  # Seoul Incheon
    "NP": "KTM",  # Kathmandu Tribhuvan
    "QA": "DOH",  # Doha Hamad
    "SA": "JED",  # Jeddah King Abdulaziz
    "TR": "IST",  # Istanbul Airport
    "CA": "YYZ",  # Toronto Pearson
    "AU": "SYD",  # Sydney Kingsford Smith
    "DE": "FRA",  # Frankfurt Airport
    "FR": "CDG",  # Paris Charles de Gaulle
    "IT": "FCO",  # Rome Fiumicino
    "ES": "MAD",  # Madrid Barajas
    "CH": "ZRH",  # Zurich Airport
    "NL": "AMS",  # Amsterdam Schiphol
    "MV": "MLE",  # Male Velana International
    "LK": "CMB",  # Colombo Bandaranaike
    "PH": "MNL",  # Manila Ninoy Aquino
    "MX": "MEX",  # Mexico City Benito Juarez
    "GR": "ATH",  # Athens International
    "PT": "LIS",  # Lisbon Humberto Delgado
    "EG": "CAI",  # Cairo International
    "NZ": "AKL",  # Auckland Airport
}

# Preferred primary airport when a specific major tourist city is mentioned
CITY_MAIN_AIRPORT: Dict[str, str] = {
    # Asia & Middle East
    "dhaka": "DAC",
    "delhi": "DEL",
    "new delhi": "DEL",
    "mumbai": "BOM",
    "kolkata": "CCU",
    "chennai": "MAA",
    "bangalore": "BLR",
    "bengaluru": "BLR",
    "hyderabad": "HYD",
    "tokyo": "NRT",
    "osaka": "KIX",
    "kyoto": "KIX",
    "bangkok": "BKK",
    "phuket": "HKT",
    "bali": "DPS",
    "denpasar": "DPS",
    "singapore": "SIN",
    "kuala lumpur": "KUL",
    "doha": "DOH",
    "dubai": "DXB",
    "abu dhabi": "AUH",
    "male": "MLE",
    "kathmandu": "KTM",
    "colombo": "CMB",
    "seoul": "ICN",
    "hong kong": "HKG",
    "shanghai": "PVG",
    "beijing": "PEK",
    # Europe
    "london": "LHR",
    "paris": "CDG",
    "rome": "FCO",
    "milan": "MXP",
    "madrid": "MAD",
    "barcelona": "BCN",
    "frankfurt": "FRA",
    "munich": "MUC",
    "berlin": "BER",
    "amsterdam": "AMS",
    "zurich": "ZRH",
    "geneva": "GVA",
    "vienna": "VIE",
    "istanbul": "IST",
    "athens": "ATH",
    "lisbon": "LIS",
    "dublin": "DUB",
    # Americas
    "new york": "JFK",
    "nyc": "JFK",
    "los angeles": "LAX",
    "san francisco": "SFO",
    "chicago": "ORD",
    "miami": "MIA",
    "toronto": "YYZ",
    "vancouver": "YVR",
    "cancun": "CUN",
    # Oceania
    "sydney": "SYD",
    "melbourne": "MEL",
    "auckland": "AKL",
}


# ==============================================================================
# 2. TEXT PROCESSING & GEOGRAPHIC RESOLUTION UTILITIES
# ==============================================================================

def clean_text(text: str) -> str:
    """
    Normalizes a text string by lowercasing, removing special characters,
    and stripping common conversational noise/stop-words.
    """
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    stop_words = {
        "flight", "flights", "ticket", "tickets", "trip", "travel",
        "plan", "complete", "days", "day", "including", "hotel",
        "hotels", "sightseeing", "under", "budget", "info", "information",
        "find", "show", "search", "please", "me", "a", "an", "the", "for"
    }
    words = [w for w in text.split() if w not in stop_words]
    return " ".join(words).strip()


def country_name_to_code(text: str) -> Optional[str]:
    """
    Resolves a text string or country name to an ISO 2-letter country code (e.g., "US", "JP").
    Uses alias dictionary first, then `pycountry` database lookups.
    """
    text_clean = clean_text(text)
    if not text_clean:
        return None

    # 1. Direct match in country aliases dictionary
    if text_clean in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[text_clean]

    # 2. Exact lookup using pycountry
    try:
        country = pycountry.countries.lookup(text_clean)
        return country.alpha_2
    except LookupError:
        pass

    # 3. Substring search in pycountry records
    for country in pycountry.countries:
        c_name = getattr(country, "name", "").lower()
        if c_name and c_name in text_clean:
            return country.alpha_2

    # 4. Substring search in our alias dictionary
    for alias, code in COUNTRY_ALIASES.items():
        if alias in text_clean:
            return code

    return None


def airport_country_matches(airport: Dict[str, Any], country_code: str) -> bool:
    """
    Checks if a given airport record from `airportsdata` matches a target 2-letter country code.
    """
    airport_country = str(airport.get("country", "")).upper().strip()
    if airport_country == country_code.upper().strip():
        return True

    # Fallback check against the country's full formal name
    try:
        country = pycountry.countries.get(alpha_2=country_code)
        if country and airport_country.lower() == country.name.lower():
            return True
    except Exception:
        pass

    return False


def get_best_airport_for_country(country_code: str) -> Optional[str]:
    """
    Finds the most prominent international airport (IATA code) for a given country code.
    Checks the preferred mapping first, then ranks candidate airports using keyword heuristics.
    """
    code_upper = country_code.upper().strip()

    # 1. Check predefined preferred hub for this country
    preferred = COUNTRY_MAIN_AIRPORT.get(code_upper)
    if preferred and preferred in AIRPORTS:
        return preferred

    # 2. Scan all airports in the country and score them
    candidates: List[Tuple[int, str]] = []

    for iata, airport in AIRPORTS.items():
        if not iata:
            continue

        if airport_country_matches(airport, code_upper):
            name = str(airport.get("name", "")).lower()
            city = str(airport.get("city", "")).lower()

            # Scoring heuristic to favor major international hubs
            score = 0
            if "international" in name:
                score += 50
            if "intl" in name:
                score += 40
            if "capital" in name:
                score += 20
            if city:
                score += 5

            candidates.append((score, iata))

    if not candidates:
        return None

    # Return the IATA code of the highest-scoring candidate
    candidates.sort(reverse=True)
    return candidates[0][1]


def resolve_location_to_iata(location: Optional[str]) -> Optional[str]:
    """
    Master geographic resolver: converts a country, city, airport name,
    or raw string into a valid 3-letter IATA airport code.

    Examples:
        - "Japan" -> "NRT"
        - "Paris" -> "CDG"
        - "Bangalore" -> "BLR"
        - "JFK" -> "JFK"
    """
    if not location:
        return None

    raw_location = str(location).strip()

    # 1. Direct valid 3-letter IATA code check
    if re.fullmatch(r"[A-Za-z]{3}", raw_location):
        code = raw_location.upper()
        if code in AIRPORTS:
            return code

    location_clean = clean_text(raw_location)
    if not location_clean:
        return None

    # 2. Preferred city dictionary lookup
    if location_clean in CITY_MAIN_AIRPORT:
        return CITY_MAIN_AIRPORT[location_clean]

    # 3. Country-level lookup
    country_code = country_name_to_code(location_clean)
    if country_code:
        airport = get_best_airport_for_country(country_code)
        if airport:
            return airport

    # 4. Search within airportsdata by city / airport name matching
    city_matches: List[Tuple[int, str]] = []

    for iata, airport in AIRPORTS.items():
        city = str(airport.get("city", "")).lower().strip()
        name = str(airport.get("name", "")).lower().strip()

        score = 0
        if city == location_clean:
            score += 100
        elif location_clean in city:
            score += 70

        if location_clean in name:
            score += 50

        if "international" in name:
            score += 10

        if score > 0:
            city_matches.append((score, iata))

    if city_matches:
        city_matches.sort(reverse=True)
        return city_matches[0][1]

    return None


def find_location_mentions(query: str) -> List[str]:
    """
    Scans a free-form natural language query for geographic locations
    (country aliases, pycountry names, and known major cities).
    """
    q = query.lower()
    mentions: List[str] = []

    # Check country aliases
    for alias in COUNTRY_ALIASES:
        if re.search(rf"\b{re.escape(alias)}\b", q):
            mentions.append(alias)

    # Check pycountry database names
    for country in pycountry.countries:
        name = getattr(country, "name", "").lower()
        if len(name) >= 4 and re.search(rf"\b{re.escape(name)}\b", q):
            mentions.append(name)

    # Check known cities
    for city in CITY_MAIN_AIRPORT:
        if re.search(rf"\b{re.escape(city)}\b", q):
            mentions.append(city)

    # Deduplicate while preserving chronological occurrence order
    unique_mentions: List[str] = []
    for item in mentions:
        if item not in unique_mentions:
            unique_mentions.append(item)

    return unique_mentions


# ==============================================================================
# 3. ROUTE PARSING LOGIC
# ==============================================================================

def parse_route(query: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parses a user query string to extract departure (origin) and arrival (destination) IATA codes.

    Returns:
        (dep_iata, arr_iata)
        - (None, None): Global / unfiltered search
        - ("DEL", "NRT"): Specific route (Delhi to Tokyo)
        - ("DEL", None): All flights departing from Delhi
        - (None, "NRT"): All flights arriving in Tokyo
    """
    q = query.strip()
    q_lower = q.lower()
    default_origin = os.getenv("DEFAULT_ORIGIN_IATA")

    # 1. Global / all-country query detection
    global_keywords = [
        "all country", "all countries", "global flight", "global flights",
        "all flight", "all flights", "worldwide flight", "worldwide flights"
    ]
    if any(keyword in q_lower for keyword in global_keywords):
        return None, None

    # 2. Check for explicit IATA code pairs (e.g., "JFK to LHR", "DAC NRT")
    codes = re.findall(r"\b[A-Z]{3}\b", q)
    valid_codes = [c for c in codes if c in AIRPORTS]
    if len(valid_codes) >= 2:
        return valid_codes[0], valid_codes[1]

    # 3. Regex pattern: "from <origin> to <destination>"
    match_from_to = re.search(
        r"\bfrom\s+(.+?)\s+\bto\s+(.+?)(?:\s+(?:on|for|under|including|with|in|at)\b|[.!?]|$)",
        q_lower,
    )
    if match_from_to:
        origin_text = match_from_to.group(1)
        dest_text = match_from_to.group(2)
        dep_iata = resolve_location_to_iata(origin_text)
        arr_iata = resolve_location_to_iata(dest_text)
        return dep_iata, arr_iata

    # 4. Regex pattern: "to <destination> from <origin>"
    match_to_from = re.search(
        r"\bto\s+(.+?)\s+\bfrom\s+(.+?)(?:\s+(?:on|for|under|including|with|in|at)\b|[.!?]|$)",
        q_lower,
    )
    if match_to_from:
        dest_text = match_to_from.group(1)
        origin_text = match_to_from.group(2)
        dep_iata = resolve_location_to_iata(origin_text)
        arr_iata = resolve_location_to_iata(dest_text)
        return dep_iata, arr_iata

    # 5. Smart multi-location mention matching (e.g., "Japan trip from India", "Paris from London")
    mentions = find_location_mentions(q)
    if len(mentions) >= 2:
        m0, m1 = mentions[0], mentions[1]
        # Check if 'from <m1>' appears in text (meaning m1 is origin, m0 is destination)
        if re.search(rf"\bfrom\s+{re.escape(m1)}\b", q_lower) or re.search(rf"\bto\s+{re.escape(m0)}\b", q_lower):
            return resolve_location_to_iata(m1), resolve_location_to_iata(m0)
        # Check if 'from <m0>' appears in text (meaning m0 is origin, m1 is destination)
        if re.search(rf"\bfrom\s+{re.escape(m0)}\b", q_lower) or re.search(rf"\bto\s+{re.escape(m1)}\b", q_lower):
            return resolve_location_to_iata(m0), resolve_location_to_iata(m1)
        # Default order: first is origin, second is destination
        return resolve_location_to_iata(m0), resolve_location_to_iata(m1)

    # 6. Single location query with explicit direction
    match_from = re.search(r"\bfrom\s+(.+?)(?:[.!?]|$)", q_lower)
    if match_from:
        origin_text = match_from.group(1)
        dep_iata = resolve_location_to_iata(origin_text)
        if dep_iata:
            return dep_iata, None

    match_to = re.search(r"\bto\s+(.+?)(?:[.!?]|$)", q_lower)
    if match_to:
        dest_text = match_to.group(1)
        arr_iata = resolve_location_to_iata(dest_text)
        if arr_iata:
            return default_origin, arr_iata

    # 7. Fallback for single location mention
    if len(mentions) == 1:
        arr_iata = resolve_location_to_iata(mentions[0])
        return default_origin, arr_iata

    return None, None


# ==============================================================================
# 4. RESPONSE FORMATTING
# ==============================================================================

def format_flight(flight: Dict[str, Any]) -> str:
    """
    Formats a single AviationStack flight record into a clean, readable card format.
    """
    airline = flight.get("airline", {}).get("name") or "Unknown airline"
    flight_number = flight.get("flight", {}).get("iata") or "Unknown flight number"
    status = (flight.get("flight_status") or "Unknown").capitalize()

    dep = flight.get("departure", {}) or {}
    arr = flight.get("arrival", {}) or {}

    dep_airport = dep.get("airport") or "Unknown departure airport"
    dep_iata = dep.get("iata") or "Unknown"
    dep_terminal = dep.get("terminal") or "N/A"
    dep_gate = dep.get("gate") or "N/A"
    dep_scheduled = dep.get("scheduled") or "Unknown"
    dep_delay = dep.get("delay")
    dep_delay_text = f"{dep_delay} mins" if dep_delay is not None else "On time"

    arr_airport = arr.get("airport") or "Unknown arrival airport"
    arr_iata = arr.get("iata") or "Unknown"
    arr_terminal = arr.get("terminal") or "N/A"
    arr_gate = arr.get("gate") or "N/A"
    arr_scheduled = arr.get("scheduled") or "Unknown"
    arr_delay = arr.get("delay")
    arr_delay_text = f"{arr_delay} mins" if arr_delay is not None else "On time"

    return f"""✈️ Airline: {airline} | Flight: {flight_number} | Status: {status}
  • Departure: {dep_airport} ({dep_iata})
    - Scheduled: {dep_scheduled} | Terminal: {dep_terminal} | Gate: {dep_gate} | Delay: {dep_delay_text}
  • Arrival: {arr_airport} ({arr_iata})
    - Scheduled: {arr_scheduled} | Terminal: {arr_terminal} | Gate: {arr_gate} | Delay: {arr_delay_text}"""


# ==============================================================================
# 5. CORE FLIGHT SEARCH FUNCTION
# ==============================================================================

def search_flights(
    query: str = "",
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    limit: int = 10,
) -> str:
    """
    Searches live flight information via AviationStack API.

    Args:
        query: Free text query (e.g. "Flights from Delhi to Tokyo", "Trip to Paris").
        origin: Optional explicit origin city/country/IATA (e.g. "DEL", "India", "London").
        destination: Optional explicit destination city/country/IATA (e.g. "NRT", "Japan", "Paris").
        limit: Max number of flights to return (default 10).

    Returns:
        Formatted string containing flight status and schedule information.
    """
    api_key = os.getenv("AVIATIONSTACK_API_KEY")
    if not api_key:
        return (
            "Flight API error: AVIATIONSTACK_API_KEY is missing.\n"
            "Please add AVIATIONSTACK_API_KEY=your_key in your .env file."
        )

    # Determine departure and arrival IATA codes
    dep_iata = resolve_location_to_iata(origin) if origin else None
    arr_iata = resolve_location_to_iata(destination) if destination else None

    # If not explicitly provided, extract from query text
    if not dep_iata and not arr_iata and query:
        dep_iata, arr_iata = parse_route(query)

    params: Dict[str, Any] = {
        "access_key": api_key,
        "limit": min(limit, 100),
    }

    if dep_iata:
        params["dep_iata"] = dep_iata
    if arr_iata:
        params["arr_iata"] = arr_iata

    try:
        response = requests.get(BASE_URL, params=params, timeout=30)

        if response.status_code == 401:
            return "Flight API error: Unauthorized (HTTP 401). Please check your AVIATIONSTACK_API_KEY."
        elif response.status_code == 429:
            return "Flight API rate limit exceeded (HTTP 429). Please try again later or upgrade your plan."
        elif response.status_code >= 500:
            return f"Flight API server error (HTTP {response.status_code})."

        data = response.json()
    except requests.exceptions.Timeout:
        return "Flight API request timed out after 30 seconds."
    except requests.exceptions.RequestException as e:
        return f"Flight API network request failed: {e}"
    except ValueError:
        return "Flight API returned an invalid non-JSON response."

    # Check for API-level errors in response body
    if "error" in data:
        error = data["error"]
        return (
            "Flight API error:\n"
            f"Code: {error.get('code', 'Unknown')}\n"
            f"Message: {error.get('message', 'Unknown error')}"
        )

    flight_data = data.get("data", [])

    if not flight_data:
        route_text = ""
        if dep_iata and arr_iata:
            route_text = f" for route {dep_iata} -> {arr_iata}"
        elif dep_iata:
            route_text = f" departing from {dep_iata}"
        elif arr_iata:
            route_text = f" arriving at {arr_iata}"

        return (
            f"No live flight data found{route_text}.\n\n"
            "Note: AviationStack provides real-time schedule and flight status information. "
            "For live ticket prices and booking, pair this with a flight fare provider (e.g. Amadeus/Skyscanner)."
        )

    # Route header
    if dep_iata and arr_iata:
        header = f"Live Flights: {dep_iata} -> {arr_iata}"
    elif dep_iata:
        header = f"Live Flights departing from {dep_iata}"
    elif arr_iata:
        header = f"Live Flights arriving at {arr_iata}"
    else:
        header = "Global Live Flight Highlights"

    formatted_flights = [format_flight(flight) for flight in flight_data[:limit]]
    return f"{header}\n\n" + "\n\n---\n\n".join(formatted_flights)


if __name__ == "__main__":
    print("Testing flight search:")
    print(search_flights("Plan a 7 days Japan trip from India"))
    print("\n" + "=" * 80 + "\n")
    print(search_flights("all country flight info"))