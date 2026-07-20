"""
Anota el PDF del informe original directamente -- parecido a cuando Carla lo
abre en Edge y comenta a mano -- en vez de generarle una página nueva
formal. Por cada criterio de la rúbrica se agrega una notita de texto con el
puntaje, cerca de la página donde la IA identificó esa sección (si la pudo
ubicar). El total y el comentario general quedan como una notita en la
primera página, a modo de "sello" de calificación.

Usa anotaciones nativas de PDF (FreeText, vía pypdf) -- son las mismas que
usa cualquier lector de PDF para mostrar comentarios: aparecen como
cuadros de texto que se pueden mover, editar o borrar en Edge/Acrobat/etc.
"""

from __future__ import annotations

import io
from collections import defaultdict

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import FreeText

from .schemas import ResultadoCalificacion

MIME_PDF = "application/pdf"

ANCHO_NOTA = 190
ALTO_NOTA = 70
MARGEN = 12
MAX_COMENTARIO = 220  # las notitas no se autoajustan -- se recorta para que no se salga del cuadro


def _recortar(texto: str, limite: int = MAX_COMENTARIO) -> str:
    texto = (texto or "").strip()
    return texto if len(texto) <= limite else texto[: limite - 1].rstrip() + "…"


def _rect_esquina_superior_derecha(mediabox, offset_index: int) -> tuple[float, float, float, float]:
    x2 = float(mediabox.right) - MARGEN
    x1 = x2 - ANCHO_NOTA
    y2 = float(mediabox.top) - MARGEN - offset_index * (ALTO_NOTA + 8)
    y1 = y2 - ALTO_NOTA
    return (x1, y1, x2, y2)


def anotar_informe_calificado(
    contenido_original: bytes,
    contenido_mime: str,
    resultado: ResultadoCalificacion,
    puntaje_maximo: float,
    identificador: str,
) -> bytes | None:
    """Devuelve el PDF original con anotaciones agregadas, o None si el
    original no es un PDF válido (ej. era un .docx) -- en ese caso no hay
    documento que anotar; el detalle técnico queda solo en la app."""
    if contenido_mime != MIME_PDF:
        return None

    reader = PdfReader(io.BytesIO(contenido_original))
    writer = PdfWriter()
    writer.append(reader)
    num_paginas = len(writer.pages)

    # Nota general: identificador + total + comentario, en la esquina
    # superior de la primera página (lo primero que se ve al abrir).
    resumen = (
        f"{identificador}\n"
        f"TOTAL: {resultado.nota_sugerida:g} / {puntaje_maximo:g}\n\n"
        f"{_recortar(resultado.observaciones, 260)}"
    )
    nota_general = FreeText(
        text=resumen,
        rect=_rect_esquina_superior_derecha(writer.pages[0].mediabox, 0),
        font="Helvetica",
        font_size="9pt",
        background_color="fff3cd",
        border_color="d4a017",
    )
    writer.add_annotation(page_number=0, annotation=nota_general)

    # Una notita por criterio, cerca de la página donde la IA dijo que
    # aparece esa sección. Si no se pudo ubicar la página, se agrupan al
    # final para que no se pierda ninguna.
    contador_por_pagina: dict[int, int] = defaultdict(int)
    contador_por_pagina[0] = 1  # ya usamos un espacio en la página 1 para la nota general
    sin_pagina = []

    for item in resultado.desglose:
        pagina = getattr(item, "pagina", None)
        if pagina and 1 <= pagina <= num_paginas:
            idx = pagina - 1
        else:
            sin_pagina.append(item)
            continue
        texto = f"{item.criterio}: {item.puntaje_obtenido:g}/{item.puntaje_maximo:g}\n{_recortar(item.comentario)}"
        nota = FreeText(
            text=texto,
            rect=_rect_esquina_superior_derecha(writer.pages[idx].mediabox, contador_por_pagina[idx]),
            font="Helvetica",
            font_size="8pt",
            background_color="e8f4fd",
            border_color="2c7fb8",
        )
        writer.add_annotation(page_number=idx, annotation=nota)
        contador_por_pagina[idx] += 1

    if sin_pagina:
        texto = "Otros criterios:\n" + "\n".join(
            f"- {i.criterio}: {i.puntaje_obtenido:g}/{i.puntaje_maximo:g} — {_recortar(i.comentario, 80)}"
            for i in sin_pagina
        )
        idx_final = num_paginas - 1
        nota = FreeText(
            text=_recortar(texto, 500),
            rect=_rect_esquina_superior_derecha(writer.pages[idx_final].mediabox, contador_por_pagina[idx_final]),
            font="Helvetica",
            font_size="8pt",
            background_color="e8f4fd",
            border_color="2c7fb8",
        )
        writer.add_annotation(page_number=idx_final, annotation=nota)

    salida = io.BytesIO()
    writer.write(salida)
    return salida.getvalue()
