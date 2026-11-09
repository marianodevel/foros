"""Conversión entre las fechas de texto de la intranet y ``datetime.date``.

La intranet publica las fechas como ``dd/mm/yyyy`` en columnas de texto. El
parseo se hace siempre en Python y nunca con ``to_date()`` de PostgreSQL: esa
función devuelve ``0001-01-01 BC`` cuando la celda viene vacía, y psycopg no
puede convertir a ``datetime.date`` una fecha anterior al año 1.
"""

import logging
import re
from datetime import date

logger = logging.getLogger(__name__)

FORMATO_FECHA_INTRANET = "%d/%m/%Y"

# Día y mes pueden venir sin cero a la izquierda ("1/2/2026"), pero el año
# siempre tiene cuatro dígitos. Se exige el patrón completo para no aceptar
# "8/11/26" como año 26, que el parseo convertiría sin avisar.
_PATRON_FECHA_INTRANET = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


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
            logger.warning(
                "Fecha de intranet inválida; se almacena como NULL: %r",
                valor,
            )
        return None

    dia, mes, anio = (int(parte) for parte in limpio.split("/"))
    try:
        return date(anio, mes, dia)
    except ValueError:
        logger.warning(
            "Fecha de intranet inválida; se almacena como NULL: %r",
            valor,
        )
        return None


def formatear_fecha_intranet(valor: date | None) -> str:
    """Devuelve ``dd/mm/yyyy`` o cadena vacía, para CSV y mensajes de usuario."""
    return valor.strftime(FORMATO_FECHA_INTRANET) if valor else ""
