"""
Database fittizio della Pubblica Amministrazione.

Simula tre registri separati come nell'architettura reale italiana:
  - ANAGRAFE_NAZIONALE (ANPR): dati anagrafici + residenza
  - STATO_CIVILE: matrimoni, figli, eventi civili
  - AGENZIA_ENTRATE: codice fiscale + dati fiscali/indirizzo fiscale

Casi inclusi (per dimostrare le capacità del sistema multi-agente):
  C001 — Mario Rossi:       match perfetto, dati consistenti
  C002/C003/C004 — Giuseppe Bianchi ×3: omonimi (Milano/Napoli/Roma)
  C005 — Anna Verdi:        presente in Anagrafe, assente in Stato Civile
  C006 — Luigi Conti:       conflitto indirizzo tra Anagrafe e Agenzia Entrate
"""

from __future__ import annotations

from typing import Optional


# ── ANAGRAFE NAZIONALE (ANPR) ─────────────────────────────────────────────────

ANAGRAFE_NAZIONALE: list[dict] = [
    {
        "id": "C001",
        "nome": "Mario",
        "cognome": "Rossi",
        "data_nascita": "1985-08-01",
        "luogo_nascita": "Roma",
        "provincia_nascita": "RM",
        "sesso": "M",
        "indirizzo": "Via del Corso numero civico 12",
        "comune_residenza": "Roma",
        "provincia_residenza": "RM",
        "cap": "00186",
    },
    {
        "id": "C002",
        "nome": "Giuseppe",
        "cognome": "Bianchi",
        "data_nascita": "1970-01-15",
        "luogo_nascita": "Milano",
        "provincia_nascita": "MI",
        "sesso": "M",
        "indirizzo": "Via Dante 5",
        "comune_residenza": "Milano",
        "provincia_residenza": "MI",
        "cap": "20121",
    },
    {
        "id": "C003",
        "nome": "Giuseppe",
        "cognome": "Bianchi",
        "data_nascita": "1985-08-15",
        "luogo_nascita": "Napoli",
        "provincia_nascita": "NA",
        "sesso": "M",
        "indirizzo": "Via Toledo 88",
        "comune_residenza": "Napoli",
        "provincia_residenza": "NA",
        "cap": "80132",
    },
    {
        "id": "C004",
        "nome": "Giuseppe",
        "cognome": "Bianchi",
        "data_nascita": "1992-12-10",
        "luogo_nascita": "Roma",
        "provincia_nascita": "RM",
        "sesso": "M",
        "indirizzo": "Via Nazionale 200",
        "comune_residenza": "Roma",
        "provincia_residenza": "RM",
        "cap": "00184",
    },
    {
        "id": "C005",
        "nome": "Anna",
        "cognome": "Verdi",
        "data_nascita": "1988-09-10",
        "luogo_nascita": "Firenze",
        "provincia_nascita": "FI",
        "sesso": "F",
        "indirizzo": "Via dei Calzaiuoli 3",
        "comune_residenza": "Firenze",
        "provincia_residenza": "FI",
        "cap": "50122",
    },
    {
        "id": "C006",
        "nome": "Luigi",
        "cognome": "Conti",
        "data_nascita": "1978-04-22",
        "luogo_nascita": "Torino",
        "provincia_nascita": "TO",
        "sesso": "M",
        # NB: indirizzo registrato in Anagrafe — vedi conflitto con Agenzia Entrate
        "indirizzo": "Via Roma 12",
        "comune_residenza": "Milano",
        "provincia_residenza": "MI",
        "cap": "20100",
    },
]


# ── STATO CIVILE ──────────────────────────────────────────────────────────────

STATO_CIVILE: dict[str, dict] = {
    "C001": {
        "stato_civile": "coniugato",
        "coniuge": {"nome": "Laura", "cognome": "Neri", "cf": "NREL RA87T50H501K"},
        "figli": [
            {"nome": "Sofia", "cognome": "Rossi", "data_nascita": "2015-03-12"},
        ],
    },
    "C002": {
        "stato_civile": "celibe",
        "coniuge": None,
        "figli": [],
    },
    "C003": {
        "stato_civile": "coniugato",
        "coniuge": {"nome": "Carla", "cognome": "Russo", "cf": "RSSCRL88E55F839P"},
        "figli": [
            {"nome": "Marco", "cognome": "Bianchi", "data_nascita": "2018-06-05"},
            {"nome": "Elena", "cognome": "Bianchi", "data_nascita": "2021-11-20"},
        ],
    },
    "C004": {
        "stato_civile": "celibe",
        "coniuge": None,
        "figli": [],
    },
    # C005 (Anna Verdi) — volutamente assente per simulare dato mancante
    "C006": {
        "stato_civile": "divorziato",
        "coniuge": None,
        "figli": [],
    },
}


