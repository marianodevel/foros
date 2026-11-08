"""Pruebas de la detección de sesión vencida y del flujo de reautenticación."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests
from django.urls import reverse

from foros.siped import gestor_tareas, scraper_tasks, session_manager
from foros.siped.exceptions import PaginaInesperada, SesionSIPEDExpirada
from foros.siped.fases.sincronizacion_movimientos import (
    ejecutar_sincronizacion_movimientos,
)
from foros.siped.models import Expediente
from foros.siped.parsers import parsear_lista_expedientes, parsear_lista_publica
from foros.siped.utils import manejar_fase_con_sesion

LOGIN_HTML = """
<html><body>
  <form action="/servicios/controli2.php" method="post">
    <input name="usuario" type="text">
    <input name="pass" type="password">
    <button type="submit">Ingresar</button>
  </form>
</body></html>
"""

LISTA_HTML = """
<html><body>
  <table class="table-striped">
    <tr><th>Expediente</th><th>Caratula</th><th>Partes</th><th>Estado</th>
        <th>Ult. mov.</th><th>Localidad</th><th>Dependencia</th><th>Secretaria</th></tr>
    <tr>
      <td><a href="ver_detalle.php?id=1">123/2024</a></td>
      <td>PEREZ C GOMEZ</td><td>2</td><td>En letra</td>
      <td>01/02/2024</td><td>Rio Gallegos</td>
      <td>Juzgado 1</td><td>Secretaria 1</td>
    </tr>
  </table>
</body></html>
"""

LISTA_VACIA_HTML = """
<html><body>
  <table class="table-striped">
    <tr><th>Expediente</th><th>Caratula</th></tr>
  </table>
