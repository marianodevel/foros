"""Módulo para la gestión y persistencia de estados de las tareas asíncronas en caché."""

from typing import Any, Dict, Optional

from celery.result import AsyncResult
from django.core.cache import cache

from .exceptions import SesionSIPEDExpirada


def _obtener_clave_cache(username: str, nombre_fase: str) -> str:
    """Genera una clave única en la caché para el usuario y la fase específica."""
    return f"siped_tarea_{username}_{nombre_fase}"


def obtener_estado_tarea(id_tarea: Optional[str], username: str, nombre_fase: str) -> Dict[str, Any]:
    """
    Consulta el estado actual de una tarea en el sistema Celery, 
    gestionando el ciclo de vida y la limpieza de los identificadores.
    """
    if not id_tarea:
        return {"estado": "IDLE", "resultado": "En espera"}

    tarea = AsyncResult(id_tarea)
    estado_tarea = tarea.state
    resultado_tarea = tarea.result
    datos_estado = {"estado": estado_tarea, "resultado": str(resultado_tarea)}

    if estado_tarea in ["SUCCESS", "FAILURE", "REVOKED"]:
        try:
            tarea.forget()
        except Exception:
            pass

        resetear_id_tarea(username, nombre_fase)
        datos_estado["recargar"] = True

        # La sesión remota de la intranet puede vencer mientras el worker
        # ejecuta la fase. En ese caso la tarea falla con una excepción
        # reconocible y la UI debe forzar un nuevo login, no mostrar "sin
        # novedades" como si el proceso hubiera terminado bien.
        if SesionSIPEDExpirada.es_resultado(resultado_tarea):
            datos_estado["sesion_expirada"] = True
            datos_estado["resultado"] = SesionSIPEDExpirada.limpiar_mensaje(
                resultado_tarea
            )

        if estado_tarea == "SUCCESS" and (
            not datos_estado["resultado"] or datos_estado["resultado"] == "None"
        ):
            datos_estado["resultado"] = "Completado"
        return datos_estado

    if estado_tarea == "PENDING" and (
        not datos_estado["resultado"] or datos_estado["resultado"] == "None"
    ):
        datos_estado["resultado"] = "En cola..."

    if estado_tarea == "STARTED" and (
        not datos_estado["resultado"] or datos_estado["resultado"] == "None"
    ):
        datos_estado["resultado"] = "Procesando..."

    return datos_estado


def registrar_tarea_iniciada(username: str, nombre_fase: str, id_tarea: str) -> None:
    """Almacena el ID de la tarea instanciada en la caché vinculada al usuario."""
    cache.set(_obtener_clave_cache(username, nombre_fase), id_tarea, timeout=86400)


def obtener_id_tarea(username: str, nombre_fase: str) -> Optional[str]:
    """Devuelve el identificador de la tarea activa para el usuario y fase solicitada."""
    return cache.get(_obtener_clave_cache(username, nombre_fase))


def resetear_id_tarea(username: str, nombre_fase: str) -> None:
    """Elimina de la caché el registro de la tarea activa para una fase y usuario determinados."""
    cache.delete(_obtener_clave_cache(username, nombre_fase))