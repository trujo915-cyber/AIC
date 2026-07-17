"""
App principal (Streamlit).

Flujo: subir Excel de registro -> elegir práctica y tipo -> material de
referencia + ejemplo(s) ya calificados -> subir fotos/PDFs/Word a calificar
-> IA sugiere -> Carla revisa y confirma -> se escribe en el Excel -> se
descarga.

Funciona igual desde el navegador del celular que desde la laptop, porque
todo corre en el servidor donde se despliega esta app -- no depende de
archivos guardados en ningún dispositivo en particular.
"""

from __future__ import annotations

import io

import openpyxl
import pandas as pd
import streamlit as st

from core.excel_parser import parse_workbook
from core.excel_writer import escribir_nota
from core.grading_engine import procesar_lote
from core.profile_manager import Perfil, exportar as exportar_perfiles, importar as importar_perfiles
from core.schemas import ArchivoReferencia, EjemploCalificado

st.set_page_config(page_title="Calificador — Ing. Química EPN", layout="wide")

MIME_POR_EXTENSION = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
TIPOS_ACEPTADOS = ["jpg", "jpeg", "png", "pdf", "docx"]


def _mime_de(nombre_archivo: str) -> str:
    ext = nombre_archivo.rsplit(".", 1)[-1].lower()
    return MIME_POR_EXTENSION.get(ext, "application/octet-stream")


def _get_secret(key: str, default: str = "") -> str:
    """st.secrets.get(...) no se comporta como un dict normal: si NO existe
    ningún archivo secrets.toml, Streamlit lanza una excepción en CUALQUIER
    acceso a st.secrets, incluso dentro de .get(). Esto lo atrapa."""
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Estado inicial
# ---------------------------------------------------------------------------
for clave, valor in {
    "perfiles": {},
    "hoja": None,
    "wb": None,
    "excel_filename": "registro.xlsx",
    "revision_items": None,
    "revision_tipo": None,
    "revision_practica": None,
    "log_cambios": [],
    "resultado_aplicacion": None,
    "conflictos_pendientes": [],
}.items():
    if clave not in st.session_state:
        st.session_state[clave] = valor


# ---------------------------------------------------------------------------
# Barra lateral: API key + perfiles guardados
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Configuración")
    api_key = _get_secret("GEMINI_API_KEY") or st.text_input(
        "Gemini API key", type="password", help="Gratis en aistudio.google.com/apikey"
    )

    st.divider()
    st.subheader("📁 Perfiles de calificación")
    st.caption(
        "Material de referencia + ejemplos guardados por práctica. Descárgalos y "
        "guárdalos en tu OneDrive para tenerlos también desde el otro dispositivo."
    )

    perfil_file = st.file_uploader("Cargar perfiles (.json)", type="json", key="perfil_uploader")
    if perfil_file is not None:
        try:
            st.session_state.perfiles = importar_perfiles(perfil_file.getvalue())
            st.success(f"{len(st.session_state.perfiles)} perfil(es) cargado(s)")
        except Exception as e:
            st.error(f"No se pudo leer el archivo de perfiles: {e}")

    if st.session_state.perfiles:
        st.download_button(
            "⬇️ Descargar perfiles actuales",
            data=exportar_perfiles(st.session_state.perfiles),
            file_name="perfiles_calificacion.json",
            mime="application/json",
        )
        with st.expander(f"Ver {len(st.session_state.perfiles)} perfil(es) guardado(s)"):
            for pid, p in st.session_state.perfiles.items():
                st.caption(f"• {p.practica} ({p.tipo}) — {len(p.ejemplos)} ejemplo(s), {len(p.material_archivos)} archivo(s) de referencia")


st.title("📋 Calificador de laboratorios — Ing. Química EPN")


# ---------------------------------------------------------------------------
# Paso 1: Excel de registro
# ---------------------------------------------------------------------------
st.header("1️⃣ Archivo de registro (Excel)")
excel_file = st.file_uploader("Sube el Excel del paralelo que vas a calificar", type=["xlsx"])

