"""Módulo para la persistencia y consulta de datos del sistema judicial."""

from typing import Any

from django.db import transaction
from django.db.models import Max
from django.db.models.functions import Greatest
from django.utils import timezone

from .fechas import parsear_fecha_hora_intranet
from .fechas import parsear_fecha_intranet
from .models import DocumentoAdjunto
from .models import Expediente
from .models import Movimiento
from .models import NovedadSIPED
from .models import ReporteBusqueda


def _valores_expediente(data: dict[str, Any]) -> dict[str, Any]:
    """Traduce una fila extraída por los parsers a campos del modelo.

    ``fec_ult_mov`` llega como texto ``dd/mm/yyyy`` desde la intranet; en la
    base se guarda como ``fecha_ult_mov`` (``DateField``). La celda vacía se
    convierte en ``NULL``: los expedientes públicos no informan último
    movimiento y no deben inventar una fecha.
    """
    return {
        "caratula":      data.get("caratula", ""),
        "partes":        data.get("partes", ""),
        "estado":        data.get("estado", ""),
        "fecha_ult_mov": parsear_fecha_intranet(data.get("fec_ult_mov")),
        "localidad":     data.get("localidad", ""),
        "dependencia":   data.get("dependencia", ""),
        "secretaria":    data.get("secretaria", ""),
        "link_detalle":  data.get("link_detalle", ""),
        "origen":        data.get("origen", "PRIVADO"),
    }


def listar_documentos_pdf(username: str) -> list[str]:
    """
    Recupera los nombres originales de los PDFs consolidados asociados a un usuario.
    Solo retorna consolidados para evitar duplicados en la lista de la UI.

    Args:
        username: Identificador del usuario.

    Returns:
        Lista de nombres de archivos ordenados de forma descendente por creación.
    """
    documentos = DocumentoAdjunto.objects.filter(
        expediente__usuario_asignado=username,
        es_consolidado=True,
    ).order_by("-fecha_creacion")

    return [doc.nombre_original for doc in documentos]


def verificar_existencia_expedientes(username: str) -> bool:
    """
    Verifica si existen expedientes registrados para el usuario en la base de datos.

    Args:
        username: Identificador del usuario.

    Returns:
        Verdadero si hay al menos un expediente, Falso en caso contrario.
    """
    return Expediente.objects.filter(usuario_asignado=username).exists()


def listar_expedientes_con_movimientos(username: str) -> list[str]:
    """
    Obtiene los números de expediente que poseen movimientos extraídos.

    Args:
        username: Identificador del usuario.

    Returns:
        Lista de números de expediente con movimientos asociados.
    """
    expedientes = (
        Expediente.objects.filter(usuario_asignado=username, movimientos__isnull=False)
        .distinct()
        .values_list("numero_expediente", flat=True)
    )

    return sorted(expedientes)


def listar_reportes_busqueda(username: str) -> list[str]:
    """
    Recupera los nombres de los archivos CSV generados por búsquedas avanzadas.

    Args:
        username: Identificador del usuario.

    Returns:
        Lista de nombres de archivo ordenados por fecha de generación.
    """
    reportes = ReporteBusqueda.objects.filter(usuario_asignado=username).order_by(
        "-fecha_generacion",
    )

    return [
        reporte.archivo_csv.name.split("/")[-1]
        for reporte in reportes
        if reporte.archivo_csv
    ]


def guardar_expedientes_lote(
    username: str,
    expedientes_data: list[dict[str, Any]],
) -> None:
    """
    Inserta o actualiza un lote de expedientes en la base de datos de forma
    transaccional.

    Args:
        username: Identificador del usuario al que pertenecen los expedientes.
        expedientes_data: Lista de diccionarios con los datos extraídos por los parsers.
    """
    with transaction.atomic():
        for data in expedientes_data:
            numero_exp = data.get("expediente", "").strip()
            if not numero_exp:
                continue

            Expediente.objects.update_or_create(
                usuario_asignado=username,
                numero_expediente=numero_exp,
                defaults=_valores_expediente(data),
            )


def sincronizar_lista_maestra(
    username: str, expedientes_data: list[dict[str, Any]],
) -> dict[str, list[Expediente]]:
    """
    Inserta o actualiza la lista maestra y clasifica los cambios detectados.

    Un expediente se considera "actualizado" cuando cambió su último movimiento
    o su estado. Los cambios puramente descriptivos (carátula, dependencia,
    etc.) se guardan sin generar una novedad.

    Args:
        username: Identificador del usuario propietario de la lista.
        expedientes_data: Filas extraídas de la lista maestra de la intranet.

    Returns:
        Diccionario con las claves ``nuevos`` y ``actualizados``, cada una con
        la lista de instancias de ``Expediente`` afectadas.
    """
    nuevos: list[Expediente] = []
    actualizados: list[Expediente] = []

    with transaction.atomic():
        for data in expedientes_data:
            numero_exp = data.get("expediente", "").strip()
            if not numero_exp:
                continue

            valores = _valores_expediente(data)

            expediente, creado = Expediente.objects.get_or_create(
                usuario_asignado=username,
                numero_expediente=numero_exp,
                defaults=valores,
            )
            if creado:
                nuevos.append(expediente)
                continue

            cambio_relevante = (
                expediente.fecha_ult_mov != valores["fecha_ult_mov"]
                or expediente.estado != valores["estado"]
            )
            for campo, valor in valores.items():
                setattr(expediente, campo, valor)
            expediente.save()
            if cambio_relevante:
                actualizados.append(expediente)

    return {"nuevos": nuevos, "actualizados": actualizados}


