# app/utils/qrcode_gen.py
import qrcode
from pathlib import Path
from io import BytesIO
import base64

STATIC_DIR = Path("static")
STATIC_DIR.mkdir(parents=True, exist_ok=True)

def generate_qr_image_bytes(payload: str, filename: str = None):
    img = qrcode.make(payload)
    if filename:
        path = STATIC_DIR / filename
        img.save(path)
        return str(path)
    # return base64 PNG bytes otherwise
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")
