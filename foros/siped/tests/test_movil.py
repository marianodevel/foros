"""Pruebas de la PWA móvil y de las notificaciones Web Push."""

from __future__ import annotations

from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.urls import reverse
from pywebpush import WebPushException

from foros.siped import session_manager
from foros.siped.fases.polling_cambios import _encolar_push_resumen
from foros.siped.models import Expediente
from foros.siped.models import NovedadSIPED
from foros.siped.models import SuscripcionPush
from foros.siped.push import enviar_resumen_push

pytestmark = pytest.mark.django_db


@pytest.fixture
def cliente_movil(client):
    session = client.session
    session["siped_cookies"] = {"PHPSESSID": "cookie-vieja"}
    session["siped_username"] = "abogado"
    session.save()
    return client


@pytest.fixture
def sesion_remota_valida():
    with patch("foros.siped.views._sesion_remota_valida", return_value=True):
        yield


@pytest.fixture
def expediente():
    return Expediente.objects.create(
        usuario_asignado="abogado",
        numero_expediente="123/2024",
        caratula="PEREZ C GOMEZ",
        dependencia="Juzgado 1",
        origen="PRIVADO",
    )


@pytest.fixture
def novedad(expediente):
    return NovedadSIPED.objects.create(
        usuario_asignado="abogado",
        expediente=expediente,
        tipo=NovedadSIPED.Tipo.EXPEDIENTE_NUEVO,
        procesada=True,
        cantidad_movimientos=2,
    )


@pytest.fixture
def suscripcion():
    return SuscripcionPush.objects.create(
        usuario="abogado",
        endpoint="https://push.example.com/v1/abc",
        p256dh="clave-p256dh",
        auth="clave-auth",
    )


class TestVistasMoviles:
    def test_sin_sesion_redirige_al_login_movil(self, client) -> None:
        respuesta = client.get(reverse("siped:movel_index"))

        assert respuesta.status_code == 302
        assert respuesta.url == reverse("siped:movel_login")

    def test_sesion_remota_vencida_llega_al_login_movil(
        self, cliente_movil,
    ) -> None:
        with patch("foros.siped.views._sesion_remota_valida", return_value=False):
            respuesta = cliente_movil.get(reverse("siped:movel_index"))

        assert respuesta.status_code == 302
        assert respuesta.url == reverse("siped:movel_login")
        assert "siped_cookies" not in cliente_movil.session

    def test_inicio_muestra_resumen_y_novedades(
        self, cliente_movil, sesion_remota_valida, novedad,
    ) -> None:
        respuesta = cliente_movil.get(reverse("siped:movel_index"))

        assert respuesta.status_code == 200
        contenido = respuesta.content.decode()
        assert "Expedientes" in contenido
        assert "123/2024" in contenido
        assert "csrftoken" in respuesta.cookies

    def test_expedientes_lista_los_del_usuario(
        self, cliente_movil, sesion_remota_valida, expediente,
    ) -> None:
        respuesta = cliente_movil.get(reverse("siped:movel_dashboard"))

        assert respuesta.status_code == 200
        contenido = respuesta.content.decode()
        assert "123/2024" in contenido
        assert "PEREZ C GOMEZ" in contenido

    def test_expedientes_respeta_la_busqueda_inicial(
        self, cliente_movil, sesion_remota_valida, expediente,
    ) -> None:
        respuesta = cliente_movil.get(
            reverse("siped:movel_dashboard"), {"buscar": "123"},
        )

        assert respuesta.status_code == 200
        assert 'value="123"' in respuesta.content.decode()

    def test_novedades_agrupa_por_fecha(
        self, cliente_movil, sesion_remota_valida, novedad,
    ) -> None:
        respuesta = cliente_movil.get(reverse("siped:movel_novedades"))

        assert respuesta.status_code == 200
        assert "Hoy" in respuesta.content.decode()

    def test_novedades_y_marcar_vistas(
        self, cliente_movil, sesion_remota_valida, novedad,
    ) -> None:
        respuesta = cliente_movil.get(reverse("siped:movel_novedades"))
        assert respuesta.status_code == 200
        assert "123/2024" in respuesta.content.decode()

        marcado = cliente_movil.post(
            reverse("siped:movel_marcar_novedades"),
        )

        assert marcado.status_code == 302
        assert marcado.url == reverse("siped:movel_novedades")
        novedad.refresh_from_db()
        assert novedad.vista is True

    def test_sincronizar_muestra_las_fases(
        self, cliente_movil, sesion_remota_valida,
    ) -> None:
        respuesta = cliente_movil.get(reverse("siped:movel_sincronizar"))

        assert respuesta.status_code == 200
        contenido = respuesta.content.decode()
        assert "Expedientes" in contenido
        assert "Movimientos" in contenido
        assert "Documentos" in contenido
        assert 'hx-get="/siped/m/fragmento/estado/fase_1/"' in contenido

    def test_fragmento_fase_renderiza_el_estado(
        self, cliente_movil,
    ) -> None:
        with patch(
            "foros.siped.views.gestor_tareas.obtener_estado_tarea",
            return_value={"estado": "SUCCESS", "resultado": "Completado"},
        ):
            respuesta = cliente_movil.get(
                reverse("siped:movel_fragmento_fase", args=["fase_1"]),
            )

        assert respuesta.status_code == 200
        contenido = respuesta.content.decode()
        assert "Completado" in contenido
        assert "chip-ok" in contenido

    def test_fragmento_fase_recarga_al_terminar(
        self, cliente_movil,
    ) -> None:
        with patch(
            "foros.siped.views.gestor_tareas.obtener_estado_tarea",
            return_value={
                "estado": "SUCCESS",
                "resultado": "Completado",
                "recargar": True,
            },
        ):
            respuesta = cliente_movil.get(
                reverse("siped:movel_fragmento_fase", args=["fase_1"]),
            )

        assert respuesta["HX-Refresh"] == "true"

    def test_fragmento_fase_desconocida_da_404(
        self, cliente_movil,
    ) -> None:
        respuesta = cliente_movil.get(
            reverse("siped:movel_fragmento_fase", args=["fase_x"]),
        )

        assert respuesta.status_code == 404

    def test_perfil_muestra_el_estado_de_push(
        self, cliente_movil, sesion_remota_valida, suscripcion,
    ) -> None:
        respuesta = cliente_movil.get(reverse("siped:movel_perfil"))

        assert respuesta.status_code == 200
        contenido = respuesta.content.decode()
        assert 'id="push-config"' in contenido
        assert 'id="push-toggle"' in contenido
        assert 'data-suscripciones="1"' in contenido

    def test_login_movil_renderiza_y_redirige(
        self, client,
    ) -> None:
        formulario = client.get(reverse("siped:movel_login"))
        assert formulario.status_code == 200
        assert "Acceso SIPED" in formulario.content.decode()

        with patch.object(
            session_manager,
            "autenticar_en_siped",
            return_value={"PHPSESSID": "cookie-nueva"},
        ):
            respuesta = client.post(
                reverse("siped:movel_login"),
                {"username": "abogado", "password": "secreta"},
            )

        assert respuesta.status_code == 302
        assert respuesta.url == reverse("siped:movel_index")


