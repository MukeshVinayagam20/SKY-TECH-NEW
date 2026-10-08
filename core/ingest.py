import io
import pymupdf as fitz
from PIL import Image, ImageOps

MAX_SIDE = 1600

def _prepare(img: Image.Image) -> bytes:
    img = ImageOps.exif_transpose(img).convert("RGB")   # fix phone rotation
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()

def file_to_images(file_bytes: bytes, filename: str) -> list[bytes]:
    if filename.lower().endswith(".pdf"):
        pages = []
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            for page in doc:
                pix = page.get_pixmap(dpi=200)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                pages.append(_prepare(img))
        return pages
    return [_prepare(Image.open(io.BytesIO(file_bytes)))]