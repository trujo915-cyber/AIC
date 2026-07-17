"""
Gestor de "perfiles de calificación": la rúbrica + ejemplo(s) ya calificados
que Carla arma una vez por práctica y reutiliza cada vez que vuelve a
calificar esa misma práctica (por ejemplo, con otro paralelo).

Diseño: en vez de depender de una base de datos externa (que requeriría
crear una cuenta nueva en otro servicio y confiar en que no se pierda nada),
los perfiles se guardan/cargan como UN SOLO archivo .json que Carla descarga
y sube, igual que ya hace con sus archivos de Excel -- puede guardarlo en la
misma carpeta de OneDrive que ya usa. Así el celular y la laptop quedan
sincronizados a través de OneDrive, sin depender de que ninguno de los dos
dispositivos tenga guardado nada "localmente".

Los documentos de ejemplo (fotos/PDF) se guardan codificados en base64
dentro del mismo JSON, así todo queda en un solo archivo portátil.
"""

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass, field

from .schemas import EjemploCalificado


@dataclass
class Perfil:
    id: str  # identificador simple, ej. "TC1-Ley Stephan Boltzmann"
    materia: str
    practica: str
    tipo: str  # "coloquio" | "informe"
    rubrica_texto: str
    puntaje_maximo: float
    ejemplos: list[EjemploCalificado] = field(default_factory=list)


def _perfil_a_dict(p: Perfil) -> dict:
    d = asdict(p)
    for ej in d["ejemplos"]:
        ej["data"] = base64.b64encode(ej["data"]).decode("ascii")
    return d


def _dict_a_perfil(d: dict) -> Perfil:
    ejemplos = [
        EjemploCalificado(
            data=base64.b64decode(ej["data"]),
            mime_type=ej["mime_type"],
            nota_asignada=ej["nota_asignada"],
            comentario=ej.get("comentario"),
        )
        for ej in d.get("ejemplos", [])
    ]
    return Perfil(
        id=d["id"],
        materia=d["materia"],
        practica=d["practica"],
        tipo=d["tipo"],
        rubrica_texto=d["rubrica_texto"],
        puntaje_maximo=d["puntaje_maximo"],
        ejemplos=ejemplos,
    )


def exportar(perfiles: dict[str, Perfil]) -> bytes:
    """Serializa todos los perfiles a bytes de un .json, para que Carla lo
    descargue y lo guarde donde quiera (ej. su carpeta de OneDrive)."""
    data = {"version": 1, "perfiles": [_perfil_a_dict(p) for p in perfiles.values()]}
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def importar(contenido: bytes) -> dict[str, Perfil]:
    """Lee un .json de perfiles previamente exportado."""
    data = json.loads(contenido.decode("utf-8"))
    perfiles = {}
    for pd in data.get("perfiles", []):
        p = _dict_a_perfil(pd)
        perfiles[p.id] = p
    return perfiles


def agregar_o_actualizar(perfiles: dict[str, Perfil], perfil: Perfil) -> dict[str, Perfil]:
    nuevos = dict(perfiles)
    nuevos[perfil.id] = perfil
    return nuevos
