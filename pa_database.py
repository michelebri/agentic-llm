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
    "C006": {
        "stato_civile": "divorziato",
        "coniuge": None,
        "figli": [],
    },
}


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
    for record in ANAGRAFE_NAZIONALE:
        if record["id"] == citizen_id:
            return record
    return None


def get_stato_civile(citizen_id: str) -> Optional[dict]:
    return STATO_CIVILE.get(citizen_id)


def get_agenzia_entrate(citizen_id: str) -> Optional[dict]:
    return AGENZIA_ENTRATE.get(citizen_id)


def get_full_citizen_record(citizen_id: str) -> Optional[dict]:
    anagrafe = get_anagrafe_by_id(citizen_id)
    if not anagrafe:
        return None

    return {
        "citizen_id": citizen_id,
        "anagrafe": anagrafe,
        "stato_civile": get_stato_civile(citizen_id),
        "agenzia_entrate": get_agenzia_entrate(citizen_id),
    }
