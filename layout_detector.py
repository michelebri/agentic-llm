from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
import requests


# ── Config ────────────────────────────────────────────────────────────────────

REGOLO_BASE_URL = "https://api.regolo.ai/v1"
_API_KEY_FILE = Path(__file__).parent / "api.txt"
API_KEY = _API_KEY_FILE.read_text().strip() if _API_KEY_FILE.exists() else ""

OCR_MODEL_NAME = "deepseek-ocr-2"
NATIVE_TEXT_MIN_CHARS = 80


# ── Tipi ──────────────────────────────────────────────────────────────────────

Region = Dict[str, Any]  # {"text": str, "bbox": [x0,y0,x1,y1], "source": str, "conf"?: float}


# ── PyMuPDF nativo ────────────────────────────────────────────────────────────

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
        clean = (text or "").replace("\xa0", " ").replace(" ", " ").strip()
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


# ── PDF → immagine base64 ─────────────────────────────────────────────────────

def _pdf_page_to_base64_png(pdf_path: str, page_idx: int = 0, dpi: int = 180) -> str:
    doc = fitz.open(pdf_path)
    page = doc[page_idx]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    img_bytes = pix.tobytes("png")
    doc.close()
    return base64.b64encode(img_bytes).decode("utf-8")


# ── DeepSeek-OCR via Regolo ───────────────────────────────────────────────────

_OCR_SYSTEM = (
    "Sei un OCR strutturato per moduli PA italiani. "
    "Analizza l'immagine fornita ed estrai TUTTE le regioni di testo visibili. "
    "Per ogni regione restituisci:\n"
    "- text: il testo esatto (senza correzioni inventate)\n"
    "- bbox: [x0, y0, x1, y1] in coordinate NORMALIZZATE 0-1 (rispetto a larghezza e altezza dell'immagine)\n"
    "- conf: confidenza 0-1\n\n"
    "Regole:\n"
    "- Includi sia testo stampato che eventuali scritte a mano.\n"
    "- Ogni paragrafo / riga distinta = una regione separata.\n"
    "- NON inventare testo non presente. Se illeggibile usa '?' nel text.\n"
    "- Loghi, timbri grafici e linee decorative: NON estrarli.\n"
    "- Tabelle: estrai ogni cella come regione separata, oppure l'intera tabella come una regione con testo riga-per-riga.\n\n"
    "Restituisci SOLO un JSON valido nella forma:\n"
    '{"regions": [{"text": "...", "bbox": [0.0, 0.0, 1.0, 1.0], "conf": 0.95}, ...]}'
)


def _call_ocr_llm(img_b64: str) -> Dict[str, Any]:
    if not API_KEY:
        raise RuntimeError("API_KEY mancante (api.txt non trovato)")

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    messages = [
        {"role": "system", "content": _OCR_SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                {"type": "text", "text": "Estrai tutte le regioni di testo come JSON {regions: [...]}."},
            ],
        },
    ]
    payload = {
        "model": OCR_MODEL_NAME,
        "messages": messages,
        "temperature": 0,
    }
    resp = requests.post(f"{REGOLO_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]


def _parse_ocr_response(raw: str) -> List[Region]:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        fragment = match.group(0)
        opens = fragment.count("{") - fragment.count("}")
        opens_sq = fragment.count("[") - fragment.count("]")
        fragment += "]" * max(opens_sq, 0) + "}" * max(opens, 0)
        try:
            parsed = json.loads(fragment)
        except Exception:
            return []

    raw_regions = parsed.get("regions") or []
    out: List[Region] = []
    for r in raw_regions:
        text = (r.get("text") or "").strip()
        bbox = r.get("bbox") or []
        if not text or len(bbox) != 4:
            continue
        try:
            bbox = [float(v) for v in bbox]
            # Clip 0-1
            bbox = [max(0.0, min(1.0, v)) for v in bbox]
        except (TypeError, ValueError):
            continue
        out.append({
            "text": text,
            "bbox": bbox,
            "source": "deepseek_ocr",
            "conf": float(r.get("conf") or 0.0),
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

    img_b64 = _pdf_page_to_base64_png(pdf_path, page_idx=page_idx, dpi=180)
    msg = _call_ocr_llm(img_b64)
    raw = msg.get("content") or ""
    regions = _parse_ocr_response(raw)
    _save_ocr_cache(cache_path, regions)
    print(f"[LayoutDetector] Cache OCR salvata → {cache_path.name}")
    return regions


# ── Entry point unificato ─────────────────────────────────────────────────────

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


# ── CLI smoke test ────────────────────────────────────────────────────────────

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
