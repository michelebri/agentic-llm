from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
import requests


API_URL = os.getenv("API_URL", "https://api.regolo.ai/v1")
API_KEY = os.getenv("API_KEY", "")

OCR_MODEL_NAME = "deepseek-ocr-2"

NATIVE_TEXT_MIN_CHARS = 80


Region = Dict[str, Any]


def _extract_native(pdf_path: str, page_idx: int = 0) -> List[Region]:
    doc = fitz.open(pdf_path)
    page = doc[page_idx]
    w, h = page.rect.width, page.rect.height

    raw = page.get_text("blocks")
    doc.close()

    regions: List[Region] = []
    for b in raw:
        if len(b) < 7:
            continue
        x0, y0, x1, y1, text, _bno, btype = b[0], b[1], b[2], b[3], b[4], b[5], b[6]
        if btype != 0:
            continue
        clean = (text or "").replace("\xa0", " ").replace(" ", " ").strip()
        clean = re.sub(r"[ \t]+", " ", clean)
        if not clean:
            continue
        regions.append({
            "text": clean,
            "bbox": [x0 / w, y0 / h, x1 / w, y1 / h],
            "source": "pymupdf_native",
        })
    return regions


def _total_chars(regions: List[Region]) -> int:
    return sum(len(r["text"]) for r in regions)


def _pdf_page_to_base64_png(pdf_path: str, page_idx: int = 0, dpi: int = 180) -> Tuple[str, int, int]:
    doc = fitz.open(pdf_path)
    page = doc[page_idx]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    img_bytes = pix.tobytes("png")
    w, h = pix.width, pix.height
    doc.close()
    return base64.b64encode(img_bytes).decode("utf-8"), w, h


def _call_ocr_llm(img_b64: str, img_w: int, img_h: int) -> tuple[str, int, int]:
    if not API_KEY:
        raise RuntimeError("API_KEY mancante (api.txt non trovato)")

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    messages = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            {"type": "text", "text": "Locate <|ref|>all text regions<|/ref|> in the image."},
        ],
    }]
    payload = {
        "model": OCR_MODEL_NAME,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 7000,
    }
    resp = requests.post(f"{API_URL}/chat/completions", headers=headers, json=payload, timeout=120)
    if not resp.ok:
        print(f"[LayoutDetector] OCR error {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"].get("content") or ""


def _parse_ocr_response(raw: str, img_w: int = 1000, img_h: int = 1000) -> List[Region]:
    out: List[Region] = []
    pattern = re.compile(
        r"(?:[a-z]+\[\[(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]\]\n?)([^\n\[]+)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(raw):
        x0, y0, x1, y1 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        text = m.group(5).strip().lstrip("#").strip()
        if not text:
            continue
        out.append({
            "text": text,
            "bbox": [
                max(0.0, min(1.0, x0 / img_w)),
                max(0.0, min(1.0, y0 / img_h)),
                max(0.0, min(1.0, x1 / img_w)),
                max(0.0, min(1.0, y1 / img_h)),
            ],
            "source": "deepseek_ocr",
            "conf": 1.0,
        })
    return out


def _ocr_cache_path(pdf_path: str, page_idx: int) -> Path:
    p = Path(pdf_path)
    content_hash = hashlib.md5(p.read_bytes()).hexdigest()[:12]
    return p.parent / f".{p.stem}_ocr_p{page_idx}_{content_hash}.json"


def _load_ocr_cache(cache_path: Path) -> Optional[List[Region]]:
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return None


def _save_ocr_cache(cache_path: Path, regions: List[Region]) -> None:
    try:
        cache_path.write_text(json.dumps(regions, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[LayoutDetector] Attenzione: impossibile salvare cache OCR ({e})")


def _extract_ocr(pdf_path: str, page_idx: int = 0) -> List[Region]:
    cache_path = _ocr_cache_path(pdf_path, page_idx)
    cached = _load_ocr_cache(cache_path)
    if cached is not None:
        print(f"[LayoutDetector] Cache OCR trovata → {cache_path.name} ({len(cached)} regions)")
        return cached

    img_b64, img_w, img_h = _pdf_page_to_base64_png(pdf_path, page_idx=page_idx, dpi=150)
    raw = _call_ocr_llm(img_b64, img_w, img_h)
    print(f"[LayoutDetector] OCR raw response: {repr(raw[:300])}")
    regions = _parse_ocr_response(raw, img_w, img_h)
    _save_ocr_cache(cache_path, regions)
    print(f"[LayoutDetector] Cache OCR salvata → {cache_path.name}")
    return regions


def detect_layout(pdf_path: str, page_idx: int = 0, force: Optional[str] = None) -> Tuple[List[Region], str]:
    if force == "native":
        return _extract_native(pdf_path, page_idx), "pymupdf_native"
    if force == "ocr":
        return _extract_ocr(pdf_path, page_idx), "deepseek_ocr"

    native = _extract_native(pdf_path, page_idx)
    if _total_chars(native) >= NATIVE_TEXT_MIN_CHARS:
        return native, "pymupdf_native"

    print(f"[LayoutDetector] PDF sembra scansione ({_total_chars(native)} char nativi) → OCR")
    return _extract_ocr(pdf_path, page_idx), "deepseek_ocr"


def _summarize(regions: List[Region], limit: int = 10) -> None:
    print(f"Totale regioni: {len(regions)}")
    for i, r in enumerate(regions[:limit]):
        text = r["text"][:80].replace("\n", " ⏎ ")
        bbox = [round(v, 3) for v in r["bbox"]]
        conf = r.get("conf", "—")
        print(f"  [{i}] bbox={bbox} conf={conf}  {text!r}")
    if len(regions) > limit:
        print(f"  ... e altre {len(regions) - limit}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test layout detector (PyMuPDF + DeepSeek-OCR)")
    parser.add_argument("pdf", help="Percorso PDF")
    parser.add_argument("--page", type=int, default=0, help="Indice pagina (default 0)")
    parser.add_argument("--force", choices=["native", "ocr"], default=None,
                        help="Forza la fonte (default: auto)")
    args = parser.parse_args()

    regions, source = detect_layout(args.pdf, page_idx=args.page, force=args.force)
    print(f"Fonte usata: {source}")
    _summarize(regions)
