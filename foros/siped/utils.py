"""Módulo de utilidades generales para manejo de archivos, nombres y sesiones."""

import csv
import functools
import os
import re
import time
import logging
from typing import Any, Callable, Dict, List, Optional

from . import constants
from . import session_manager
from .exceptions import PaginaInesperada, SesionSIPEDExpirada

logger = logging.getLogger(__name__)

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    logger.critical("ERROR CRÍTICO: 'pypdf' no está instalado. Asegúrese de agregarlo a uv.")
    raise

# Importamos los catálogos de manera relativa
try:
    from .catalogos.abogados import ABOGADOS
except Exception as e:
    logger.warning(f"No se pudo cargar el catalogo de ABOGADOS: {e}")
    ABOGADOS = {}

try:
    from .catalogos.localidades import LOCALIDADES
except Exception:
    LOCALIDADES = {}

try:
    from .catalogos.dependencias import DEPENDENCIAS_POR_LOCALIDAD
except Exception:
    DEPENDENCIAS_POR_LOCALIDAD = {}

try:
    from .catalogos.tipos_juicio import TIPOS_JUICIO
except Exception:
    TIPOS_JUICIO = {}

def limpiar_nombre_archivo(name: Any) -> str:
    if not name:
        name = "SIN_NOMBRE"
    name = str(name).replace("/", "-")
    name = re.sub(r'[\\*?:"<>|]', "", name)
    return name[:150].strip()

def obtener_ruta_usuario(username: str) -> str:
    if not username:
        username = "default"
    username_safe = limpiar_nombre_archivo(str(username))
    ruta_usuario = os.path.join(constants.DATA_ROOT_DIR, username_safe)
    os.makedirs(ruta_usuario, exist_ok=True)
    return ruta_usuario

def guardar_a_csv(data: List[Dict[str, Any]], filename: str, subdirectory: str = ".") -> None:
    if not data:
        logger.warning(f"No hay datos para guardar en {filename}.")
        return
    try:
        os.makedirs(subdirectory, exist_ok=True)
        filepath = os.path.join(subdirectory, filename)
        logger.info(f"Guardando {len(data)} filas en {filepath}...")

        headers = data[0].keys()
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(data)
    except Exception as e:
        logger.error(f"Error al guardar CSV: {e}")

def leer_csv_a_diccionario(filepath: str) -> Optional[List[Dict[str, str]]]:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except FileNotFoundError:
        logger.info(f"Nota: No se encontro el archivo '{filepath}'.")
        return None
    except Exception as e:
        logger.error(f"Error al leer el CSV: {e}")
        return None

def fusionar_pdfs(source_directory: str, output_pdf_path: str) -> None:
    logger.info(f"Fusionando PDFs en: {output_pdf_path}...")
    pdf_files = [f for f in os.listdir(source_directory) if f.lower().endswith(".pdf")]

    if not pdf_files:
        logger.warning("No se encontraron archivos .pdf para fusionar.")
        return

    pdf_files.sort()
    merger = PdfWriter()
    archivos_agregados = []

    try:
        for filename in pdf_files:
            filepath = os.path.join(source_directory, filename)
            with open(filepath, "rb") as f:
                reader = PdfReader(f)
                if len(reader.pages) > 0:
                    for page in reader.pages:
                        merger.add_page(page)
                    archivos_agregados.append(filename)
                else:
                    logger.warning(f"ADVERTENCIA: '{filename}' esta vacio, saltando.")

        if archivos_agregados:
            with open(output_pdf_path, "wb") as f:
                merger.write(f)
            logger.info(f"PDF fusionado exitosamente. Documentos incluidos: {len(archivos_agregados)}")
        else:
            logger.warning("No se pudo fusionar ningun archivo PDF valido.")
    except Exception as e:
        logger.error(f"ERROR al fusionar PDFs: {e}", exc_info=True)

def manejar_fase_con_sesion(nombre_fase: str) -> Callable:
    def decorador(funcion_nucleo: Callable) -> Callable:
        @functools.wraps(funcion_nucleo)
        def wrapper(cookies: dict, *args: Any, **kwargs: Any) -> Any:
            logger.info(f"--- INICIANDO {nombre_fase} ---")
            try:
                session = session_manager.crear_sesion_con_cookies(cookies)

                # Verificación explícita contra la intranet: la presencia de la
                # cookie en la sesión de Django no garantiza que siga vigente.
                if not session_manager.verificar_sesion(session):
                    raise SesionSIPEDExpirada()

                mensaje = funcion_nucleo(session, *args, **kwargs)
                logger.info(mensaje)
                return mensaje
            except (SesionSIPEDExpirada, PaginaInesperada):
                # Estas excepciones deben llegar intactas al estado de Celery
                # para que la UI pueda distinguir "sesión vencida" de un error
                # genérico o de un resultado vacío.
                logger.error("Fallo controlado en %s", nombre_fase, exc_info=True)
                raise
            except Exception as e:
                mensaje = f"Error fatal en {nombre_fase}: {e}"
                logger.error(mensaje, exc_info=True)
                raise Exception(mensaje) from e
        return wrapper
    return decorador