# ── AGENZIA DELLE ENTRATE ─────────────────────────────────────────────────────
# Contiene il codice fiscale validato + indirizzo fiscale (può differire da
# quello anagrafico in caso di domicilio fiscale separato).

AGENZIA_ENTRATE: dict[str, dict] = {
    "C001": {
        "codice_fiscale": "RSSMRA85M01H501Q",
        "indirizzo_fiscale": "Via del Corso numero civico 12",
        "comune_fiscale": "Roma",
        "cap_fiscale": "00186",
        "reddito_annuo": 35000,
    },
    "C002": {
        "codice_fiscale": "BNCGPP70A15F205T",
        "indirizzo_fiscale": "Via Dante 5",
        "comune_fiscale": "Milano",
        "cap_fiscale": "20121",
        "reddito_annuo": 42000,
    },
    "C003": {
        "codice_fiscale": "BNCGPP85M15F839Q",
        "indirizzo_fiscale": "Via Toledo 88",
        "comune_fiscale": "Napoli",
        "cap_fiscale": "80132",
        "reddito_annuo": 28000,
    },
    "C004": {
        "codice_fiscale": "BNCGPP92T10H501X",
        "indirizzo_fiscale": "Via Nazionale 200",
        "comune_fiscale": "Roma",
        "cap_fiscale": "00184",
        "reddito_annuo": 31000,
    },
    "C005": {
        "codice_fiscale": "VRDNNA88P50D612X",
        "indirizzo_fiscale": "Via dei Calzaiuoli 3",
        "comune_fiscale": "Firenze",
        "cap_fiscale": "50122",
        "reddito_annuo": 24000,
    },
    "C006": {
        "codice_fiscale": "CNTLGU78D22L219Z",
        # CONFLITTO: indirizzo fiscale a Roma, ma Anagrafe lo dà residente a Milano
        "indirizzo_fiscale": "Via Napoli 8",
        "comune_fiscale": "Roma",
        "cap_fiscale": "00184",
        "reddito_annuo": 55000,
    },
}


# ── Funzioni di lookup ────────────────────────────────────────────────────────

def search_anagrafe(
    nome: Optional[str] = None,
    cognome: Optional[str] = None,
    codice_fiscale: Optional[str] = None,
) -> list[dict]:
    """
    Cerca cittadini in Anagrafe Nazionale.
    Match case-insensitive su nome/cognome. Se viene fornito codice_fiscale,
    risolve prima tramite Agenzia Entrate e restituisce il record anagrafico.
    Ritorna sempre una lista (può essere vuota o contenere più match per omonimia).
    """
    if codice_fiscale:
        cf = codice_fiscale.strip().upper()
        for citizen_id, fiscal in AGENZIA_ENTRATE.items():
            if fiscal["codice_fiscale"].upper() == cf:
                record = get_anagrafe_by_id(citizen_id)
                return [record] if record else []
        return []

    results = []
    nome_l = nome.strip().lower() if nome else None
    cognome_l = cognome.strip().lower() if cognome else None

    for record in ANAGRAFE_NAZIONALE:
        if nome_l and record["nome"].lower() != nome_l:
            continue
        if cognome_l and record["cognome"].lower() != cognome_l:
            continue
        results.append(record)

    return results


def get_anagrafe_by_id(citizen_id: str) -> Optional[dict]:
    """Restituisce il record anagrafico per ID, o None se non trovato."""
    for record in ANAGRAFE_NAZIONALE:
        if record["id"] == citizen_id:
            return record
    return None


def get_stato_civile(citizen_id: str) -> Optional[dict]:
    """Restituisce i dati di stato civile per il cittadino, o None se assenti."""
    return STATO_CIVILE.get(citizen_id)


def get_agenzia_entrate(citizen_id: str) -> Optional[dict]:
    """Restituisce i dati fiscali per il cittadino, o None se assenti."""
    return AGENZIA_ENTRATE.get(citizen_id)


def get_full_citizen_record(citizen_id: str) -> Optional[dict]:
    """
    Restituisce il record completo aggregato dai tre registri.
    Ogni sezione è etichettata con la propria sorgente per il tracking di provenance.
    """
    anagrafe = get_anagrafe_by_id(citizen_id)
    if not anagrafe:
        return None

    return {
        "citizen_id": citizen_id,
        "anagrafe": anagrafe,
        "stato_civile": get_stato_civile(citizen_id),
        "agenzia_entrate": get_agenzia_entrate(citizen_id),
    }
