"""Módulo para la sincronización de la lista de expedientes privados."""

import logging
import requests

from .. import scraper_tasks
from .. import gestor_almacenamiento
from ..utils import manejar_fase_con_sesion

logger = logging.getLogger(__name__)


@manejar_fase_con_sesion("SINCRONIZACION DE EXPEDIENTES")
def ejecutar_sincronizacion_expedientes(session: requests.Session, username: str) -> str:
    """
    Ejecuta la extracción y almacenamiento en base de datos de la lista principal de expedientes.

    Args:
        session: Sesión HTTP activa.
        username: Identificador del usuario actual.

    Returns:
        Cadena de texto con el resultado de la operación.
    """
    lista_expedientes = scraper_tasks.raspar_lista_expedientes(session)

    if lista_expedientes:
        gestor_almacenamiento.guardar_expedientes_lote(username, lista_expedientes)
        return f"Lista de expedientes sincronizada en base de datos. Total: {len(lista_expedientes)}"

    return "No se encontraron expedientes en la bandeja del usuario."