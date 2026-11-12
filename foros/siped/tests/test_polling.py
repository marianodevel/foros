"""Pruebas del polling automático de cambios en la lista maestra."""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from unittest.mock import Mock
from unittest.mock import patch

import pytest
import requests
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from foros.siped import scraper_tasks
from foros.siped.cripto import ErrorCifrado
from foros.siped.cripto import cifrar_cookies
from foros.siped.cripto import descifrar_cookies
from foros.siped.exceptions import SesionSIPEDExpirada
from foros.siped.exceptions import SolicitudIncompleta
from foros.siped.fases.polling_cambios import ejecutar_polling_usuario
from foros.siped.fases.polling_cambios import encolar_polling_cambios
from foros.siped.models import Expediente
from foros.siped.models import Movimiento
from foros.siped.models import NovedadSIPED
from foros.siped.models import SesionSIPED

pytestmark = pytest.mark.django_db

URL_AJAX = "https://intranet.jussantacruz.gob.ar/siped/expediente/buscar/ver_mas_escritosAjax.php"


def _respuesta(
    html: str,
    url: str = URL_AJAX,
    content_type: str = "text/html; charset=UTF-8",
) -> Mock:
    respuesta = Mock()
    respuesta.text = html
    respuesta.content = html.encode()
    respuesta.url = url
    respuesta.status_code = 200
    respuesta.headers = {"Content-Type": content_type}
    respuesta.history = []
    respuesta.raise_for_status = Mock()
    return respuesta


def _expediente_data(
    numero: str = "123/2024",
    fec_ult_mov: str = "01/02/2024",
    estado: str = "En letra",
) -> dict:
    return {
        "expediente": numero,
        "caratula": "PEREZ C GOMEZ",
        "partes": "2",
        "estado": estado,
        "fec_ult_mov": fec_ult_mov,
        "localidad": "Rio Gallegos",
        "dependencia": "Juzgado 1",
        "secretaria": "Secretaria 1",
        "link_detalle": f"https://intranet/detalle.php?exp={numero}",
    }


@pytest.fixture
def sesion_siped():
    return SesionSIPED.objects.create(
        username_intranet="abogado",
        cookies_cifradas=cifrar_cookies({"PHPSESSID": "cookie-vieja"}),
    )


class TestCifrado:
    def test_roundtrip(self) -> None:
        cookies = {"PHPSESSID": "abc123", "otra": "valor"}
        assert descifrar_cookies(cifrar_cookies(cookies)) == cookies

    def test_token_invalido_lanza(self) -> None:
        with pytest.raises(ErrorCifrado):
            descifrar_cookies("esto-no-es-un-token")

    def test_token_vacio_lanza(self) -> None:
        with pytest.raises(ErrorCifrado):
            descifrar_cookies("")


