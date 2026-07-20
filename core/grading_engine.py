"""
Orquesta el flujo completo para un lote de documentos (fotos de coloquio o
PDFs/Word de informe): llama al motor de IA, empareja el nombre detectado
contra el roster real, y arma una lista de resultados lista para la
pantalla de revisión -- incluyendo por qué cada ítem sí o no necesita que
Carla lo mire con más atención.

La función de calificación (`calificar_fn`) se recibe como parámetro -- por
defecto es `ai_client.calificar`, pero para pruebas se le puede pasar
cualquier función con la misma firma. Así toda esta orquestación se puede
probar sin llamar a la API real de Gemini.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable

from .excel_parser import Estudiante, HojaDetectada, Practica
from .name_matcher import Coincidencia, emparejar
from .pdf_report import anotar_informe_calificado
from .schemas import EjemploCalificado, ResultadoCalificacion
from .text_utils import similitud_contencion

PAUSA_ENTRE_DOCUMENTOS = 4.5  # segundos entre documentos, para no toparse el límite de solicitudes/minuto

UMBRAL_AMBIGUEDAD = 0.08  # si el 2do candidato queda a menos de esto del 1ro, es ambiguo
UMBRAL_PRACTICA_DISTINTA = 0.34  # por debajo de esto (palabras en común), se considera otra práctica

_SEPARADORES_NOMBRES = re.compile(r",|;|\n|\s+y\s+|\s+Y\s+|&")


def _practica_coincide(esperada: str, detectada: str) -> bool:
    """Compara por PALABRAS en común, no por caracteres -- 'ley stephan
    boltzmann' vs 'Ley de Stefan-Boltzmann' debe coincidir (misma práctica,
    otra redacción); 'conducción entre 2 medios' vs 'difusión gaseosa en
    aire' NO debe coincidir (práctica distinta)."""
    if not detectada.strip():
        return True  # la IA no reportó nada -- no bloqueamos por falta de dato
    return similitud_contencion(esperada, detectada) >= UMBRAL_PRACTICA_DISTINTA


@dataclass
class ItemRevision:
    archivo: str
    resultado_ia: ResultadoCalificacion
    coincidencias: list[Coincidencia]
    estudiante_sugerido: Estudiante | None  # solo coloquio
    grupo_sugerido: str | None  # solo informe
    requiere_atencion: bool
    motivos: list[str] = field(default_factory=list)
    pdf_calificado: bytes | None = None  # solo informe


def _extraer_nombres_candidatos(texto: str) -> list[str]:
    """Divide 'Juan Pérez, María López y Carlos Ruiz' en nombres individuales."""
    if not texto:
        return []
    partes = _SEPARADORES_NOMBRES.split(texto)
    return [p.strip() for p in partes if p.strip()]


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


def _resolver_grupo_informe(
    resultado: ResultadoCalificacion, hoja: HojaDetectada
) -> tuple[str | None, list[str]]:
    """Para informes, la fuente más confiable de identidad son los NOMBRES de
    los autores -- el informe casi siempre los lista -- y NO un número de
    grupo que la IA tendría que adivinar sin conocer la numeración interna
    de Carla. Se emparejan los nombres detectados contra el roster, y el
    grupo se deriva de ahí. El campo 'grupo_detectado' que reporta la IA
    queda solo como respaldo secundario, por si el informe sí lo indica
    explícitamente y no se pudo emparejar ningún nombre."""
    motivos = []
    candidatos = _extraer_nombres_candidatos(resultado.nombre_detectado)

    grupos_encontrados: set[str] = set()
    for nombre in candidatos:
        coincidencias = emparejar(nombre, hoja.estudiantes)
        mejor = coincidencias[0] if coincidencias else None
        if mejor and mejor.nivel == "alta":
            estudiante = next(e for e in hoja.estudiantes if e.fila == mejor.estudiante_fila)
            if estudiante.grupo:
                grupos_encontrados.add(estudiante.grupo)

    if len(grupos_encontrados) == 1:
        return grupos_encontrados.pop(), motivos

    if len(grupos_encontrados) > 1:
        motivos.append(
            f"los autores detectados pertenecen a distintos grupos del roster ({sorted(grupos_encontrados)})"
        )
        return None, motivos

    # No se pudo emparejar ningún nombre de autor -- probamos con lo que
    # diga la IA directamente en 'grupo_detectado', como respaldo.
    grupos_validos = {e.grupo for e in hoja.estudiantes if e.grupo}
    if resultado.grupo_detectado and resultado.grupo_detectado in grupos_validos:
        motivos.append("grupo tomado del campo detectado por la IA (no se emparejó ningún autor por nombre)")
        return resultado.grupo_detectado, motivos

    motivos.append("no se pudo identificar el grupo, ni por los nombres de los autores ni por el campo de grupo")
    return None, motivos


