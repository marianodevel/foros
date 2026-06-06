"""Módulo para la extracción y actualización de nuevos movimientos."""

import logging
import requests

from .. import scraper_tasks
from .. import gestor_almacenamiento
from ..models import Expediente
from ..utils import manejar_fase_con_sesion

logger = logging.getLogger(__name__)


@manejar_fase_con_sesion("SINCRONIZACION DE MOVIMIENTOS")
def ejecutar_sincronizacion_movimientos(session: requests.Session, username: str) -> str:
    """
    Extrae y sincroniza las novedades y nuevos movimientos para cada expediente registrado,
    optimizando la extracción para no procesar historiales completos ya almacenados.

    Args:
        session: Sesión HTTP activa.
        username: Identificador del usuario actual.

    Returns:
        Cadena de texto con el resultado y estadísticas de la operación.
    """
    expedientes_a_procesar = Expediente.objects.filter(usuario_asignado=username)

    if not expedientes_a_procesar.exists():
        mensaje = f"Error: No se encontraron expedientes registrados para {username}. Ejecute la sincronización de expedientes primero."
        logger.error(mensaje)
        return mensaje

    total_expedientes = expedientes_a_procesar.count()
    logger.info("Iniciando control de novedades para %d expedientes.", total_expedientes)

    contador_movimientos_nuevos = 0

    for i, expediente in enumerate(expedientes_a_procesar):
        nro_expediente = expediente.numero_expediente
        logger.info("Procesando %d/%d: %s", i + 1, total_expedientes, nro_expediente)

        try:
            expediente_data = {
                "expediente": expediente.numero_expediente,
                "link_detalle": expediente.link_detalle,
                "dependencia": expediente.dependencia,
                "origen": expediente.origen
            }
            
            movimientos = scraper_tasks.raspar_movimientos_de_expediente(
                session, expediente_data
            )

            if movimientos:
                gestor_almacenamiento.guardar_movimientos_lote(
                    username, nro_expediente, movimientos
                )
                
                cantidad = len(movimientos)
                contador_movimientos_nuevos += cantidad
                logger.info("  > Registrados %d movimientos nuevos/actualizados.", cantidad)
            else:
                logger.info("  > Sin novedades.")

        except Exception as e:
            logger.error(
                "  > Error al procesar %s: %s", nro_expediente, e, exc_info=True
            )

    return f"Sincronización completada. Total de movimientos nuevos registrados: {contador_movimientos_nuevos}"