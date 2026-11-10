"""Notificaciones Web Push para la PWA SIPED."""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from pywebpush import WebPushException
from pywebpush import webpush

from .models import SuscripcionPush

logger = logging.getLogger(__name__)

TTL_PUSH = 3600
LARGO_MAXIMO_ENDPOINT = 500
ESTADOS_SUSCRIPCION_INVALIDA = (404, 410)


def _error(mensaje: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": mensaje}, status=status)


def _payload_json(request) -> dict | None:
    try:
        datos = json.loads(request.body)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return None
    return datos if isinstance(datos, dict) else None


def _endpoint_valido(endpoint) -> bool:
    return (
        isinstance(endpoint, str)
        and endpoint.startswith("https://")
        and len(endpoint) <= LARGO_MAXIMO_ENDPOINT
    )


def _parsear_suscripcion(request) -> tuple[str, dict] | None:
    datos = _payload_json(request)
    if not datos:
        return None

    endpoint = datos.get("endpoint")
    claves = datos.get("keys", {})
    if not _endpoint_valido(endpoint) or not isinstance(claves, dict):
        return None

    p256dh = claves.get("p256dh")
    auth = claves.get("auth")
    if not isinstance(p256dh, str) or not isinstance(auth, str):
        return None
    if not p256dh or not auth:
        return None

    return endpoint, {"p256dh": p256dh, "auth": auth}


def _vapid_configurado() -> bool:
    return bool(settings.VAPID_PRIVATE_KEY and settings.VAPID_SUBJECT)


def _enviar_a_suscripcion(suscripcion: SuscripcionPush, payload: dict) -> bool:
    try:
        webpush(
            subscription_info={
                "endpoint": suscripcion.endpoint,
                "keys": {
                    "p256dh": suscripcion.p256dh,
                    "auth": suscripcion.auth,
                },
            },
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_SUBJECT},
            ttl=TTL_PUSH,
            timeout=10,
        )
    except WebPushException as exc:
        if exc.status_code in ESTADOS_SUSCRIPCION_INVALIDA:
            logger.info("Suscripción push %s vencida, se elimina.", suscripcion.pk)
            suscripcion.delete()
        else:
            logger.warning(
                "Error enviando push %s (HTTP %s): %s",
                suscripcion.pk,
                exc.status_code,
                exc,
            )
        return False
    except Exception:
        logger.exception("Error inesperado enviando push %s", suscripcion.pk)
        return False

    suscripcion.ultimo_envio = timezone.now()
    suscripcion.save(update_fields=["ultimo_envio"])
    return True


def enviar_push_a_usuario(usuario: str, payload: dict) -> dict:
    """Envía un payload a todos los dispositivos activos de un usuario."""
    if not _vapid_configurado():
        logger.warning("Web Push sin configurar: faltan las claves VAPID.")
        return {"enviados": 0, "fallidos": 0, "configurado": False}

    suscripciones = list(
        SuscripcionPush.objects.filter(usuario=usuario, activa=True),
    )
    enviados = sum(
        1 for suscripcion in suscripciones
        if _enviar_a_suscripcion(suscripcion, payload)
    )
    return {
        "enviados": enviados,
        "fallidos": len(suscripciones) - enviados,
        "configurado": True,
    }


def enviar_resumen_push(
    usuario: str,
    expedientes: int,
    movimientos: int,
) -> dict:
    """Notifica un resumen del polling sin exponer datos de expedientes."""
    partes = []
    if expedientes:
        partes.append(f"{expedientes} expediente(s) con cambios")
    if movimientos:
        partes.append(f"{movimientos} movimiento(s) nuevo(s)")

    payload = {
        "title": "SIPED - Novedades",
        "body": " y ".join(partes) or "Hay novedades en tus expedientes.",
        "icon": "/static/siped/movil/icons/icon-192.png",
        "badge": "/static/siped/movil/icons/badge-72.png",
        "tag": "siped-novedades",
        "renotify": True,
        "data": {"url": "/siped/m/novedades/", "tipo": "novedades"},
    }
    return enviar_push_a_usuario(usuario, payload)


@require_POST
def suscribir_push(request):
    """Registra o actualiza la suscripción push de este dispositivo."""
    usuario = request.session.get("siped_username")
    if not usuario:
        return _error("sin sesión", status=403)

    parseada = _parsear_suscripcion(request)
    if not parseada:
        return _error("suscripción inválida")

    endpoint, claves = parseada
    SuscripcionPush.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "usuario": usuario,
            "p256dh": claves["p256dh"],
            "auth": claves["auth"],
            "user_agent": request.META.get("HTTP_USER_AGENT", ""),
            "activa": True,
        },
    )
    return JsonResponse({"ok": True, "suscripto": True})


@require_POST
def desuscribir_push(request):
    """Elimina la suscripción push de este dispositivo."""
    usuario = request.session.get("siped_username")
    if not usuario:
        return _error("sin sesión", status=403)

    datos = _payload_json(request) or {}
    endpoint = datos.get("endpoint")
    if not _endpoint_valido(endpoint):
        return _error("falta endpoint")

    SuscripcionPush.objects.filter(usuario=usuario, endpoint=endpoint).delete()
    return JsonResponse({"ok": True, "desuscripto": True})


@require_POST
def enviar_push_test(request):
    """Envía una notificación de prueba a los dispositivos del usuario."""
    usuario = request.session.get("siped_username")
    if not usuario:
        return _error("sin sesión", status=403)
    if not _vapid_configurado():
        return _error("Las notificaciones push no están configuradas.", status=503)

    payload = {
        "title": "SIPED - Prueba",
        "body": "Las notificaciones push están funcionando.",
        "icon": "/static/siped/movil/icons/icon-192.png",
        "badge": "/static/siped/movil/icons/badge-72.png",
        "tag": "siped-prueba",
        "data": {"url": "/siped/m/perfil/", "tipo": "prueba"},
    }
    resultado = enviar_push_a_usuario(usuario, payload)
    return JsonResponse({"ok": True, **resultado})
