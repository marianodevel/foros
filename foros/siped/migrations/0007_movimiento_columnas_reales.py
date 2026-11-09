"""Alinea ``Movimiento`` con la tabla real de la intranet.

La intranet agregó la columna ``Fecha Firma`` entre ``Descripción/detalle`` y
``Fecha Publicación``. El parser anterior leía posiciones fijas, así que desde
ese cambio todos los campos quedaron corridos un lugar.

Esta migración reubica los datos ya guardados:

* ``nombre_escrito``  -> ``codigo_escrito``
* ``fecha_presentacion`` (bonos/tasas) -> ``tasa``
* ``tipo`` (fecha/hora) -> ``fecha_presentacion`` (DateTimeField)
* ``estado`` -> ``tipo``
* ``generado_por`` -> ``estado``
* ``descripcion`` -> ``generado_por``
* ``fecha_firma`` (detalle) -> ``descripcion``
* ``fecha_firma`` arranca en ``NULL``: la columna nueva no tiene histórico.

Las tres filas totalmente vacías que dejaba la tabla se eliminan.
"""

from datetime import datetime

from django.db import migrations
from django.db import models
from django.utils import timezone

FORMATO = "%d/%m/%Y %H:%M:%S"


def _parsear_fecha_hora(valor):
    """Convierte ``dd/mm/yyyy HH:MM:SS`` en datetime con zona, o ``None``."""
    texto = (valor or "").strip()
    if not texto:
        return None

    try:
        fecha_hora = datetime.strptime(texto, FORMATO)  # noqa: DTZ007
    except ValueError:
        return None

    return timezone.make_aware(fecha_hora, timezone.get_default_timezone())


def _formatear_fecha_hora(valor):
    """Convierte un datetime con zona al texto que usaba el campo anterior."""
    if not valor:
        return ""

    return timezone.localtime(
        valor,
        timezone.get_default_timezone(),
    ).strftime(FORMATO)


def migrar_columnas(apps, schema_editor):
    """Mueve cada valor a la columna que le corresponde en la tabla real."""
    Movimiento = apps.get_model("siped", "Movimiento")
    a_actualizar = []
    a_eliminar = []

    for movimiento in Movimiento.objects.all().iterator():
        codigo = (movimiento.nombre_escrito or "").strip()
        tasa = (movimiento.fecha_presentacion or "").strip()
        presentacion = _parsear_fecha_hora(movimiento.tipo)
        tipo = (movimiento.estado or "").strip()
        estado = (movimiento.generado_por or "").strip()
        generado_por = (movimiento.descripcion or "").strip()
        descripcion = (movimiento.fecha_firma or "").strip()
        link = (movimiento.link_escrito or "").strip()

        fila_vacia = not any(
            [
                codigo,
                tasa,
                presentacion,
                tipo,
                estado,
                generado_por,
                descripcion,
                movimiento.fecha_publicacion,
                link,
            ],
        )
        if fila_vacia:
            a_eliminar.append(movimiento.id)
            continue

        movimiento.codigo_escrito = codigo
        movimiento.tasa = tasa
        movimiento.fecha_presentacion_dt = presentacion
        movimiento.tipo = tipo
        movimiento.estado = estado
        movimiento.generado_por = generado_por
        movimiento.descripcion = descripcion
        movimiento.fecha_firma_dt = None
        a_actualizar.append(movimiento)

    if a_actualizar:
        Movimiento.objects.bulk_update(
            a_actualizar,
            [
                "codigo_escrito",
                "tasa",
                "fecha_presentacion_dt",
                "tipo",
                "estado",
                "generado_por",
                "descripcion",
                "fecha_firma_dt",
            ],
            batch_size=500,
        )

    if a_eliminar:
        Movimiento.objects.filter(id__in=a_eliminar).delete()


def revertir_columnas(apps, schema_editor):
    """Reconstruye las columnas anteriores a partir de las nuevas."""
    Movimiento = apps.get_model("siped", "Movimiento")
    a_actualizar = []

    for movimiento in Movimiento.objects.all().iterator():
        movimiento.nombre_escrito = movimiento.codigo_escrito
        movimiento.fecha_presentacion = movimiento.tasa
        movimiento.fecha_firma = movimiento.descripcion
        movimiento.descripcion = movimiento.generado_por
        movimiento.generado_por = movimiento.estado
        movimiento.estado = movimiento.tipo
        movimiento.tipo = _formatear_fecha_hora(
            movimiento.fecha_presentacion_dt,
        )
        a_actualizar.append(movimiento)

    if a_actualizar:
        Movimiento.objects.bulk_update(
            a_actualizar,
            [
                "nombre_escrito",
                "fecha_presentacion",
                "fecha_firma",
                "descripcion",
                "generado_por",
                "estado",
                "tipo",
            ],
            batch_size=500,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("siped", "0006_movimiento_fecha_publicacion"),
    ]

    operations = [
        migrations.AddField(
            model_name="movimiento",
            name="codigo_escrito",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Código de la presentación electrónica "
                    "(por ejemplo, PE1234567-2026)."
                ),
                max_length=50,
            ),
        ),
        migrations.AddField(
            model_name="movimiento",
            name="tasa",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Estado de bonos y tasas informado por la intranet.",
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name="movimiento",
            name="fecha_presentacion_dt",
            field=models.DateTimeField(
                blank=True,
                help_text=(
                    "Presentación del escrito (hora de Argentina), "
                    "ya convertida."
                ),
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="movimiento",
            name="fecha_firma_dt",
            field=models.DateTimeField(
                blank=True,
                help_text=(
                    "Firma del movimiento (hora de Argentina), ya convertida."
                ),
                null=True,
            ),
        ),
        migrations.RunPython(migrar_columnas, revertir_columnas),
        migrations.RemoveField(
            model_name="movimiento",
            name="fecha_presentacion",
        ),
        migrations.RemoveField(
            model_name="movimiento",
            name="nombre_escrito",
        ),
        migrations.RemoveField(
            model_name="movimiento",
            name="fecha_firma",
        ),
        migrations.RenameField(
            model_name="movimiento",
            old_name="fecha_presentacion_dt",
            new_name="fecha_presentacion",
        ),
        migrations.RenameField(
            model_name="movimiento",
            old_name="fecha_firma_dt",
            new_name="fecha_firma",
        ),
    ]