if excel_file is not None and st.button("Leer archivo"):
    try:
        hojas = parse_workbook(io.BytesIO(excel_file.getvalue()))
        if not hojas:
            st.error(
                "No se detectaron prácticas/estudiantes en este archivo. Revisa que "
                "tenga encabezados C/P/I/T y una columna de nombres reconocible."
            )
        else:
            st.session_state.hoja = hojas[0]  # si hay varias hojas válidas, se usa la primera
            st.session_state.wb = openpyxl.load_workbook(io.BytesIO(excel_file.getvalue()))
            st.session_state.excel_filename = excel_file.name
            st.session_state.revision_items = None
            st.session_state.resultado_aplicacion = None
            st.session_state.conflictos_pendientes = []
            st.session_state.log_cambios = []
            st.rerun()
    except Exception as e:
        st.error(f"No se pudo leer el archivo: {e}")

hoja = st.session_state.hoja

if hoja is not None:
    st.success(f"✅ {len(hoja.estudiantes)} estudiantes · {len(hoja.practicas)} práctica(s) detectada(s)")
    with st.expander("Ver qué se detectó"):
        st.write("**Prácticas:** " + ", ".join(p.nombre for p in hoja.practicas))
        st.dataframe(
            pd.DataFrame([{"Estudiante": e.nombre, "Grupo": e.grupo} for e in hoja.estudiantes]),
            use_container_width=True,
            height=200,
        )

    # -----------------------------------------------------------------
    # Paso 2: qué calificar
    # -----------------------------------------------------------------
    st.header("2️⃣ ¿Qué vas a calificar?")
    col1, col2 = st.columns(2)
    with col1:
        practica_nombre = st.selectbox("Práctica", [p.nombre for p in hoja.practicas])
    with col2:
        tipo = st.radio("Tipo", ["coloquio", "informe"], horizontal=True)

    practica = next(p for p in hoja.practicas if p.nombre == practica_nombre)
    perfil_id = f"{practica_nombre}|{tipo}"
    perfil_existente = st.session_state.perfiles.get(perfil_id)

    # -----------------------------------------------------------------
    # Paso 3: material de referencia + ejemplos
    # -----------------------------------------------------------------
    st.header("3️⃣ Material de referencia y ejemplo(s) ya calificado(s)")
    st.caption(
        "No tiene que ser solo una rúbrica formal: puede ser texto libre, la guía de "
        "la práctica, o un formato de ejemplo -- en foto, PDF o Word."
    )
    puntaje_default = 2.0 if tipo == "coloquio" else 7.0

    rubrica_texto = st.text_area(
        "Texto libre (rúbrica, notas, criterios, lo que sea útil)",
        value=perfil_existente.rubrica_texto if perfil_existente else "",
        placeholder="Ej:\nDesarrollo del problema /1.5\nResultado final /0.5\n\n(también puedes dejar esto vacío y solo subir archivos abajo)",
        height=100,
    )
    puntaje_maximo = st.number_input(
        "Puntaje máximo de este rubro",
        value=perfil_existente.puntaje_maximo if perfil_existente else puntaje_default,
        step=0.5,
    )

    material_subido = st.file_uploader(
        "Archivos de referencia (rúbrica escaneada, guía de la práctica, formato de ejemplo...)",
        type=TIPOS_ACEPTADOS,
        accept_multiple_files=True,
        key=f"material_{perfil_id}",
        help="Foto, PDF o Word. Puedes subir varios a la vez.",
    )
    material_archivos: list[ArchivoReferencia] = (
        [ArchivoReferencia(data=f.getvalue(), mime_type=_mime_de(f.name), nombre=f.name) for f in material_subido]
        if material_subido
        else (perfil_existente.material_archivos if perfil_existente else [])
    )
    if material_subido:
        st.caption(f"{len(material_subido)} archivo(s) de referencia listo(s) para usar.")
    elif perfil_existente and perfil_existente.material_archivos:
        st.caption(f"Usando {len(perfil_existente.material_archivos)} archivo(s) de referencia ya guardado(s) en el perfil.")

    ejemplos_subidos = st.file_uploader(
        "Ejemplo(s) YA CALIFICADOS por ti para esta práctica (opcional, pero mejora mucho la calificación)",
        type=TIPOS_ACEPTADOS,
        accept_multiple_files=True,
        key=f"ejemplos_{perfil_id}",
    )
    ejemplos: list[EjemploCalificado] = []
    if ejemplos_subidos:
        st.caption("Indica la nota real que le pusiste a cada ejemplo:")
        for f in ejemplos_subidos:
            c1, c2 = st.columns([3, 1])
            with c1:
                st.caption(f.name)
            with c2:
                nota_ej = st.number_input(
                    "Nota", min_value=0.0, max_value=float(puntaje_maximo), step=0.1,
                    key=f"nota_{perfil_id}_{f.name}", label_visibility="collapsed",
                )
            ejemplos.append(EjemploCalificado(data=f.getvalue(), mime_type=_mime_de(f.name), nota_asignada=nota_ej))
    elif perfil_existente:
        ejemplos = perfil_existente.ejemplos
        if ejemplos:
            st.caption(f"Usando {len(ejemplos)} ejemplo(s) ya guardado(s) en el perfil.")

    if st.button("💾 Guardar como perfil reusable"):
        if not rubrica_texto.strip() and not material_archivos:
            st.warning("Agrega al menos texto o un archivo de referencia antes de guardar.")
        else:
            nuevo = Perfil(
                id=perfil_id, materia="", practica=practica_nombre, tipo=tipo,
                rubrica_texto=rubrica_texto, puntaje_maximo=puntaje_maximo,
                ejemplos=ejemplos, material_archivos=material_archivos,
            )
            st.session_state.perfiles[perfil_id] = nuevo
            st.session_state.perfil_recien_guardado = True

    if st.session_state.get("perfil_recien_guardado"):
        st.warning(
            "⚠️ El perfil se guardó **solo en esta sesión** (en memoria). El archivo .json que "
            "subiste al inicio NO se modifica solo -- para no perder este cambio, descarga el "
            "archivo actualizado de perfiles ahora mismo y reemplaza el que tenías en OneDrive:"
        )
        st.download_button(
            "⬇️ Descargar perfiles actualizados (con este cambio incluido)",
            data=exportar_perfiles(st.session_state.perfiles),
            file_name="perfiles_calificacion.json",
            mime="application/json",
            key="descarga_inmediata_perfil",
        )

    # -----------------------------------------------------------------
    # Paso 4: documentos a calificar
    # -----------------------------------------------------------------
    st.header("4️⃣ Fotos, PDFs o Word a calificar")
    docs_subidos = st.file_uploader(
        "Sube los documentos nuevos de esta práctica (varios a la vez)",
        type=TIPOS_ACEPTADOS,
        accept_multiple_files=True,
        key=f"docs_{perfil_id}",
    )

    if st.button("✨ Calificar con IA", type="primary", disabled=not docs_subidos):
        if not api_key:
            st.error("Falta la API key de Gemini (barra lateral).")
        elif not rubrica_texto.strip() and not material_archivos:
            st.error("Falta el material de referencia del paso 3 (texto o archivo).")
        else:
            documentos = [(f.name, f.getvalue(), _mime_de(f.name)) for f in docs_subidos]
            with st.spinner(f"Calificando {len(documentos)} documento(s)..."):
                try:
                    items = procesar_lote(
                        tipo=tipo, hoja=hoja, practica=practica, documentos=documentos,
                        rubrica_texto=rubrica_texto, puntaje_maximo=puntaje_maximo,
                        ejemplos=ejemplos, material_archivos=material_archivos, api_key=api_key,
                    )
                    st.session_state.revision_items = items
                    st.session_state.revision_tipo = tipo
                    st.session_state.revision_practica = practica
                    st.session_state.resultado_aplicacion = None
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al calificar: {e}")


