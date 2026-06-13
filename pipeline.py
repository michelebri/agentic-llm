from __future__ import annotations

import datetime
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from blueprint import Blueprint, blueprint_to_dict, render_blueprint
from filler import fill_blueprint, validate_blueprint
from layout_detector import detect_layout

RESULTS_DIR = Path(__file__).parent / "experiments" / "results"


# ── Artefact helpers ──────────────────────────────────────────────────────────

def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_run_dir(stem: str) -> Path:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RESULTS_DIR / f"{stem}_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


# ── Pipeline result ───────────────────────────────────────────────────────────

class PipelineResult:
    def __init__(
        self,
        document_type: str,
        blueprint: Blueprint,
        filled_blueprint: Blueprint,
        chat_questions: List[Dict[str, str]],
        missing_fields: List[str],
        validation: Dict[str, Any],
        output_pdf: str,
        run_dir: Path,
    ):
        self.document_type = document_type
        self.blueprint = blueprint
        self.filled_blueprint = filled_blueprint
        self.chat_questions = chat_questions
        self.missing_fields = missing_fields
        self.validation = validation
        self.output_pdf = output_pdf
        self.run_dir = run_dir

    def as_analysis_dict(self) -> Dict[str, Any]:
        return {
            "document_type": self.document_type,
            "chat_opening": _build_chat_opening(self.document_type, self.chat_questions),
            "chat_questions": self.chat_questions,
            "blueprint": self.blueprint,
            "filled_blueprint": self.filled_blueprint,
            "missing_fields": self.missing_fields,
            "validation": self.validation,
        }


def _build_chat_opening(document_type: str, chat_questions: List[Dict]) -> str:
    if not chat_questions:
        return (
            f"Ho analizzato il documento «{document_type}». "
            "Tutti i dati necessari sono già disponibili. "
            "Vuoi procedere con la generazione?"
        )
    n = len(chat_questions)
    return (
        f"Ho analizzato il documento «{document_type}». "
        f"Per completarlo ho bisogno di {n} informazion{'e' if n == 1 else 'i'} aggiuntiv{'a' if n == 1 else 'e'}. "
        "Iniziamo!"
    )


# ── Step runners ──────────────────────────────────────────────────────────────

def _step_layout(pdf_path: str) -> Tuple[List[Dict], str]:
    print("[Pipeline] Step 1 — Layout Detector")
    regions, source = detect_layout(pdf_path)
    print(f"  source={source}  regions={len(regions)}")
    return regions, source


def _step_classify(pdf_path: str, citizen_record: Optional[Dict]) -> Dict[str, Any]:
    print("[Pipeline] Step 2 — Classifier")
    from agents import classify_document
    cls = classify_document(pdf_path, citizen_record=citizen_record)
    print(f"  type={cls.get('document_type')}  complexity={cls.get('complexity')}")
    return cls


def _step_architect(
    pdf_path: str,
    regions: List[Dict],
    document_type: str,
    citizen_record: Optional[Dict],
) -> Tuple[Blueprint, List[Dict[str, str]]]:
    print("[Pipeline] Step 3 — Blueprint Architect")
    from agents import build_blueprint
    bp, chat_q = build_blueprint(pdf_path, regions, document_type, citizen_record=citizen_record)
    print(f"  blocks={len(bp.blocks)}  chat_questions={len(chat_q)}")
    return bp, chat_q


def _step_fill(
    bp: Blueprint,
    citizen_record: Optional[Dict],
    collected: Optional[Dict],
) -> Tuple[Blueprint, List[str]]:
    print("[Pipeline] Step 4 — Filler")
    filled, missing = fill_blueprint(bp, citizen_record=citizen_record, collected=collected)
    print(f"  missing={missing}")
    return filled, missing


def _step_validate(
    filled_bp: Blueprint,
    citizen_record: Optional[Dict],
    collected: Optional[Dict],
    missing: List[str],
) -> Dict[str, Any]:
    print("[Pipeline] Step 5 — Validator")
    report = validate_blueprint(filled_bp, citizen_record=citizen_record,
                                collected=collected, missing_fields=missing)
    print(f"  status={report['overall_status']}  alerts={len(report['alerts'])}")
    return report


def _step_render(filled_bp: Blueprint, output_path: str) -> None:
    print("[Pipeline] Step 6 — Renderer")
    render_blueprint(filled_bp, output_path)
    print(f"  PDF: {output_path}")


# ── Public API ────────────────────────────────────────────────────────────────

def run_analysis(
    pdf_path: str,
    citizen_record: Optional[Dict] = None,
    collected: Optional[Dict] = None,
) -> Dict[str, Any]:
    regions, _source = _step_layout(pdf_path)
    cls = _step_classify(pdf_path, citizen_record)
    document_type = cls.get("document_type", "Documento PA")
    bp, chat_q = _step_architect(pdf_path, regions, document_type, citizen_record)

    filled, missing = _step_fill(bp, citizen_record, collected)

    return {
        "document_type": document_type,
        "chat_opening": _build_chat_opening(document_type, chat_q),
        "chat_questions": chat_q,
        "blueprint": bp,
        "filled_blueprint": filled,
        "missing_fields": missing,
    }


def run_generation(
    pdf_path: str,
    workspace_dir: str,
    document_analysis: Dict[str, Any],
    citizen_record: Optional[Dict] = None,
    collected: Optional[Dict] = None,
    pdf_filename: str = "document.pdf",
) -> Tuple[str, Dict[str, Any]]:
    bp: Blueprint = document_analysis.get("blueprint")
    if bp is None:
        raise ValueError("document_analysis manca di 'blueprint'")

    filled, missing = _step_fill(bp, citizen_record, collected)
    report = _step_validate(filled, citizen_record, collected, missing)

    stem = Path(pdf_filename).stem
    output_path = str(Path(workspace_dir) / f"{stem}_filled.pdf")
    _step_render(filled, output_path)
    _save_run(pdf_filename, bp, filled, citizen_record, collected, report, output_path)

    return output_path, report


def _save_run(
    pdf_filename: str,
    bp: Blueprint,
    filled_bp: Blueprint,
    citizen_record: Optional[Dict],
    collected: Optional[Dict],
    report: Dict[str, Any],
    output_pdf: str,
) -> None:
    stem = Path(pdf_filename).stem
    run_dir = _make_run_dir(stem)

    shutil.copy2(output_pdf, run_dir / f"{stem}_filled.pdf")
    _write_json(run_dir / "blueprint.json", blueprint_to_dict(bp))
    _write_json(run_dir / "filled_blueprint.json", blueprint_to_dict(filled_bp))
    _write_json(run_dir / "citizen_record.json", citizen_record or {})
    _write_json(run_dir / "collected_data.json", collected or {})
    _write_json(run_dir / "validation.json", report)
    print(f"[Pipeline] Artefatti salvati in {run_dir}")
