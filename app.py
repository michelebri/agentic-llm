import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from flask import Flask, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.utils import secure_filename

from llm_core import (
    chat_reply,
    detect_conflicts,
    lookup_richiedente,
    set_logger,
    verify_document,
)
from pipeline import run_analysis, run_generation
from provenance import ProvenanceLog, Source
from agent_log import AgentLogger

app = Flask(__name__)
secret_key = os.environ.get("SECRET_KEY")
if not secret_key:
    raise RuntimeError("SECRET_KEY environment variable is required")
app.secret_key = secret_key
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

ALLOWED_EXTENSIONS = {"pdf"}
WORKSPACES: dict[str, dict] = {}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_workspace():
    if "workspace_id" not in session:
        session["workspace_id"] = str(uuid.uuid4())
    workspace_id = session["workspace_id"]
    workspace = WORKSPACES.get(workspace_id)
    if workspace is None:
        workspace_dir = Path(tempfile.mkdtemp(prefix=f"docgen_{workspace_id}_"))
        workspace = {
            "workspace_id": workspace_id,
            "dir": workspace_dir,
            "pdf_path": None,
            "pdf_filename": None,
            "nome_richiedente": "",
            "cognome_richiedente": "",
            "document_analysis": None,
            "citizen_record": None,
            "conflicts": [],
            "chat_history": [],          # list of {role, content} for LLM
            "collected_data": {},        # data gathered in chat
            "provenance": ProvenanceLog(),
            "agent_log": AgentLogger(),
            "output_pdf": None,
        }
        WORKSPACES[workspace_id] = workspace
    return workspace


def cleanup_workspace():
    workspace_id = session.get("workspace_id")
    if not workspace_id:
        return
    workspace = WORKSPACES.pop(workspace_id, None)
    if workspace is not None:
        shutil.rmtree(workspace["dir"], ignore_errors=True)




def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── Hooks ──────────────────────────────────────────────────────────────────────

@app.before_request
def _attach_agent_logger():
    workspace_id = session.get("workspace_id")
    if workspace_id and workspace_id in WORKSPACES:
        set_logger(WORKSPACES[workspace_id].get("agent_log"))
    else:
        set_logger(None)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    cleanup_workspace()
    session.clear()
    session["workspace_id"] = str(uuid.uuid4())
    workspace = get_workspace()

    if "file" not in request.files:
        flash("Nessun file selezionato", "error")
        return redirect(url_for("index"))

    file = request.files["file"]
    nome = request.form.get("nome", "").strip()
    cognome = request.form.get("cognome", "").strip()

    if not nome or not cognome:
        flash("Nome e cognome del richiedente sono obbligatori", "error")
        return redirect(url_for("index"))

    if not file.filename:
        flash("Nessun file selezionato", "error")
        return redirect(url_for("index"))

    if not allowed_file(file.filename):
        flash("Sono ammessi solo file PDF", "error")
        return redirect(url_for("index"))

    filename = secure_filename(file.filename)
    pdf_path = workspace["dir"] / f"{uuid.uuid4()}_{filename}"
    file.save(pdf_path)

    workspace["pdf_path"] = str(pdf_path)
    workspace["pdf_filename"] = filename
    workspace["nome_richiedente"] = nome
    workspace["cognome_richiedente"] = cognome

    # Lookup citizen in PA database
    lookup_result = lookup_richiedente(nome, cognome)
    workspace["lookup_result"] = lookup_result

    candidates = lookup_result.get("candidates", [])
    if len(candidates) == 1:
        # Auto-select unique match
        chosen = candidates[0]
        workspace["citizen_record"] = chosen
        conflicts = detect_conflicts(chosen)
        workspace["conflicts"] = conflicts
        _record_citizen_provenance(workspace, chosen)
    elif len(candidates) > 1:
        # Multiple matches — let user pick
        return redirect(url_for("conferma_cittadino_get"))

    return _proceed_to_analysis(workspace)


def _record_citizen_provenance(workspace, citizen_record):
    provenance: ProvenanceLog = workspace["provenance"]
    citizen_id = citizen_record.get("citizen_id", "")
    a = citizen_record.get("anagrafe") or {}
    sc = citizen_record.get("stato_civile") or {}
    ae = citizen_record.get("agenzia_entrate") or {}

    for fld in ("nome", "cognome", "data_nascita", "luogo_nascita",
                "provincia_nascita", "sesso", "indirizzo",
                "comune_residenza", "provincia_residenza", "cap"):
        if a.get(fld):
            provenance.add(fld, a[fld], Source.ANAGRAFE, citizen_id=citizen_id)

    if ae:
        for fld in ("codice_fiscale", "indirizzo_fiscale", "comune_fiscale", "cap_fiscale"):
            if ae.get(fld):
                provenance.add(fld, ae[fld], Source.AGENZIA_ENTRATE, citizen_id=citizen_id)

    if sc:
        provenance.add("stato_civile", sc.get("stato_civile", ""),
                       Source.STATO_CIVILE, citizen_id=citizen_id)


