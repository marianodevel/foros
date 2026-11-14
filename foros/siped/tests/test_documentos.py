"""Pruebas del scraping de páginas de escrito y su vista alternativa."""

from unittest.mock import Mock

import pytest

from foros.siped import scraper_tasks
from foros.siped.exceptions import PaginaInesperada

URL_DETEXP = (
    "https://intranet.jussantacruz.gob.ar/siped/expediente/buscar/"
    "ver_escrito_detexp.php?esc_ide=TWpreU16QXpOQT09&exp_id=212011&frm=&cerrar=1"
)
URL_VER_ESCRITO = URL_DETEXP.replace("ver_escrito_detexp.php", "ver_escrito.php")

ENCABEZADO_DOCUMENTO = """
<div>Poder Judicial de la provincia de Santa Cruz</div>
<div>Expediente: 23215/2025</div>
"""

PAGINA_SIN_ARCHIVO = f"""
<html><body>{ENCABEZADO_DOCUMENTO}
<p>Estimados: se informan los datos de la cuenta abierta en autos.</p>
<p>N° 1-459744/8 - CBU 0860001102800045974487</p>
</body></html>
"""

PAGINA_CON_PDF = f"""
<html><body>{ENCABEZADO_DOCUMENTO}
<a href="../../agrega_plantilla/pdfabogado.php?id_escrito=2923034">
Descargar archivo PDF</a>
</body></html>
"""


def _respuesta(html: str, url: str = URL_DETEXP) -> Mock:
    respuesta = Mock()
    respuesta.text = html
    respuesta.url = url
    respuesta.status_code = 200
    respuesta.headers = {"Content-Type": "text/html; charset=UTF-8"}
    respuesta.content = html.encode()
    respuesta.history = []
    respuesta.raise_for_status = Mock()
    return respuesta


class TestRasparContenidoDocumento:
    def test_fallback_recupera_el_pdf_de_ver_escrito(self) -> None:
        session = Mock()
        session.get.side_effect = [
            _respuesta(PAGINA_SIN_ARCHIVO),
            _respuesta(PAGINA_CON_PDF, url=URL_VER_ESCRITO),
        ]

        datos = scraper_tasks.raspar_contenido_documento(session, URL_DETEXP)

        assert datos["url_pdf_principal"].endswith(
            "/siped/agrega_plantilla/pdfabogado.php?id_escrito=2923034",
        )
        assert [llamada.args[0] for llamada in session.get.call_args_list] == [
            URL_DETEXP,
            URL_VER_ESCRITO,
        ]

    def test_no_reintenta_si_la_primaria_ya_tiene_pdf(self) -> None:
        session = Mock()
        session.get.return_value = _respuesta(PAGINA_CON_PDF)

        datos = scraper_tasks.raspar_contenido_documento(session, URL_DETEXP)

        assert datos["url_pdf_principal"]
        assert session.get.call_count == 1

    def test_documento_sin_archivo_se_omite_con_aviso(self, caplog) -> None:
        session = Mock()
        session.get.side_effect = [
            _respuesta(PAGINA_SIN_ARCHIVO),
            _respuesta(PAGINA_SIN_ARCHIVO, url=URL_VER_ESCRITO),
        ]

        with caplog.at_level("WARNING"):
            datos = scraper_tasks.raspar_contenido_documento(session, URL_DETEXP)

        assert datos["url_pdf_principal"] is None
        assert datos["adjuntos"] == []
        assert "no publica archivo descargable" in caplog.text

    def test_pagina_no_reconocida_lanza(self) -> None:
        session = Mock()
        session.get.return_value = _respuesta(
            "<html><body>otra cosa</body></html>",
            url=URL_VER_ESCRITO,
        )

        with pytest.raises(PaginaInesperada):
            scraper_tasks.raspar_contenido_documento(session, URL_VER_ESCRITO)
