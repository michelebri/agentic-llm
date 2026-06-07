# Multi-Agent Document Generation System

Automated document generation from unstructured PDFs using a modular four-step pipeline with vision-language models and deterministic rule-based filling.

## Overview

This system transforms scanned or digital Italian public administration (PA) documents into clean, structured, fillable PDFs. It intelligently extracts document structure, classifies documents, and fills placeholders with data from citizen records and user input.

**Key Features:**
- 🔍 **Adaptive Layout Detection**: Hybrid native PDF extraction + OCR fallback
- 🤖 **Intelligent Document Understanding**: LLM-based classification and structure reconstruction
- 📝 **Deterministic Field Filling**: Rule-based substitution with complete provenance tracking
- ✅ **Comprehensive Validation**: Format checks, field completeness, cross-field consistency
- 🎨 **Clean PDF Rendering**: Flow-layout rendering for legibility and consistency
- 🔐 **Privacy-First**: Open-source models only, zero data retention

## Architecture

```
Step 1: Adaptive Layout Detection
    ├─ Native PDF extraction (PyMuPDF)
    └─ OCR Fallback (DeepSeek-OCR-2)
         ↓
Step 2: Document Understanding & Structure Reconstruction
    ├─ Document Classification (metadata + complexity)
    └─ Blueprint Extraction (typed logical blocks)
         ↓
Step 3: Rule-Based Field Instantiation
    └─ Deterministic field filling with provenance tracking
         ↓
Step 4: Validation & Rendering
    ├─ Rule-based quality checks
    └─ PDF rendering with consistent styling
```

## System Architecture

### Core Components

| File | Purpose |
|------|---------|
| `layout_detector.py` | Step 1: Extracts text regions from PDFs |
| `agents.py` | Step 2: Classifier & Blueprint Architect agents |
| `filler.py` | Step 3-4: Deterministic filling & validation |
| `blueprint.py` | Blueprint data structures and PDF rendering |
| `pa_database.py` | Citizen data management |
| `pipeline.py` | Pipeline orchestration |
| `app.py` | Flask web interface |

### 5-Agent Pipeline (LLM-based)

- **Lookup Agent**: Retrieves citizen data from database
- **Classifier Agent**: Identifies document type and complexity
- **Conflict Agent**: Resolves data inconsistencies
- **Filler Agent**: Deterministically fills fields (no LLM)
- **Verifier Agent**: Validates output integrity

## Installation

### Requirements

- Python 3.8+
- CUDA/GPU (recommended for OCR)

### Setup

```bash
# Clone repository
git clone https://github.com/yourusername/multi-agent-document-generation.git
cd multi-agent-document-generation

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up API key (optional, for remote LLM calls)
echo "your-api-key-here" > api.txt
```

## Usage

### Web Interface

```bash
python app.py
# Open http://localhost:5000
```

### Programmatic Usage

```python
from pipeline import run_pipeline

result = run_pipeline(
    pdf_path="path/to/document.pdf",
    citizen_record={
        "anagrafe": {
            "nome": "Mario",
            "cognome": "Rossi",
            "data_nascita": "1990-01-15",
            ...
        }
    },
    collected_data={
        "custom_field": "value"
    }
)

print(result.validation)  # Check validation results
print(result.output_pdf)  # Path to generated PDF
```

## Configuration

### Environment Variables

```bash
# API endpoint for LLM calls
export REGOLO_BASE_URL="https://api.regolo.ai/v1"

# Model names
export OCR_MODEL_NAME="deepseek-ocr-2"
export CLASSIFIER_MODEL="gemma4-31b"
```

### API Key

Store your API key in `api.txt`:

```
your-api-key-here
```

**Security**: `api.txt` is in `.gitignore` and will not be committed.

## Pipeline Outputs

Each run generates artifacts in `experiments/results/{document_type}_{timestamp}/`:

```
├── blueprint.json              # Extracted structure
├── citizen_record.json         # Retrieved citizen data
├── collected_data.json         # User-provided answers
├── filled_blueprint.json       # Blueprint with data filled
├── validation.json             # Validation results
└── {document_type}_filled.pdf  # Final output PDF
```

## Supported Block Types

The blueprint system supports:

- **title** - Main document title (centered, bold)
- **subtitle** - Document subtitle
- **heading** - Section headings
- **paragraph** - Static text (boilerplate, legal text)
- **filled_paragraph** - Dynamic content with `[DA CHIEDERE: field_id]` markers
- **list** - Bulleted/enumerated items
- **table** - Tabular data
- **signature** - Signature line + place/date
- **spacer** - Vertical spacing
- **footnote** - Small legal notes
- **image_text** - Text extracted from images

