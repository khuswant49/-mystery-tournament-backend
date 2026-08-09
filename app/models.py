import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


def _uuid() -> str:
    return str(uuid.uuid4())


class Round(SQLModel, table=True):
    __tablename__ = "rounds"

    id: str = Field(default_factory=_uuid, primary_key=True)
    scenario_id: str
    status: str = Field(default="pending")  # pending | in_progress | closed
    timer_limit_seconds: int = Field(default=300)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


class Entry(SQLModel, table=True):
    __tablename__ = "entries"

    id: str = Field(default_factory=_uuid, primary_key=True)
    round_id: str = Field(foreign_key="rounds.id", index=True)
    player_name: str
    joined_at: datetime = Field(default_factory=datetime.utcnow)
    submitted_at: Optional[datetime] = None
    elapsed_seconds: Optional[float] = None
    correct: Optional[bool] = None
    score: Optional[int] = None
    ending: Optional[str] = None


class Car(SQLModel, table=True):
    __tablename__ = "cars"

    id: Optional[int] = Field(default=None, primary_key=True)
    sort_order: int = Field(index=True)
    label: str
    wifi_ssid: str
    wifi_password: str
    # Base control page URL, e.g. "http://192.168.4.1" -- the per-player session
    # token is appended as a ?session= query param when a QrAward is generated.
    control_url: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class LobbyPresence(SQLModel, table=True):
    """A lightweight heartbeat, not a real join -- a player's game sends one
    every poll tick while sitting on the "waiting for a round" screen, before
    any round exists to actually /api/join into. Lets the admin see who's
    sitting in the lobby before deciding to start a round. player_name is the
    primary key (upsert-by-name): if two players share a name they'll share
    one row here, which is an acceptable simplification for a presence
    display, not an authoritative record of anything.
    """

    __tablename__ = "lobby_presence"

    player_name: str = Field(primary_key=True)
    last_seen: datetime = Field(default_factory=datetime.utcnow)


class BackendMode(SQLModel, table=True):
    """Single-row settings table the admin edits to tell every game client
    (via GET /api/backend_mode) whether the event is currently running on
    this cloud deployment or has switched to a LAN host for the day -- see
    game/core/systems/cloud_client.rpy's bootstrap-against-cloud-first
    design. id is always 1; there is exactly one row."""

    __tablename__ = "backend_mode"

    id: int = Field(default=1, primary_key=True)
    mode: str = Field(default="cloud")  # "cloud" | "lan"
    lan_api_base: str = Field(default="")
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class QrAward(SQLModel, table=True):
    __tablename__ = "qr_awards"

    id: Optional[int] = Field(default=None, primary_key=True)
    round_id: str = Field(foreign_key="rounds.id", index=True)
    entry_id: str = Field(foreign_key="entries.id", index=True, unique=True)
    rank: int
    car_id: int = Field(foreign_key="cars.id")
    session_token: str = Field(default_factory=_uuid)
    wifi_png_b64: str
    control_png_b64: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
