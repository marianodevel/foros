"""Módulo para la ejecución de consultas y generación de reportes filtrados."""

import csv
import io
import logging
from typing import Any, Dict

import requests
from django.core.files.base import ContentFile

from .. import gestor_almacenamiento, scraper_tasks
from ..models import ReporteBusqueda
from ..utils import generar_nombre_busqueda_avanzada, manejar_fase_con_sesion

logger = logging.getLogger(__name__)


@manejar_fase_con_sesion("BUSQUEDA AVANZADA")
def ejecutar_busqueda_avanzada(
    session: requests.Session, username: str, filtros: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Ejecuta una búsqueda con parámetros específicos, almacena los resultados en el ORM
    y genera un archivo CSV persistente vinculado a un registro de reporte.

    Args:
        session: Sesión HTTP activa.
        username: Identificador del usuario que ejecuta la consulta.
        filtros: Diccionario con los parámetros de la petición.

    Returns:
        Diccionario con el estado, cantidad de resultados y ruta del archivo generado.
    """
    logger.info("Iniciando búsqueda avanzada para %s con parámetros: %s", username, filtros)
    
    expedientes_filtrados = scraper_tasks.raspar_busqueda_parametrizada(
        session, filtros
    )

    if not expedientes_filtrados:
        logger.warning("La búsqueda no retornó resultados.")
        return {"status": "empty", "count": 0}

    for exp in expedientes_filtrados:
        exp["origen"] = "BUSQUEDA_AVANZADA"

    gestor_almacenamiento.guardar_expedientes_lote(username, expedientes_filtrados)

    buffer_csv = io.StringIO()
    encabezados = expedientes_filtrados[0].keys()
    escritor_csv = csv.DictWriter(buffer_csv, fieldnames=encabezados)
    
    escritor_csv.writeheader()
    escritor_csv.writerows(expedientes_filtrados)
    
    contenido_csv = buffer_csv.getvalue()
    nombre_archivo = generar_nombre_busqueda_avanzada(filtros)

    reporte = ReporteBusqueda(
        usuario_asignado=username,
        parametros_busqueda=filtros,
        cantidad_resultados=len(expedientes_filtrados),
    )
    
    reporte.archivo_csv.save(
        nombre_archivo, ContentFile(contenido_csv.encode("utf-8")), save=True
    )

    logger.info("Reporte generado exitosamente: %s", reporte.archivo_csv.name)
    
    return {
        "status": "success",
        "count": len(expedientes_filtrados),
        "file": reporte.archivo_csv.name,
    }