</body></html>
"""


def _respuesta(
    html: str = "",
    url: str = "https://intranet.jussantacruz.gob.ar/siped/expediente/buscar/submit_buscar_abogado.php",
    content_type: str = "text/html; charset=UTF-8",
) -> Mock:
    respuesta = Mock()
    respuesta.text = html
    respuesta.url = url
    respuesta.status_code = 200
    respuesta.headers = {"Content-Type": content_type}
    respuesta.content = html.encode()
    respuesta.history = []
    respuesta.raise_for_status = Mock()
    return respuesta


def _sesion_falsa(respuesta: Mock | None = None, error: Exception | None = None) -> Mock:
    session = Mock(spec=requests.Session)
    if error is not None:
        session.get.side_effect = error
    else:
        session.get.return_value = respuesta
    return session


class TestDeteccionLogin:
    def test_excepcion_es_idempotente_al_deserializar(self) -> None:
        original = SesionSIPEDExpirada("La cookie venció.")
        reconstruida = SesionSIPEDExpirada(str(original))

        assert str(reconstruida).count(SesionSIPEDExpirada.PREFIJO) == 1
        assert SesionSIPEDExpirada.es_resultado(reconstruida)
        assert SesionSIPEDExpirada.limpiar_mensaje(reconstruida) == "La cookie venció."

    def test_detecta_login_por_formulario(self) -> None:
        assert session_manager.es_pagina_login(_respuesta(LOGIN_HTML))

    def test_detecta_login_por_url_final(self) -> None:
        respuesta = _respuesta(
            "<html><body>redirigiendo...</body></html>",
            url="https://intranet.jussantacruz.gob.ar/servicios/controli2.php",
        )
        assert session_manager.es_pagina_login(respuesta)

    def test_pagina_de_expedientes_no_es_login(self) -> None:
        assert not session_manager.es_pagina_login(_respuesta(LISTA_HTML))

    def test_pagina_vacia_no_es_login(self) -> None:
        assert not session_manager.es_pagina_login(_respuesta(""))

    def test_verificar_respuesta_autenticada_lanza(self) -> None:
        with pytest.raises(SesionSIPEDExpirada):
            session_manager.verificar_respuesta_autenticada(_respuesta(LOGIN_HTML))


class TestVerificarSesion:
    def test_false_cuando_la_intranet_devuelve_login(self) -> None:
        session = _sesion_falsa(_respuesta(LOGIN_HTML))
        assert session_manager.verificar_sesion(session) is False

    def test_true_cuando_la_intranet_devuelve_pagina_protegida(self) -> None:
        session = _sesion_falsa(_respuesta(LISTA_HTML))
        assert session_manager.verificar_sesion(session) is True

    def test_true_ante_error_de_red(self) -> None:
        session = _sesion_falsa(error=requests.ConnectionError("sin red"))
        assert session_manager.verificar_sesion(session) is True

    def test_false_ante_401_o_403(self) -> None:
        respuesta = _respuesta("")
        respuesta.status_code = 403
        respuesta.raise_for_status.side_effect = requests.HTTPError(
            response=respuesta
        )
        session = _sesion_falsa(respuesta)
        assert session_manager.verificar_sesion(session) is False


class TestParsersEstrictos:
    def test_lista_privada_sin_tabla_lanza(self) -> None:
        with pytest.raises(PaginaInesperada):
            parsear_lista_expedientes("<html><body>otra cosa</body></html>")

    def test_lista_publica_sin_tabla_lanza(self) -> None:
        with pytest.raises(PaginaInesperada):
            parsear_lista_publica("<html><body>otra cosa</body></html>")

    def test_lista_vacia_es_un_resultado_valido(self) -> None:
        assert parsear_lista_expedientes(LISTA_VACIA_HTML) == []
        assert parsear_lista_publica(LISTA_VACIA_HTML) == []

    def test_pagina_sin_resultados_no_lanza(self) -> None:
        html = "<html><body><p>No se encontraron resultados para la búsqueda.</p></body></html>"
        assert parsear_lista_expedientes(html) == []
        assert parsear_lista_publica(html) == []


class TestScrapersConSesionVencida:
    def test_lista_de_expedientes_lanza_sesion_expirada(self) -> None:
        session = _sesion_falsa(_respuesta(LOGIN_HTML))
        with pytest.raises(SesionSIPEDExpirada):
            scraper_tasks.raspar_lista_expedientes(session)

    def test_detalle_sin_parametros_lanza_pagina_inesperada(self) -> None:
        session = _sesion_falsa(_respuesta("<html><body>sin formulario</body></html>"))
        with pytest.raises(PaginaInesperada):
            scraper_tasks.raspar_movimientos_de_expediente(
                session,
                {"expediente": "123/2024", "link_detalle": "https://intranet/detalle.php"},
            )

    def test_busqueda_avanzada_lanza_sesion_expirada(self) -> None:
        session = _sesion_falsa(_respuesta(LOGIN_HTML))
        with pytest.raises(SesionSIPEDExpirada):
            scraper_tasks.raspar_busqueda_parametrizada(session, {})


class TestDescargaPdf:
    def test_rechaza_el_login_como_si_fuera_pdf(self) -> None:
        session = _sesion_falsa(_respuesta(LOGIN_HTML))
        with pytest.raises(SesionSIPEDExpirada):
            scraper_tasks.descargar_pdf_en_memoria(session, "https://intranet/pdf.php")

    def test_rechaza_html_que_no_es_pdf(self) -> None:
        session = _sesion_falsa(_respuesta("<html><body>error</body></html>"))
        with pytest.raises(PaginaInesperada):
            scraper_tasks.descargar_pdf_en_memoria(session, "https://intranet/pdf.php")

    def test_acepta_un_pdf_real(self) -> None:
        session = _sesion_falsa(
            _respuesta("%PDF-1.4 contenido", content_type="application/pdf")
        )
        assert (
            scraper_tasks.descargar_pdf_en_memoria(session, "https://intranet/pdf.php")
            == b"%PDF-1.4 contenido"
        )


class TestFaseDecorada:
    def test_falla_antes_de_ejecutar_si_la_sesion_expiro(self) -> None:
        @manejar_fase_con_sesion("PRUEBA")
        def fase(session, username):
            return "no debería ejecutarse"

        with (
            patch(
                "foros.siped.session_manager.crear_sesion_con_cookies",
                return_value=Mock(),
            ),
            patch("foros.siped.session_manager.verificar_sesion", return_value=False),
            pytest.raises(SesionSIPEDExpirada),
        ):
            fase(cookies={}, username="abogado")

    def test_ejecuta_cuando_la_sesion_es_valida(self) -> None:
        @manejar_fase_con_sesion("PRUEBA")
        def fase(session, username):
            return "ok"

        with (
            patch(
                "foros.siped.session_manager.crear_sesion_con_cookies",
                return_value=Mock(),
            ),
            patch("foros.siped.session_manager.verificar_sesion", return_value=True),
        ):
            assert fase(cookies={}, username="abogado") == "ok"

    def test_no_envuelve_pagina_inesperada_en_error_generico(self) -> None:
        @manejar_fase_con_sesion("PRUEBA")
        def fase(session, username):
            raise PaginaInesperada("estructura distinta")

        with (
            patch(
                "foros.siped.session_manager.crear_sesion_con_cookies",
                return_value=Mock(),
            ),
            patch("foros.siped.session_manager.verificar_sesion", return_value=True),
            pytest.raises(PaginaInesperada),
        ):
            fase(cookies={}, username="abogado")

    @pytest.mark.django_db
    def test_movimientos_no_oculta_la_sesion_expirada_entre_expedientes(self) -> None:
        Expediente.objects.create(
            usuario_asignado="abogado",
            numero_expediente="1/2024",
            caratula="PRUEBA",
            origen="PRIVADO",
        )

        with (
            patch("foros.siped.session_manager.verificar_sesion", return_value=True),
            patch(
                "foros.siped.fases.sincronizacion_movimientos."
                "scraper_tasks.raspar_movimientos_de_expediente",
                side_effect=SesionSIPEDExpirada(),
            ),
            pytest.raises(SesionSIPEDExpirada),
        ):
            ejecutar_sincronizacion_movimientos(cookies={}, username="abogado")


class TestGestorTareas:
    def test_marca_sesion_expirada_en_el_resultado(self) -> None:
        tarea = Mock(
            state="FAILURE",
            result=SesionSIPEDExpirada("La cookie venció."),
        )

        def _olvidar_resultado():
            # Celery limpia la caché al hacer forget(): el estado debe leerse
            # antes para no perder la detección de la sesión expirada.
            tarea.state = "PENDING"
            tarea.result = None

        tarea.forget.side_effect = _olvidar_resultado

        with (
            patch("foros.siped.gestor_tareas.AsyncResult", return_value=tarea),
            patch("foros.siped.gestor_tareas.resetear_id_tarea") as resetear,
        ):
            estado = gestor_tareas.obtener_estado_tarea("id", "abogado", "fase_1")

        assert estado["sesion_expirada"] is True
        assert estado["resultado"] == "La cookie venció."
        assert estado["estado"] == "FAILURE"
        assert estado["recargar"] is True
        resetear.assert_called_once_with("abogado", "fase_1")

    def test_resultado_normal_no_marca_expiracion(self) -> None:
        tarea = Mock(state="SUCCESS", result="Todo bien")
        with (
            patch("foros.siped.gestor_tareas.AsyncResult", return_value=tarea),
            patch("foros.siped.gestor_tareas.resetear_id_tarea"),
        ):
            estado = gestor_tareas.obtener_estado_tarea("id", "abogado", "fase_1")

        assert "sesion_expirada" not in estado
        assert estado["resultado"] == "Todo bien"


@pytest.fixture
def cliente_con_sesion_siped(client, db):
    session = client.session
    session["siped_cookies"] = {"PHPSESSID": "cookie-vieja"}
    session["siped_username"] = "abogado"
    session.save()
    return client


class TestVistas:
    @pytest.mark.django_db
    def test_indice_redirige_y_limpia_si_la_sesion_remota_expiro(
        self, cliente_con_sesion_siped
    ) -> None:
        with patch("foros.siped.views._sesion_remota_valida", return_value=False):
            respuesta = cliente_con_sesion_siped.get(reverse("siped:indice"))

        assert respuesta.status_code == 302
        assert respuesta.url == reverse("siped:login")
        assert "siped_cookies" not in cliente_con_sesion_siped.session
        assert "siped_username" not in cliente_con_sesion_siped.session

    def test_login_con_cookie_vencida_muestra_el_formulario(
        self, cliente_con_sesion_siped
    ) -> None:
        with patch("foros.siped.views._sesion_remota_valida", return_value=False):
            respuesta = cliente_con_sesion_siped.get(reverse("siped:login"))

        assert respuesta.status_code == 200
        assert "siped_cookies" not in cliente_con_sesion_siped.session

    def test_login_con_renovar_permite_reautenticarse(
        self, cliente_con_sesion_siped
    ) -> None:
        respuesta = cliente_con_sesion_siped.get(
            reverse("siped:login"), {"renovar": "1"}
        )

        assert respuesta.status_code == 200
        assert "siped_cookies" not in cliente_con_sesion_siped.session

    def test_login_exitoso_guarda_cookies_y_usuario(
        self, cliente_con_sesion_siped
    ) -> None:
        cliente_con_sesion_siped.get(reverse("siped:login"), {"renovar": "1"})

        with patch(
            "foros.siped.views.session_manager.autenticar_en_siped",
            return_value={"PHPSESSID": "cookie-nueva"},
        ):
            respuesta = cliente_con_sesion_siped.post(
                reverse("siped:login"),
                {"username": "abogado", "password": "secreta"},
            )

        assert respuesta.status_code == 302
        assert respuesta.url == reverse("siped:indice")
        assert cliente_con_sesion_siped.session["siped_cookies"] == {
            "PHPSESSID": "cookie-nueva"
        }
        assert cliente_con_sesion_siped.session["siped_username"] == "abogado"

    def test_fragmento_estado_redirige_si_la_tarea_detecto_expiracion(
        self, cliente_con_sesion_siped
    ) -> None:
        estado_expirado = {
            "estado": "FAILURE",
            "resultado": SesionSIPEDExpirada.MENSAJE_POR_DEFECTO,
            "recargar": True,
            "sesion_expirada": True,
        }
        with (
            patch(
                "foros.siped.views.gestor_tareas.obtener_id_tarea",
                return_value="id",
            ),
            patch(
                "foros.siped.views.gestor_tareas.obtener_estado_tarea",
                return_value=estado_expirado,
            ),
        ):
            respuesta = cliente_con_sesion_siped.get(
                reverse("siped:fragmento_estado", args=["fase_1"])
            )

        assert respuesta.status_code == 200
        assert respuesta["HX-Redirect"] == reverse("siped:login")
        assert "siped_cookies" not in cliente_con_sesion_siped.session

    def test_iniciar_fase_no_encola_si_la_sesion_expiro(
        self, cliente_con_sesion_siped
    ) -> None:
        with (
            patch("foros.siped.views._sesion_remota_valida", return_value=False),
            patch("foros.siped.views.sincronizar_expedientes_task") as tarea,
        ):
            respuesta = cliente_con_sesion_siped.post(
                reverse("siped:iniciar_fase", args=["fase_1"])
            )

        assert respuesta.status_code == 200
        assert respuesta["HX-Redirect"] == reverse("siped:login")
        tarea.delay.assert_not_called()
        assert "siped_cookies" not in cliente_con_sesion_siped.session

    def test_logout_requiere_post(self, cliente_con_sesion_siped) -> None:
        respuesta_get = cliente_con_sesion_siped.get(reverse("siped:logout"))
        assert respuesta_get.status_code == 405

        respuesta_post = cliente_con_sesion_siped.post(reverse("siped:logout"))
        assert respuesta_post.status_code == 302
        assert "siped_cookies" not in cliente_con_sesion_siped.session
