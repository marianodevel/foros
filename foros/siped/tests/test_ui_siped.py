"""Pruebas de la interfaz de escritorio de SIPED."""

from __future__ import annotations

from datetime import date
from datetime import datetime
from http import HTTPStatus
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from foros.siped.models import Expediente
from foros.siped.models import Movimiento
from foros.siped.models import NovedadSIPED

pytestmark = pytest.mark.django_db


@pytest.fixture
def cliente(client, db):
    session = client.session
    session["siped_cookies"] = {"PHPSESSID": "cookie"}
    session["siped_username"] = "abogado"
    session.save()
    return client


@pytest.fixture
def expediente():
    return Expediente.objects.create(
        usuario_asignado="abogado",
        numero_expediente="123/2024",
        caratula="PEREZ C GOMEZ",
        fecha_ult_mov=date(2024, 2, 1),
    )


@pytest.fixture
def novedad(expediente):
    return NovedadSIPED.objects.create(
        usuario_asignado="abogado",
        expediente=expediente,
        tipo=NovedadSIPED.Tipo.MOVIMIENTOS_NUEVOS,
        procesada=True,
        cantidad_movimientos=1,
    )


@pytest.fixture
def movimiento(novedad):
    return Movimiento.objects.create(
        expediente=novedad.expediente,
        novedad=novedad,
        codigo_escrito="PE1234567-2024",
        descripcion="TEXTO NUEVO DEL MOVIMIENTO",
        fecha_presentacion=datetime(
            2024, 2, 2, 10, 0, tzinfo=timezone.get_current_timezone(),
        ),
        tipo="ESCRITO",
        estado="PUBLICADO",
        generado_por="ABOGADO",
    )


class TestNavegacion:
    def test_indice_muestra_las_tres_pestanas(self, cliente) -> None:
        with patch("foros.siped.views._sesion_remota_valida", return_value=True):
            respuesta = cliente.get(reverse("siped:indice"))

        contenido = respuesta.content.decode()
        assert reverse("siped:indice") in contenido
        assert reverse("siped:dashboard") in contenido
        assert reverse("siped:sincronizar") in contenido
        assert "Novedades" in contenido
        assert "Expedientes" in contenido
        assert "Sincronización" in contenido

    def test_sincronizar_renderiza_las_herramientas(self, cliente) -> None:
        with patch("foros.siped.views._sesion_remota_valida", return_value=True):
            respuesta = cliente.get(reverse("siped:sincronizar"))

        assert respuesta.status_code == HTTPStatus.OK
        assert "Sincronización de Expedientes" in respuesta.content.decode()
        assert respuesta.context["tab_activa"] == "sincronizacion"

    def test_dashboard_es_la_pestana_de_expedientes(self, cliente) -> None:
        respuesta = cliente.get(reverse("siped:dashboard"))

        assert respuesta.status_code == HTTPStatus.OK
        assert respuesta.context["tab_activa"] == "expedientes"


class TestDetalleNovedad:
    def test_indice_expande_el_movimiento_en_linea(
        self, cliente, novedad, movimiento,
    ) -> None:
        with patch("foros.siped.views._sesion_remota_valida", return_value=True):
            respuesta = cliente.get(reverse("siped:indice"))

        contenido = respuesta.content.decode()
        assert f'data-bs-target="#detalle-novedad-{novedad.pk}"' in contenido
        assert movimiento.descripcion in contenido
        assert 'class="ms-2 fw-semibold text-decoration-none"' not in contenido

    def test_indice_incluye_el_auto_refresco(self, cliente, novedad) -> None:
        with patch("foros.siped.views._sesion_remota_valida", return_value=True):
            respuesta = cliente.get(reverse("siped:indice"))

        assert reverse("siped:fragmento_novedades") in respuesta.content.decode()
        assert "novedades_token" in respuesta.context


class TestAutoRefrescoNovedades:
    def test_sin_cambios_no_recarga(self, cliente, novedad) -> None:
        with patch("foros.siped.views._sesion_remota_valida", return_value=True):
            indice = cliente.get(reverse("siped:indice"))

        respuesta = cliente.get(
            reverse("siped:fragmento_novedades"),
            {"token": indice.context["novedades_token"]},
        )

        assert respuesta.status_code == HTTPStatus.NO_CONTENT
        assert "HX-Refresh" not in respuesta

    def test_con_cambios_recarga(self, cliente, novedad) -> None:
        respuesta = cliente.get(
            reverse("siped:fragmento_novedades"),
            {"token": "token-viejo"},
        )

        assert respuesta.status_code == HTTPStatus.NO_CONTENT
        assert respuesta["HX-Refresh"] == "true"


class TestOrdenExpedientes:
    def test_dashboard_ordena_por_fecha_ult_mov(self, cliente) -> None:
        Expediente.objects.create(
            usuario_asignado="abogado",
            numero_expediente="viejo",
            caratula="VIEJO",
            fecha_ult_mov=date(2024, 1, 1),
        )
        Expediente.objects.create(
            usuario_asignado="abogado",
            numero_expediente="nuevo",
            caratula="NUEVO",
            fecha_ult_mov=date(2024, 3, 1),
        )
        Expediente.objects.create(
            usuario_asignado="abogado",
            numero_expediente="sin-fecha",
            caratula="SIN FECHA",
            fecha_ult_mov=None,
        )

        respuesta = cliente.get(reverse("siped:dashboard"))
        numeros = [exp.numero_expediente for exp in respuesta.context["expedientes"]]

        assert numeros == ["nuevo", "viejo", "sin-fecha"]

    def test_dashboard_abre_el_expediente_indicado(
        self, cliente, expediente,
    ) -> None:
        respuesta = cliente.get(
            reverse("siped:dashboard"),
            {"expediente": expediente.pk},
        )

        assert respuesta.context["expediente_abierto"] == expediente.pk
