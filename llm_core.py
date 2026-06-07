import base64
import json
import re
import requests
import fitz
from pathlib import Path
from typing import List, Dict, Any, Optional

from pa_database import (
    search_anagrafe,
    get_agenzia_entrate,
    get_stato_civile,
    get_full_citizen_record,
)
from agent_log import AgentLogger
from provenance import Source

_CURRENT_LOGGER: Optional[AgentLogger] = None


def set_logger(logger: Optional[AgentLogger]) -> None:
    global _CURRENT_LOGGER
    _CURRENT_LOGGER = logger


def _log() -> Optional[AgentLogger]:
    return _CURRENT_LOGGER


REGOLO_BASE_URL = "https://api.regolo.ai/v1"
_api_key_file = Path(__file__).parent / "api.txt"
API_KEY = _api_key_file.read_text().strip()
MODEL_NAME = "gemma4-31b"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_json_loads(s: str) -> Any:
    try:
        return json.loads(s)
    except json.JSONDecodeError as original_exc:
        try:
            depth = 0
            cut = len(s)
            for i in range(len(s) - 1, -1, -1):
                if s[i] in ('}', ']'):
                    depth += 1
                elif s[i] in ('{', '['):
                    depth -= 1
                if depth == 0:
                    cut = i + 1
                    break
            fixed = s[:cut]
            open_brackets = fixed.count('[') - fixed.count(']')
            open_braces = fixed.count('{') - fixed.count('}')
            fixed += ']' * max(open_brackets, 0) + '}' * max(open_braces, 0)
            return json.loads(fixed)
        except Exception:
            raise original_exc


def _pdf_page_to_base64(pdf_path: str, page: int = 0, dpi: int = 120) -> str:
    doc = fitz.open(pdf_path)
    pg = doc[page]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = pg.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    img_bytes = pix.tobytes("png")
    doc.close()
    return base64.b64encode(img_bytes).decode("utf-8")


def _call_llm(messages: List[Dict], tools: Optional[List] = None, tool_choice: str = "auto") -> Dict:
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {"model": MODEL_NAME, "messages": messages, "temperature": 0}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice
    response = requests.post(f"{REGOLO_BASE_URL}/chat/completions", headers=headers, json=payload)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]








# ── PIPELINE 3-STADI: Classifier → Structurer → Compose ─────────────────────

CLASSIFIER_TOOL = [{
    "type": "function",
    "function": {
        "name": "report_classification",
        "description": "Riporta il tipo di documento. Chiamare UNA SOLA VOLTA.",
        "parameters": {
            "type": "object",
            "properties": {
                "document_type": {"type": "string", "description": "Tipo di documento PA (es. 'Dichiarazione di nascita di un figlio')"},
                "summary": {"type": "string", "description": "Breve descrizione (1-2 frasi) di cosa serve compilare"},
                "chat_opening": {"type": "string", "description": "Messaggio iniziale chat: cosa serve e tono colloquiale"},
            },
            "required": ["document_type", "summary", "chat_opening"],
        },
    },
}]


def classify_document(pdf_path: str, citizen_record: Optional[Dict] = None) -> Dict:
    """Stadio 1: Classifier (vision-only). Identifica il documento, scrive opening."""
    logger = _log()
    if logger:
        logger.agent_start("Classifier", Path(pdf_path).name)

    try:
        img_b64 = _pdf_page_to_base64(pdf_path, page=0, dpi=110)
    except Exception as exc:
        print(f"[Classifier] immagine fallita: {exc}")
        img_b64 = None

    citizen_ctx = ""
    if citizen_record:
        a = citizen_record.get("anagrafe") or {}
        citizen_ctx = f"\nDati anagrafici noti del cittadino: {a.get('nome')} {a.get('cognome')}."
    else:
        citizen_ctx = "\nIl cittadino NON ha dati noti in anagrafe — serve raccoglierli in chat."

    system_prompt = (
        "Sei un esperto di moduli PA italiani. Guarda l'immagine e identifica il documento.\n"
        "Chiama report_classification con:\n"
        "- document_type: nome ufficiale del modulo\n"
        "- summary: 1-2 frasi su cosa serve compilare\n"
        "- chat_opening: messaggio amichevole per iniziare la raccolta dati in chat"
        + citizen_ctx
    )
    user_content: Any = [{"type": "text", "text": "Identifica questo documento e chiama report_classification."}]
    if img_b64:
        user_content.insert(0, {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}})

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    result = {}
    for _ in range(3):
        msg = _call_llm(messages, tools=CLASSIFIER_TOOL)
        messages.append(msg)
        for tc in msg.get("tool_calls") or []:
            if tc["function"]["name"] == "report_classification":
                try:
                    result = _safe_json_loads(tc["function"]["arguments"])
                except Exception:
                    result = {}
                break
        if result:
            break
        messages.append({"role": "user", "content": "Chiama report_classification ora."})

    if logger:
        logger.decision("Classifier", result.get("document_type", "?"))
        logger.agent_end("Classifier")

    return {
        "document_type": result.get("document_type", "Documento PA"),
        "summary": result.get("summary", ""),
        "chat_opening": result.get("chat_opening", "Come posso aiutarti?"),
    }