def procesar_lote(
    tipo: str,  # "coloquio" | "informe"
    hoja: HojaDetectada,
    practica: Practica,
    documentos: list[tuple[str, bytes, str]],  # (nombre_archivo, data, mime_type)
    rubrica_texto: str,
    puntaje_maximo: float,
    ejemplos: list[EjemploCalificado] | None = None,
    material_archivos: list | None = None,
    materia: str = "",
    api_key: str | None = None,
    calificar_fn: Callable | None = None,
) -> list[ItemRevision]:
    usando_api_real = calificar_fn is None
    if calificar_fn is None:
        from .ai_client import calificar as calificar_fn  # import diferido: solo si hace falta de verdad

    ejemplos = ejemplos or []
    material_archivos = material_archivos or []
    nombres_candidatos = [e.nombre for e in hoja.estudiantes]

    items: list[ItemRevision] = []
    for indice_doc, (nombre_archivo, data, mime) in enumerate(documentos):
        if usando_api_real and indice_doc > 0:
            time.sleep(PAUSA_ENTRE_DOCUMENTOS)
        resultado = calificar_fn(
            tipo=tipo,
            nombre_practica=practica.nombre,
            rubrica_texto=rubrica_texto,
            puntaje_maximo=puntaje_maximo,
            contenido=data,
            contenido_mime=mime,
            nombres_candidatos=nombres_candidatos,
            ejemplos=ejemplos,
            material_archivos=material_archivos,
            api_key=api_key,
        )

        estudiante_sugerido = None
        grupo_sugerido = None
        pdf_calificado = None

        practica_ok = _practica_coincide(practica.nombre, resultado.practica_detectada)
        motivos_practica = []
        if not practica_ok:
            motivos_practica.append(
                f"el documento parece ser de otra práctica ('{resultado.practica_detectada}'), "
                f"no de '{practica.nombre}' -- revisa que sea el archivo correcto"
            )

        if tipo == "coloquio":
            coincidencias = emparejar(resultado.nombre_detectado, hoja.estudiantes)
            mejor = coincidencias[0] if coincidencias else None
            if mejor and mejor.nivel != "baja":
                estudiante_sugerido = next(e for e in hoja.estudiantes if e.fila == mejor.estudiante_fila)
            requiere_atencion, motivos = _evaluar_atencion_coloquio(resultado, coincidencias)
            requiere_atencion = requiere_atencion or not practica_ok
            motivos = motivos_practica + motivos
        else:
            coincidencias = []
            grupo_sugerido, motivos_grupo = _resolver_grupo_informe(resultado, hoja)
            motivos = motivos_practica + list(motivos_grupo)
            if resultado.confianza_nombre != "alta":
                motivos.append("la IA no está segura de haber identificado bien a los autores")
            if resultado.observaciones:
                motivos.append(f"la IA dejó una observación: {resultado.observaciones}")
            requiere_atencion = (
                grupo_sugerido is None or bool(motivos_grupo) or resultado.confianza_nombre != "alta" or not practica_ok
            )

            identificador = f"Grupo {grupo_sugerido}" if grupo_sugerido else resultado.nombre_detectado
            try:
                pdf_calificado = anotar_informe_calificado(data, mime, resultado, puntaje_maximo, identificador)
            except Exception as e:
                motivos.append(f"no se pudo anotar el PDF calificado: {e}")

        items.append(
            ItemRevision(
                archivo=nombre_archivo,
                resultado_ia=resultado,
                coincidencias=coincidencias[:3],
                estudiante_sugerido=estudiante_sugerido,
                grupo_sugerido=grupo_sugerido,
                requiere_atencion=requiere_atencion,
                motivos=motivos,
                pdf_calificado=pdf_calificado,
            )
        )
    return items