class TestPushEndpoints:
    def test_suscribir_guarda_el_dispositivo(
        self, cliente_movil,
    ) -> None:
        respuesta = cliente_movil.post(
            reverse("siped:movel_push_suscribir"),
            data={
                "endpoint": "https://push.example.com/v1/nuevo",
                "keys": {"p256dh": "p256", "auth": "auth"},
            },
            content_type="application/json",
        )

        assert respuesta.status_code == 200
        suscripcion = SuscripcionPush.objects.get(
            endpoint="https://push.example.com/v1/nuevo",
        )
        assert suscripcion.usuario == "abogado"
        assert suscripcion.activa is True

    def test_suscribir_rechaza_endpoint_inseguro(self, cliente_movil) -> None:
        respuesta = cliente_movil.post(
            reverse("siped:movel_push_suscribir"),
            data={
                "endpoint": "http://push.example.com/v1/nuevo",
                "keys": {"p256dh": "p256", "auth": "auth"},
            },
            content_type="application/json",
        )

        assert respuesta.status_code == 400
        assert not SuscripcionPush.objects.exists()

    def test_desuscribir_elimina_el_dispositivo(
        self, cliente_movil, suscripcion,
    ) -> None:
        respuesta = cliente_movil.post(
            reverse("siped:movel_push_desuscribir"),
            data={"endpoint": suscripcion.endpoint},
            content_type="application/json",
        )

        assert respuesta.status_code == 200
        assert not SuscripcionPush.objects.exists()

    @override_settings(
        VAPID_PRIVATE_KEY="clave-privada",
        VAPID_PUBLIC_KEY="clave-publica",
        VAPID_SUBJECT="mailto:test@example.com",
    )
    def test_push_de_prueba_envia_y_registra(
        self, cliente_movil, suscripcion,
    ) -> None:
        with patch("foros.siped.push.webpush") as enviar:
            respuesta = cliente_movil.post(reverse("siped:movel_push_test"))

        assert respuesta.status_code == 200
        assert respuesta.json()["enviados"] == 1
        enviar.assert_called_once()
        suscripcion.refresh_from_db()
        assert suscripcion.ultimo_envio is not None


class TestEnvioPush:
    @override_settings(
        VAPID_PRIVATE_KEY="clave-privada",
        VAPID_PUBLIC_KEY="clave-publica",
        VAPID_SUBJECT="mailto:test@example.com",
    )
    def test_elimina_suscripcion_vencida(self, suscripcion) -> None:
        respuesta = Mock(status_code=410)
        with patch(
            "foros.siped.push.webpush",
            side_effect=WebPushException("vencida", response=respuesta),
        ):
            resultado = enviar_resumen_push("abogado", 1, 3)

        assert resultado["enviados"] == 0
        assert not SuscripcionPush.objects.exists()

    def test_encola_resumen_solo_si_hay_dispositivos(
        self, suscripcion,
    ) -> None:
        with patch(
            "foros.siped.fases.polling_cambios.current_app.send_task",
        ) as enviar:
            _encolar_push_resumen("abogado", 1, 2)

        enviar.assert_called_once_with(
            "siped.enviar_push_resumen",
            args=["abogado", 1, 2],
        )

    def test_no_encola_si_no_hay_novedades(self, suscripcion) -> None:
        with patch(
            "foros.siped.fases.polling_cambios.current_app.send_task",
        ) as enviar:
            _encolar_push_resumen("abogado", 0, 0)

        enviar.assert_not_called()


class TestArchivosPwa:
    def test_manifest_con_mime_correcto(self, client) -> None:
        respuesta = client.get(reverse("siped:movel_manifest"))

        assert respuesta.status_code == 200
        assert respuesta["Content-Type"] == "application/manifest+json"

    def test_service_worker_controla_todo_siped(self, client) -> None:
        respuesta = client.get(reverse("siped:movel_service_worker"))

        assert respuesta.status_code == 200
        assert respuesta["Service-Worker-Allowed"] == "/siped/"
        assert "javascript" in respuesta["Content-Type"]