# ---------------------------------------------------------------------------
# Aviso persistente del último "Aplicar" (fuera del bloque de arriba para
# que sí se vea -- antes se mostraba justo antes de un st.rerun() y
# desaparecía sin que se alcanzara a leer)
# ---------------------------------------------------------------------------
resultado = st.session_state.resultado_aplicacion
if resultado:
    if resultado["aplicados"] > 0:
        st.success(f"✅ Archivo actualizado: {resultado['aplicados']} nota(s) escrita(s) correctamente.")
    else:
        st.info("ℹ️ No se escribió ninguna nota nueva (0 filas aprobadas, o todas quedaron como conflicto).")
    if resultado["sin_asignar"]:
        st.warning(f"⚠️ {resultado['sin_asignar']} fila(s) aprobadas pero sin estudiante/grupo asignado -- no se aplicaron.")

if st.session_state.conflictos_pendientes:
    st.warning(
        f"⚠️ {len(st.session_state.conflictos_pendientes)} celda(s) ya tenían una nota distinta a la nueva. "
        "Revisa la diferencia y elige si quieres sobrescribirla:"
    )
    filas_conflicto = [
        {
            "Estudiante": c["estudiante"].nombre,
            "Celda": c["celda"],
            "Nota actual": c["valor_anterior"],
            "Nota nueva propuesta": c["valor_nuevo"],
            "Sobrescribir": False,
        }
        for c in st.session_state.conflictos_pendientes
    ]
    df_conf = st.data_editor(
        pd.DataFrame(filas_conflicto),
        column_config={
            "Estudiante": st.column_config.TextColumn(disabled=True),
            "Celda": st.column_config.TextColumn(disabled=True),
            "Nota actual": st.column_config.NumberColumn(disabled=True),
            "Nota nueva propuesta": st.column_config.NumberColumn(disabled=True),
            "Sobrescribir": st.column_config.CheckboxColumn(),
        },
        hide_index=True,
        use_container_width=True,
        key="editor_conflictos",
    )
    if st.button("✍️ Aplicar sobrescrituras seleccionadas"):
        aplicados_forzados = 0
        restantes = []
        ws = st.session_state.wb[hoja.hoja] if hoja else None
        for i, c in enumerate(st.session_state.conflictos_pendientes):
            if bool(df_conf.iloc[i]["Sobrescribir"]) and ws is not None:
                r = escribir_nota(ws, hoja, c["practica"], c["estudiante"], c["campo"], c["valor_nuevo"], forzar=True)
                if r.ok:
                    aplicados_forzados += 1
                    st.session_state.log_cambios.append(
                        f"{c['estudiante'].nombre} — {c['practica'].nombre} ({c['campo']}) = {c['valor_nuevo']} (sobrescrito)"
                    )
                    continue
            restantes.append(c)
        st.session_state.conflictos_pendientes = restantes
        st.session_state.resultado_aplicacion = {"aplicados": aplicados_forzados, "sin_asignar": 0}
        st.rerun()


