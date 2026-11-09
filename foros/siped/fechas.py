"""Conversión entre las fechas de la intranet y ``date``/``datetime``.

La intranet publica las fechas como texto: ``dd/mm/yyyy`` para el último
movimiento y ``dd/mm/yyyy HH:MM:SS`` para la fecha de publicación. El parseo se
hace siempre en Python y nunca con ``to_date()`` de PostgreSQL: esa función
devuelve ``0001-01-01 BC`` cuando la celda viene vacía, y psycopg no puede
convertir a ``datetime.date`` una fecha anterior al año 1.
"""

import logging
import re
from datetime import date
from datetime import datetime

from django.utils import timezone

logger = logging.getLogger(__name__)

FORMATO_FECHA_INTRANET = "%d/%m/%Y"
FORMATO_FECHA_HORA_INTRANET = "%d/%m/%Y %H:%M:%S"

# Día y mes pueden venir sin cero a la izquierda ("1/2/2026"), pero el año
# siempre tiene cuatro dígitos. Se exige el patrón completo para no aceptar
# "8/11/26" como año 26, que el parseo convertiría sin avisar.
_PATRON_FECHA_INTRANET = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
_PATRON_FECHA_HORA_INTRANET = re.compile(
    r"^\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}:\d{2}$",
)


def _advertir_valor_invalido(valor: str) -> None:
    logger.warning("Fecha de intranet inválida; se almacena como NULL: %r", valor)


def parsear_fecha_intranet(valor: str | None) -> date | None:
    """Convierte una fecha ``dd/mm/yyyy`` de la intranet en ``date``.

    Devuelve ``None`` cuando la celda viene vacía o no es una fecha válida.
    La celda vacía es un caso legítimo: los expedientes públicos no informan
    último movimiento, y ``fecha_ult_mov`` queda en ``NULL``.

    Args:
        valor: Texto tal como lo entrega el parser.

    Returns:
        La fecha parseada, o ``None`` si no se puede interpretar.
    """
    if not isinstance(valor, str):
        return None

    limpio = valor.strip()
    if not _PATRON_FECHA_INTRANET.match(limpio):
        if limpio:
            _advertir_valor_invalido(limpio)
        return None

    dia, mes, anio = (int(parte) for parte in limpio.split("/"))
    try:
        return date(anio, mes, dia)
    except ValueError:
        _advertir_valor_invalido(limpio)
        return None


def parsear_fecha_hora_intranet(valor: str | None) -> datetime | None:
    """Convierte ``dd/mm/yyyy HH:MM:SS`` en un ``datetime`` con zona local.

    La intranet publica la fecha de publicación con hora de pared de Argentina
    y sin zona horaria. Se interpreta en ``TIME_ZONE`` para guardarla como
    instante absoluto y que Django la pueda comparar y serializar.

    Args:
        valor: Texto tal como lo entrega el parser.

    Returns:
        El ``datetime`` con zona, o ``None`` si no se puede interpretar.
    """
    if not isinstance(valor, str):
        return None

    limpio = valor.strip()
    if not _PATRON_FECHA_HORA_INTRANET.match(limpio):
        if limpio:
            _advertir_valor_invalido(limpio)
        return None

    try:
        # Es naive a propósito: el origen no informa zona horaria y se le
        # asigna la del proyecto justo después.
        fecha_hora = datetime.strptime(  # noqa: DTZ007
            limpio,
            FORMATO_FECHA_HORA_INTRANET,
        )
    except ValueError:
        _advertir_valor_invalido(limpio)
        return None

    return timezone.make_aware(fecha_hora, timezone.get_default_timezone())


def formatear_fecha_intranet(valor: date | None) -> str:
    """Devuelve ``dd/mm/yyyy`` o cadena vacía, para CSV y mensajes de usuario."""
    return valor.strftime(FORMATO_FECHA_INTRANET) if valor else ""
