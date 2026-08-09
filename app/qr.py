import base64
import io

import qrcode


def _escape_wifi_field(value: str) -> str:
    # Per the WIFI: QR spec, these characters must be backslash-escaped when
    # they appear inside the SSID/password fields.
    for ch in ("\\", ";", ",", ":"):
        value = value.replace(ch, "\\" + ch)
    return value


def wifi_qr_payload(ssid: str, password: str) -> str:
    return "WIFI:T:WPA;S:{};P:{};H:false;;".format(
        _escape_wifi_field(ssid), _escape_wifi_field(password)
    )


def png_base64(data: str) -> str:
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def wifi_qr_png_base64(ssid: str, password: str) -> str:
    return png_base64(wifi_qr_payload(ssid, password))


def control_qr_png_base64(control_url: str, session_token: str) -> str:
    sep = "&" if "?" in control_url else "?"
    url = f"{control_url}{sep}session={session_token}"
    return png_base64(url)
