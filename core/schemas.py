"""
Contratos de datos compartidos entre módulos.

Deliberadamente sin dependencias externas (solo dataclasses del stdlib) para
que `grading_engine.py`, `name_matcher.py`, etc. se puedan importar y probar
en cualquier entorno, con o sin el SDK de Gemini/pydantic instalado. Solo
`ai_client.py` conoce pydantic, y al final convierte su resultado a estas
mismas formas.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DesgloseItem:
    criterio: str
    puntaje_obtenido: float
    puntaje_maximo: float
    comentario: str = ""
    pagina: int | None = None  # página del PDF (1-indexada) donde está esa sección, si se pudo ubicar


@dataclass
class ResultadoCalificacion:
    nombre_detectado: str
    confianza_nombre: str  # "alta" | "media" | "baja"
    nota_sugerida: float
    desglose: list[DesgloseItem] = field(default_factory=list)
    observaciones: str = ""
    grupo_detectado: str | None = None
    practica_detectada: str = ""  # de qué práctica PARECE tratarse el documento, según su contenido


@dataclass
class ArchivoReferencia:
    """Un archivo de contexto/referencia (rúbrica escaneada, guía de prácticas,
    formato de ejemplo) que se le manda a la IA como material adicional --
    no es un ejemplo calificado, es contexto para entender qué se espera."""
    data: bytes
    mime_type: str
    nombre: str = ""


@dataclass
class EjemploCalificado:
    data: bytes
    mime_type: str
    nota_asignada: float
    comentario: str | None = None
