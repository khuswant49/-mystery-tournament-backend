import os

# Falls back to a local SQLite file when DATABASE_URL isn't set, so the backend
# is runnable/testable without a Postgres install. Render sets DATABASE_URL
# for you when a Postgres instance is attached to the web service.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./local.db")

ADMIN_PIN = os.environ.get("ADMIN_PIN", "change-me")
COOKIE_SECRET = os.environ.get("COOKIE_SECRET", "dev-only-insecure-secret")

CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")]

# Mirrors CLOUD_API_BASE_STABLE in game/core/systems/cloud_client.rpy -- the
# one well-known address every game client bootstraps against. Used to
# redirect the admin back to the canonical cloud dashboard when they switch
# the Backend Mode toggle back to "cloud" (see admin.py's backend_mode_update),
# and to tell whether THIS running instance is that canonical deployment or
# a LAN/other instance (see backend_mode_page). Env-overridable so tests
# don't have to match the real production URL exactly -- see conftest.py.
CANONICAL_CLOUD_ADMIN_URL = os.environ.get(
    "CANONICAL_CLOUD_ADMIN_URL", "https://mystery-tournament-backend.onrender.com"
)

# Every round auto-closes once this many seconds pass since it opened, even if
# fewer than 3 players ever finish correctly. The scenario itself gives a
# player 300s (5 min) from the moment THEY join, but the round's own clock
# starts from when the ADMIN opens it -- if a player joins even slightly
# late, their 5-minute investigation window can run past the round's own
# 300s deadline, closing the round before they ever get to submit (this bit
# us in testing: an entry that submits after closing gets its score recorded
# but never receives a QrAward, since award_top_finishers() only runs once,
# at the moment of closure). 420s (7 min) gives ~2 minutes of join-lag
# buffer; tune this based on how staggered your players actually joining in
# practice turns out to be.
DEFAULT_ROUND_TIMER_SECONDS = 420

# How many correct finishers close a round and win car access.
QUALIFYING_SLOTS = 3

# Shared master secret the admin's own device presents to a car's local
# /admin/set-password endpoint to push a freshly-rotated WiFi password (see
# round_service.create_round's per-round rotation and
# esp32_car_wifi/car*/car*.ino's handleSetPassword). NOT a per-player
# session token, and never sent to game clients -- only used server-side to
# build the "push" link/QR shown to the admin. Must match the ADMIN_KEY
# constant flashed into all 3 cars' firmware; change this before the event.
CAR_ADMIN_KEY = os.environ.get("CAR_ADMIN_KEY", "change-this-admin-key")

# Mirrors game/story/entry/meta_flow.rpy's MT_CASE_CATALOGUE. Keep in sync by hand
# if a scenario is added/renamed there — this backend can't import .rpy files.
SCENARIO_CATALOGUE = [
    {"id": "SC01", "title": "The Ashcroft Mask Heist"},
    {"id": "SC02", "title": "The Missing Sapphire"},
    {"id": "SC03", "title": "The Vanishing Portrait"},
    {"id": "SC04", "title": "The Locked Restoration Room"},
    {"id": "SC05", "title": "The Silent Security Room"},
    {"id": "SC06", "title": "The False Donation"},
]
