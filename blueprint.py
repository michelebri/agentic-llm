from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Literal, Optional, Union, Dict, Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)


# ── Block types ───────────────────────────────────────────────────────────────

@dataclass
class TitleBlock:
    text: str
    kind: Literal["title"] = "title"


@dataclass
class SubtitleBlock:
    text: str
    kind: Literal["subtitle"] = "subtitle"


@dataclass
class HeadingBlock:
    text: str
    centered: bool = True
    kind: Literal["heading"] = "heading"


@dataclass
class ParagraphBlock:
    text: str
    align: Literal["left", "center", "right", "justify"] = "left"
    kind: Literal["paragraph"] = "paragraph"


@dataclass
class FilledParagraphBlock:
    template: str
    align: Literal["left", "center", "right", "justify"] = "left"
    kind: Literal["filled_paragraph"] = "filled_paragraph"


@dataclass
class ListBlock:
    intro: Optional[str] = None
    items: List[str] = field(default_factory=list)
    bullet: str = "•"
    kind: Literal["list"] = "list"


@dataclass
class TableBlock:
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    kind: Literal["table"] = "table"


@dataclass
class SignatureBlock:
    label: str = "Firma del dichiarante"
    place_date: bool = True
    kind: Literal["signature"] = "signature"


@dataclass
class SpacerBlock:
    mm_height: float = 6.0
    kind: Literal["spacer"] = "spacer"


@dataclass
class FootnoteBlock:
    text: str
    align: Literal["left", "center", "right"] = "left"
    kind: Literal["footnote"] = "footnote"


@dataclass
class ImageTextBlock:
    text: str
    kind: Literal["image_text"] = "image_text"


Block = Union[
    TitleBlock,
    SubtitleBlock,
    HeadingBlock,
    ParagraphBlock,
    FilledParagraphBlock,
    ListBlock,
    TableBlock,
    SignatureBlock,
    SpacerBlock,
    FootnoteBlock,
    ImageTextBlock,
]


# ── Blueprint container & state ───────────────────────────────────────────────

@dataclass
class Blueprint:
    document_type: str
    blocks: List[Block] = field(default_factory=list)
    lingua: str = "it"


@dataclass
class BlueprintState:
    pdf_path: str
    document_type: str = ""
    chat_opening: str = ""
    complexity: str = "simple"
    lingua: str = "it"
    regions: List[Dict[str, Any]] = field(default_factory=list)
    blueprint: Optional[Blueprint] = None
    filled_blueprint: Optional[Blueprint] = None
    chat_questions: List[Dict[str, str]] = field(default_factory=list)
    validation: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


# ── Serializzazione (per cache/log) ──────────────────────────────────────────

def block_to_dict(b: Block) -> Dict[str, Any]:
    return asdict(b)


def blueprint_to_dict(bp: Blueprint) -> Dict[str, Any]:
    return {
        "document_type": bp.document_type,
        "lingua": bp.lingua,
        "blocks": [block_to_dict(b) for b in bp.blocks],
    }


_BLOCK_CTORS = {
    "title": TitleBlock,
    "subtitle": SubtitleBlock,
    "heading": HeadingBlock,
    "paragraph": ParagraphBlock,
    "filled_paragraph": FilledParagraphBlock,
    "list": ListBlock,
    "table": TableBlock,
    "signature": SignatureBlock,
    "spacer": SpacerBlock,
    "footnote": FootnoteBlock,
    "image_text": ImageTextBlock,
}


def dict_to_block(d: Dict[str, Any]) -> Block:
    kind = d.get("kind")
    ctor = _BLOCK_CTORS.get(kind)
    if ctor is None:
        raise ValueError(f"Unknown block kind: {kind}")
    return ctor(**{k: v for k, v in d.items() if k != "kind" or kind == "kind"})


def dict_to_blueprint(d: Dict[str, Any]) -> Blueprint:
    blocks = [dict_to_block(b) for b in d.get("blocks", [])]
    return Blueprint(
        document_type=d.get("document_type", ""),
        blocks=blocks,
        lingua=d.get("lingua", "it"),
    )


