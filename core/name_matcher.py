"""
Empareja el nombre detectado (por la IA, desde una foto/PDF) contra la lista
real de estudiantes matriculados, usando similitud de texto.

Por qué existe esto además de la "confianza_nombre" que ya reporta la IA:
dos señales independientes son más confiables que una sola. La IA puede estar
muy segura sobre un nombre mal leído; este módulo lo contrasta de forma
puramente estadística contra el roster real del Excel.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

from .excel_parser import Estudiante


def _normalizar(nombre: str) -> str:
    n = nombre.strip().lower()
    n = "".join(c for c in unicodedata.normalize("NFD", n) if unicodedata.category(c) != "Mn")
    n = re.sub(r"[^a-z\s]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _tokens(nombre: str) -> set[str]:
    return set(_normalizar(nombre).split())


@dataclass
class Coincidencia:
    estudiante_fila: int
    nombre_roster: str
    score: float  # 0-1
    nivel: str  # "alta" | "media" | "baja"


def emparejar(
    nombre_detectado: str,
    candidatos: list[Estudiante],
    umbral_alta: float = 0.82,
    umbral_media: float = 0.55,
) -> list[Coincidencia]:
    """Devuelve las coincidencias ordenadas de mejor a peor, combinando:
    - similitud de secuencia de caracteres (buena para errores de OCR/letra)
    - solapamiento de palabras (buena para nombre/apellido en otro orden,
      o cuando falta un segundo nombre/apellido)
    """
    det_norm = _normalizar(nombre_detectado)
    det_tokens = _tokens(nombre_detectado)

    resultados = []
    for est in candidatos:
        cand_norm = _normalizar(est.nombre)
        cand_tokens = _tokens(est.nombre)

        seq_score = difflib.SequenceMatcher(None, det_norm, cand_norm).ratio()
        # Contención en vez de Jaccard simétrico: si TODAS las palabras detectadas
        # están en el nombre del roster, cuenta como fuerte, aunque el roster tenga
        # más palabras (nombre completo) que lo que alcanzó a leerse a mano.
        overlap = (
            len(det_tokens & cand_tokens) / min(len(det_tokens), len(cand_tokens))
            if det_tokens and cand_tokens
            else 0.0
        )
        score = max(seq_score, overlap)
        nivel = "alta" if score >= umbral_alta else "media" if score >= umbral_media else "baja"
        resultados.append(
            Coincidencia(estudiante_fila=est.fila, nombre_roster=est.nombre, score=round(score, 3), nivel=nivel)
        )

    resultados.sort(key=lambda c: -c.score)
    return resultados
