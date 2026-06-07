"""
agents.py — Agenti LLM della pipeline (Step 3 + Step 4).

- Classifier: identifica il documento (vision-only, output piccolo).
- Blueprint Architect: produce blocks tipizzati a partire da regions + immagine.

Entrambi usano l'endpoint Regolo OpenAI-compatible (gemma4-31b).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz
import requests

from blueprint import (
    Blueprint,
    Block,
    dict_to_block,
)


# ── Config ────────────────────────────────────────────────────────────────────

REGOLO_BASE_URL = "https://api.regolo.ai/v1"
_API_KEY_FILE = Path(__file__).parent / "api.txt"
API_KEY = _API_KEY_FILE.read_text().strip() if _API_KEY_FILE.exists() else ""

MODEL_NAME = "gemma4-31b"  # Modello "ragionatore" per Classifier + Architect


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pdf_hash(pdf_path: str) -> str:
    return hashlib.md5(Path(pdf_path).read_bytes()).hexdigest()[:12]


def _agent_cache_path(pdf_path: str, step: str) -> Path:
    p = Path(pdf_path)
    return p.parent / f".{p.stem}_{step}_{_pdf_hash(pdf_path)}.json"


def _load_cache(path: Path) -> Optional[Dict]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _save_cache(path: Path, data: Dict) -> None:
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[Cache] impossibile salvare {path.name}: {e}")


def _pdf_page_to_b64(pdf_path: str, page_idx: int = 0, dpi: int = 130) -> str:
    doc = fitz.open(pdf_path)
    page = doc[page_idx]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    img_bytes = pix.tobytes("png")
    doc.close()
    return base64.b64encode(img_bytes).decode("utf-8")


def _safe_json_loads(s: str) -> Any:
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # auto-chiusura parentesi/quadre
        opens = s.count("{") - s.count("}")
        opens_sq = s.count("[") - s.count("]")
        s2 = s + "]" * max(opens_sq, 0) + "}" * max(opens, 0)
        try:
            return json.loads(s2)
        except Exception:
            return {}


def _call_llm(messages: List[Dict], tools: Optional[List] = None, tool_choice: str = "auto") -> Dict:
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload: Dict[str, Any] = {"model": MODEL_NAME, "messages": messages, "temperature": 0}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice
    resp = requests.post(f"{REGOLO_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=180)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]


# ── STEP 3: Classifier ────────────────────────────────────────────────────────

CLASSIFIER_TOOL = [{
    "type": "function",
    "function": {
        "name": "report_classification",
        "description": "Identifica il documento PA. Chiamare UNA SOLA VOLTA.",
        "parameters": {
            "type": "object",
            "properties": {
                "document_type": {
                    "type": "string",
                    "description": "Nome ufficiale del modulo (es. \"Dichiarazione sostitutiva dell'atto di notorietà\").",
                },
                "summary": {
                    "type": "string",
                    "description": "1-2 frasi su cosa serve compilare.",
                },
                "complexity": {
                    "type": "string",
                    "enum": ["simple", "medium", "complex"],
                    "description": "Stima della complessità del documento (per scegliere modello/profondità).",
                },
                "lingua": {
                    "type": "string",
                    "description": "Codice lingua a 2 lettere (es. 'it', 'en').",
                },
                "chat_opening": {
                    "type": "string",
                    "description": "Messaggio iniziale amichevole per il cittadino in chat.",
                },
            },
            "required": ["document_type", "summary", "complexity", "lingua", "chat_opening"],
        },
    },
}]


def classify_document(pdf_path: str, citizen_record: Optional[Dict] = None) -> Dict[str, Any]:
    """Step 3 — Classifier. Identifica documento, lingua, complessità."""
    cache_path = _agent_cache_path(pdf_path, "classifier")
    cached = _load_cache(cache_path)
    if cached:
        print(f"[Classifier] Cache trovata → {cache_path.name}")
        return cached

    try:
        img_b64 = _pdf_page_to_b64(pdf_path, page_idx=0, dpi=110)
    except Exception as exc:
        print(f"[Classifier] errore immagine: {exc}")
        img_b64 = None

    citizen_ctx = ""
    if citizen_record:
        a = citizen_record.get("anagrafe") or {}
        citizen_ctx = f"\nDati anagrafici noti: {a.get('nome', '')} {a.get('cognome', '')}.".strip()
    else:
        citizen_ctx = "\nNessun dato anagrafico noto del cittadino."

    system_prompt = (
        "Sei un esperto di moduli PA italiani. Guarda l'immagine della pagina 1 e identifica il documento.\n"
        "Chiama report_classification con:\n"
        "- document_type: nome ufficiale del modulo\n"
        "- summary: 1-2 frasi su cosa va compilato\n"
        "- complexity: simple (modulo breve), medium (più sezioni), complex (multipli paragrafi/tabelle)\n"
        "- lingua: codice ISO 2 lettere\n"
        "- chat_opening: messaggio iniziale amichevole per chiedere i dati al cittadino"
        + citizen_ctx
    )

    user_content: Any = [{"type": "text", "text": "Identifica il documento e chiama report_classification."}]
    if img_b64:
        user_content.insert(0, {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}})

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    result: Dict[str, Any] = {}
    for _ in range(3):
        msg = _call_llm(messages, tools=CLASSIFIER_TOOL)
        messages.append(msg)
        for tc in msg.get("tool_calls") or []:
            if tc["function"]["name"] == "report_classification":
                result = _safe_json_loads(tc["function"]["arguments"])
                break
        if result:
            break
        messages.append({"role": "user", "content": "Chiama report_classification ora."})

    out = {
        "document_type": result.get("document_type", "Documento PA"),
        "summary": result.get("summary", ""),
        "complexity": result.get("complexity", "simple"),
        "lingua": result.get("lingua", "it"),
        "chat_opening": result.get("chat_opening", "Come posso aiutarti?"),
    }
    _save_cache(cache_path, out)
    return out


# ── STEP 4: Blueprint Architect ───────────────────────────────────────────────

# Tool schema con i Block ammessi. Schema stretto = output stabile su gemma4.

ARCHITECT_TOOL = [{
    "type": "function",
    "function": {
        "name": "report_blueprint",
        "description": (
            "Produce la struttura logica del documento come lista di Block tipizzati. "
            "Chiamare UNA SOLA VOLTA."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "blocks": {
                    "type": "array",
                    "description": (
                        "Lista ordinata di Block che descrivono il documento. "
                        "Ogni Block ha un campo 'kind' che ne determina il rendering."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": [
                                    "title", "subtitle", "heading", "paragraph",
                                    "filled_paragraph", "list", "table",
                                    "signature", "spacer", "footnote", "image_text",
                                ],
                                "description": (
                                    "title: titolo principale centrato grassetto. "
                                    "subtitle: sottotitolo centrato sotto il titolo. "
                                    "heading: intestazione di sezione (es. 'DICHIARA'). "
                                    "paragraph: paragrafo statico (boilerplate, articoli di legge). "
                                    "filled_paragraph: paragrafo che contiene dati da compilare. "
                                    "Usa segnaposto [DA CHIEDERE: field_id] per campi non noti. "
                                    "list: lista puntata di righe (es. documenti allegati). "
                                    "table: tabella con headers e rows. "
                                    "signature: riga firma a fine documento. "
                                    "spacer: spazio verticale. "
                                    "footnote: note legali piccole. "
                                    "image_text: testo estratto da un'immagine (per scansioni)."
                                ),
                            },
                            "text": {"type": "string", "description": "Per title/subtitle/heading/paragraph/footnote/image_text."},
                            "template": {"type": "string", "description": "Solo per filled_paragraph. Es: 'Il sottoscritto [DA CHIEDERE: nome] [DA CHIEDERE: cognome]'"},
                            "align": {"type": "string", "enum": ["left", "center", "right", "justify"], "description": "Allineamento (default left)."},
                            "centered": {"type": "boolean", "description": "Solo heading: True se centrato (default True)."},
                            "intro": {"type": "string", "description": "Solo list: testo introduttivo prima della lista."},
                            "items": {"type": "array", "items": {"type": "string"}, "description": "Solo list: voci della lista."},
                            "headers": {"type": "array", "items": {"type": "string"}, "description": "Solo table: intestazioni colonne."},
                            "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}, "description": "Solo table: righe (lista di celle)."},
                            "label": {"type": "string", "description": "Solo signature: etichetta sotto la riga firma (default 'Firma del dichiarante')."},
                            "place_date": {"type": "boolean", "description": "Solo signature: include riga 'Luogo e data' (default True)."},
                            "mm_height": {"type": "number", "description": "Solo spacer: altezza in mm (default 6)."},
                        },
                        "required": ["kind"],
                    },
                },
                "chat_questions": {
                    "type": "array",
                    "description": "Domande da fare in chat per ogni [DA CHIEDERE: field_id] usato nei blocks.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field_id": {"type": "string"},
                            "question": {"type": "string"},
                        },
                        "required": ["field_id", "question"],
                    },
                },
            },
            "required": ["blocks", "chat_questions"],
        },
    },
}]


def _regions_summary(regions: List[Dict[str, Any]], max_items: int = 80) -> str:
    """Compatta le regions in righe testuali per il prompt LLM."""
    lines = []
    for i, r in enumerate(regions[:max_items]):
        bbox = [round(v, 3) for v in r.get("bbox", [0, 0, 0, 0])]
        text = (r.get("text") or "").replace("\n", " ")
        lines.append(f"[{i}] bbox={bbox} text={text!r}")
    if len(regions) > max_items:
        lines.append(f"... e altre {len(regions) - max_items} regioni")
    return "\n".join(lines)


def build_blueprint(
    pdf_path: str,
    regions: List[Dict[str, Any]],
    document_type: str,
    citizen_record: Optional[Dict] = None,
) -> tuple[Blueprint, List[Dict[str, str]]]:
    """
    Step 4 — Blueprint Architect.
    Riceve immagine + regions + tipo documento, produce Blueprint + chat_questions.
    """
    from blueprint import dict_to_blueprint

    cache_path = _agent_cache_path(pdf_path, "architect")
    cached = _load_cache(cache_path)
    if cached:
        print(f"[Architect] Cache trovata → {cache_path.name}")
        bp = dict_to_blueprint(cached["blueprint"])
        return bp, cached.get("chat_questions", [])

    try:
        img_b64 = _pdf_page_to_b64(pdf_path, page_idx=0, dpi=120)
    except Exception as exc:
        print(f"[Architect] errore immagine: {exc}")
        img_b64 = None

    # Contesto dati anagrafici
    avail_ctx = ""
    avail_keys: List[str] = []
    sesso: Optional[str] = None  # "M" | "F" | None
    if citizen_record:
        a = citizen_record.get("anagrafe") or {}
        ae = citizen_record.get("agenzia_entrate") or {}
        sc = citizen_record.get("stato_civile") or {}

        # Determina sesso: campo esplicito o euristica da codice fiscale
        _sesso_raw = (a.get("sesso") or "").upper().strip()
        if _sesso_raw in ("M", "F"):
            sesso = _sesso_raw
        else:
            cf = ae.get("codice_fiscale") or ""
            if len(cf) >= 11:
                try:
                    day = int(cf[9:11])
                    sesso = "F" if day > 40 else "M"
                except ValueError:
                    pass

        pairs = [
            ("nome", a.get("nome")),
            ("cognome", a.get("cognome")),
            ("data_nascita", a.get("data_nascita")),
            ("luogo_nascita", a.get("luogo_nascita")),
            ("provincia_nascita", a.get("provincia_nascita")),
            ("indirizzo", a.get("indirizzo")),
            ("comune_residenza", a.get("comune_residenza")),
            ("cap", a.get("cap")),
            ("codice_fiscale", ae.get("codice_fiscale")),
            ("stato_civile", sc.get("stato_civile")),
        ]
        avail_keys = [k for k, v in pairs if v]
        if avail_keys:
            avail_ctx = (
                "\n\nDATI NOTI del cittadino (puoi inserirli inline nei filled_paragraph):\n"
                + "\n".join(f"- {k}: {dict(pairs)[k]}" for k in avail_keys)
            )

    # Istruzione genere per concordanza grammaticale
    if sesso == "M":
        genere_ctx = (
            "\n\nGENERE DICHIARANTE: MASCHILE. "
            "Usa SEMPRE la forma maschile per tutte le concordanze: "
            "'il sottoscritto', 'nato', 'residente', 'identificato', 'il dichiarante', ecc. "
            "NON usare mai forme doppie come 'il/la', 'nato/a', 'il/il'."
        )
    elif sesso == "F":
        genere_ctx = (
            "\n\nGENERE DICHIARANTE: FEMMINILE. "
            "Usa SEMPRE la forma femminile per tutte le concordanze: "
            "'la sottoscritta', 'nata', 'residente', 'identificata', 'la dichiarante', ecc. "
            "NON usare mai forme doppie come 'il/la', 'nato/a', 'il/il'."
        )
    else:
        genere_ctx = (
            "\n\nGENERE DICHIARANTE: non noto. "
            "Usa la forma neutra 'il/la sottoscritto/a', 'nato/a' ecc. "
            "oppure la forma maschile come default se la frase lo richiede."
        )

    system_prompt = (
        f"Sei un esperto di moduli PA italiani. Devi RICOSTRUIRE il documento '{document_type}' "
        "come Blueprint strutturato (lista di Block tipizzati) per renderlo poi in PDF pulito.\n\n"
        "OBIETTIVO: produrre una versione ordinata, leggibile, fedele AL SENSO del documento, "
        "non al pixel originale. Il rendering finale userà flow layout, non bbox.\n\n"
        "REGOLE per i Block:\n"
        "1. ORDINE: top-to-bottom, left-to-right. Segui il flusso logico di lettura.\n"
        "2. TITLE: solo per il titolo principale del modulo (es. 'DICHIARAZIONE SOSTITUTIVA').\n"
        "3. SUBTITLE: sottotitolo immediatamente sotto il titolo.\n"
        "4. HEADING: parole/frasi chiave centrate (es. 'DICHIARA', 'CHIEDE').\n"
        "5. PARAGRAPH: testo statico (articoli di legge, frasi standard).\n"
        "6. FILLED_PARAGRAPH: frasi che contengono dati personali del cittadino. "
        "   USA il marker [DA CHIEDERE: field_id] per ogni campo NON noto. "
        "   Per i campi NOTI inserisci il valore direttamente inline (vedi DATI NOTI sotto).\n"
        "7. LIST: OBBLIGATORIO quando il documento ha righe puntinate o spazi ripetuti per elencare "
        "   più elementi distinti (es. lista documenti, lista beni, lista dichiarazioni le liste potrebbero avere anche spazi con righe vuote nei documenti). "
        "   NON collassare una lista in un unico filled_paragraph con un solo [DA CHIEDERE: x]: "
        "   usa sempre items separati es. [DA CHIEDERE: documento_1], [DA CHIEDERE: documento_2], ecc. "
        "   Metti 2-4 items vuoti come placeholder se non sai quanti sono.\n"
        "8. TABLE: solo se davvero c'è una tabella nel documento.\n"
        "9. SIGNATURE: alla fine, per la riga firma + 'Luogo e data'.\n"
        "10. SPACER: solo se serve uno stacco verticale evidente. Default 6mm.\n"
        "11. FOOTNOTE: note piccole a fine pagina (es. versione modulo).\n"
        "12. IMAGE_TEXT: testo proveniente da loghi/immagini con scritte (raro). NON includere loghi puramente decorativi.\n\n"
        "REGOLE STRUTTURA:\n"
        "- NON spezzare una frase logica in più block: una frase = un block.\n"
        "- NON ripetere lo stesso testo in più block.\n"
        "- Salta linee di puntini ('....') che sono solo spazio per scrivere: usa [DA CHIEDERE: x].\n"
        "- Salta loghi, timbri grafici, decorazioni.\n"
        "- field_id chiari e standard: nome, cognome, data_nascita, luogo_nascita, "
        "provincia_nascita, codice_fiscale, indirizzo, comune_residenza, cap. "
        "Per campi specifici usa nomi descrittivi (figlio_nome, documento_1, telefono_ufficio).\n\n"
        "OUTPUT chat_questions: una domanda per OGNI field_id [DA CHIEDERE: x] usato nei block "
        "che NON è nei DATI NOTI."
        + genere_ctx
        + avail_ctx
    )

    regions_text = _regions_summary(regions)
    user_content: Any = [
        {"type": "text", "text": (
            f"Regioni di testo estratte dal documento ({len(regions)} totali):\n{regions_text}\n\n"
            "Costruisci il Blueprint e chiama report_blueprint."
        )},
    ]
    if img_b64:
        user_content.insert(0, {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}})

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    result: Dict[str, Any] = {}
    for _ in range(3):
        msg = _call_llm(messages, tools=ARCHITECT_TOOL)
        messages.append(msg)
        for tc in msg.get("tool_calls") or []:
            if tc["function"]["name"] == "report_blueprint":
                result = _safe_json_loads(tc["function"]["arguments"])
                break
        if result:
            break
        messages.append({"role": "user", "content": "Chiama report_blueprint ora."})

    raw_blocks = result.get("blocks", []) or []
    blocks: List[Block] = []
    for d in raw_blocks:
        try:
            blocks.append(dict_to_block(d))
        except Exception as exc:
            print(f"[Architect] block invalido scartato: {exc} → {d}")

    chat_questions = result.get("chat_questions", []) or []
    bp = Blueprint(document_type=document_type, blocks=blocks)

    from blueprint import blueprint_to_dict
    _save_cache(cache_path, {
        "blueprint": blueprint_to_dict(bp),
        "chat_questions": chat_questions,
    })

    return bp, chat_questions


# ── CLI smoke test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from layout_detector import detect_layout
    from blueprint import render_blueprint, blueprint_to_dict

    parser = argparse.ArgumentParser(description="Pipeline parziale: Classifier → Architect → render")
    parser.add_argument("pdf", help="Percorso PDF")
    parser.add_argument("-o", "--out", default="pipeline_test.pdf", help="PDF output")
    parser.add_argument("--no-render", action="store_true", help="Salta il rendering finale")
    args = parser.parse_args()

    print(f"\n=== Step 2: Layout Detector ===")
    regions, source = detect_layout(args.pdf)
    print(f"Source: {source}   Regions: {len(regions)}")

    print(f"\n=== Step 3: Classifier ===")
    cls = classify_document(args.pdf)
    print(json.dumps(cls, indent=2, ensure_ascii=False))

    print(f"\n=== Step 4: Blueprint Architect ===")
    bp, chat_q = build_blueprint(
        pdf_path=args.pdf,
        regions=regions,
        document_type=cls["document_type"],
    )
    print(f"Blocks: {len(bp.blocks)}")
    print(f"chat_questions: {len(chat_q)}")
    print(json.dumps(blueprint_to_dict(bp), indent=2, ensure_ascii=False)[:2000])

    if not args.no_render:
        print(f"\n=== Renderer ===")
        render_blueprint(bp, args.out)
        print(f"Generato: {args.out}")