# ── Renderer (Python puro, no LLM) ────────────────────────────────────────────

def _styles() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "BPTitle", parent=base["Title"], fontSize=14, leading=18,
            alignment=1, spaceAfter=10, fontName="Helvetica-Bold",
        ),
        "subtitle": ParagraphStyle(
            "BPSubtitle", parent=base["Normal"], fontSize=10, leading=13,
            alignment=1, spaceAfter=8, fontName="Helvetica-Bold",
        ),
        "heading": ParagraphStyle(
            "BPHeading", parent=base["Normal"], fontSize=12, leading=15,
            spaceBefore=6, spaceAfter=6, fontName="Helvetica-Bold",
        ),
        "heading_center": ParagraphStyle(
            "BPHeadingC", parent=base["Normal"], fontSize=12, leading=15,
            alignment=1, spaceBefore=6, spaceAfter=6, fontName="Helvetica-Bold",
        ),
        "paragraph": ParagraphStyle(
            "BPParagraph", parent=base["Normal"], fontSize=10, leading=13,
            alignment=0, spaceAfter=6,
        ),
        "paragraph_center": ParagraphStyle(
            "BPParagraphC", parent=base["Normal"], fontSize=10, leading=13,
            alignment=1, spaceAfter=6,
        ),
        "paragraph_justify": ParagraphStyle(
            "BPParagraphJ", parent=base["Normal"], fontSize=10, leading=13,
            alignment=4, spaceAfter=6,
        ),
        "filled": ParagraphStyle(
            "BPFilled", parent=base["Normal"], fontSize=10.5, leading=14,
            alignment=0, spaceAfter=6, textColor=colors.HexColor("#111"),
        ),
        "list_intro": ParagraphStyle(
            "BPListIntro", parent=base["Normal"], fontSize=10, leading=13,
            spaceAfter=4,
        ),
        "list_item": ParagraphStyle(
            "BPListItem", parent=base["Normal"], fontSize=10, leading=13,
            leftIndent=14, bulletIndent=4, spaceAfter=2,
        ),
        "signature_label": ParagraphStyle(
            "BPSignLabel", parent=base["Normal"], fontSize=9, leading=11,
            alignment=2, textColor=colors.HexColor("#555"),
        ),
        "place_date": ParagraphStyle(
            "BPPlaceDate", parent=base["Normal"], fontSize=10, leading=13,
            alignment=0, spaceAfter=2,
        ),
        "footnote": ParagraphStyle(
            "BPFootnote", parent=base["Normal"], fontSize=8, leading=10,
            textColor=colors.HexColor("#666"),
        ),
        "image_text": ParagraphStyle(
            "BPImgText", parent=base["Normal"], fontSize=10, leading=13,
            alignment=0, spaceAfter=6,
        ),
    }


def _align_to_style(styles: Dict[str, ParagraphStyle], align: str) -> ParagraphStyle:
    return {
        "left":    styles["paragraph"],
        "center":  styles["paragraph_center"],
        "justify": styles["paragraph_justify"],
        "right":   styles["paragraph"],  # raro, fallback left
    }.get(align, styles["paragraph"])