def _texto_movimiento(data: dict[str, Any], clave: str) -> str:
    """Devuelve el valor de ``data`` como texto sin espacios sobrantes."""
    valor = data.get(clave)
    return valor.strip() if isinstance(valor, str) else ""


def _valores_movimiento(data: dict[str, Any]) -> dict[str, Any]:
    """Traduce una fila de la tabla de movimientos a campos del modelo."""
    return {
        "codigo_escrito": _texto_movimiento(data, "codigo_escrito"),
        "tasa": _texto_movimiento(data, "tasa"),
        "fecha_presentacion": parsear_fecha_hora_intranet(
            data.get("fecha_presentacion"),
        ),
        "tipo": _texto_movimiento(data, "tipo"),
        "estado": _texto_movimiento(data, "estado"),
        "generado_por": _texto_movimiento(data, "generado_por"),
        "descripcion": _texto_movimiento(data, "descripcion"),
        "fecha_firma": parsear_fecha_hora_intranet(data.get("fecha_firma")),
        "fecha_publicacion": parsear_fecha_hora_intranet(
            data.get("fecha_publicacion"),
        ),
    }


def guardar_movimientos_lote(
    username: str,
    numero_expediente: str,
    movimientos_data: list[dict[str, Any]],
    novedad: NovedadSIPED | None = None,
) -> tuple[int, int]:
    """
    Inserta o actualiza un lote de movimientos asociados a un expediente específico.

    Usa ``link_escrito`` como clave de unicidad cuando está disponible, ya que
    es el identificador más estable extraído del HTML. Cuando el movimiento no
    tiene link (por ejemplo, providencias sin documento adjunto) usa el código
    de escrito junto con la fecha de presentación como clave.

    Al finalizar, adelanta ``Expediente.fecha_ult_mov`` si los movimientos
    sincronizados son más recientes que la fecha que informó la lista maestra.
    Sólo avanza: nunca retrocede una fecha ya guardada.

    Args:
        username: Identificador del usuario propietario del expediente.
        numero_expediente: Número de expediente al que corresponden los movimientos.
        movimientos_data: Lista de diccionarios con los datos extraídos de la
            plataforma.
        novedad: Novedad que originó la sincronización. Solo se asigna a los
            movimientos creados; las actualizaciones conservan su vínculo.

    Returns:
        Tupla ``(creados, actualizados)``. Si el expediente no existe devuelve
        ``(0, 0)``.
    """
    try:
        expediente = Expediente.objects.get(
            usuario_asignado=username,
            numero_expediente=numero_expediente,
        )
    except Expediente.DoesNotExist:
        return 0, 0

    creados = 0
    actualizados = 0

    with transaction.atomic():
        for data in movimientos_data:
            valores = _valores_movimiento(data)
            link = _texto_movimiento(data, "link_escrito")
            codigo = valores["codigo_escrito"]

            # Algunas respuestas incluyen filas separadoras vacías. Sin link
            # ni código no hay forma de identificar el movimiento.
            if not link and not codigo:
                continue

            if link:
                lookup = {"expediente": expediente, "link_escrito": link}
                defaults = valores
            else:
                lookup = {
                    "expediente": expediente,
                    "codigo_escrito": codigo,
                    "fecha_presentacion": valores["fecha_presentacion"],
                }
                defaults = {**valores, "link_escrito": ""}

            _, creado = Movimiento.objects.update_or_create(
                defaults=defaults,
                create_defaults={**defaults, "novedad": novedad},
                **lookup,
            )
            if creado:
                creados += 1
            else:
                actualizados += 1

        _adelantar_fecha_ult_mov(expediente)

    return creados, actualizados


def _adelantar_fecha_ult_mov(expediente: Expediente) -> None:
    """Actualiza ``fecha_ult_mov`` si los movimientos guardados son posteriores."""
    ultima = Movimiento.objects.filter(expediente=expediente).aggregate(
        ultima=Max(
            Greatest("fecha_presentacion", "fecha_firma", "fecha_publicacion"),
        ),
    )["ultima"]

    if not ultima:
        return

    fecha_local = timezone.localtime(
        ultima,
        timezone.get_default_timezone(),
    ).date()
    if expediente.fecha_ult_mov is None or fecha_local > expediente.fecha_ult_mov:
        Expediente.objects.filter(pk=expediente.pk).update(
            fecha_ult_mov=fecha_local,
        )
        expediente.fecha_ult_mov = fecha_local