# ---------------------------------------------------------------------------
# Paso 5: revisión
# ---------------------------------------------------------------------------
items = st.session_state.revision_items
if items:
    st.header("5️⃣ Revisar y confirmar")
    st.caption("Nada se escribe en el Excel todavía. Revisa, corrige lo necesario, y confirma.")

    tipo_rev = st.session_state.revision_tipo
    practica_rev = st.session_state.revision_practica
    SIN_ASIGNAR = "— sin asignar —"
    nombres_roster = [e.nombre for e in hoja.estudiantes]
    grupos_roster = sorted({e.grupo for e in hoja.estudiantes if e.grupo}, key=str)
    opciones_estudiante = [SIN_ASIGNAR] + nombres_roster
    opciones_grupo = [SIN_ASIGNAR] + grupos_roster

    filas = []
    for i, it in enumerate(items):
        fila = {
            "Archivo": it.archivo,
            "Detectado por IA": it.resultado_ia.nombre_detectado,
            "Nota sugerida": it.resultado_ia.nota_sugerida,
            "Aprobar": not it.requiere_atencion,
            "Motivo de alerta": "; ".join(it.motivos) if it.motivos else "—",
        }
        if tipo_rev == "coloquio":
            fila["Estudiante"] = it.estudiante_sugerido.nombre if it.estudiante_sugerido else SIN_ASIGNAR
        else:
            grupo_ia = it.grupo_sugerido
            fila["Grupo"] = grupo_ia if grupo_ia in grupos_roster else SIN_ASIGNAR
        filas.append(fila)

    df = pd.DataFrame(filas)
    columnas_orden = ["Archivo", "Detectado por IA"] + (["Estudiante"] if tipo_rev == "coloquio" else ["Grupo"]) + ["Nota sugerida", "Aprobar", "Motivo de alerta"]
    df = df[columnas_orden]

    column_config = {
        "Nota sugerida": st.column_config.NumberColumn(min_value=0.0, step=0.1),
        "Aprobar": st.column_config.CheckboxColumn(),
        "Motivo de alerta": st.column_config.TextColumn(disabled=True),
        "Detectado por IA": st.column_config.TextColumn(disabled=True),
        "Archivo": st.column_config.TextColumn(disabled=True),
    }
    if tipo_rev == "coloquio":
        column_config["Estudiante"] = st.column_config.SelectboxColumn(options=opciones_estudiante)
    else:
        column_config["Grupo"] = st.column_config.SelectboxColumn(options=opciones_grupo)

    df_editado = st.data_editor(df, column_config=column_config, use_container_width=True, hide_index=True)

    if st.button("✅ Aplicar notas confirmadas al Excel", type="primary"):
        campo = "C" if tipo_rev == "coloquio" else "I"
        aplicados, sin_asignar = 0, 0
        nuevos_conflictos = []

        for _, fila in df_editado.iterrows():
            if not fila["Aprobar"]:
                continue

            clave_destino = fila["Estudiante"] if tipo_rev == "coloquio" else fila["Grupo"]
            if clave_destino == SIN_ASIGNAR:
                sin_asignar += 1
                continue

            if tipo_rev == "coloquio":
                destinatarios = [e for e in hoja.estudiantes if e.nombre == fila["Estudiante"]]
            else:
                destinatarios = [e for e in hoja.estudiantes if e.grupo == fila["Grupo"]]

            ws = st.session_state.wb[hoja.hoja]
            for est in destinatarios:
                valor_nuevo = float(fila["Nota sugerida"])
                r = escribir_nota(ws, hoja, practica_rev, est, campo, valor_nuevo)
                if r.ok:
                    aplicados += 1
                    st.session_state.log_cambios.append(f"{est.nombre} — {practica_rev.nombre} ({campo}) = {valor_nuevo}")
                else:
                    nuevos_conflictos.append({
                        "estudiante": est, "practica": practica_rev, "campo": campo,
                        "valor_anterior": r.valor_anterior, "valor_nuevo": valor_nuevo, "celda": r.celda,
                    })

        # Se guarda en session_state y se muestra en el bloque de ARRIBA en el
        # próximo render -- nunca justo antes de un st.rerun(), porque el
        # rerun borra cualquier st.success/st.warning antes de que se alcance
        # a ver (ese era el bug por el que "no aparecía ningún aviso").
        st.session_state.resultado_aplicacion = {"aplicados": aplicados, "sin_asignar": sin_asignar}
        st.session_state.conflictos_pendientes = st.session_state.conflictos_pendientes + nuevos_conflictos
        st.session_state.revision_items = None
        st.rerun()


# ---------------------------------------------------------------------------
# Paso 6: descargar
# ---------------------------------------------------------------------------
if st.session_state.wb is not None:
    st.header("6️⃣ Descargar Excel actualizado")
    if not st.session_state.log_cambios:
        st.info("Todavía no se ha aplicado ningún cambio en esta sesión -- este archivo sería igual al que subiste.")
    else:
        with st.expander(f"Ver los {len(st.session_state.log_cambios)} cambios aplicados en esta sesión"):
            for linea in st.session_state.log_cambios:
                st.caption(linea)

    buffer = io.BytesIO()
    st.session_state.wb.save(buffer)
    buffer.seek(0)
    st.download_button(
        "⬇️ Descargar Excel actualizado",
        data=buffer,
        file_name=st.session_state.excel_filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    st.caption("Sube este archivo a la carpeta correspondiente de OneDrive para reemplazar el anterior.")
