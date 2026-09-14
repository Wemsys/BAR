"""
Generación de reportes PDF a partir de un DataFrame ya filtrado (por
fecha y/o moneda) desde el dashboard.

Se usa `reportlab` porque es una librería 100% Python (sin binarios del
sistema como wkhtmltopdf), lo que la hace trivial de instalar en
Streamlit Community Cloud, Docker o Coolify sin tocar el Dockerfile.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# Salvaguarda: un PDF con demasiadas filas se vuelve enorme y lento de
# generar/abrir. Si se supera este límite, se trunca y se avisa en el
# propio PDF (para el histórico completo siempre está el CSV).
MAX_ROWS_PER_PDF = 2000


def dataframe_to_pdf_bytes(
    df: Optional[pd.DataFrame],
    title: str,
    filters_desc: str = "",
) -> bytes:
    """Convierte un DataFrame a los bytes de un PDF con una tabla,
    título, fecha de generación y los filtros aplicados."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        topMargin=1.3 * cm,
        bottomMargin=1.3 * cm,
        leftMargin=1.0 * cm,
        rightMargin=1.0 * cm,
        title=title,
    )
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(title, styles["Title"]))
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    elements.append(Paragraph(f"Generado: {generated}", styles["Normal"]))
    if filters_desc:
        elements.append(Paragraph(f"Filtros aplicados: {filters_desc}", styles["Normal"]))
    elements.append(Spacer(1, 0.4 * cm))

    if df is None or df.empty:
        elements.append(Paragraph("No hay datos para este rango/selección.", styles["Normal"]))
        doc.build(elements)
        return buffer.getvalue()

    truncated = len(df) > MAX_ROWS_PER_PDF
    if truncated:
        df = df.head(MAX_ROWS_PER_PDF)

    note = f"Total de registros incluidos: {len(df)}"
    if truncated:
        note += f" (truncado a {MAX_ROWS_PER_PDF} filas; descarga el CSV para el histórico completo)"
    elements.append(Paragraph(note, styles["Normal"]))
    elements.append(Spacer(1, 0.3 * cm))

    header_style = ParagraphStyle(
        "header", fontSize=6.5, leading=8, textColor=colors.white, fontName="Helvetica-Bold"
    )
    cell_style = ParagraphStyle("cell", fontSize=6, leading=7.5)

    columns = list(df.columns)
    data = [[Paragraph(str(c), header_style) for c in columns]]
    # fillna antes de astype(str): con columnas 100% None, pandas puede
    # dejar NaN (float) en vez de la cadena "None" tras astype(str).
    safe_df = df.fillna("").astype(str)
    for row in safe_df.values.tolist():
        data.append([Paragraph(v, cell_style) for v in row])

    col_width = doc.width / max(len(columns), 1)
    table = Table(data, colWidths=[col_width] * len(columns), repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    elements.append(table)

    doc.build(elements)
    return buffer.getvalue()