@app.route("/conferma_cittadino", methods=["GET"])
def conferma_cittadino_get():
    workspace = get_workspace()
    lookup_result = workspace.get("lookup_result")
    if not lookup_result:
        return redirect(url_for("index"))
    return render_template(
        "conferma_cittadino.html",
        candidates=lookup_result["candidates"],
        reasoning=lookup_result["reasoning"],
    )


@app.route("/conferma_cittadino", methods=["POST"])
def conferma_cittadino_post():
    workspace = get_workspace()
    lookup_result = workspace.get("lookup_result")
    if not lookup_result:
        return redirect(url_for("index"))

    scelta = request.form.get("scelta")
    citizen_id = request.form.get("citizen_id")

    if scelta == "nessuno" or not citizen_id:
        workspace["citizen_record"] = None
    else:
        chosen = next(
            (c for c in lookup_result["candidates"] if c["anagrafe"]["id"] == citizen_id),
            None,
        )
        if not chosen:
            flash("Selezione non valida", "error")
            return redirect(url_for("conferma_cittadino_get"))

        workspace["citizen_record"] = chosen
        _record_citizen_provenance(workspace, chosen)

        conflicts = detect_conflicts(chosen)
        workspace["conflicts"] = conflicts
        if conflicts:
            return redirect(url_for("risolvi_conflitto_get"))

    return _proceed_to_analysis(workspace)


def _proceed_to_analysis(workspace):
    pdf_path = workspace["pdf_path"]

    try:
        analysis = run_analysis(
            pdf_path,
            citizen_record=workspace.get("citizen_record"),
        )
    except Exception as exc:
        print(f"[WARN] Document analysis failed: {exc}")
        analysis = {
            "document_type": "Documento PA",
            "chat_opening": "Come posso aiutarti a compilare questo documento?",
            "chat_questions": [],
            "blueprint": None,
            "filled_blueprint": None,
            "missing_fields": [],
        }

    workspace["document_analysis"] = analysis

    if not workspace.get("citizen_record"):
        return redirect(url_for("dati_anagrafici_get"))

    _init_chat(workspace)
    return redirect(url_for("chat_page"))


def _init_chat(workspace):
    """Inizializza la chat history e filtra le chat_questions già coperte dal citizen_record."""
    analysis = workspace.get("document_analysis") or {}

    # Rimuovi dalle chat_questions i campi già coperti dai dati anagrafici
    citizen_record = workspace.get("citizen_record") or {}
    a = citizen_record.get("anagrafe") or {}
    ae = citizen_record.get("agenzia_entrate") or {}
    sc = citizen_record.get("stato_civile") or {}
    covered = {k for d in (a, ae, sc) for k, v in d.items() if v}

    collected = workspace.get("collected_data") or {}
    covered = covered | set(collected.keys())

    chat_questions = analysis.get("chat_questions", [])
    filtered = [q for q in chat_questions if q.get("field_id") not in covered]
    analysis["chat_questions"] = filtered

    workspace["chat_history"] = [
        {"role": "assistant", "content": analysis.get("chat_opening", "Come posso aiutarti?")}
    ]


ANAGRAFE_FORM_FIELDS = [
    ("nome",              "Nome",              "text",  True),
    ("cognome",           "Cognome",           "text",  True),
    ("data_nascita",      "Data di nascita",   "date",  True),
    ("luogo_nascita",     "Comune di nascita", "text",  True),
    ("provincia_nascita", "Provincia (sigla)", "text",  True),
    ("codice_fiscale",    "Codice fiscale",    "text",  True),
    ("indirizzo",         "Indirizzo",         "text",  False),
    ("comune_residenza",  "Comune residenza",  "text",  False),
    ("cap",               "CAP",               "text",  False),
]


@app.route("/dati_anagrafici", methods=["GET"])
def dati_anagrafici_get():
    workspace = get_workspace()
    if not workspace.get("document_analysis"):
        return redirect(url_for("index"))
    nome = workspace.get("nome_richiedente", "")
    cognome = workspace.get("cognome_richiedente", "")
    return render_template(
        "dati_anagrafici.html",
        fields=ANAGRAFE_FORM_FIELDS,
        nome_pre=nome,
        cognome_pre=cognome,
    )