class TestDeteccionDeCambios:
    def test_expediente_nuevo_crea_novedad_y_procesa(self, sesion_siped) -> None:
        with (
            patch(
                "foros.siped.fases.polling_cambios.scraper_tasks."
                "raspar_lista_expedientes",
                return_value=[_expediente_data()],
            ),
            patch(
                "foros.siped.fases.polling_cambios.scraper_tasks."
                "raspar_movimientos_de_expediente",
                return_value=[],
            ) as movimientos,
            patch("foros.siped.fases.polling_cambios.time.sleep"),
        ):
            resultado = ejecutar_polling_usuario("abogado")

        expediente = Expediente.objects.get(
            usuario_asignado="abogado", numero_expediente="123/2024",
        )
        novedad = NovedadSIPED.objects.get(expediente=expediente)
        assert "1 expedientes nuevos" in resultado
        assert novedad.tipo == NovedadSIPED.Tipo.EXPEDIENTE_NUEVO
        assert novedad.procesada is True
        assert novedad.cantidad_movimientos == 0
        movimientos.assert_called_once()

    def test_cambio_de_ultimo_movimiento_genera_novedad(self, sesion_siped) -> None:
        expediente = Expediente.objects.create(
            usuario_asignado="abogado",
            numero_expediente="123/2024",
            caratula="PEREZ C GOMEZ",
            fecha_ult_mov=date(2024, 2, 1),
            estado="En letra",
            link_detalle="https://intranet/detalle.php?exp=123",
        )
        movimiento = {
            "codigo_escrito": "PE1234567-2024",
            "tasa": "",
            "fecha_presentacion": "02/02/2024 10:00:00",
            "tipo": "ESCRITO",
            "estado": "PUBLICADO",
            "generado_por": "ABOGADO",
            "descripcion": "Escrito nuevo",
            "fecha_firma": "",
            "fecha_publicacion": "02/02/2024 10:05",
            "link_escrito": "https://intranet/ver_escrito.php?id=99",
        }

        with (
            patch(
                "foros.siped.fases.polling_cambios.scraper_tasks."
                "raspar_lista_expedientes",
                return_value=[_expediente_data(fec_ult_mov="02/02/2024")],
            ),
            patch(
                "foros.siped.fases.polling_cambios.scraper_tasks."
                "raspar_movimientos_de_expediente",
                return_value=[movimiento],
            ),
            patch("foros.siped.fases.polling_cambios.time.sleep"),
        ):
            ejecutar_polling_usuario("abogado")

        expediente.refresh_from_db()
        novedad = NovedadSIPED.objects.get(expediente=expediente)
        assert expediente.fecha_ult_mov == date(2024, 2, 2)
        assert novedad.tipo == NovedadSIPED.Tipo.MOVIMIENTOS_NUEVOS
        assert novedad.procesada is True
        assert novedad.cantidad_movimientos == 1
        assert Movimiento.objects.filter(expediente=expediente).count() == 1

    def test_novedad_vincula_los_movimientos_nuevos(self, sesion_siped) -> None:
        expediente = Expediente.objects.create(
            usuario_asignado="abogado",
            numero_expediente="123/2024",
            caratula="PEREZ C GOMEZ",
            fecha_ult_mov=date(2024, 2, 1),
            estado="En letra",
            link_detalle="https://intranet/detalle.php?exp=123",
        )
        movimiento = {
            "codigo_escrito": "PE1234567-2024",
            "tasa": "",
            "fecha_presentacion": "02/02/2024 10:00:00",
            "tipo": "ESCRITO",
            "estado": "PUBLICADO",
            "generado_por": "ABOGADO",
            "descripcion": "Texto completo del escrito",
            "fecha_firma": "",
            "fecha_publicacion": "",
            "link_escrito": "https://intranet/ver_escrito.php?id=100",
        }

        with (
            patch(
                "foros.siped.fases.polling_cambios.scraper_tasks."
                "raspar_lista_expedientes",
                return_value=[_expediente_data(fec_ult_mov="02/02/2024")],
            ),
            patch(
                "foros.siped.fases.polling_cambios.scraper_tasks."
                "raspar_movimientos_de_expediente",
                return_value=[movimiento],
            ),
            patch("foros.siped.fases.polling_cambios.time.sleep"),
        ):
            ejecutar_polling_usuario("abogado")

        novedad = NovedadSIPED.objects.get(expediente=expediente)
        assert list(
            novedad.movimientos.values_list("descripcion", flat=True),
        ) == ["Texto completo del escrito"]

    def test_cambio_de_estado_tambien_refresca_movimientos(
        self, sesion_siped,
    ) -> None:
        Expediente.objects.create(
            usuario_asignado="abogado",
            numero_expediente="123/2024",
            caratula="PEREZ C GOMEZ",
            fecha_ult_mov=date(2024, 2, 1),
            estado="En letra",
            link_detalle="https://intranet/detalle.php?exp=123",
        )

        with (
            patch(
                "foros.siped.fases.polling_cambios.scraper_tasks."
                "raspar_lista_expedientes",
                return_value=[_expediente_data(estado="Archivado")],
            ),
            patch(
                "foros.siped.fases.polling_cambios.scraper_tasks."
                "raspar_movimientos_de_expediente",
                return_value=[],
            ),
            patch("foros.siped.fases.polling_cambios.time.sleep"),
        ):
            ejecutar_polling_usuario("abogado")

        assert NovedadSIPED.objects.filter(
            tipo=NovedadSIPED.Tipo.MOVIMIENTOS_NUEVOS,
        ).exists()

    def test_sin_cambios_no_pide_movimientos(self, sesion_siped) -> None:
        Expediente.objects.create(
            usuario_asignado="abogado",
            numero_expediente="123/2024",
            caratula="PEREZ C GOMEZ",
            fecha_ult_mov=date(2024, 2, 1),
            estado="En letra",
            link_detalle="https://intranet/detalle.php?exp=123",
        )

        with (
            patch(
                "foros.siped.fases.polling_cambios.scraper_tasks."
                "raspar_lista_expedientes",
                return_value=[_expediente_data()],
            ),
            patch(
                "foros.siped.fases.polling_cambios.scraper_tasks."
                "raspar_movimientos_de_expediente",
            ) as movimientos,
        ):
            ejecutar_polling_usuario("abogado")

        movimientos.assert_not_called()
        assert NovedadSIPED.objects.count() == 0
        assert Expediente.objects.count() == 1

    def test_cambio_descriptivo_no_genera_novedad(self, sesion_siped) -> None:
        Expediente.objects.create(
            usuario_asignado="abogado",
            numero_expediente="123/2024",
            caratula="CARATULA VIEJA",
            fecha_ult_mov=date(2024, 2, 1),
            estado="En letra",
            link_detalle="https://intranet/detalle.php?exp=123",
        )

        with patch(
            "foros.siped.fases.polling_cambios.scraper_tasks."
            "raspar_lista_expedientes",
            return_value=[_expediente_data()],
        ):
            ejecutar_polling_usuario("abogado")

        expediente = Expediente.objects.get(numero_expediente="123/2024")
        assert expediente.caratula == "PEREZ C GOMEZ"
        assert NovedadSIPED.objects.count() == 0

    def test_no_duplica_novedad_pendiente(self, sesion_siped) -> None:
        expediente = Expediente.objects.create(
            usuario_asignado="abogado",
            numero_expediente="123/2024",
            caratula="PEREZ C GOMEZ",
            fecha_ult_mov=date(2024, 2, 1),
            estado="En letra",
            link_detalle="https://intranet/detalle.php?exp=123",
        )
        NovedadSIPED.objects.create(
            usuario_asignado="abogado",
            expediente=expediente,
            tipo=NovedadSIPED.Tipo.MOVIMIENTOS_NUEVOS,
            procesada=False,
        )

        with (
            patch(
                "foros.siped.fases.polling_cambios.scraper_tasks."
                "raspar_lista_expedientes",
                return_value=[_expediente_data(fec_ult_mov="02/02/2024")],
            ),
            patch(
                "foros.siped.fases.polling_cambios.scraper_tasks."
                "raspar_movimientos_de_expediente",
                return_value=[],
            ),
            patch("foros.siped.fases.polling_cambios.time.sleep"),
        ):
            ejecutar_polling_usuario("abogado")

        assert NovedadSIPED.objects.count() == 1


