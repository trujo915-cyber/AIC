"""
Orquesta el flujo completo para un lote de documentos (fotos de coloquio o
PDFs de informe): llama al motor de IA, empareja el nombre detectado contra
el roster real, y arma una lista de resultados lista para la pantalla de
revisión -- incluyendo por qué cada ítem sí o no necesita que Carla lo mire
con más atención.

La función de calificación (`calificar_fn`) se recibe como parámetro -- por
defecto es `ai_client.calificar`, pero para pruebas se le puede pasar
cualquier función con la misma firma. Así toda esta orquestación se puede
probar sin llamar a la API real de Gemini.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .excel_parser import Estudiante, HojaDetectada, Practica
from .name_matcher import Coincidencia, emparejar
from .schemas import EjemploCalificado, ResultadoCalificacion

UMBRAL_AMBIGUEDAD = 0.08  # si el 2do candidato queda a menos de esto del 1ro, es ambiguo


@dataclass
class ItemRevision:
    archivo: str
    resultado_ia: ResultadoCalificacion
    coincidencias: list[Coincidencia]
    estudiante_sugerido: Estudiante | None
    requiere_atencion: bool
    motivos: list[str] = field(default_factory=list)


def _evaluar_atencion_coloquio(
    resultado: ResultadoCalificacion, coincidencias: list[Coincidencia]
) -> tuple[bool, list[str]]:
    """Coloquio: la señal de confianza es el emparejamiento por nombre individual."""
    motivos = []

    if resultado.confianza_nombre != "alta":
        motivos.append("la IA no está segura de haber leído bien el nombre")

    mejor = coincidencias[0] if coincidencias else None
    if mejor is None or mejor.nivel != "alta":
        motivos.append("el nombre no coincide con claridad contra el roster")
    elif len(coincidencias) > 1 and (mejor.score - coincidencias[1].score) < UMBRAL_AMBIGUEDAD:
        motivos.append(f"nombre ambiguo: también podría ser '{coincidencias[1].nombre_roster}'")

    if resultado.observaciones:
        motivos.append(f"la IA dejó una observación: {resultado.observaciones}")

    return (len(motivos) > 0, motivos)


def _evaluar_atencion_informe(
    resultado: ResultadoCalificacion, grupos_validos: set[str]
) -> tuple[bool, list[str]]:
    """Informe: la identidad relevante es el GRUPO, no el nombre individual --
    un informe puede listar 3-4 autores, así que emparejar 'nombre_detectado'
    contra estudiantes uno a uno no tiene sentido aquí."""
    motivos = []

    if resultado.confianza_nombre != "alta":
        motivos.append("la IA no está segura de haber identificado bien el grupo/autores")

    grupo = resultado.grupo_detectado
    if not grupo or grupo not in grupos_validos:
        motivos.append("el grupo detectado no coincide con ningún grupo del roster")

    if resultado.observaciones:
        motivos.append(f"la IA dejó una observación: {resultado.observaciones}")

    return (len(motivos) > 0, motivos)


def procesar_lote(
    tipo: str,  # "coloquio" | "informe"
    hoja: HojaDetectada,
    practica: Practica,
    documentos: list[tuple[str, bytes, str]],  # (nombre_archivo, data, mime_type)
    rubrica_texto: str,
    puntaje_maximo: float,
    ejemplos: list[EjemploCalificado] | None = None,
    api_key: str | None = None,
    calificar_fn: Callable | None = None,
) -> list[ItemRevision]:
    if calificar_fn is None:
        from .ai_client import calificar as calificar_fn  # import diferido: solo si hace falta de verdad

    ejemplos = ejemplos or []
    nombres_candidatos = [e.nombre for e in hoja.estudiantes]

    items: list[ItemRevision] = []
    for nombre_archivo, data, mime in documentos:
        resultado = calificar_fn(
            tipo=tipo,
            nombre_practica=practica.nombre,
            rubrica_texto=rubrica_texto,
            puntaje_maximo=puntaje_maximo,
            contenido=data,
            contenido_mime=mime,
            nombres_candidatos=nombres_candidatos,
            ejemplos=ejemplos,
            api_key=api_key,
        )

        if tipo == "coloquio":
            coincidencias = emparejar(resultado.nombre_detectado, hoja.estudiantes)
            mejor = coincidencias[0] if coincidencias else None
            estudiante_sugerido = None
            if mejor and mejor.nivel != "baja":
                estudiante_sugerido = next(e for e in hoja.estudiantes if e.fila == mejor.estudiante_fila)
            requiere_atencion, motivos = _evaluar_atencion_coloquio(resultado, coincidencias)
        else:
            coincidencias = []
            estudiante_sugerido = None
            grupos_validos = {e.grupo for e in hoja.estudiantes if e.grupo}
            requiere_atencion, motivos = _evaluar_atencion_informe(resultado, grupos_validos)

        items.append(
            ItemRevision(
                archivo=nombre_archivo,
                resultado_ia=resultado,
                coincidencias=coincidencias[:3],
                estudiante_sugerido=estudiante_sugerido,
                requiere_atencion=requiere_atencion,
                motivos=motivos,
            )
        )
    return items
