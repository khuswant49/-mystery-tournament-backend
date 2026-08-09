from sqlmodel import Session, select

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
        wifi_png_b64=wifi_qr_png_base64(car.wifi_ssid, car.wifi_password),
    )
    award.control_png_b64 = control_qr_png_base64(car.control_url, award.session_token)
    db.add(award)
    db.commit()
    db.refresh(award)
    return award