# ── CHAT AGENT ────────────────────────────────────────────────────────────────

def chat_reply(history: List[Dict], user_message: str, document_context: Dict, citizen_record: Optional[Dict]) -> Dict:
    """
    Risponde a un messaggio dell'utente nella chat di raccolta dati.
    Restituisce {"reply": str, "ready": bool, "collected": dict}
    """
    chat_questions = document_context.get("chat_questions", [])
    fields_desc = "\n".join(
        f"- {q.get('field_id', '?')}: {q.get('question', '')}"
        for q in chat_questions
    )

    citizen_ctx = ""
    if citizen_record:
        a = citizen_record.get("anagrafe") or {}
        ae = citizen_record.get("agenzia_entrate") or {}
        citizen_ctx = (
            f"Dati già disponibili: {a.get('nome')} {a.get('cognome')}, "
            f"nato {a.get('data_nascita')} a {a.get('luogo_nascita')}, "
            f"residente in {a.get('indirizzo')} {a.get('comune_residenza')}, "
            f"CF {ae.get('codice_fiscale', 'N/D')}.\n"
        )
    else:
        citizen_ctx = "ATTENZIONE: Nessun dato anagrafico disponibile — il cittadino non è stato trovato in anagrafe. Tutti i dati personali devono essere raccolti manualmente dall'utente in questa chat.\n"

    system = (
        f"Sei un funzionario della PA che sta aiutando un cittadino a compilare: "
        f"{document_context.get('document_type', 'un modulo PA')}.\n"
        f"{citizen_ctx}"
        f"Informazioni ancora necessarie:\n{fields_desc}\n\n"
        "Conversa in modo naturale. Quando hai raccolto tutte le informazioni necessarie, "
        "rispondi con un JSON nella forma:\n"
        '{"reply": "testo risposta", "ready": true, "collected": {"field_id": "valore", ...}}\n'
        "Altrimenti rispondi con:\n"
        '{"reply": "testo risposta", "ready": false, "collected": {"field_id": "valore", ...}}\n'
        "collected deve contenere tutti i dati raccolti finora, anche dai turni precedenti.\n"
        "Rispondi SOLO con il JSON."
    )

    messages = [{"role": "system", "content": system}] + history + [
        {"role": "user", "content": user_message}
    ]

    msg = _call_llm(messages)
    raw = msg.get("content", "")

    try:
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        parsed = _safe_json_loads(json_match.group(0) if json_match else raw)
        return {
            "reply": parsed.get("reply", raw),
            "ready": bool(parsed.get("ready", False)),
            "collected": parsed.get("collected", {}),
        }
    except Exception:
        return {"reply": raw, "ready": False, "collected": {}}


# ── LOOKUP AGENT ──────────────────────────────────────────────────────────────

LOOKUP_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "cerca_anagrafe",
            "description": "Cerca cittadini nell'Anagrafe per nome e cognome.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome": {"type": "string"},
                    "cognome": {"type": "string"},
                },
                "required": ["nome", "cognome"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "riporta_candidati",
            "description": "Riporta i citizen_id dei candidati trovati. Chiamare UNA SOLA VOLTA alla fine.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_ids": {"type": "array", "items": {"type": "string"}},
                    "reasoning": {"type": "string"},
                },
                "required": ["candidate_ids", "reasoning"],
            },
        },
    },
]


