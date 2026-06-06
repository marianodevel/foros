"""Módulo central para la orquestación de tareas de web scraping del sistema."""

import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from django.db.models import QuerySet

from . import constants
from . import parsers
from .models import Movimiento

logger = logging.getLogger(__name__)


def descargar_archivo_en_memoria(session: requests.Session, url_archivo: str) -> Optional[bytes]:
    """Descarga un archivo binario y lo retorna en memoria para ser guardado por el ORM."""
    try:
        respuesta = session.get(url_archivo, stream=True, timeout=30)
        respuesta.raise_for_status()
        return respuesta.content
    except requests.RequestException as e:
        logger.error("Error descargando archivo desde %s: %s", url_archivo, e)
        return None


def raspar_lista_expedientes(session: requests.Session) -> List[Dict[str, str]]:
    all_expedientes_list = []
    current_inicio = 0
    page_count = 1

    while True:
        logger.info("Obteniendo página de lista %d (inicio=%d)...", page_count, current_inicio)
        params = {"inicio": current_inicio}

        try:
            r_lista = session.get(constants.LISTA_EXPEDIENTES_URL, params=params, timeout=30)
            r_lista.raise_for_status()

            expedientes_en_pagina = parsers.parsear_lista_expedientes(r_lista.text)
            if not expedientes_en_pagina:
                break

            all_expedientes_list.extend(expedientes_en_pagina)
            
            next_inicio = parsers.encontrar_siguiente_inicio_universal(r_lista.text)
            if next_inicio is not None:
                current_inicio = next_inicio
                page_count += 1
            else:
                break

        except requests.RequestException as e:
            logger.error("Error al obtener la página %d: %s", page_count, e)
            break

    return all_expedientes_list


def raspar_movimientos_de_expediente(
    session: requests.Session, expediente_dict: Dict[str, Any]
) -> List[Dict[str, str]]:
    """
    Reconstruye el historial de movimientos de un expediente.
    Soporta URLs directas y URLs con frameset dinámico.
    """
    link_contenedor = expediente_dict.get("link_detalle")
    expediente_nro = expediente_dict.get("expediente", "Desconocido")

    if not link_contenedor:
        return []

    try:
        # 1. Petición inicial (puede ser frameset o contenido directo)
        r_detalle = session.get(link_contenedor, timeout=30)
        r_detalle.raise_for_status()
        soup = BeautifulSoup(r_detalle.text, "html.parser")

        # 2. Resolución dual (Lógica extraída del original)
        frame_sup = soup.find("frame", attrs={"name": "sup"})
        if frame_sup and frame_sup.get("src"):
            url_contenido_real = urljoin(link_contenedor, frame_sup.get("src"))
            r_detalle = session.get(url_contenido_real, timeout=30)
            r_detalle.raise_for_status()

        # 3. Extracción de Parámetros AJAX
        ajax_params_base = parsers.parsear_detalle_para_ajax_params(r_detalle.text)
        if "exp_id" not in ajax_params_base:
            logger.error("No se pudieron extraer los parámetros AJAX base para %s.", expediente_nro)
            return []

        # 4. Control de paginación temprana
        movimientos_existentes: QuerySet = Movimiento.objects.filter(
            expediente__numero_expediente=expediente_nro
        ).values_list('link_escrito', flat=True)
        enlaces_conocidos = {enlace for enlace in movimientos_existentes if enlace}

        offset = 0
        mov_page_count = 1
        movimientos_del_expediente = []
        detener_paginacion = False

        while not detener_paginacion:
            ajax_params = ajax_params_base.copy()
            ajax_params.update({
                "numerodemas": mov_page_count,
                "offset": offset,
                "usuariointerno": 0,
                "tipof": "",
                "estadose": "",
                "descripcorta": "",
                "contenido": "",
                "pe": "",
                "acumulados": "",
            })

            r_movimientos = session.get(constants.AJAX_MOVIMIENTOS_URL, params=ajax_params, timeout=30)
            
            if len(r_movimientos.text) < 200:
                break

            movimientos_de_pagina = parsers.parsear_movimientos_de_ajax_html(
                r_movimientos.text, expediente_nro
            )
            if not movimientos_de_pagina:
                break

            for mov in movimientos_de_pagina:
                link_escrito = mov.get("link_escrito", "")
                if link_escrito and link_escrito in enlaces_conocidos:
                    detener_paginacion = True
                    break
                movimientos_del_expediente.append(mov)

            offset += 10
            mov_page_count += 1
            time.sleep(0.25)

        return movimientos_del_expediente

    except requests.RequestException as e:
        logger.error("Error de red procesando expediente %s: %s", expediente_nro, e)
        return []