class TestErroresYBloqueo:
    def test_lista_incompleta_no_aplica_cambios(self, sesion_siped) -> None:
        with patch(
            "foros.siped.fases.polling_cambios.scraper_tasks."
            "raspar_lista_expedientes",
            side_effect=SolicitudIncompleta("se cortó la conexión"),
        ):
            resultado = ejecutar_polling_usuario("abogado")

        sesion_siped.refresh_from_db()
        assert "Polling incompleto" in resultado
        assert Expediente.objects.count() == 0
        assert sesion_siped.fallos_consecutivos == 1
        assert sesion_siped.proximo_intento is not None
        assert sesion_siped.estado == SesionSIPED.Estado.ACTIVA

    def test_sesion_expirada_se_marca_y_no_reintenta(self, sesion_siped) -> None:
        with patch(
            "foros.siped.fases.polling_cambios.scraper_tasks."
            "raspar_lista_expedientes",
            side_effect=SesionSIPEDExpirada(),
        ):
            resultado = ejecutar_polling_usuario("abogado")

        sesion_siped.refresh_from_db()
        assert "expiró" in resultado
        assert sesion_siped.estado == SesionSIPED.Estado.EXPIRADA
        assert sesion_siped.cookies_cifradas == ""

    def test_bloqueo_impide_ejecucion_concurrente(self, sesion_siped) -> None:
        SesionSIPED.objects.filter(pk=sesion_siped.pk).update(
            bloqueado_hasta=timezone.now() + timedelta(minutes=10),
        )

        with patch(
            "foros.siped.fases.polling_cambios.scraper_tasks."
            "raspar_lista_expedientes",
        ) as lista:
            resultado = ejecutar_polling_usuario("abogado")

        assert "ya está en curso" in resultado
        lista.assert_not_called()

    def test_exito_resetea_fallos_y_libera_bloqueo(self, sesion_siped) -> None:
        SesionSIPED.objects.filter(pk=sesion_siped.pk).update(
            fallos_consecutivos=3,
            proximo_intento=timezone.now() + timedelta(hours=1),
        )

        with (
            patch(
                "foros.siped.fases.polling_cambios.scraper_tasks."
                "raspar_lista_expedientes",
                return_value=[],
            ),
            patch("foros.siped.fases.polling_cambios.time.sleep"),
        ):
            ejecutar_polling_usuario("abogado")

        sesion_siped.refresh_from_db()
        assert sesion_siped.fallos_consecutivos == 0
        assert sesion_siped.proximo_intento is None
        assert sesion_siped.ultimo_polling is not None
        assert sesion_siped.bloqueado_hasta is None