def _execute_lookup_tool(name: str, args: Dict) -> Any:
    if name == "cerca_anagrafe":
        return search_anagrafe(nome=args.get("nome"), cognome=args.get("cognome"))
    return {"error": f"Tool sconosciuto: {name}"}


def lookup_richiedente(nome: str, cognome: str) -> Dict:
    """Ricerca diretta nel DB PA, senza LLM."""
    results = search_anagrafe(nome=nome, cognome=cognome)
    candidates = [c for c in (get_full_citizen_record(r["id"]) for r in results) if c]
    return {"candidates": candidates, "reasoning": "Ricerca diretta anagrafe.", "n_candidates": len(candidates)}


# ── CONFLICT DETECTION ────────────────────────────────────────────────────────

CONFLICT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "riporta_conflitti",
            "description": "Riporta conflitti tra registri PA. Lista vuota se nessun conflitto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "conflicts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "source_a": {"type": "string"},
                                "value_a": {"type": "string"},
                                "source_b": {"type": "string"},
                                "value_b": {"type": "string"},
                                "severity": {"type": "string", "enum": ["alta", "media", "bassa"]},
                                "explanation": {"type": "string"},
                            },
                            "required": ["field", "source_a", "value_a", "source_b", "value_b", "severity", "explanation"],
                        },
                    },
                },
                "required": ["conflicts"],
            },
        },
    },
]


def detect_conflicts(citizen_record: Dict) -> List[Dict]:
    logger = _log()
    if logger:
        logger.agent_start("Conflict Agent", "Confronto registri PA")

    a = citizen_record.get("anagrafe") or {}
    ae = citizen_record.get("agenzia_entrate") or {}
    sc = citizen_record.get("stato_civile") or {}

    summary = (
        f"ANAGRAFE:\n{json.dumps(a, ensure_ascii=False, indent=2)}\n\n"
        f"AGENZIA ENTRATE:\n{json.dumps(ae, ensure_ascii=False, indent=2)}\n\n"
        f"STATO CIVILE:\n{json.dumps(sc, ensure_ascii=False, indent=2)}"
    )

    messages = [
        {"role": "system", "content": (
            "Confronta i dati del cittadino tra registri diversi. "
            "Segnala solo conflitti reali (non differenze formali). "
            "Chiama riporta_conflitti UNA SOLA VOLTA."
        )},
        {"role": "user", "content": summary},
    ]

    for _ in range(3):
        msg = _call_llm(messages, tools=CONFLICT_TOOLS)
        messages.append(msg)
        for tc in (msg.get("tool_calls") or []):
            if tc["function"]["name"] == "riporta_conflitti":
                try:
                    args = _safe_json_loads(tc["function"]["arguments"])
                except Exception:
                    args = {}
                conflicts = args.get("conflicts", [])
                if logger:
                    logger.decision("Conflict Agent", f"{len(conflicts)} conflitti")
                    logger.agent_end("Conflict Agent")
                return conflicts
        messages.append({"role": "user", "content": "Chiama riporta_conflitti ora."})

    if logger:
        logger.agent_end("Conflict Agent")
    return []


# ── VERIFIER AGENT ────────────────────────────────────────────────────────────

VERIFY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "riporta_verifica",
            "description": "Riporta esito verifica documento. Alert-only, nessuna autocorrezione.",
            "parameters": {
                "type": "object",
                "properties": {
                    "checks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "check_id": {"type": "string"},
                                "label": {"type": "string"},
                                "status": {"type": "string", "enum": ["ok", "warning", "error"]},
                                "message": {"type": "string"},
                            },
                            "required": ["check_id", "label", "status", "message"],
                        },
                    },
                    "alerts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "current_value": {"type": "string"},
                                "severity": {"type": "string", "enum": ["alta", "media", "bassa"]},
                                "issue": {"type": "string"},
                            },
                            "required": ["field", "current_value", "severity", "issue"],
                        },
                    },
                    "overall_status": {"type": "string", "enum": ["ok", "warning", "error"]},
                },
                "required": ["checks", "alerts", "overall_status"],
            },
        },
    },
]