def raspar_contenido_documento(
    session: requests.Session, document_url: str
) -> Optional[Dict[str, Any]]:
    if not document_url or not document_url.strip():
        return None

    try:
        r_documento = session.get(document_url, timeout=30)
        r_documento.raise_for_status()
        return parsers.parsear_pagina_documento(r_documento.text)
    except requests.RequestException as e:
        logger.error("Error al obtener el contenido documental en %s: %s", document_url, e)
        return None


def raspar_busqueda_parametrizada(
    session: requests.Session, filtros_usuario: Dict[str, Any]
) -> List[Dict[str, Any]]:
    url_submit = f"{constants.BASE_URL}/siped/expediente/buscar/submit.php"

    payload = {
        "id_localidad": filtros_usuario.get("id_localidad", "18"),
        "id_dependencia": filtros_usuario.get("id_dependencia", ""),
        "nro_expediente": filtros_usuario.get("nro_expediente", ""),
        "anio": filtros_usuario.get("anio", ""),
        "cmb_documental": filtros_usuario.get("cmb_documental", ""),
        "filtro_archivados": filtros_usuario.get("filtro_archivados", "todos"),
        "juicio": filtros_usuario.get("juicio", ""),
        "texto": filtros_usuario.get("texto", ""),
        "organismo_origen": filtros_usuario.get("organismo_origen", "2"),
        "id_abogado": filtros_usuario.get("id_abogado", ""),
        "txt_abogado": filtros_usuario.get("txt_abogado", ""),
        "abogado": filtros_usuario.get("abogado", ""),
        "dnij": filtros_usuario.get("dnij", ""),
        "apellidoj": filtros_usuario.get("apellidoj", ""),
        "nombresj": filtros_usuario.get("nombresj", ""),
        "fecha_alta_dia_desde": filtros_usuario.get("fecha_alta_dia_desde", "0"),
        "fecha_alta_mes_desde": filtros_usuario.get("fecha_alta_mes_desde", ""),
        "fecha_alta_anio_desde": filtros_usuario.get("fecha_alta_anio_desde", ""),
        "date": "",
        "fecha_alta_dia_hasta": filtros_usuario.get("fecha_alta_dia_hasta", "0"),
        "fecha_alta_mes_hasta": filtros_usuario.get("fecha_alta_mes_hasta", ""),
        "fecha_alta_anio_hasta": filtros_usuario.get("fecha_alta_anio_hasta", ""),
        "ordenar_por": "exp_numero",
        "orden": "ASC",
        "inicio": 0,
    }

    all_expedientes = []
    page_count = 1
    vistos = set()

    while True:
        try:
            respuesta = session.get(url_submit, params=payload, timeout=30)
            respuesta.raise_for_status()

            expedientes_pagina = parsers.parsear_lista_publica(respuesta.text)

            if not expedientes_pagina:
                break

            ids_actuales = [e.get("expediente") for e in expedientes_pagina if e.get("expediente")]
            if vistos.intersection(ids_actuales):
                break

            vistos.update(ids_actuales)
            all_expedientes.extend(expedientes_pagina)

            next_inicio = parsers.encontrar_siguiente_inicio_universal(respuesta.text)
            if next_inicio is not None and next_inicio > payload["inicio"]:
                payload["inicio"] = next_inicio
                page_count += 1
                time.sleep(0.5)
            else:
                break

        except requests.RequestException as e:
            logger.error("Error de comunicación en la búsqueda avanzada: %s", e)
            break

    return all_expedientes