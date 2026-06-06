"""Módulo para la extracción masiva de expedientes de acceso público."""

import logging
from typing import Any, Dict

import requests

from .. import gestor_almacenamiento, scraper_tasks
from ..catalogos.localidades import LOCALIDADES
from ..utils import manejar_fase_con_sesion

logger = logging.getLogger(__name__)


@manejar_fase_con_sesion("SINCRONIZACION MASIVA PUBLICA")
def ejecutar_sincronizacion_publica(session: requests.Session, username: str) -> Dict[str, Any]:
    """
    Itera sobre el catálogo de localidades para extraer todos los expedientes públicos
    disponibles y registrarlos en la base de datos.

    Args:
        session: Sesión HTTP activa.
        username: Identificador del usuario actual.

    Returns:
        Diccionario con el estado de la operación y el conteo de registros.
    """
    logger.info("Iniciando extracción masiva pública para: %s", username)
    expedientes_totales = []

    for id_loc, nombre_loc in LOCALIDADES.items():
        logger.info("Consultando registros en: %s", nombre_loc)
        filtros_loc = {"organismo_origen": "2", "id_localidad": str(id_loc)}

        expedientes_loc = scraper_tasks.raspar_busqueda_parametrizada(
            session, filtros_loc
        )

        if expedientes_loc:
            for exp in expedientes_loc:
                exp["origen"] = "PUBLICO"
            expedientes_totales.extend(expedientes_loc)
            logger.info("  > Recuperados %d expedientes.", len(expedientes_loc))

    if expedientes_totales:
        gestor_almacenamiento.guardar_expedientes_lote(username, expedientes_totales)
        logger.info("Proceso completado. Total consolidado: %d", len(expedientes_totales))
        return {"status": "success", "count": len(expedientes_totales)}

    logger.warning("No se obtuvieron resultados públicos en el ciclo actual.")
    return {"status": "empty", "count": 0}
