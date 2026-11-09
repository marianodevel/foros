"""Convierte ``Movimiento.fecha_publicacion`` de texto a ``DateTimeField``.

La intranet publica la fecha con hora de pared de Argentina
(``dd/mm/yyyy HH:MM:SS``) y sin zona horaria. El backfill parsea en Python y
asigna ``TIME_ZONE``; las celdas vacías o inválidas quedan en ``NULL``.
"""

from datetime import datetime

from django.db import migrations, models
from django.utils import timezone

FORMATO = "%d/%m/%Y %H:%M:%S"


def migrar_fechas(apps, schema_editor):
    """Copia las fechas válidas de ``fecha_publicacion`` al campo temporal."""
    Movimiento = apps.get_model("siped", "Movimiento")
    actualizados = []

    for movimiento in Movimiento.objects.only("id", "fecha_publicacion").iterator():
        valor = (movimiento.fecha_publicacion or "").strip()
        fecha_hora = None
        if valor:
            try:
                fecha_hora = datetime.strptime(valor, FORMATO)
            except ValueError:
                fecha_hora = None
            else:
                fecha_hora = timezone.make_aware(
                    fecha_hora,
                    timezone.get_default_timezone(),
                )
        movimiento.fecha_publicacion_dt = fecha_hora
        actualizados.append(movimiento)

    Movimiento.objects.bulk_update(
        actualizados,
        ["fecha_publicacion_dt"],
        batch_size=500,
    )


def revertir_fechas(apps, schema_editor):
    """Restaura el texto original en ``fecha_publicacion`` al volver atrás."""
    Movimiento = apps.get_model("siped", "Movimiento")
    actualizados = []

    for movimiento in Movimiento.objects.only("id", "fecha_publicacion_dt").iterator():
        if movimiento.fecha_publicacion_dt:
            local = timezone.localtime(
                movimiento.fecha_publicacion_dt,
                timezone.get_default_timezone(),
            )
            movimiento.fecha_publicacion = local.strftime(FORMATO)
        else:
            movimiento.fecha_publicacion = ""
        actualizados.append(movimiento)

    Movimiento.objects.bulk_update(
        actualizados,
        ["fecha_publicacion"],
        batch_size=500,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("siped", "0005_expediente_fecha_ult_mov"),
    ]

    operations = [
        migrations.AddField(
            model_name="movimiento",
            name="fecha_publicacion_dt",
            field=models.DateTimeField(
                blank=True,
                help_text="Publicación en la intranet (hora de Argentina), ya convertida.",
                null=True,
            ),
        ),
        migrations.RunPython(migrar_fechas, revertir_fechas),
        migrations.RemoveField(
            model_name="movimiento",
            name="fecha_publicacion",
        ),
        migrations.RenameField(
            model_name="movimiento",
            old_name="fecha_publicacion_dt",
            new_name="fecha_publicacion",
        ),
    ]
