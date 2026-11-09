"""Pruebas de la conversión de fechas de la intranet."""

from datetime import date

import pytest
from django.utils import timezone

from foros.siped.fechas import formatear_fecha_hora_intranet
from foros.siped.fechas import formatear_fecha_intranet
from foros.siped.fechas import parsear_fecha_hora_intranet
from foros.siped.fechas import parsear_fecha_intranet


class TestParsearFechaIntranet:
    @pytest.mark.parametrize("valor", ["08/11/2026", "8/11/2026", " 08/11/2026 "])
    def test_fecha_valida(self, valor: str) -> None:
        assert parsear_fecha_intranet(valor) == date(2026, 11, 8)

    @pytest.mark.parametrize("valor", ["", "   ", None])
    def test_sin_fecha(self, valor: str | None) -> None:
        assert parsear_fecha_intranet(valor) is None

    @pytest.mark.parametrize(
        "valor",
        [
            "31/02/2026",
            "00/00/0000",
            "01/01/0000",
            "2026-11-08",
            "8/11/26",
            "abc",
            "08/11/2026 10:00",
        ],
    )
    def test_fecha_invalida(self, valor: str) -> None:
        assert parsear_fecha_intranet(valor) is None


class TestParsearFechaHoraIntranet:
    def test_fecha_hora_valida(self) -> None:
        valor = parsear_fecha_hora_intranet("15/11/2024 11:12:07")

        local = timezone.localtime(valor, timezone.get_default_timezone())
        assert timezone.is_aware(valor)
        assert local.strftime("%d/%m/%Y %H:%M:%S") == "15/11/2024 11:12:07"

    def test_fecha_hora_sin_segundos(self) -> None:
        valor = parsear_fecha_hora_intranet("15/11/2024 11:12")

        local = timezone.localtime(valor, timezone.get_default_timezone())
        assert timezone.is_aware(valor)
        assert local.strftime("%d/%m/%Y %H:%M:%S") == "15/11/2024 11:12:00"

    def test_asume_la_zona_del_proyecto(self) -> None:
        valor = parsear_fecha_hora_intranet("15/11/2024 11:12:07")

        # America/Argentina/Buenos_Aires es UTC-3 todo el año.
        assert valor.utcoffset().total_seconds() == -3 * 60 * 60

    @pytest.mark.parametrize(
        "valor",
        [
            "",
            "   ",
            None,
            "15/11/2024",
            "15/11/2024 25:00:00",
            "31/02/2024 10:00:00",
            "2024-11-15 11:12:07",
            "abc",
        ],
    )
    def test_fecha_hora_invalida(self, valor: str | None) -> None:
        assert parsear_fecha_hora_intranet(valor) is None


class TestFormatearFechaIntranet:
    def test_fecha(self) -> None:
        assert formatear_fecha_intranet(date(2026, 11, 8)) == "08/11/2026"

    def test_sin_fecha(self) -> None:
        assert formatear_fecha_intranet(None) == ""


class TestFormatearFechaHoraIntranet:
    def test_fecha_hora(self) -> None:
        valor = parsear_fecha_hora_intranet("15/11/2024 11:12:07")

        assert formatear_fecha_hora_intranet(valor) == "15/11/2024 11:12:07"

    def test_sin_fecha_hora(self) -> None:
        assert formatear_fecha_hora_intranet(None) == ""
