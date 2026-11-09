"""Pruebas del almacenamiento de movimientos."""

import pytest
from django.utils import timezone

from foros.siped import gestor_almacenamiento
from foros.siped.models import Expediente
from foros.siped.models import Movimiento

pytestmark = pytest.mark.django_db

FORMATO = "%d/%m/%Y %H:%M:%S"


@pytest.fixture
def expediente():
    return Expediente.objects.create(
        usuario_asignado="abogado",
        numero_expediente="123/2024",
        caratula="PEREZ C GOMEZ",
    )


def _movimiento(**overrides) -> dict:
    data = {
        "nombre_escrito": "Escrito",
        "fecha_presentacion": "01/02/2024",
        "tipo": "Escrito",
        "estado": "Presentado",
        "generado_por": "Abogado",
        "descripcion": "",
        "fecha_firma": "",
        "fecha_publicacion": "15/11/2024 11:12:07",
        "link_escrito": "https://intranet/ver_escrito.php?id=1",
    }
    data.update(overrides)
    return data


class TestFechaPublicacion:
    def test_guarda_datetime_con_zona(self, expediente) -> None:
        gestor_almacenamiento.guardar_movimientos_lote(
            "abogado",
            "123/2024",
            [_movimiento()],
        )

        movimiento = Movimiento.objects.get(expediente=expediente)
        assert timezone.is_aware(movimiento.fecha_publicacion)
        local = timezone.localtime(
            movimiento.fecha_publicacion,
            timezone.get_default_timezone(),
        )
        assert local.strftime(FORMATO) == "15/11/2024 11:12:07"

    def test_fecha_vacia_guarda_none(self, expediente) -> None:
        gestor_almacenamiento.guardar_movimientos_lote(
            "abogado",
            "123/2024",
            [_movimiento(fecha_publicacion="")],
        )

        movimiento = Movimiento.objects.get(expediente=expediente)
        assert movimiento.fecha_publicacion is None

    def test_fecha_sin_hora_guarda_none(self, expediente) -> None:
        gestor_almacenamiento.guardar_movimientos_lote(
            "abogado",
            "123/2024",
            [_movimiento(fecha_publicacion="15/11/2024")],
        )

        movimiento = Movimiento.objects.get(expediente=expediente)
        assert movimiento.fecha_publicacion is None
