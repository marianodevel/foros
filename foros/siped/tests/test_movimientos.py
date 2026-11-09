"""Pruebas del almacenamiento de movimientos."""

from datetime import date

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
        "expediente_nro": "123/2024",
        "codigo_escrito": "PE1234567-2026",
        "tasa": "",
        "fecha_presentacion": "27/10/2026 12:32:57",
        "tipo": "OFICIO",
        "estado": "DESGLOSADO",
        "generado_por": "BRIAMONTE, JORGE ALBERTO",
        "descripcion": "OFICIO A CONFRONTE",
        "fecha_firma": "",
        "fecha_publicacion": "27/10/2026 12:32",
        "link_escrito": "https://intranet/ver_escrito.php?id=1",
    }
    data.update(overrides)
    return data


def _local(valor):
    return timezone.localtime(valor, timezone.get_default_timezone())


class TestAlmacenamiento:
    def test_mapea_todas_las_columnas(self, expediente) -> None:
        gestor_almacenamiento.guardar_movimientos_lote(
            "abogado",
            "123/2024",
            [_movimiento(tasa="✅ Exento Bono C.A.")],
        )

        movimiento = Movimiento.objects.get(expediente=expediente)
        assert movimiento.codigo_escrito == "PE1234567-2026"
        assert movimiento.tasa == "✅ Exento Bono C.A."
        assert movimiento.tipo == "OFICIO"
        assert movimiento.estado == "DESGLOSADO"
        assert movimiento.generado_por == "BRIAMONTE, JORGE ALBERTO"
        assert movimiento.descripcion == "OFICIO A CONFRONTE"
        assert movimiento.link_escrito == "https://intranet/ver_escrito.php?id=1"

    def test_fechas_con_zona(self, expediente) -> None:
        gestor_almacenamiento.guardar_movimientos_lote(
            "abogado",
            "123/2024",
            [_movimiento(fecha_firma="27/10/2026 12:40:01")],
        )

        movimiento = Movimiento.objects.get(expediente=expediente)
        assert timezone.is_aware(movimiento.fecha_presentacion)
        assert timezone.is_aware(movimiento.fecha_firma)
        assert timezone.is_aware(movimiento.fecha_publicacion)
        assert (
            _local(movimiento.fecha_presentacion).strftime(FORMATO)
            == "27/10/2026 12:32:57"
        )
        assert (
            _local(movimiento.fecha_firma).strftime(FORMATO)
            == "27/10/2026 12:40:01"
        )
        # La publicación viene sin segundos.
        assert (
            _local(movimiento.fecha_publicacion).strftime(FORMATO)
            == "27/10/2026 12:32:00"
        )

    @pytest.mark.parametrize(
        "campo",
        ["fecha_presentacion", "fecha_firma", "fecha_publicacion"],
    )
    def test_fecha_vacia_guarda_none(self, expediente, campo: str) -> None:
        gestor_almacenamiento.guardar_movimientos_lote(
            "abogado",
            "123/2024",
            [_movimiento(**{campo: ""})],
        )

        movimiento = Movimiento.objects.get(expediente=expediente)
        assert getattr(movimiento, campo) is None

    def test_fecha_sin_hora_guarda_none(self, expediente) -> None:
        gestor_almacenamiento.guardar_movimientos_lote(
            "abogado",
            "123/2024",
            [_movimiento(fecha_publicacion="15/11/2024")],
        )

        movimiento = Movimiento.objects.get(expediente=expediente)
        assert movimiento.fecha_publicacion is None


class TestDeduplicacion:
    def test_actualiza_por_link(self, expediente) -> None:
        gestor_almacenamiento.guardar_movimientos_lote(
            "abogado", "123/2024", [_movimiento()],
        )
        creados, actualizados = gestor_almacenamiento.guardar_movimientos_lote(
            "abogado",
            "123/2024",
            [_movimiento(tipo="PROVIDENCIA")],
        )

        assert (creados, actualizados) == (0, 1)
        assert Movimiento.objects.get(expediente=expediente).tipo == "PROVIDENCIA"

    def test_sin_link_usa_codigo_y_fecha(self, expediente) -> None:
        sin_link = _movimiento(link_escrito="")
        gestor_almacenamiento.guardar_movimientos_lote(
            "abogado", "123/2024", [sin_link],
        )
        creados, actualizados = gestor_almacenamiento.guardar_movimientos_lote(
            "abogado", "123/2024", [sin_link],
        )

        assert (creados, actualizados) == (0, 1)
        assert Movimiento.objects.filter(expediente=expediente).count() == 1

    def test_sin_link_y_fecha_distinta_crea_otro(self, expediente) -> None:
        gestor_almacenamiento.guardar_movimientos_lote(
            "abogado",
            "123/2024",
            [_movimiento(link_escrito="")],
        )
        gestor_almacenamiento.guardar_movimientos_lote(
            "abogado",
            "123/2024",
            [_movimiento(link_escrito="", fecha_presentacion="28/10/2026 09:00:00")],
        )

        assert (
            Movimiento.objects.filter(expediente=expediente).count() == 2  # noqa: PLR2004
        )

    def test_ignora_filas_vacias(self, expediente) -> None:
        fila_vacia = {
            "codigo_escrito": "",
            "tasa": "",
            "fecha_presentacion": "",
            "tipo": "",
            "estado": "",
            "generado_por": "",
            "descripcion": "",
            "fecha_firma": "",
            "fecha_publicacion": "",
            "link_escrito": "",
        }

        creados, actualizados = gestor_almacenamiento.guardar_movimientos_lote(
            "abogado", "123/2024", [fila_vacia],
        )

        assert (creados, actualizados) == (0, 0)
        assert not Movimiento.objects.filter(expediente=expediente).exists()


class TestFechaUltimoMovimiento:
    def test_adelanta_la_fecha_del_expediente(self, expediente) -> None:
        assert expediente.fecha_ult_mov is None

        gestor_almacenamiento.guardar_movimientos_lote(
            "abogado", "123/2024", [_movimiento()],
        )

        expediente.refresh_from_db()
        assert expediente.fecha_ult_mov == date(2026, 10, 27)

    def test_nunca_retrocede_la_fecha(self, expediente) -> None:
        expediente.fecha_ult_mov = date(2026, 12, 1)
        expediente.save(update_fields=["fecha_ult_mov"])

        gestor_almacenamiento.guardar_movimientos_lote(
            "abogado", "123/2024", [_movimiento()],
        )

        expediente.refresh_from_db()
        assert expediente.fecha_ult_mov == date(2026, 12, 1)