def generar_nombre_busqueda_avanzada(filtros: Dict[str, Any]) -> str:
    # (El cuerpo de esta función se mantiene idéntico al original, ya que 
    # la lógica de diccionarios no depende de Flask/Django)
    partes = []
    procesados = {
        "nro_expediente", "anio", "cmb_documental", "texto", "abogado", "txt_abogado",
        "id_abogado", "dnij", "apellidoj", "nombresj", "id_localidad", "id_dependencia",
        "juicio", "fecha_alta_dia_desde", "fecha_alta_mes_desde", "fecha_alta_anio_desde",
        "fecha_alta_dia_hasta", "fecha_alta_mes_hasta", "fecha_alta_anio_hasta",
        "filtro_archivados", "organismo_origen", "date", "ordenar_por", "orden", "inicio",
    }

    nro = str(filtros.get("nro_expediente", "")).strip()
    anio = str(filtros.get("anio", "")).strip()
    inc = str(filtros.get("cmb_documental", "")).strip()
    if nro or anio or inc:
        exp_text = f"Exp_{nro}" if nro else "Exp"
        if anio: exp_text += f"-{anio}"
        if inc: exp_text += f"-{inc}"
        partes.append(exp_text)

    texto = str(filtros.get("texto", "")).strip()
    if texto:
        texto_corto = "_".join(texto.split()[:3])
        partes.append(f"Caratula_{texto_corto}")

    abogado_id = str(filtros.get("abogado", "")).strip()
    if abogado_id:
        txt_abogado = ABOGADOS.get(abogado_id, "")
        if txt_abogado:
            apellido = txt_abogado.split("-")[0].strip().replace(" ", "_")
            partes.append(f"Abog_{apellido}")
        else:
            partes.append(f"Abog_ID{abogado_id}")

    dni = str(filtros.get("dnij", "")).strip()
    apellido_j = str(filtros.get("apellidoj", "")).strip()
    nombre_j = str(filtros.get("nombresj", "")).strip()
    if dni or apellido_j or nombre_j:
        just = "Justiciable"
        if apellido_j: just += f"_{apellido_j.replace(' ', '')}"
        elif nombre_j: just += f"_{nombre_j.replace(' ', '')}"
        if dni: just += f"_DNI{dni}"
        partes.append(just)

    loc_id = str(filtros.get("id_localidad", "")).strip()
    dep_id = str(filtros.get("id_dependencia", "")).strip()

    if loc_id and loc_id != "18":
        loc_name = LOCALIDADES.get(loc_id, loc_id)
        loc_name = re.sub(r"[^A-Za-z0-9]", "", loc_name)
        partes.append(f"Loc_{loc_name}")

    if dep_id:
        dep_name = DEPENDENCIAS_POR_LOCALIDAD.get(loc_id, {}).get(dep_id, "")
        if dep_name:
            dep_corta = "".join([w[0].upper() for w in dep_name.split() if len(w) > 2])
            partes.append(f"Dep_{dep_corta}")
        else:
            partes.append(f"Dep_ID{dep_id}")

    juicio_id = str(filtros.get("juicio", "")).strip()
    if juicio_id:
        j_name = TIPOS_JUICIO.get(juicio_id, "")
        if j_name:
            j_corto = "".join([w.capitalize() for w in j_name.split()[:2]])
            partes.append(f"Juicio_{j_corto}")
        else:
            partes.append(f"Juicio_ID{juicio_id}")

    dia_d = str(filtros.get("fecha_alta_dia_desde", "0")).strip()
    mes_d = str(filtros.get("fecha_alta_mes_desde", "")).strip()
    anio_d = str(filtros.get("fecha_alta_anio_desde", "")).strip()
    if anio_d and mes_d and dia_d != "0":
        partes.append(f"Desde_{anio_d}{mes_d.zfill(2)}{dia_d.zfill(2)}")

    dia_h = str(filtros.get("fecha_alta_dia_hasta", "0")).strip()
    mes_h = str(filtros.get("fecha_alta_mes_hasta", "")).strip()
    anio_h = str(filtros.get("fecha_alta_anio_hasta", "")).strip()
    if anio_h and mes_h and dia_h != "0":
        partes.append(f"Hasta_{anio_h}{mes_h.zfill(2)}{dia_h.zfill(2)}")

    archivados = str(filtros.get("filtro_archivados", "")).strip()
    if archivados and archivados != "todos":
        partes.append(f"Arch_{archivados}")

    origen = str(filtros.get("organismo_origen", "")).strip()
    if origen and origen != "2":
        partes.append(f"NivelAcceso_{origen}")

    for key, value in filtros.items():
        if key not in procesados:
            val_str = str(value).strip()
            if val_str and val_str not in ("0", ""):
                partes.append(f"{key}_{val_str}")

    if not partes:
        return f"busqueda_avanzada_general_{int(time.time())}.csv"

    nombre_crudo = "_".join(partes)
    nombre_limpio = limpiar_nombre_archivo(nombre_crudo)

    return f"busqueda_{nombre_limpio}.csv"