"""Settings and sources. Paths, URLs and secrets come from environment variables (see .env.example)."""
import os

DEFAULT_HOME = {"name": "Montmédy", "lat": 49.5207, "lon": 5.3683}  # reference town of the example profile
HOME = {
    "name": os.environ.get("SCOUT_HOME_NAME", DEFAULT_HOME["name"]),
    "lat": float(os.environ.get("SCOUT_HOME_LAT", DEFAULT_HOME["lat"])),
    "lon": float(os.environ.get("SCOUT_HOME_LON", DEFAULT_HOME["lon"])),
}

DEMO = os.environ.get("SCOUT_DEMO", "") not in ("", "0")  # synthetic offers + fake LLM + fake geo table, fully offline
DATA_DIR = os.environ.get("SCOUT_DATA", "./data")          # SQLite database
OUT_DIR = os.environ.get("SCOUT_OUT_DIR", "./out")         # daily digests (Markdown, Obsidian-friendly)
PROFILE_FILE = os.environ.get("SCOUT_PROFILE", "./profile.md")  # copy of profile.example.md
BIND = os.environ.get("SCOUT_BIND", "127.0.0.1")
PORT = int(os.environ.get("SCOUT_PORT", "8096"))

# Main LLM: any OpenAI-compatible server (llama.cpp, vLLM...). Fact extraction and, by default, fit judgement.
LLM_URL = os.environ.get("SCOUT_LLM_URL", "http://127.0.0.1:8080/v1")
LLM_KEY = os.environ.get("SCOUT_LLM_KEY", "")
LLM_KEY_FILE = os.environ.get("SCOUT_LLM_KEY_FILE", "")   # alternative to SCOUT_LLM_KEY (Docker secret)
LLM_MODEL = os.environ.get("SCOUT_LLM_MODEL", "local-model")

# Optional second, bigger model for the fit judgement, on another machine that is not always available.
# Disabled while SCOUT_PC_STATUS_URL is empty. The status endpoint must answer
# {"user_idle": bool, "ai_mode": bool, "gpu": {"vram_total_mib", "vram_used_mib"}, "models": [{"id", "status"}]}.
PC_LLM_URL = os.environ.get("SCOUT_PC_LLM_URL", "")
PC_STATUS_URL = os.environ.get("SCOUT_PC_STATUS_URL", "")
PC_KEY = os.environ.get("SCOUT_PC_KEY", "")
PC_KEY_FILE = os.environ.get("SCOUT_PC_KEY_FILE", "")
PC_MODEL = os.environ.get("SCOUT_PC_MODEL", "big-model")
PC_MODEL_MIB = int(os.environ.get("SCOUT_PC_MODEL_MIB", "13000"))  # VRAM needed to run it fully on the GPU
REFIT_PER_RUN = 80  # offers judged by the main model that the bigger model re-judges on each run

# Notifications through ntfy (https://ntfy.sh or self-hosted). Disabled while the topic is empty.
NTFY_URL = os.environ.get("SCOUT_NTFY_URL", "https://ntfy.sh")
NTFY_TOPIC = os.environ.get("SCOUT_NTFY_TOPIC", "")
NTFY_TOKEN = os.environ.get("SCOUT_NTFY_TOKEN", "")
DASHBOARD_URL = os.environ.get("SCOUT_DASHBOARD_URL", "")  # optional "open" button in notifications

CONTACT = os.environ.get("SCOUT_CONTACT", "set SCOUT_CONTACT")
USER_AGENT = f"job-scout/1.0 (personal job search; contact: {CONTACT})"

RUN_HOURS = (7, 11, 15, 19)  # daily runs (local time)
NOTIFY_MIN_SCORE = 80        # notify above this score
DIGEST_MIN_SCORE = 50        # listed in the daily digest

