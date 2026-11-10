"""Módulo de definición de tareas asíncronas para la aplicación SIPED."""

from typing import Any, Dict

from celery import shared_task
from celery.utils.log import get_task_logger

from .fases.sincronizacion_expedientes import ejecutar_sincronizacion_expedientes
from .fases.sincronizacion_movimientos import ejecutar_sincronizacion_movimientos
from .fases.sincronizacion_documentos import ejecutar_sincronizacion_documentos
from .fases.sincronizacion_publica import ejecutar_sincronizacion_publica
from .fases.sincronizacion_busqueda_avanzada import ejecutar_busqueda_avanzada
from .fases.sincronizacion_individual import ejecutar_sincronizacion_individual
from .fases.descarga_publica import ejecutar_descarga_publica
from .fases.polling_cambios import (
    encolar_polling_cambios,
    ejecutar_polling_usuario,
)
from .push import enviar_resumen_push

logger = get_task_logger(__name__)


@shared_task(bind=True, name="siped.sincronizar_expedientes", soft_time_limit=3600, time_limit=3660)
def sincronizar_expedientes_task(self, cookies: dict, username: str) -> str:
    return ejecutar_sincronizacion_expedientes(cookies=cookies, username=username)


@shared_task(bind=True, name="siped.sincronizar_movimientos", soft_time_limit=3600, time_limit=3660)
def sincronizar_movimientos_task(self, cookies: dict, username: str) -> str:
    return ejecutar_sincronizacion_movimientos(cookies=cookies, username=username)


@shared_task(bind=True, name="siped.sincronizar_documentos", soft_time_limit=3600, time_limit=3660)
def sincronizar_documentos_task(self, cookies: dict, username: str) -> str:
    return ejecutar_sincronizacion_documentos(cookies=cookies, username=username)


@shared_task(bind=True, name="siped.sincronizacion_individual", soft_time_limit=3600, time_limit=3660)
def sincronizacion_individual_task(self, cookies: dict, nro_expediente: str, username: str) -> str:
    return ejecutar_sincronizacion_individual(
        cookies=cookies, nro_expediente_objetivo=nro_expediente, username=username
    )


@shared_task(bind=True, name="siped.sincronizacion_publica", soft_time_limit=3600, time_limit=3660)
def sincronizacion_publica_task(self, cookies: dict, username: str) -> Dict[str, Any]:
    return ejecutar_sincronizacion_publica(cookies=cookies, username=username)


@shared_task(bind=True, name="siped.busqueda_avanzada", soft_time_limit=3600, time_limit=3660)
def busqueda_avanzada_task(
    self, cookies: dict, username: str, filtros: Dict[str, Any]
) -> Dict[str, Any]:
    return ejecutar_busqueda_avanzada(
        cookies=cookies, username=username, filtros=filtros
    )


@shared_task(bind=True, name="siped.descarga_publica", soft_time_limit=3600, time_limit=3660)
def descarga_publica_task(self, cookies: dict, link_detalle: str, username: str) -> str:
    return ejecutar_descarga_publica(
        cookies=cookies, link_detalle_objetivo=link_detalle, username=username
    )


@shared_task(name="siped.encolar_polling_cambios")
def encolar_polling_cambios_task() -> int:
    """Encola un polling por cada sesión activa (tarea periódica de Beat)."""
    return encolar_polling_cambios()


@shared_task(
    bind=True,
    name="siped.polling_cambios_usuario",
    soft_time_limit=1500,
    time_limit=1560,
)
def polling_cambios_usuario_task(self, username_intranet: str) -> str:
    """Consulta la lista maestra de un usuario y refresca sus novedades."""
    return ejecutar_polling_usuario(username_intranet)


@shared_task(
    name="siped.enviar_push_resumen",
    soft_time_limit=60,
    time_limit=90,
)
def enviar_push_resumen_task(
    usuario: str,
    expedientes: int,
    movimientos: int,
) -> dict:
    """Envía el resumen de novedades a los dispositivos del usuario."""
    return enviar_resumen_push(usuario, expedientes, movimientos)
