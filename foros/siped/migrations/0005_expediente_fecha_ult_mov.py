"""Reemplaza ``fec_ult_mov`` (texto ``dd/mm/yyyy``) por ``fecha_ult_mov`` (fecha).

El backfill se hace en Python, no con ``to_date()`` de PostgreSQL: esa función
devuelve ``0001-01-01 BC`` para la celda vacía y psycopg no puede convertir
fechas anteriores al año 1. Las celdas vacías o inválidas quedan en ``NULL``.
"""

from datetime import datetime

from django.db import migrations, models


def migrar_fechas(apps, schema_editor):
    """Copia las fechas válidas de ``fec_ult_mov`` a ``fecha_ult_mov``."""
    Expediente = apps.get_model("siped", "Expediente")
    actualizados = []

    for expediente in Expediente.objects.only("id", "fec_ult_mov").iterator():
        valor = (expediente.fec_ult_mov or "").strip()
        fecha = None
        if valor:
            try:
                fecha = datetime.strptime(valor, "%d/%m/%Y").date()
            except ValueError:
                fecha = None
        expediente.fecha_ult_mov = fecha
        actualizados.append(expediente)

    Expediente.objects.bulk_update(actualizados, ["fecha_ult_mov"], batch_size=500)


def revertir_fechas(apps, schema_editor):
    """Restaura el texto ``dd/mm/yyyy`` en ``fec_ult_mov`` al volver atrás."""
    Expediente = apps.get_model("siped", "Expediente")
    actualizados = []

    for expediente in Expediente.objects.only("id", "fecha_ult_mov").iterator():
        expediente.fec_ult_mov = (
            expediente.fecha_ult_mov.strftime("%d/%m/%Y")
            if expediente.fecha_ult_mov
            else ""
        )
        actualizados.append(expediente)

    Expediente.objects.bulk_update(actualizados, ["fec_ult_mov"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("siped", "0004_sesionsiped_novedadsiped"),
    ]

    operations = [
        migrations.AddField(
            model_name="expediente",
            name="fecha_ult_mov",
            field=models.DateField(
                blank=True,
                db_index=True,
                help_text="Último movimiento según la intranet, ya convertido a fecha.",
                null=True,
            ),
        ),
        migrations.RunPython(migrar_fechas, revertir_fechas),
        migrations.RemoveField(
            model_name="expediente",
            name="fec_ult_mov",
        ),
    ]