class TestEncolado:
    def test_encola_solo_sesiones_activas(self, sesion_siped) -> None:
        SesionSIPED.objects.create(
            username_intranet="expirado",
            cookies_cifradas="",
            estado=SesionSIPED.Estado.EXPIRADA,
        )
        SesionSIPED.objects.create(
            username_intranet="con_backoff",
            cookies_cifradas=cifrar_cookies({"PHPSESSID": "x"}),
            proximo_intento=timezone.now() + timedelta(hours=1),
        )

        with (
            patch(
                "foros.siped.fases.polling_cambios.current_app.send_task",
            ) as send_task,
            patch(
                "foros.siped.fases.polling_cambios.random.randint",
                return_value=42,
            ),
        ):
            enviadas = encolar_polling_cambios()

        assert enviadas == 1
        send_task.assert_called_once_with(
            "siped.polling_cambios_usuario",
            args=["abogado"],
            countdown=42,
            expires=30 * 60,
        )

    def test_beat_tiene_la_tarea_programada(self) -> None:
        entrada = settings.CELERY_BEAT_SCHEDULE["siped-polling-cambios"]
        assert entrada["task"] == "siped.encolar_polling_cambios"
        assert entrada["schedule"].minute == {0, 30}


class TestScrapers:
    def test_lista_incompleta_lanza_solicitud_incompleta(self) -> None:
        session = Mock(spec=requests.Session)
        session.get.side_effect = requests.ConnectionError("sin red")

        with pytest.raises(SolicitudIncompleta):
            scraper_tasks.raspar_lista_expedientes(session)

    def test_movimientos_no_se_detienen_por_historial_de_otro_usuario(
        self, sesion_siped,
    ) -> None:
        otro = Expediente.objects.create(
            usuario_asignado="otro",
            numero_expediente="123/2024",
            caratula="MISMO EXPEDIENTE",
        )
        Movimiento.objects.create(
            expediente=otro,
            link_escrito="https://intranet/ver_escrito.php?id=1",
            codigo_escrito="PE1234567-2024",
        )
        propio = Expediente.objects.create(
            usuario_asignado="abogado",
            numero_expediente="123/2024",
            caratula="MISMO EXPEDIENTE",
        )

        detalle = _respuesta(
            '<html><body><input name="id" value="123"></body></html>',
            url="https://intranet/detalle.php?exp=123",
        )
        pagina = _respuesta(
            """
            <html><body>
            <table class="table-hover">
              <tr><th></th><th>Nombre</th><th>Tasa</th><th>Fecha Presentación</th>
                  <th>Tipo</th><th>Estado</th><th>Generado por</th>
                  <th>Descripción/detalle</th><th>Fecha Firma</th>
                  <th>Fecha Publicación</th></tr>
              <tr>
                <td></td>
                <td>PE1234567-2024</td>
                <td></td>
                <td>02/02/2024 10:00:00</td>
                <td>ESCRITO</td>
                <td>PUBLICADO</td>
                <td>ABOGADO</td>
                <td>Escrito nuevo</td>
                <td></td>
                <td>02/02/2024 10:05</td>
                <td></td>
                <td></td>
                <form action="https://intranet/ver_escrito.php?id=1">
                  <input type="submit" value="PE1234567-2024">
                </form>
              </tr>
            </table>
            </body></html>
            """,
        )
        fin = _respuesta("<html></html>")

        session = Mock(spec=requests.Session)
        session.get.side_effect = [detalle, pagina, fin]

        movimientos = scraper_tasks.raspar_movimientos_de_expediente(
            session,
            {
                "expediente": "123/2024",
                "expediente_id": propio.id,
                "link_detalle": "https://intranet/detalle.php?exp=123",
            },
        )

        assert len(movimientos) == 1
        assert "ver_escrito.php?id=1" in movimientos[0]["link_escrito"]


class TestNovedadesUI:
    @pytest.fixture
    def cliente(self, client, db):
        session = client.session
        session["siped_cookies"] = {"PHPSESSID": "cookie"}
        session["siped_username"] = "abogado"
        session.save()
        return client

    @pytest.fixture
    def novedad(self):
        expediente = Expediente.objects.create(
            usuario_asignado="abogado",
            numero_expediente="123/2024",
            caratula="PEREZ C GOMEZ",
        )
        return NovedadSIPED.objects.create(
            usuario_asignado="abogado",
            expediente=expediente,
            tipo=NovedadSIPED.Tipo.EXPEDIENTE_NUEVO,
            procesada=True,
            cantidad_movimientos=2,
        )

    def test_indice_muestra_las_novedades(self, cliente, novedad) -> None:
        with patch("foros.siped.views._sesion_remota_valida", return_value=True):
            respuesta = cliente.get(reverse("siped:indice"))

        assert respuesta.status_code == 200
        contenido = respuesta.content.decode()
        assert "Novedades del polling automático" in contenido
        assert "123/2024" in contenido
        assert "1 sin ver" in contenido

    def test_marcar_novedades_vistas(self, cliente, novedad) -> None:
        respuesta = cliente.post(reverse("siped:marcar_novedades_vistas"))

        assert respuesta.status_code == 302
        novedad.refresh_from_db()
        assert novedad.vista is True
