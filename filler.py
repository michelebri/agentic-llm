from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from blueprint import (
    Block,
    Blueprint,
    FilledParagraphBlock,
    FootnoteBlock,
    HeadingBlock,
    ImageTextBlock,
    ListBlock,
    ParagraphBlock,
    SignatureBlock,
    SpacerBlock,
    SubtitleBlock,
    TableBlock,
    TitleBlock,
)


# ── Pattern marker ────────────────────────────────────────────────────────────

DA_CHIEDERE_RE = re.compile(r"\[DA CHIEDERE:\s*([a-zA-Z0-9_\.\-]+)\s*\]", re.IGNORECASE)


# ── Costruzione data pool ─────────────────────────────────────────────────────

def _build_data_pool(citizen_record: Optional[Dict], collected: Optional[Dict]) -> Dict[str, str]:
    pool: Dict[str, str] = {}
    if citizen_record:
        a = citizen_record.get("anagrafe") or {}
        ae = citizen_record.get("agenzia_entrate") or {}
        sc = citizen_record.get("stato_civile") or {}
        pool.update({
            "nome":              a.get("nome", "") or "",
            "cognome":           a.get("cognome", "") or "",
            "data_nascita":      a.get("data_nascita", "") or "",
            "luogo_nascita":     a.get("luogo_nascita", "") or "",
            "provincia_nascita": a.get("provincia_nascita", "") or "",
            "indirizzo":         a.get("indirizzo", "") or "",
            "comune_residenza":  a.get("comune_residenza", "") or "",
            "provincia_residenza": a.get("provincia_residenza", "") or "",
            "cap":               a.get("cap", "") or "",
            "codice_fiscale":    ae.get("codice_fiscale", "") or "",
            "stato_civile":      sc.get("stato_civile", "") or "",
        })
    if collected:
        for k, v in collected.items():
            if v:
                pool[k] = str(v)
    return {k: v for k, v in pool.items() if v}


# ── Sostituzione marker ───────────────────────────────────────────────────────

def _substitute(text: str, pool: Dict[str, str], missing: set[str]) -> str:
    if not text or "[DA CHIEDERE:" not in text.upper():
        return text

    def _repl(m: re.Match) -> str:
        key = m.group(1).strip()
        val = pool.get(key)
        if val:
            return val
        missing.add(key)
        return m.group(0)

    return DA_CHIEDERE_RE.sub(_repl, text)


# ── Filler sul Block ──────────────────────────────────────────────────────────

def _fill_block(b: Block, pool: Dict[str, str], missing: set[str]) -> Block:
    if isinstance(b, FilledParagraphBlock):
        return replace(b, template=_substitute(b.template, pool, missing))

    if isinstance(b, (ParagraphBlock, TitleBlock, SubtitleBlock, FootnoteBlock, ImageTextBlock)):
        return replace(b, text=_substitute(b.text, pool, missing))

    if isinstance(b, HeadingBlock):
        return replace(b, text=_substitute(b.text, pool, missing))

    if isinstance(b, ListBlock):
        new_intro = _substitute(b.intro, pool, missing) if b.intro else b.intro
        new_items = [_substitute(it, pool, missing) for it in b.items]
        return replace(b, intro=new_intro, items=new_items)

    if isinstance(b, TableBlock):
        new_headers = [_substitute(h, pool, missing) for h in b.headers]
        new_rows = [[_substitute(c, pool, missing) for c in row] for row in b.rows]
        return replace(b, headers=new_headers, rows=new_rows)

    if isinstance(b, (SignatureBlock, SpacerBlock)):
        return b  # niente da fare

    return b


def fill_blueprint(
    bp: Blueprint,
    citizen_record: Optional[Dict] = None,
    collected: Optional[Dict] = None,
) -> Tuple[Blueprint, List[str]]:
    pool = _build_data_pool(citizen_record, collected)
    missing: set[str] = set()
    new_blocks = [_fill_block(b, pool, missing) for b in bp.blocks]
    filled = Blueprint(
        document_type=bp.document_type,
        blocks=new_blocks,
        lingua=bp.lingua,
    )
    return filled, sorted(missing)


# ── Validator ────────────────────────────────────────────────────────────────

CF_RE = re.compile(r"^[A-Z0-9]{16}$")
DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
CAP_RE = re.compile(r"^\d{5}$")


