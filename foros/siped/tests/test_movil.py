"""Pruebas de la PWA móvil y de las notificaciones Web Push."""

from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from pywebpush import WebPushException

from foros.siped import session_manager
from foros.siped.fases.polling_cambios import _encolar_push_resumen
from foros.siped.models import Expediente
from foros.siped.models import Movimiento
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

    def test_expedientes_enlaza_la_tarjeta_al_detalle(
        self, cliente_movil, sesion_remota_valida, expediente,
    ) -> None:
        respuesta = cliente_movil.get(reverse("siped:movel_dashboard"))

        assert respuesta.status_code == HTTPStatus.OK
        assert reverse(
            "siped:movel_expediente", args=[expediente.pk],
        ) in respuesta.content.decode()

    def test_expediente_detalle_muestra_el_texto_del_movimiento(
        self, cliente_movil, sesion_remota_valida, expediente,
    ) -> None:
        Movimiento.objects.create(
            expediente=expediente,
            tipo="PROVIDENCIA",
            estado="PUBLICADO",
            generado_por="SECRETARIA",
            descripcion="TEXTO COMPLETO DEL MOVIMIENTO",
            fecha_presentacion=timezone.now(),
        )

        respuesta = cliente_movil.get(
            reverse("siped:movel_expediente", args=[expediente.pk]),
        )

        assert respuesta.status_code == HTTPStatus.OK
        contenido = respuesta.content.decode()
        assert "123/2024" in contenido
        assert "PEREZ C GOMEZ" in contenido
        assert "TEXTO COMPLETO DEL MOVIMIENTO" in contenido

    def test_expediente_de_otro_usuario_da_404(
        self, cliente_movil, sesion_remota_valida,
    ) -> None:
        ajeno = Expediente.objects.create(
            usuario_asignado="otro",
            numero_expediente="999/2024",
            origen="PRIVADO",
        )

        respuesta = cliente_movil.get(
            reverse("siped:movel_expediente", args=[ajeno.pk]),
        )

        assert respuesta.status_code == HTTPStatus.NOT_FOUND

    def test_expediente_publico_da_404(
        self, cliente_movil, sesion_remota_valida,
    ) -> None:
        publico = Expediente.objects.create(
            usuario_asignado="abogado",
            numero_expediente="888/2024",
            caratula="EXPEDIENTE PUBLICO",
            origen="PUBLICO",
        )

        respuesta = cliente_movil.get(
            reverse("siped:movel_expediente", args=[publico.pk]),
        )

        assert respuesta.status_code == HTTPStatus.NOT_FOUND

    def test_detalle_marca_expedientes_como_pestana_activa(
        self, cliente_movil, sesion_remota_valida, expediente,
    ) -> None:
        respuesta = cliente_movil.get(
            reverse("siped:movel_expediente", args=[expediente.pk]),
        )

        assert respuesta.status_code == HTTPStatus.OK
        assert 'aria-current="page"' in respuesta.content.decode()

    def test_novedades_muestra_los_movimientos_vinculados(
        self, cliente_movil, sesion_remota_valida, novedad,
    ) -> None:
        novedad.detalle = "Detalle de la novedad"
        novedad.save()
        Movimiento.objects.create(
            expediente=novedad.expediente,
            novedad=novedad,
            tipo="ESCRITO",
            descripcion="MOVIMIENTO VINCULADO A LA NOVEDAD",
            fecha_presentacion=timezone.now(),
        )
        Movimiento.objects.create(
            expediente=novedad.expediente,
            tipo="ESCRITO",
            descripcion="MOVIMIENTO ANTERIOR SIN VINCULO",
            fecha_presentacion=timezone.now() - timedelta(days=10),
        )

        respuesta = cliente_movil.get(reverse("siped:movel_novedades"))

        assert respuesta.status_code == HTTPStatus.OK
        contenido = respuesta.content.decode()
        assert "MOVIMIENTO VINCULADO A LA NOVEDAD" in contenido
        assert "MOVIMIENTO ANTERIOR SIN VINCULO" not in contenido
        assert "Últimos movimientos" not in contenido
        assert "Detalle de la novedad" in contenido

    def test_novedades_sin_vinculo_usa_los_ultimos_movimientos(
        self, cliente_movil, sesion_remota_valida, novedad,
    ) -> None:
        Movimiento.objects.create(
            expediente=novedad.expediente,
            tipo="ESCRITO",
            descripcion="ULTIMO MOVIMIENTO DEL EXPEDIENTE",
            fecha_presentacion=timezone.now(),
        )

        respuesta = cliente_movil.get(reverse("siped:movel_novedades"))

        assert respuesta.status_code == HTTPStatus.OK
        contenido = respuesta.content.decode()
        assert "ULTIMO MOVIMIENTO DEL EXPEDIENTE" in contenido
        assert "Últimos movimientos" in contenido

    def test_fallback_limita_a_tres_y_al_expediente_de_la_novedad(
        self, cliente_movil, sesion_remota_valida, novedad,
    ) -> None:
        ahora = timezone.now()
        for indice in range(4):
            Movimiento.objects.create(
                expediente=novedad.expediente,
                tipo="ESCRITO",
                descripcion=f"MOVIMIENTO PROPIO {indice}",
                fecha_presentacion=ahora - timedelta(days=indice),
            )
        otro = Expediente.objects.create(
            usuario_asignado="abogado",
            numero_expediente="555/2024",
            caratula="OTRO EXPEDIENTE",
            origen="PRIVADO",
        )
        Movimiento.objects.create(
            expediente=otro,
            tipo="ESCRITO",
            descripcion="MOVIMIENTO DE OTRO EXPEDIENTE",
            fecha_presentacion=ahora,
        )

        respuesta = cliente_movil.get(reverse("siped:movel_novedades"))

        assert respuesta.status_code == HTTPStatus.OK
        contenido = respuesta.content.decode()
        assert "MOVIMIENTO PROPIO 0" in contenido
        assert "MOVIMIENTO PROPIO 1" in contenido
        assert "MOVIMIENTO PROPIO 2" in contenido
        assert "MOVIMIENTO PROPIO 3" not in contenido
        assert "MOVIMIENTO DE OTRO EXPEDIENTE" not in contenido

    def test_fallback_no_hace_una_consulta_por_novedad(
        self, cliente_movil, sesion_remota_valida, novedad,
    ) -> None:
        Movimiento.objects.create(
            expediente=novedad.expediente,
            tipo="ESCRITO",
            descripcion="MOVIMIENTO DEL EXPEDIENTE",
            fecha_presentacion=timezone.now(),
        )

        with CaptureQueriesContext(connection) as una_novedad:
            cliente_movil.get(reverse("siped:movel_novedades"))

        for _ in range(4):
            NovedadSIPED.objects.create(
                usuario_asignado="abogado",
                expediente=novedad.expediente,
                tipo=NovedadSIPED.Tipo.EXPEDIENTE_NUEVO,
                procesada=True,
            )

        with CaptureQueriesContext(connection) as cinco_novedades:
            cliente_movil.get(reverse("siped:movel_novedades"))

        assert len(cinco_novedades) == len(una_novedad)

    def test_novedades_oculta_expedientes_publicos(
        self, cliente_movil, sesion_remota_valida,
    ) -> None:
        publico = Expediente.objects.create(
            usuario_asignado="abogado",
            numero_expediente="777/2024",
            caratula="EXPEDIENTE PUBLICO",
            origen="PUBLICO",
        )
        NovedadSIPED.objects.create(
            usuario_asignado="abogado",
            expediente=publico,
            tipo=NovedadSIPED.Tipo.EXPEDIENTE_NUEVO,
            procesada=True,
        )

        respuesta = cliente_movil.get(reverse("siped:movel_novedades"))

        assert respuesta.status_code == HTTPStatus.OK
        assert "777/2024" not in respuesta.content.decode()

    def test_inicio_oculta_novedades_de_expedientes_publicos(
        self, cliente_movil, sesion_remota_valida,
    ) -> None:
        publico = Expediente.objects.create(
            usuario_asignado="abogado",
            numero_expediente="666/2024",
            caratula="EXPEDIENTE PUBLICO",
            origen="PUBLICO",
        )
        NovedadSIPED.objects.create(
            usuario_asignado="abogado",
            expediente=publico,
            tipo=NovedadSIPED.Tipo.EXPEDIENTE_NUEVO,
            procesada=True,
        )

        respuesta = cliente_movil.get(reverse("siped:movel_index"))

        assert respuesta.status_code == HTTPStatus.OK
        assert "666/2024" not in respuesta.content.decode()

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