# Collectors that run by default: public JSON APIs and open data. The collectors that read HTML pages or
# sitemaps are opt-in (SCOUT_SOURCES=eures,forem,jobslu,...): check each site's terms before enabling them.
DEFAULT_SOURCES = "eures,forem,workday,recruitee,amazon"
SOURCES = [s.strip() for s in os.environ.get("SCOUT_SOURCES", DEFAULT_SOURCES).split(",") if s.strip()]

# Sources ---------------------------------------------------------------------------------
EURES_QUERIES = [
    # (EURES/NUTS location codes, ISCO groups, keywords)
    (["lu"], ["C25"], []),                 # ICT professionals, Luxembourg (ADEM feed)
    (["lu"], ["C35"], []),                 # ICT technicians
    (["lu"], ["C31"], []),                 # science / engineering technicians (electronics, mechanics...)
    (["frf3"], ["C25", "C35"], []),        # Lorraine (France Travail feed)
    (["lu", "frf3"], [], ["impression 3D"]),
    (["lu", "frf3"], [], ["électronique"]),
    (["lu"], [], ["fablab"]),
]
EURES_MAX_PER_QUERY = 100

FOREM_RADIUS_KM = 90
FOREM_FILTERS = [
    'metiercodedimeco like "M18*"',  # IT occupations
    'search(titreoffre, "informatique")', 'search(titreoffre, "électronique")',
    'search(titreoffre, "électronicien")', 'search(titreoffre, "automaticien")',
    'search(titreoffre, "développeur")', 'search(titreoffre, "réseau")', 'search(titreoffre, "3D")',
    'search(titreoffre, "helpdesk")', 'search(titreoffre, "prototyp")',
]

WORKDAY = [  # (tenant, instance, site, search text, display name): public career-page JSON
    ("statestreet", "wd1", "Global", "Luxembourg", "State Street"),
    ("pwc", "wd3", "Global_Experienced_Careers", "Luxembourg", "PwC"),
    ("ing", "wd3", "ICSGBLCOR", "Luxembourg", "ING"),
    ("paypal", "wd1", "jobs", "Luxembourg", "PayPal"),
    ("goodyear", "wd1", "GoodyearCareers", "Luxembourg", "Goodyear"),
]
RECRUITEE = ["aubay"]
AMAZON_LOCATIONS = [("Luxembourg", "LUX")]
ICTJOB_SITEMAPS = ["https://www.ictjob.lu/en/jobs-sitemap.xml"]
# jobs.lu categories: IT (14), technical support (29), manufacturing/engineering (16: CAD, prototyping, electronics),
# graduates (10), telecoms (37); 40 offers per page, sorted by date; 3 s between two pages.
JOBSLU_CATEGORIES = [14, 29, 16, 10, 37]
JOBSLU_MAX_PAGES = 4
JOBSLU_DELAY = 3

# Known towns -> driving minutes from the default home (OSRM, no traffic), to avoid API calls.
# Only valid for the default home: ignored when SCOUT_HOME_* is overridden (Nominatim + OSRM are used instead).
_DEFAULT_COMMUTES = {
    "stenay": 18, "virton": 21, "longuyon": 26, "florenville": 31, "longwy": 39, "verdun": 48,
    "arlon": 49, "petange": 51, "pétange": 51, "neufchateau": 52, "sedan": 52, "windhof": 53,
    "differdange": 57, "libramont": 59, "libramont-chevigny": 59, "belval": 60, "esch-sur-alzette": 61,
    "bastogne": 63, "luxembourg": 64, "leudelange": 64, "cloche d'or": 65, "charleville-mezieres": 67,
    "bettembourg": 68, "kirchberg": 68, "findel": 69, "hayange": 70, "colmar-berg": 77, "thionville": 79,
    "betzdorf": 84, "marche-en-famenne": 88, "metz": 91, "namur": 109, "liege": 117,
}
KNOWN_COMMUTES = _DEFAULT_COMMUTES if HOME == DEFAULT_HOME else {}