def _validate_cf(value: str) -> Optional[str]:
    """Ritorna messaggio errore o None se ok."""
    if not value:
        return "codice fiscale mancante"
    v = value.replace(" ", "").upper()
    if not CF_RE.match(v):
        return f"codice fiscale non valido (atteso 16 caratteri alfanumerici): '{value}'"
    return None


def _validate_date(value: str) -> Optional[str]:
    if not value:
        return "data mancante"
    if not DATE_RE.match(value):
        return f"data non in formato gg/mm/aaaa: '{value}'"
    try:
        d = datetime.strptime(value, "%d/%m/%Y")
    except ValueError:
        return f"data non valida (calendario): '{value}'"
    if d.year < 1900 or d > datetime.now():
        return f"data implausibile: '{value}'"
    return None


def _validate_cap(value: str) -> Optional[str]:
    if not value:
        return None  # opzionale
    if not CAP_RE.match(value):
        return f"CAP non valido (atteso 5 cifre): '{value}'"
    return None


def _validate_provincia(value: str) -> Optional[str]:
    if not value:
        return None
    if len(value) != 2 or not value.isalpha():
        return f"provincia non valida (attesa sigla 2 lettere, es. RM): '{value}'"
    return None


def validate_blueprint(
    bp: Blueprint,
    citizen_record: Optional[Dict] = None,
    collected: Optional[Dict] = None,
    missing_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    pool = _build_data_pool(citizen_record, collected)
    alerts: List[Dict[str, str]] = []

    if missing_fields:
        for fid in missing_fields:
            alerts.append({"field": fid, "severity": "error", "issue": "campo richiesto non fornito"})

    field_validators = {
        "codice_fiscale": _validate_cf,
        "data_nascita":   _validate_date,
        "cap":            _validate_cap,
        "provincia_nascita": _validate_provincia,
    }
    for fid, fn in field_validators.items():
        if fid in pool:
            err = fn(pool[fid])
            if err:
                alerts.append({"field": fid, "severity": "warning", "issue": err})

    if not bp.blocks:
        alerts.append({"field": "_document", "severity": "error", "issue": "blueprint vuoto"})

    has_error = any(a["severity"] == "error" for a in alerts)
    has_warn = any(a["severity"] == "warning" for a in alerts)
    status = "error" if has_error else ("warning" if has_warn else "ok")

    return {
        "overall_status": status,
        "alerts": alerts,
        "missing_required": list(missing_fields or []),
    }


# ── CLI smoke test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json
    from blueprint import render_blueprint, blueprint_to_dict
    from agents import classify_document, build_blueprint
    from layout_detector import detect_layout

    parser = argparse.ArgumentParser(description="Pipeline completa")
    parser.add_argument("pdf", help="Percorso PDF")
    parser.add_argument("-o", "--out", default="pipeline_full.pdf", help="PDF output")
    args = parser.parse_args()

    citizen_record = {
        "anagrafe": {
            "nome": "Mario",
            "cognome": "Rossi",
            "data_nascita": "12/03/1980",
            "luogo_nascita": "Roma",
            "provincia_nascita": "RM",
            "indirizzo": "Via Roma 16",
            "comune_residenza": "Roma",
            "cap": "00100",
        },
        "agenzia_entrate": {"codice_fiscale": "RSSMRA80C12H501Z"},
        "stato_civile": {"stato_civile": "celibe"},
    }
    collected = {
        "numero_civico": "16",
        "documento_possesso_1": "Carta d'identità",
        "documento_possesso_2": "Tessera sanitaria",
    }

    print("=== Layout Detector ===")
    regions, source = detect_layout(args.pdf)
    print(f"  source={source}  regions={len(regions)}")

    print("\n=== Classifier ===")
    cls = classify_document(args.pdf, citizen_record=citizen_record)
    print(f"  type={cls['document_type']}  complexity={cls['complexity']}")

    print("\n=== Blueprint Architect ===")
    bp, chat_q = build_blueprint(args.pdf, regions, cls["document_type"], citizen_record=citizen_record)
    print(f"  blocks={len(bp.blocks)}  chat_questions={len(chat_q)}")

    print("\n=== Filler ===")
    filled_bp, missing = fill_blueprint(bp, citizen_record=citizen_record, collected=collected)
    print(f"  missing fields: {missing}")

    print("\n=== Validator ===")
    report = validate_blueprint(filled_bp, citizen_record=citizen_record, collected=collected,
                                missing_fields=missing)
    print(json.dumps(report, indent=2, ensure_ascii=False))

    print("\n=== Renderer ===")
    render_blueprint(filled_bp, args.out)
    print(f"  PDF: {args.out}")
