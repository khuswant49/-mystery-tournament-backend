from sqlmodel import Session, select

from app.config import CANONICAL_CLOUD_ADMIN_URL
from app.models import Car, QrAward
from app.qr import control_qr_png_base64, wifi_qr_png_base64


def award_count(db: Session, round_id: str) -> int:
    return len(db.exec(select(QrAward).where(QrAward.round_id == round_id)).all())


def award_entry(db: Session, round_id: str, entry_id: str, rank: int) -> QrAward:
    """Awards a single car slot to a single entry, right now -- called
    synchronously from submit_result() the instant a qualifying correct
    submission lands, not batched up at round-close time. This is what makes
    the QR reveal instant for whoever finishes 1st/2nd/3rd: they don't wait
    on anyone else, they get their own award the moment they qualify.

    rank determines which car (by Car.sort_order) this player gets -- rank 1
    is whichever car has sort_order 1, and so on.
    """
    car = db.exec(select(Car).order_by(Car.sort_order.asc())).all()[rank - 1]

    award = QrAward(
        round_id=round_id,
        entry_id=entry_id,
        rank=rank,
        car_id=car.id,
        # Still generated for backward compatibility with the WiFi-AP flow
        # (esp32_car_wifi/), which is kept around as a fallback and not yet
        # retired -- see project_context.md's "Phase 2 architecture pivot".
        # Unused by the new Bluetooth-bridge control page below.
        wifi_png_b64=wifi_qr_png_base64(car.wifi_ssid, car.wifi_password),
    )
    # Always the public cloud URL, never a LAN address -- players control cars
    # over their own mobile data, so this has to be reachable from anywhere,
    # regardless of whatever mode Phase 1 gameplay itself is running in.
    control_url = f"{CANONICAL_CLOUD_ADMIN_URL}/car-control/{car.id}"
    award.control_png_b64 = control_qr_png_base64(control_url, award.session_token)
    db.add(award)
    db.commit()
    db.refresh(award)
    return award
