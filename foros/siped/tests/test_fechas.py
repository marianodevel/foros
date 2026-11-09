"""Pruebas de la conversión de fechas de la intranet."""

from datetime import date

import pytest

from foros.siped.fechas import formatear_fecha_intranet
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


class TestFormatearFechaIntranet:
    def test_fecha(self) -> None:
        assert formatear_fecha_intranet(date(2026, 11, 8)) == "08/11/2026"

    def test_sin_fecha(self) -> None:
        assert formatear_fecha_intranet(None) == ""
