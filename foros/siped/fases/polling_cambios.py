"""Polling automático de la lista maestra de expedientes de la intranet."""

import logging
import random
import time
from datetime import timedelta

from celery import current_app
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from requests.utils import dict_from_cookiejar

from .. import constants
from .. import gestor_almacenamiento
from .. import scraper_tasks
from .. import session_manager
from ..cripto import ErrorCifrado
from ..cripto import cifrar_cookies
from ..cripto import descifrar_cookies
from ..exceptions import PaginaInesperada
from ..exceptions import SesionSIPEDExpirada
from ..exceptions import SolicitudIncompleta
from ..fechas import formatear_fecha_intranet
from ..models import NovedadSIPED
from ..models import SesionSIPED

logger = logging.getLogger(__name__)

NOMBRE_TAREA_POLLING = "siped.polling_cambios_usuario"


def _ahora():
    return timezone.now()


def encolar_polling_cambios() -> int:
    """
    Encola un polling por cada sesión activa de la intranet.

    La dispersión aleatoria (``countdown``) evita que todas las cuentas
    consulten la intranet exactamente al mismo tiempo.
    """
    ahora = _ahora()
    sesiones = (
        SesionSIPED.objects.filter(
            estado=SesionSIPED.Estado.ACTIVA,
            cookies_cifradas__gt="",
        )
        .filter(
            Q(proximo_intento__isnull=True) | Q(proximo_intento__lte=ahora),
            Q(bloqueado_hasta__isnull=True) | Q(bloqueado_hasta__lt=ahora),
        )
        .values_list("username_intranet", flat=True)
    )

    enviadas = 0
    for username in sesiones:
        countdown = random.randint(0, constants.POLLING_JITTER_MAXIMO)
        current_app.send_task(
            NOMBRE_TAREA_POLLING,
            args=[username],
            countdown=countdown,
            expires=constants.POLLING_INTERVALO_MINUTOS * 60,
        )
        enviadas += 1
        logger.info(
            "Polling de %s encolado con %s segundos de dispersión.",
            username,
            countdown,
        )

    return enviadas


def _bloquear_sesion(sesion: SesionSIPED) -> bool:
    """
    Toma el bloqueo de polling de forma atómica.

    Se usa la base de datos y no la caché porque el entorno local configura
    ``LocMemCache``, que no se comparte entre el proceso web y el worker.
    """
    ahora = _ahora()
    actualizadas = (
        SesionSIPED.objects.filter(pk=sesion.pk)
        .filter(Q(bloqueado_hasta__isnull=True) | Q(bloqueado_hasta__lt=ahora))
        .update(
            bloqueado_hasta=ahora
            + timedelta(minutes=constants.POLLING_BLOQUEO_MINUTOS),
        )
    )
    return actualizadas == 1


def _marcar_expirada(sesion: SesionSIPED, detalle: str) -> None:
    logger.warning("Sesión SIPED expirada para %s: %s", sesion.username_intranet, detalle)
    SesionSIPED.objects.filter(pk=sesion.pk).update(
        estado=SesionSIPED.Estado.EXPIRADA,
        cookies_cifradas="",
        ultimo_polling=_ahora(),
        ultimo_error=detalle[:1000],
    )


def _registrar_fallo(sesion: SesionSIPED, error: Exception) -> None:
    fallos = sesion.fallos_consecutivos + 1
    minutos = min(5 * (2 ** (fallos - 1)), 360)
    logger.warning(
        "Polling de %s falló (%s fallos consecutivos): %s. "
        "Próximo intento en %s minutos.",
        sesion.username_intranet,
        fallos,
        error,
        minutos,
    )
    SesionSIPED.objects.filter(pk=sesion.pk).update(
        fallos_consecutivos=fallos,
        proximo_intento=_ahora() + timedelta(minutes=minutos),
        ultimo_error=str(error)[:1000],
    )


def _registrar_exito(sesion: SesionSIPED, session) -> None:
    cookies_actuales = dict_from_cookiejar(session.cookies)
    valores = {
        "ultimo_polling": _ahora(),
        "ultimo_error": "",
        "fallos_consecutivos": 0,
        "proximo_intento": None,
    }
    if cookies_actuales:
        valores["cookies_cifradas"] = cifrar_cookies(cookies_actuales)
    SesionSIPED.objects.filter(pk=sesion.pk).update(**valores)


def _registrar_novedad(
    username: str,
    expediente,
    tipo: str,
    detalle: str,
) -> bool:
    """
    Crea una novedad o actualiza la que ya está pendiente para el expediente.

    Evita que dos ciclos consecutivos encolen dos veces el mismo expediente
    cuando el anterior todavía no llegó a procesarse.
    """
    pendiente = NovedadSIPED.objects.filter(
        usuario_asignado=username,
        expediente=expediente,
        procesada=False,
    ).first()
    if pendiente:
        pendiente.tipo = tipo
        pendiente.detalle = detalle
        pendiente.save(update_fields=["tipo", "detalle"])
        return False

    NovedadSIPED.objects.create(
        usuario_asignado=username,
        expediente=expediente,
        tipo=tipo,
        detalle=detalle,
    )
    return True