def _block_to_flowables(b: Block, styles: Dict[str, ParagraphStyle]) -> List[Any]:
    if isinstance(b, TitleBlock):
        return [Paragraph(b.text, styles["title"])]
    if isinstance(b, SubtitleBlock):
        return [Paragraph(b.text, styles["subtitle"])]
    if isinstance(b, HeadingBlock):
        return [Paragraph(b.text, styles["heading_center"] if b.centered else styles["heading"])]
    if isinstance(b, ParagraphBlock):
        return [Paragraph(b.text, _align_to_style(styles, b.align))]
    if isinstance(b, FilledParagraphBlock):
        return [Paragraph(b.template, styles["filled"])]
    if isinstance(b, ListBlock):
        flow = []
        if b.intro:
            flow.append(Paragraph(b.intro, styles["list_intro"]))
        for it in b.items:
            flow.append(Paragraph(f"{b.bullet} {it}", styles["list_item"]))
        return flow
    if isinstance(b, TableBlock):
        data = []
        if b.headers:
            data.append(b.headers)
        data.extend(b.rows or [])
        if not data:
            return []
        t = Table(data, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")) if b.headers else ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        return [t, Spacer(1, 4 * mm)]
    if isinstance(b, SignatureBlock):
        flow = [Spacer(1, 10 * mm)]
        if b.place_date:
            flow.append(Paragraph("Luogo e data: ______________________", styles["place_date"]))
        flow.append(Spacer(1, 6 * mm))
        flow.append(Paragraph("_______________________________", styles["signature_label"]))
        flow.append(Paragraph(b.label, styles["signature_label"]))
        return flow
    if isinstance(b, SpacerBlock):
        return [Spacer(1, b.mm_height * mm)]
    if isinstance(b, FootnoteBlock):
        return [Paragraph(b.text, styles["footnote"])]
    if isinstance(b, ImageTextBlock):
        return [Paragraph(b.text, styles["image_text"])]
    return []


def render_blueprint(bp: Blueprint, output_path: str) -> None:
    page_w, page_h = A4
    margin = 20 * mm

    doc = BaseDocTemplate(
        output_path, pagesize=A4,
        leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=margin,
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        showBoundary=0,
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame])])

    styles = _styles()
    flow = []
    for b in bp.blocks:
        flow.extend(_block_to_flowables(b, styles))
    doc.build(flow)


# ── Smoke test demo blueprint ─────────────────────────────────────────────────

def demo_blueprint() -> Blueprint:
    return Blueprint(
        document_type="Dichiarazione sostitutiva dell'atto di notorietà",
        blocks=[
            TitleBlock(text="DICHIARAZIONE SOSTITUTIVA DELL'ATTO DI NOTORIETÀ"),
            SubtitleBlock(text="DA PRESENTARE ALLA PUBBLICA AMMINISTRAZIONE O AI GESTORI DI PUBBLICI SERVIZI"),
            SpacerBlock(mm_height=4),
            FilledParagraphBlock(
                template=(
                    "Il/la sottoscritto/a <b>Mario Rossi</b> nato/a a <b>Roma (RM)</b> "
                    "il <b>12/03/1980</b> residente in <b>Via Roma 16, Roma (RM) 00100</b>,"
                ),
                align="justify",
            ),
            ParagraphBlock(
                text=(
                    "consapevole delle responsabilità penali, nel caso di dichiarazioni mendaci, "
                    "di formazione o uso di atti falsi, ai sensi dell'art. 76 del D.P.R. 28 dicembre 2000 n. 445,"
                ),
                align="justify",
            ),
            HeadingBlock(text="DICHIARA", centered=True),
            ParagraphBlock(text="Che le fotocopie dei seguenti documenti sono conformi agli originali depositati presso l'ente che li ha rilasciati:"),
            ListBlock(items=[
                "[DA CHIEDERE: documento_1]",
                "[DA CHIEDERE: documento_2]",
                "[DA CHIEDERE: documento_3]",
            ]),
            SpacerBlock(mm_height=6),
            ParagraphBlock(
                text=(
                    "Identità del dichiarante, all'ufficio competente via fax, tramite un incaricato, "
                    "oppure a mezzo posta."
                ),
                align="left",
            ),
            ParagraphBlock(
                text=(
                    "Caso in cui il dichiarante non sappia o non possa firmare: nessuna firma personalmente."
                ),
            ),
            SpacerBlock(mm_height=10),
            ParagraphBlock(text="Responsabile del trattamento dati è il/la Sig./ra: [DA CHIEDERE: responsabile_trattamento]"),
            ParagraphBlock(text="Recapito dell'ufficio al quale rivolgersi per richieste o lamentele: [DA CHIEDERE: telefono_ufficio]"),
            SignatureBlock(label="Firma del dichiarante", place_date=True),
            FootnoteBlock(text="V.1 – 12.1.2004", align="left"),
        ],
    )


if __name__ == "__main__":
    out = "blueprint_demo.pdf"
    render_blueprint(demo_blueprint(), out)
    print(f"Generato {out}")
