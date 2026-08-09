from typing import Optional

from pydantic import BaseModel


# ---------- Public API (game-facing) ----------

class JoinRequest(BaseModel):
    name: str


class JoinResponse(BaseModel):
    entry_id: str
    round_id: str
    scenario_id: str
    status: str


class RoundStateResponse(BaseModel):
    round_id: str
    scenario_id: str
    status: str
    opened_at: Optional[str] = None


class ActiveRoundResponse(BaseModel):
    active: bool
    round_id: Optional[str] = None
    scenario_id: Optional[str] = None


class BackendModeResponse(BaseModel):
    mode: str  # "cloud" | "lan"
    lan_api_base: Optional[str] = None


class HeartbeatRequest(BaseModel):
    name: str


class HeartbeatResponse(BaseModel):
    ok: bool = True


class SubmitRequest(BaseModel):
    elapsed_seconds: float
    correct: bool
    score: int
    ending: str


class SubmitResponse(BaseModel):
    ok: bool = True


class CarAward(BaseModel):
    label: str
    control_url: str
    wifi_qr_png_b64: str
    control_qr_png_b64: str


class EntryResultResponse(BaseModel):
    round_status: str
    rank: Optional[int] = None
    car: Optional[CarAward] = None


# ---------- Admin API ----------

class AdminLoginRequest(BaseModel):
    pin: str


class CreateRoundRequest(BaseModel):
    scenario_id: str


class CarUpdateRequest(BaseModel):
    label: str
    wifi_ssid: str
    wifi_password: str
    control_url: str