@app.route("/dati_anagrafici", methods=["POST"])
def dati_anagrafici_post():
    workspace = get_workspace()
    if not workspace.get("document_analysis"):
        return redirect(url_for("index"))

    # Costruisce citizen_record sintetico dai dati inseriti
    data_nascita = request.form.get("data_nascita", "")
    # Normalizza data: se arriva da <input type="date"> è YYYY-MM-DD, converti in gg/mm/aaaa
    if data_nascita and "-" in data_nascita:
        parts = data_nascita.split("-")
        if len(parts) == 3:
            data_nascita = f"{parts[2]}/{parts[1]}/{parts[0]}"

    anagrafe = {
        "nome":              request.form.get("nome", "").strip(),
        "cognome":           request.form.get("cognome", "").strip(),
        "data_nascita":      data_nascita,
        "luogo_nascita":     request.form.get("luogo_nascita", "").strip(),
        "provincia_nascita": request.form.get("provincia_nascita", "").strip().upper(),
        "indirizzo":         request.form.get("indirizzo", "").strip(),
        "comune_residenza":  request.form.get("comune_residenza", "").strip(),
        "cap":               request.form.get("cap", "").strip(),
    }
    citizen_record = {
        "citizen_id":       "manual",
        "anagrafe":         anagrafe,
        "agenzia_entrate":  {"codice_fiscale": request.form.get("codice_fiscale", "").strip().upper()},
        "stato_civile":     {},
    }
    workspace["citizen_record"] = citizen_record

    # Pre-popola collected_data con tutti gli alias comuni usati nei placeholder
    # così format_map li risolve senza chiederli in chat
    a = anagrafe
    cf = request.form.get("codice_fiscale", "").strip().upper()
    workspace["collected_data"] = {
        # chiavi canoniche
        "nome": a["nome"], "cognome": a["cognome"],
        "data_nascita": a["data_nascita"], "luogo_nascita": a["luogo_nascita"],
        "provincia_nascita": a["provincia_nascita"], "codice_fiscale": cf,
        "indirizzo": a["indirizzo"], "comune_residenza": a["comune_residenza"], "cap": a["cap"],
        # alias abbreviati usati spesso nei placeholder LLM
        "luogo": a["luogo_nascita"], "prov": a["provincia_nascita"],
        "data": a["data_nascita"], "cf": cf,
        # prefisso genitore/dichiarante
        "genitore_nome": a["nome"], "genitore_cognome": a["cognome"],
        "genitore_data_nascita": a["data_nascita"], "genitore_luogo_nascita": a["luogo_nascita"],
        "genitore_prov_nascita": a["provincia_nascita"], "genitore_cf": cf,
        "dichiarante_nome": a["nome"], "dichiarante_cognome": a["cognome"],
        "dichiarante_data_nascita": a["data_nascita"], "dichiarante_luogo_nascita": a["luogo_nascita"],
        "dichiarante_prov_nascita": a["provincia_nascita"],
    }

    _init_chat(workspace)
    return redirect(url_for("chat_page"))


@app.route("/risolvi_conflitto", methods=["GET"])
def risolvi_conflitto_get():
    workspace = get_workspace()
    conflicts = workspace.get("conflicts")
    if not conflicts:
        return _proceed_to_analysis(workspace)
    return render_template("risolvi_conflitto.html", conflicts=conflicts)


@app.route("/risolvi_conflitto", methods=["POST"])
def risolvi_conflitto_post():
    workspace = get_workspace()
    conflicts = workspace.get("conflicts") or []
    provenance: ProvenanceLog = workspace["provenance"]
    citizen_id = (workspace.get("citizen_record") or {}).get("citizen_id")

    n = int(request.form.get("n_conflicts", 0))
    for i in range(n):
        choice = request.form.get(f"conflict_{i}")
        field = request.form.get(f"field_{i}")
        value_a = request.form.get(f"value_a_{i}")
        value_b = request.form.get(f"value_b_{i}")
        source_a = request.form.get(f"source_a_{i}")
        source_b = request.form.get(f"source_b_{i}")
        chosen_value = value_a if choice == "a" else value_b
        chosen_source = source_a if choice == "a" else source_b

        provenance.add(
            field, chosen_value, Source.USER_CONFLICT_RESOLUTION,
            citizen_id=citizen_id,
            notes=f"Conflitto: {source_a}='{value_a}' vs {source_b}='{value_b}'. Scelto: {chosen_source}.",
        )
        # Apply resolution to citizen record
        if workspace.get("citizen_record"):
            rec = workspace["citizen_record"]
            for section in ("anagrafe", "agenzia_entrate", "stato_civile"):
                d = rec.get(section)
                if isinstance(d, dict) and field in d:
                    d[field] = chosen_value

    return _proceed_to_analysis(workspace)


# ── Chat ───────────────────────────────────────────────────────────────────────

@app.route("/chat")
def chat_page():
    workspace = get_workspace()
    analysis = workspace.get("document_analysis")
    if not analysis:
        return redirect(url_for("index"))

    chat_history = workspace.get("chat_history", [])
    return render_template(
        "chat.html",
        document_type=analysis.get("document_type", "Documento PA"),
        chat_history=chat_history,
    )