def _validate_codice_fiscale(cf: str) -> bool:
    if not cf or len(cf) != 16:
        return False
    cf = cf.upper()
    if not re.match(r"^[A-Z0-9]{15}[A-Z]$", cf):
        return False
    odd_map = {
        "0": 1, "1": 0, "2": 5, "3": 7, "4": 9, "5": 13, "6": 15, "7": 17, "8": 19, "9": 21,
        "A": 1, "B": 0, "C": 5, "D": 7, "E": 9, "F": 13, "G": 15, "H": 17, "I": 19,
        "J": 21, "K": 2, "L": 4, "M": 18, "N": 20, "O": 11, "P": 3, "Q": 6, "R": 8,
        "S": 12, "T": 14, "U": 16, "V": 10, "W": 22, "X": 25, "Y": 24, "Z": 23,
    }
    even_map = {
        "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
        "A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5, "G": 6, "H": 7, "I": 8,
        "J": 9, "K": 10, "L": 11, "M": 12, "N": 13, "O": 14, "P": 15, "Q": 16, "R": 17,
        "S": 18, "T": 19, "U": 20, "V": 21, "W": 22, "X": 23, "Y": 24, "Z": 25,
    }
    total = sum((odd_map if i % 2 == 0 else even_map)[ch] for i, ch in enumerate(cf[:15]))
    return chr(ord("A") + (total % 26)) == cf[15]


def verify_document(output_pdf_path: str, citizen_record: Optional[Dict] = None) -> Dict:
    """
    Verifier: converte il PDF output in immagine, LLM lo legge e segnala anomalie.
    Alert-only.
    """
    logger = _log()
    if logger:
        logger.agent_start("Verifier Agent", "Alert-only")

    deterministic_checks = []

    # Checksum CF
    if citizen_record:
        cf = (citizen_record.get("agenzia_entrate") or {}).get("codice_fiscale", "")
        if cf:
            ok = _validate_codice_fiscale(cf)
            deterministic_checks.append({
                "check_id": "cf_checksum",
                "label": "Validazione Codice Fiscale",
                "status": "ok" if ok else "error",
                "message": f"CF {cf} {'valido' if ok else 'NON valido (checksum errato)'}.",
            })

    # Converti PDF in immagine per verifica visiva
    try:
        img_b64 = _pdf_page_to_base64(output_pdf_path, page=0, dpi=120)
    except Exception as exc:
        if logger:
            logger.warning("Verifier Agent", f"Impossibile leggere PDF output: {exc}")
            logger.agent_end("Verifier Agent")
        return {"checks": deterministic_checks, "alerts": [], "overall_status": "warning"}

    messages = [
        {"role": "system", "content": (
            "Sei un funzionario PA senior che rivede un documento compilato. "
            "MODALITÀ ALERT-ONLY: non suggerire correzioni, solo segnalare problemi. "
            "Cerca: placeholder non rimossi ('___', '(nome)', '...'), "
            "campi vuoti dove ci si aspetta contenuto, testo palesemente sbagliato. "
            "Chiama riporta_verifica UNA SOLA VOLTA."
        )},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            {"type": "text", "text": "Verifica il documento compilato e segnala eventuali problemi."},
        ]},
    ]

    llm_checks, alerts, overall = [], [], "ok"

    for _ in range(3):
        msg = _call_llm(messages, tools=VERIFY_TOOLS)
        messages.append(msg)
        for tc in (msg.get("tool_calls") or []):
            if tc["function"]["name"] == "riporta_verifica":
                try:
                    args = _safe_json_loads(tc["function"]["arguments"])
                except Exception:
                    args = {}
                llm_checks = args.get("checks", [])
                alerts = args.get("alerts", [])
                overall = args.get("overall_status", "ok")
                break
        if llm_checks or alerts:
            break
        messages.append({"role": "user", "content": "Chiama riporta_verifica ora."})

    all_checks = deterministic_checks + llm_checks
    if any(c["status"] == "error" for c in all_checks):
        overall = "error"
    elif any(c["status"] == "warning" for c in all_checks) or alerts:
        overall = "warning" if overall != "error" else overall

    if logger:
        logger.decision("Verifier Agent", f"{overall} | {len(all_checks)} check, {len(alerts)} alert")
        logger.agent_end("Verifier Agent")

    return {"checks": all_checks, "alerts": alerts, "overall_status": overall}