def _registrar_cambios(
    username: str, cambios: dict[str, list],
) -> int:
    creadas = 0
    with transaction.atomic():
        for expediente in cambios["nuevos"]:
            if _registrar_novedad(
                username,
                expediente,
                NovedadSIPED.Tipo.EXPEDIENTE_NUEVO,
                f"Carátula: {expediente.caratula[:200]}",
            ):
                creadas += 1
        for expediente in cambios["actualizados"]:
            if _registrar_novedad(
                username,
                expediente,
                NovedadSIPED.Tipo.MOVIMIENTOS_NUEVOS,
                "Último movimiento: "
                f"{formatear_fecha_intranet(expediente.fecha_ult_mov) or 'sin fecha'}",
            ):
                creadas += 1
    return creadas


def _procesar_novedades(session, username: str) -> tuple[int, int]:
    """
    Refresca los movimientos de las novedades pendientes, con un tope por
    corrida para no exceder el tiempo de la tarea. Lo que quede pendiente se
    retoma en el próximo ciclo.
    """
    pendientes = list(
        NovedadSIPED.objects.filter(
            usuario_asignado=username, procesada=False,
        )
        .select_related("expediente")
        .order_by("detectada_en")[: constants.POLLING_MAX_EXPEDIENTES],
    )

    expedientes_procesados = 0
    movimientos_nuevos = 0

    for indice, novedad in enumerate(pendientes):
        expediente = novedad.expediente
        datos = {
            "expediente": expediente.numero_expediente,
            "expediente_id": expediente.id,
            "link_detalle": expediente.link_detalle,
            "dependencia": expediente.dependencia,
            "origen": expediente.origen,
        }

        movimientos = scraper_tasks.raspar_movimientos_de_expediente(session, datos)
        creados, _ = gestor_almacenamiento.guardar_movimientos_lote(
            username, expediente.numero_expediente, movimientos,
        )

        novedad.cantidad_movimientos = creados
        novedad.procesada = True
        novedad.detalle = f"{creados} movimientos nuevos"
        novedad.save(
            update_fields=["cantidad_movimientos", "procesada", "detalle"],
        )

        expedientes_procesados += 1
        movimientos_nuevos += creados

        if indice < len(pendientes) - 1:
            time.sleep(
                random.uniform(
                    constants.POLLING_ESPERA_MINIMA,
                    constants.POLLING_ESPERA_MAXIMA,
                ),
            )

    return expedientes_procesados, movimientos_nuevos


def _ejecutar_polling(sesion: SesionSIPED) -> str:
    username = sesion.username_intranet

    try:
        cookies = descifrar_cookies(sesion.cookies_cifradas)
    except ErrorCifrado as exc:
        _marcar_expirada(sesion, str(exc))
        return "No se pudieron descifrar las cookies almacenadas."

    try:
        session = session_manager.crear_sesion_con_cookies(cookies)

        # La primera petición de la lista ya valida si la intranet devolvió el
        # login, así que no hace falta un request extra de verificación.
        lista = scraper_tasks.raspar_lista_expedientes(session)
        cambios = gestor_almacenamiento.sincronizar_lista_maestra(username, lista)
        novedades = _registrar_cambios(username, cambios)

        procesados, movimientos = _procesar_novedades(session, username)
        _registrar_exito(sesion, session)

        return (
            f"Polling completado: {len(cambios['nuevos'])} expedientes nuevos, "
            f"{len(cambios['actualizados'])} con cambios, "
            f"{novedades} novedades creadas, {procesados} expedientes "
            f"procesados y {movimientos} movimientos nuevos."
        )
    except SesionSIPEDExpirada as exc:
        _marcar_expirada(sesion, str(exc))
        return "La sesión de la intranet expiró."
    except (SolicitudIncompleta, PaginaInesperada) as exc:
        _registrar_fallo(sesion, exc)
        return f"Polling incompleto: {exc}"
    except Exception as exc:
        logger.exception("Error inesperado durante el polling de %s", username)
        _registrar_fallo(sesion, exc)
        return f"Error inesperado durante el polling: {exc}"


def ejecutar_polling_usuario(username_intranet: str) -> str:
    """
    Consulta la lista maestra de un usuario y refresca lo que haya cambiado.

    Es idempotente: puede ejecutarse varias veces sin duplicar expedientes,
    movimientos ni novedades.
    """
    try:
        sesion = SesionSIPED.objects.get(username_intranet=username_intranet)
    except SesionSIPED.DoesNotExist:
        return f"No hay sesión almacenada para {username_intranet}."

    if (
        sesion.estado != SesionSIPED.Estado.ACTIVA
        or not sesion.cookies_cifradas
    ):
        return f"La sesión de {username_intranet} no está activa."

    if not _bloquear_sesion(sesion):
        logger.info("El polling de %s ya está en curso; se omite.", username_intranet)
        return "El polling ya está en curso."

    try:
        return _ejecutar_polling(sesion)
    finally:
        SesionSIPED.objects.filter(pk=sesion.pk).update(bloqueado_hasta=None)
