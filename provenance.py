"""
Tracciamento di provenance per ogni campo compilato.

Ogni valore inserito nel documento finale porta con sé:
  - source: da quale registro/fonte proviene
  - confidence: quanto è affidabile (0-1)
  - retrieved_at: timestamp del recupero
  - citizen_id: collegamento al record sorgente (se applicabile)

Questo è il pilastro "trasparenza" del sistema, richiesto dall'AI Act
per l'uso di IA nella Pubblica Amministrazione.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional


class Source(str, Enum):
    """Sorgenti possibili per un campo compilato."""
    ANAGRAFE = "Anagrafe Nazionale (ANPR)"
    STATO_CIVILE = "Stato Civile"
    AGENZIA_ENTRATE = "Agenzia delle Entrate"
    USER_CONFIRMED = "Confermato dall'utente"
    USER_INPUT = "Inserito dall'utente"
    USER_CONFLICT_RESOLUTION = "Scelto dall'utente (risoluzione conflitto)"
    LLM_INFERRED = "Inferito dall'agente"


@dataclass
class ProvenanceEntry:
    """Traccia la provenance di un singolo campo del documento."""
    field_id: str
    value: str
    source: Source
    confidence: float = 1.0
    citizen_id: Optional[str] = None
    retrieved_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["source"] = self.source.value
        return d


class ProvenanceLog:
    """Raccolta di tutte le entries di provenance per un documento."""

    def __init__(self):
        self.entries: list[ProvenanceEntry] = []

    def add(
        self,
        field_id: str,
        value: str,
        source: Source,
        confidence: float = 1.0,
        citizen_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> ProvenanceEntry:
        entry = ProvenanceEntry(
            field_id=field_id,
            value=str(value),
            source=source,
            confidence=confidence,
            citizen_id=citizen_id,
            notes=notes,
        )
        self.entries.append(entry)
        return entry

    def get(self, field_id: str) -> Optional[ProvenanceEntry]:
        for e in self.entries:
            if e.field_id == field_id:
                return e
        return None

    def by_source(self) -> dict[str, int]:
        """Conta quanti campi vengono da ciascuna sorgente."""
        counts: dict[str, int] = {}
        for e in self.entries:
            counts[e.source.value] = counts.get(e.source.value, 0) + 1
        return counts

    def to_list(self) -> list[dict]:
        return [e.to_dict() for e in self.entries]

    def summary(self) -> dict:
        """Riepilogo per dashboard / report finale."""
        return {
            "total_fields": len(self.entries),
            "by_source": self.by_source(),
            "average_confidence": (
                sum(e.confidence for e in self.entries) / len(self.entries)
                if self.entries else 0.0
            ),
            "entries": self.to_list(),
        }