@app.route("/chat/message", methods=["POST"])
def chat_message():
    workspace = get_workspace()
    analysis = workspace.get("document_analysis")
    if not analysis:
        return jsonify({"error": "session expired"}), 400

    user_message = request.json.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "empty message"}), 400

    chat_history = workspace.get("chat_history", [])
    # Build LLM-compatible history (skip the initial assistant opening since it's in system)
    llm_history = [h for h in chat_history if h["role"] != "assistant" or chat_history.index(h) > 0]

    result = chat_reply(
        history=llm_history,
        user_message=user_message,
        document_context=analysis,
        citizen_record=workspace.get("citizen_record"),
    )

    # Update history
    chat_history.append({"role": "user", "content": user_message})
    chat_history.append({"role": "assistant", "content": result["reply"]})
    workspace["chat_history"] = chat_history

    # Merge collected data
    collected = workspace.get("collected_data", {})
    collected.update(result.get("collected", {}))
    workspace["collected_data"] = collected

    return jsonify({
        "reply": result["reply"],
        "ready": result["ready"],
    })


@app.route("/generating")
def generating():
    return render_template("generating.html")


@app.route("/generate", methods=["POST"])
def generate():
    workspace = get_workspace()
    analysis = workspace.get("document_analysis")
    citizen_record = workspace.get("citizen_record")
    collected = workspace.get("collected_data", {})

    if not analysis or not analysis.get("blueprint"):
        flash("Sessione scaduta o analisi non disponibile", "error")
        return redirect(url_for("index"))

    try:
        output_path, report = run_generation(
            pdf_path=workspace["pdf_path"],
            workspace_dir=str(workspace["dir"]),
            document_analysis=analysis,
            citizen_record=citizen_record,
            collected=collected,
            pdf_filename=workspace["pdf_filename"],
        )
    except Exception as exc:
        flash(f"Errore durante la generazione: {exc}", "error")
        return redirect(url_for("index"))

    workspace["output_pdf"] = output_path
    workspace["verification_report"] = report

    return redirect(url_for("result"))


@app.route("/verifica", methods=["GET"])
def verifica():
    workspace = get_workspace()
    report = workspace.get("verification_report")
    if not report:
        return redirect(url_for("index"))
    return render_template(
        "verifica.html",
        checks=report.get("checks", []),
        alerts=report.get("alerts", []),
        overall_status=report["overall_status"],
    )


@app.route("/verify_now", methods=["POST"])
def verify_now():
    workspace = get_workspace()
    output_pdf = workspace.get("output_pdf")
    if not output_pdf or not os.path.exists(output_pdf):
        return jsonify({"error": "PDF non trovato"}), 400
    report = verify_document(output_pdf, workspace.get("citizen_record"))
    workspace["verification_report"] = report
    return jsonify(report)


@app.route("/audit_log")
def audit_log():
    workspace = get_workspace()
    provenance: ProvenanceLog = workspace["provenance"]
    payload = {
        "richiedente": {
            "nome": workspace.get("nome_richiedente"),
            "cognome": workspace.get("cognome_richiedente"),
        },
        "citizen_id": (workspace.get("citizen_record") or {}).get("citizen_id"),
        "provenance": provenance.summary(),
        "verification": workspace.get("verification_report"),
        "conflicts": workspace.get("conflicts"),
        "collected_data": workspace.get("collected_data"),
    }
    audit_path = workspace["dir"] / "audit_log.json"
    write_json(str(audit_path), payload)
    return send_file(audit_path, as_attachment=True, download_name="audit_log.json")


@app.route("/result")
def result():
    workspace = get_workspace()
    output_pdf = workspace.get("output_pdf")
    if not output_pdf or not os.path.exists(output_pdf):
        flash("Nessun PDF generato trovato", "error")
        return redirect(url_for("index"))

    provenance: ProvenanceLog = workspace["provenance"]
    return render_template(
        "result.html",
        pdf_filename=os.path.basename(output_pdf),
        provenance=provenance.summary(),
        has_audit=True,
    )


@app.route("/download/<filename>")
def download_file(filename):
    workspace = get_workspace()
    output_pdf = workspace.get("output_pdf")
    if not output_pdf or not os.path.exists(output_pdf):
        flash("File not found", "error")
        return redirect(url_for("index"))

    actual_basename = os.path.basename(output_pdf)
    if os.path.basename(secure_filename(filename)) != actual_basename:
        flash("Invalid filename", "error")
        return redirect(url_for("index"))

    return send_file(output_pdf, as_attachment=True, download_name=actual_basename)


@app.route("/reset", methods=["POST"])
def reset():
    cleanup_workspace()
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_ENV") == "development"
    host = "127.0.0.1" if debug_mode else "0.0.0.0"
    app.run(host=host, port=5000, debug=debug_mode)
