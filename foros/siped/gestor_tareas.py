"""Módulo para la gestión y persistencia de estados de las tareas asíncronas en caché."""

from typing import Any, Dict, Optional

from celery.result import AsyncResult
from django.core.cache import cache


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
    datos_estado = {"estado": tarea.state, "resultado": str(tarea.result)}

    if tarea.state in ["SUCCESS", "FAILURE", "REVOKED"]:
        try:
            tarea.forget()
        except Exception:
            pass
        
        resetear_id_tarea(username, nombre_fase)
        datos_estado["recargar"] = True

        if tarea.state == "SUCCESS" and (
            not datos_estado["resultado"] or datos_estado["resultado"] == "None"
        ):
            datos_estado["resultado"] = "Completado"
        return datos_estado

    if tarea.state == "PENDING" and (
        not datos_estado["resultado"] or datos_estado["resultado"] == "None"
    ):
        datos_estado["resultado"] = "En cola..."

    if tarea.state == "STARTED" and (
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