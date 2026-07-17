"""
Motor de calificación asistida por IA, usando la API de Gemini (Google).

Nota para quien mantenga este código: este módulo requiere el paquete
`google-genai` (NO `google-generativeai`, que está descontinuado) y `pydantic`.
Instalar con: pip install google-genai pydantic

Requiere una variable de entorno GEMINI_API_KEY (o pasar api_key explícito),
obtenida gratis en https://aistudio.google.com/apikey

Este es el ÚNICO módulo del proyecto que depende de pydantic/google-genai.
Recibe y devuelve los tipos definidos en `schemas.py` (dataclasses puras),
para que el resto de la app se pueda probar sin estas dependencias.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from .prompt_builder import construir_instrucciones
from .schemas import DesgloseItem, EjemploCalificado, ResultadoCalificacion

# gemini-3.5-flash: modelo actual, multimodal (imagen + PDF nativo), gratuito
# en el free tier a la fecha de escritura (verificar en
# https://ai.google.dev/gemini-api/docs/pricing si cambia).
MODEL = "gemini-3.5-flash"


# ---- Esquema interno solo para pedirle a Gemini salida estructurada ----
# (se convierte a schemas.ResultadoCalificacion antes de devolver nada)

class _DesgloseItemSchema(BaseModel):
    criterio: str
    puntaje_obtenido: float
    puntaje_maximo: float
    comentario: str


class _ResultadoSchema(BaseModel):
    nombre_detectado: str = Field(
        description="Nombre del estudiante (o integrantes del grupo separados por "
        "coma, si es informe) tal como se identifica en el documento"
    )
    confianza_nombre: str = Field(description="'alta', 'media' o 'baja'")
    grupo_detectado: str = Field(default="", description="Número de grupo si aplica, o vacío")
    nota_sugerida: float
    desglose: list[_DesgloseItemSchema]
    observaciones: str


def _cliente(api_key: str | None = None) -> genai.Client:
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "Falta la API key de Gemini. Configúrala como variable de entorno "
            "GEMINI_API_KEY (en Streamlit Cloud: Settings -> Secrets)."
        )
    return genai.Client(api_key=key)


def calificar(
    tipo: str,  # "coloquio" | "informe"
    nombre_practica: str,
    rubrica_texto: str,
    puntaje_maximo: float,
    contenido: bytes,
    contenido_mime: str,  # "image/jpeg" | "image/png" | "application/pdf"
    nombres_candidatos: list[str] | None = None,
    ejemplos: list[EjemploCalificado] | None = None,
    api_key: str | None = None,
) -> ResultadoCalificacion:
    """Envía la rúbrica + ejemplos + el documento nuevo a Gemini y devuelve
    una sugerencia de calificación estructurada. NO escribe nada en el Excel;
    eso lo hace el módulo de escritura después de que Carla revise."""

    nombres_candidatos = nombres_candidatos or []
    ejemplos = ejemplos or []

    instrucciones = construir_instrucciones(
        tipo=tipo,
        nombre_practica=nombre_practica,
        rubrica_texto=rubrica_texto,
        puntaje_maximo=puntaje_maximo,
        nombres_candidatos=nombres_candidatos,
        num_ejemplos=len(ejemplos),
    )

    contents: list = [instrucciones]

    for i, ej in enumerate(ejemplos, start=1):
        contents.append(
            f"--- Ejemplo {i}: ya calificado por Carla con nota real "
            f"{ej.nota_asignada}/{puntaje_maximo} ---"
        )
        contents.append(types.Part.from_bytes(data=ej.data, mime_type=ej.mime_type))
        if ej.comentario:
            contents.append(f"Comentario de Carla sobre este ejemplo: {ej.comentario}")

    contents.append("--- Documento NUEVO a calificar ahora ---")
    contents.append(types.Part.from_bytes(data=contenido, mime_type=contenido_mime))

    client = _cliente(api_key)
    response = client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_ResultadoSchema,
            temperature=0.2,  # priorizamos consistencia sobre creatividad
        ),
    )
    r = _ResultadoSchema.model_validate_json(response.text)

    return ResultadoCalificacion(
        nombre_detectado=r.nombre_detectado,
        confianza_nombre=r.confianza_nombre,
        nota_sugerida=r.nota_sugerida,
        desglose=[
            DesgloseItem(
                criterio=d.criterio,
                puntaje_obtenido=d.puntaje_obtenido,
                puntaje_maximo=d.puntaje_maximo,
                comentario=d.comentario,
            )
            for d in r.desglose
        ],
        observaciones=r.observaciones,
        grupo_detectado=r.grupo_detectado or None,
    )
