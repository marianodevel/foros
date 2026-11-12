"""Pruebas del orden cronológico y del almacenamiento de fechas de expedientes."""

from __future__ import annotations

from datetime import date
from http import HTTPStatus
from unittest.mock import patch

import pytest
from django.urls import reverse

from foros.siped import gestor_almacenamiento
from foros.siped.forms import DescargaPublicaForm
from foros.siped.forms import SincronizacionIndividualForm
from foros.siped.models import Expediente

pytestmark = pytest.mark.django_db


def _crear(
    numero: str,
    fecha: date | None,
    *,
    usuario: str = "abogado",
    origen: str = "PRIVADO",
) -> Expediente:
    return Expediente.objects.create(
        usuario_asignado=usuario,
        numero_expediente=numero,
        caratula=f"CARATULA {numero}",
        fecha_ult_mov=fecha,
        origen=origen,
        link_detalle=f"https://intranet/detalle.php?exp={numero}",
    )


class TestOrdenSelectores:
    def test_individual_ordena_por_fecha_desc(self) -> None:
        _crear("viejo", date(2024, 1, 1))
        _crear("nuevo", date(2024, 3, 1))
        _crear("medio", date(2024, 2, 1))

        form = SincronizacionIndividualForm(usuario="abogado")
        numeros = [
            exp.numero_expediente
            for exp in form.fields["expediente_seleccionado"].queryset
        ]

        assert numeros == ["nuevo", "medio", "viejo"]

    def test_individual_deja_los_sin_fecha_al_final(self) -> None:
        _crear("sin-fecha", None)
        _crear("con-fecha", date(2024, 3, 1))

        form = SincronizacionIndividualForm(usuario="abogado")
        numeros = [
            exp.numero_expediente
            for exp in form.fields["expediente_seleccionado"].queryset
        ]

        assert numeros == ["con-fecha", "sin-fecha"]

    def test_publico_no_falla_con_fecha_vacia(self) -> None:
        # Regresión: convertir la celda vacía con to_date() producía
        # "0001-01-01 BC" y psycopg abortaba al materializar el formulario.
        _crear("publico-sin-fecha", None, origen="BUSQUEDA_AVANZADA")
        _crear("publico-con-fecha", date(2024, 5, 1), origen="PUBLICO")

        form = DescargaPublicaForm(usuario="abogado")
        numeros = [
            exp.numero_expediente
            for exp in form.fields["link_detalle_seleccionado"].queryset
        ]

        assert numeros == ["publico-con-fecha", "publico-sin-fecha"]


class TestAlmacenamientoDeFechas:
    def test_guardar_lote_convierte_el_texto_a_fecha(self) -> None:
        gestor_almacenamiento.guardar_expedientes_lote(
            "abogado",
            [{"expediente": "123/2024", "caratula": "X", "fec_ult_mov": "08/11/2026"}],
        )

        expediente = Expediente.objects.get(numero_expediente="123/2024")
        assert expediente.fecha_ult_mov == date(2026, 11, 8)

    def test_guardar_lote_con_fecha_vacia_guarda_none(self) -> None:
        gestor_almacenamiento.guardar_expedientes_lote(
            "abogado",
            [{"expediente": "123/2024", "caratula": "X", "fec_ult_mov": ""}],
        )

        expediente = Expediente.objects.get(numero_expediente="123/2024")
        assert expediente.fecha_ult_mov is None

    def test_cambio_solo_descriptivo_no_marca_actualizado(self) -> None:
        Expediente.objects.create(
            usuario_asignado="abogado",
            numero_expediente="123/2024",
            caratula="CARATULA VIEJA",
            estado="En letra",
            fecha_ult_mov=date(2026, 11, 8),
        )

        resultado = gestor_almacenamiento.sincronizar_lista_maestra(
            "abogado",
            [
                {
                    "expediente": "123/2024",
                    "caratula": "CARATULA NUEVA",
                    "estado": "En letra",
                    "fec_ult_mov": "08/11/2026",
                },
            ],
        )

        # La fecha se compara como fecha, no como texto: no debe generar novedad.
        assert resultado["actualizados"] == []
        assert Expediente.objects.get(numero_expediente="123/2024").caratula == (
            "CARATULA NUEVA"
        )


class TestIndiceConFechasVacias:
    @pytest.fixture
    def cliente(self, client, db):
        session = client.session
        session["siped_cookies"] = {"PHPSESSID": "cookie"}
        session["siped_username"] = "abogado"
        session.save()
        return client

    def test_indice_renderiza_con_expedientes_sin_fecha(self, cliente) -> None:
        _crear("privado-sin-fecha", None)
        _crear("publico-sin-fecha", None, origen="BUSQUEDA_AVANZADA")

        with patch("foros.siped.views._sesion_remota_valida", return_value=True):
            respuesta = cliente.get(reverse("siped:sincronizar"))

        assert respuesta.status_code == HTTPStatus.OK
        contenido = respuesta.content.decode()
        assert "privado-sin-fecha" in contenido
        assert "publico-sin-fecha" in contenido
