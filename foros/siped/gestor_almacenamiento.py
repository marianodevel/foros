"""Módulo para la persistencia y consulta de datos del sistema judicial."""

from typing import Any, Dict, List

from django.db import transaction

from .fechas import parsear_fecha_intranet
from .models import DocumentoAdjunto, Expediente, Movimiento, ReporteBusqueda


def _valores_expediente(data: Dict[str, Any]) -> Dict[str, Any]:
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


def listar_documentos_pdf(username: str) -> List[str]:
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
        es_consolidado=True
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


def listar_expedientes_con_movimientos(username: str) -> List[str]:
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

    return sorted(list(expedientes))


def listar_reportes_busqueda(username: str) -> List[str]:
    """
    Recupera los nombres de los archivos CSV generados por búsquedas avanzadas.

    Args:
        username: Identificador del usuario.

    Returns:
        Lista de nombres de archivo ordenados por fecha de generación.
    """
    reportes = ReporteBusqueda.objects.filter(usuario_asignado=username).order_by(
        "-fecha_generacion"
    )

    return [
        reporte.archivo_csv.name.split("/")[-1]
        for reporte in reportes
        if reporte.archivo_csv
    ]


def guardar_expedientes_lote(username: str, expedientes_data: List[Dict[str, Any]]) -> None:
    """
    Inserta o actualiza un lote de expedientes en la base de datos de forma transaccional.

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
    username: str, expedientes_data: List[Dict[str, Any]]
) -> Dict[str, List[Expediente]]:
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
    nuevos: List[Expediente] = []
    actualizados: List[Expediente] = []

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


def guardar_movimientos_lote(
    username: str, numero_expediente: str, movimientos_data: List[Dict[str, Any]]
) -> tuple[int, int]:
    """
    Inserta o actualiza un lote de movimientos asociados a un expediente específico.
    Usa link_escrito como clave de unicidad cuando está disponible, ya que es el
    identificador más estable extraído del HTML. Cuando el movimiento no tiene link
    (ej: providencias sin documento adjunto), hace fallback a nombre+fecha.

    Args:
        username: Identificador del usuario propietario del expediente.
        numero_expediente: Número de expediente al que corresponden los movimientos.
        movimientos_data: Lista de diccionarios con los datos extraídos de la plataforma.

    Returns:
        Tupla ``(creados, actualizados)``. Si el expediente no existe devuelve
        ``(0, 0)``.
    """
    try:
        expediente = Expediente.objects.get(
            usuario_asignado=username, numero_expediente=numero_expediente
        )
    except Expediente.DoesNotExist:
        return 0, 0

    creados = 0
    actualizados = 0

    with transaction.atomic():
        for data in movimientos_data:
            link = data.get("link_escrito", "").strip()

            if link:
                _, creado = Movimiento.objects.update_or_create(
                    expediente=expediente,
                    link_escrito=link,
                    defaults={
                        "fecha_presentacion": data.get("fecha_presentacion", ""),
                        "nombre_escrito":     data.get("nombre_escrito", ""),
                        "tipo":               data.get("tipo", ""),
                        "estado":             data.get("estado", ""),
                        "generado_por":       data.get("generado_por", ""),
                        "descripcion":        data.get("descripcion", ""),
                        "fecha_firma":        data.get("fecha_firma", ""),
                        "fecha_publicacion":  data.get("fecha_publicacion", ""),
                    },
                )
                if creado:
                    creados += 1
                else:
                    actualizados += 1
            else:
                # Sin link: fallback al par nombre+fecha (movimientos sin documento)
                _, creado = Movimiento.objects.update_or_create(
                    expediente=expediente,
                    nombre_escrito=data.get("nombre_escrito", ""),
                    fecha_presentacion=data.get("fecha_presentacion", ""),
                    defaults={
                        "tipo":              data.get("tipo", ""),
                        "estado":            data.get("estado", ""),
                        "generado_por":      data.get("generado_por", ""),
                        "descripcion":       data.get("descripcion", ""),
                        "fecha_firma":       data.get("fecha_firma", ""),
                        "fecha_publicacion": data.get("fecha_publicacion", ""),
                        "link_escrito":      "",
                    },
                )
                if creado:
                    creados += 1
                else:
                    actualizados += 1

    return creados, actualizados
