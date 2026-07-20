"""Utilidades de texto compartidas entre name_matcher y grading_engine."""

from __future__ import annotations

import re
import unicodedata


def normalizar(texto: str) -> str:
    n = texto.strip().lower()
    n = "".join(c for c in unicodedata.normalize("NFD", n) if unicodedata.category(c) != "Mn")
    n = re.sub(r"[^a-z0-9\s]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def tokens(texto: str) -> set[str]:
    return set(normalizar(texto).split())


def similitud_contencion(a: str, b: str) -> float:
    """Similitud por solapamiento de palabras, relativa al texto MÁS CORTO
    (contención) -- funciona mejor que comparar caracteres para frases
    técnicas: 'conducción de calor' vs 'transferencia de calor por
    conducción' deben verse como relacionadas; 'ley stephan boltzmann' vs
    'intercambiador tubos concéntricos' deben verse como no relacionadas."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))