## Field Markers

Dynamic fields use the marker syntax:

```
[DA CHIEDERE: field_id]
```

Examples:

```
Il sottoscritto [DA CHIEDERE: nome] [DA CHIEDERE: cognome],
nato a [DA CHIEDERE: luogo_nascita] il [DA CHIEDERE: data_nascita].
```

**Available Standard Fields:**

- `nome`, `cognome`
- `data_nascita`, `luogo_nascita`, `provincia_nascita`
- `indirizzo`, `comune_residenza`, `cap`, `provincia_residenza`
- `codice_fiscale`, `stato_civile`
- Custom fields per document type

## Validation Rules

The validator checks:

1. **Completeness**: All mandatory fields are filled
2. **Format Constraints**:
   - Codice Fiscale: 16 alphanumeric characters
   - Dates: DD/MM/YYYY format + plausibility
   - CAP: 5 digits
   - Province: 2-letter codes
3. **Grammatical Concordance**: Gender agreement (M/F)
4. **Cross-Field Consistency** (planned): Age ↔ birth date alignment

## Examples

### Example 1: Birth Declaration (Dichiarazione di Nascita)

Input PDF → Extracted Regions → Classified as "Dichiarazione di Nascita di un Figlio"
→ Blueprint with 15 blocks → Filled with citizen + user data → Validated PDF

### Example 2: Sworn Statement (Dichiarazione Sostitutiva)

Input PDF → Classified as "Dichiarazione sostitutiva di atto di notorietà"
→ Blueprint with list items → User provides document list → PDF with enumerated items

## Methodology

See [METHODOLOGY_ALIGNMENT.md](METHODOLOGY_ALIGNMENT.md) for detailed comparison between the academic methodology and implementation.

Key paper claims:
- ✅ Adaptive layout detection with hybrid native/OCR
- ✅ Function calling for structured LLM outputs
- ✅ Deterministic field filling without LLM variance
- ✅ Complete provenance tracking (partial implementation)
- ⚠️ Grammatical concordance validation (incomplete)
- ⚠️ Cross-field consistency checks (not yet implemented)

## Limitations

1. **Model Variance**: Blueprint reconstruction may collapse enumerated lists into single placeholders. Mitigation: use Blueprint pre-computation.

2. **Language**: Currently optimized for Italian PA documents. Extensible to other languages via configuration.

3. **Handwriting**: OCR distinguishes printed vs. handwritten text but validation doesn't currently use this information.

## Performance

- **Layout Detection**: ~1-3 seconds (native PDF) | ~5-10 seconds (OCR)
- **Classification**: ~2-3 seconds (with caching)
- **Blueprint Extraction**: ~10-15 seconds (with caching)
- **Field Filling**: <1 second
- **Validation**: <1 second
- **Rendering**: ~1-2 seconds

**Total Pipeline**: 1-2 minutes (first run) | 5-10 seconds (with Blueprint pre-computation)

## Troubleshooting

### API Key Not Found

```
Error: API key not found. Create api.txt with your API key.
```

**Fix**: `echo "your-key" > api.txt`

### OCR Timeout

**Fix**: Increase timeout in `layout_detector.py`:

```python
resp = requests.post(..., timeout=300)  # 5 minutes
```

### Low OCR Confidence

If OCR confidence is below 0.7, the system flags it in validation alerts.

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/improvement`)
3. Commit changes (`git commit -am 'Add improvement'`)
4. Push to branch (`git push origin feature/improvement`)
5. Open a Pull Request

## License

MIT License - See LICENSE file for details

## Citation

If you use this system in research, please cite:

```bibtex
@software{brienza2024multiagentagent,
  title={Multi-Agent Document Generation System},
  author={Brienza, Michele},
  year={2024},
  url={https://github.com/yourusername/multi-agent-document-generation}
}
```

## Contact

- **Author**: Michele Brienza
- **Email**: michelebrienza1997@gmail.com
- **Issues**: [GitHub Issues](https://github.com/yourusername/multi-agent-document-generation/issues)

## Roadmap

- [ ] Grammatical concordance validation
- [ ] Cross-field consistency checks (age ↔ birth date)
- [ ] Email/phone validation
- [ ] Handwriting detection in validation
- [ ] Multi-language support (EN, FR, ES, DE)
- [ ] Document template management UI
- [ ] Audit trail export
- [ ] Batch processing
- [ ] REST API expansion
