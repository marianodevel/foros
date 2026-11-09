"""Pruebas del parser de la tabla de movimientos de la intranet."""

from foros.siped import parsers

URL_ESCRITO = "https://intranet/siped/expediente/buscar/ver_escrito_detexp.php?id=1"


def _tabla(encabezados: list[str], filas: list[list[str]]) -> str:
    cabecera = "".join(f"<th>{texto}</th>" for texto in encabezados)
    cuerpo = ""
    for fila in filas:
        celdas = "".join(f"<td>{texto}</td>" for texto in fila)
        cuerpo += f"<tr>{celdas}</tr>"

    return f'<table class="table-hover"><tr>{cabecera}</tr>{cuerpo}</table>'


ENCABEZADOS_REALES = [
    "",
    "Nombre",
    "Tasa",
    "Fecha Presentación",
    "Tipo",
    "Estado",
    "Generado por",
    "Descripción/detalle",
    "Fecha Firma",
    "Fecha Publicación",
]

# La tabla real devuelve dos celdas vacías extra al final de cada fila.
FILA_REAL = [
    "",
    "PE1234567-2026",
    "✅ Exento Bono C.A.",
    "27/10/2026 12:32:57",
    "OFICIO",
    "DESGLOSADO",
    "BRIAMONTE, JORGE ALBERTO",
    '<font title="OFICIO A CONFRONTE">OFICIO A CONFRONTE</font>',
    "",
    "27/10/2026 12:32",
    "",
    "",
]


class TestColumnasReales:
    def test_mapea_por_encabezado(self) -> None:
        cabecera = "".join(f"<th>{texto}</th>" for texto in ENCABEZADOS_REALES)
        celdas = "".join(f"<td>{texto}</td>" for texto in FILA_REAL)
        html = (
            f'<table class="table-hover"><tr>{cabecera}</tr>'
            f"<tr>{celdas}"
            f'<form action="{URL_ESCRITO}">'
            '<input type="submit" value="PE1234567-2026"></form>'
            "</tr></table>"
        )

        movimientos = parsers.parsear_movimientos_de_ajax_html(html, "123/2024")

        assert len(movimientos) == 1
        movimiento = movimientos[0]
        assert movimiento["codigo_escrito"] == "PE1234567-2026"
        assert movimiento["tasa"] == "✅ Exento Bono C.A."
        assert movimiento["fecha_presentacion"] == "27/10/2026 12:32:57"
        assert movimiento["tipo"] == "OFICIO"
        assert movimiento["estado"] == "DESGLOSADO"
        assert movimiento["generado_por"] == "BRIAMONTE, JORGE ALBERTO"
        assert movimiento["descripcion"] == "OFICIO A CONFRONTE"
        assert movimiento["fecha_firma"] == ""
        assert movimiento["fecha_publicacion"] == "27/10/2026 12:32"
        assert movimiento["link_escrito"] == URL_ESCRITO

    def test_respeta_un_orden_de_columnas_distinto(self) -> None:
        encabezados = [
            "",
            "Tipo",
            "Nombre",
            "Fecha Publicación",
            "Estado",
            "Fecha Presentación",
            "Tasa",
            "Generado por",
            "Descripción/detalle",
            "Fecha Firma",
        ]
        fila = [
            "",
            "PROVIDENCIA",
            "PE7654321-2026",
            "01/11/2026 08:15",
            "PUBLICADO",
            "31/10/2026 17:00:00",
            "",
            "JUZGADO",
            "DISPONE MEDIDAS",
            "01/11/2026 08:14:59",
        ]

        movimientos = parsers.parsear_movimientos_de_ajax_html(
            _tabla(encabezados, [fila]), "456/2026",
        )

        assert len(movimientos) == 1
        movimiento = movimientos[0]
        assert movimiento["tipo"] == "PROVIDENCIA"
        assert movimiento["codigo_escrito"] == "PE7654321-2026"
        assert movimiento["fecha_publicacion"] == "01/11/2026 08:15"
        assert movimiento["estado"] == "PUBLICADO"
        assert movimiento["fecha_presentacion"] == "31/10/2026 17:00:00"
        assert movimiento["generado_por"] == "JUZGADO"
        assert movimiento["descripcion"] == "DISPONE MEDIDAS"
        assert movimiento["fecha_firma"] == "01/11/2026 08:14:59"

    def test_sin_encabezado_usa_el_orden_conocido(self) -> None:
        celdas = "".join(f"<td>{texto}</td>" for texto in FILA_REAL)
        html = f'<table class="table-hover"><tr>{celdas}</tr></table>'

        movimientos = parsers.parsear_movimientos_de_ajax_html(html, "123/2024")

        assert len(movimientos) == 1
        assert movimientos[0]["tipo"] == "OFICIO"
        assert movimientos[0]["fecha_publicacion"] == "27/10/2026 12:32"

    def test_layout_viejo_sin_columna_fecha_firma(self) -> None:
        encabezados = [
            "",
            "Nombre",
            "Tasa",
            "Fecha Presentación",
            "Tipo",
            "Estado",
            "Generado por",
            "Descripción/detalle",
            "Fecha Publicación",
        ]
        fila = [
            "",
            "PE1234567-2025",
            "",
            "15/05/2025 18:19:59",
            "OFICIO",
            "PUBLICADO",
            "JUZGADO",
            "OFICIO A CONFRONTE",
            "16/05/2025 09:00",
        ]

        movimientos = parsers.parsear_movimientos_de_ajax_html(
            _tabla(encabezados, [fila]), "123/2025",
        )

        assert len(movimientos) == 1
        movimiento = movimientos[0]
        assert movimiento["tipo"] == "OFICIO"
        assert movimiento["fecha_publicacion"] == "16/05/2025 09:00"
        assert movimiento["fecha_firma"] == ""

    def test_solo_encabezado_devuelve_lista_vacia(self) -> None:
        html = _tabla(ENCABEZADOS_REALES, [])

        assert parsers.parsear_movimientos_de_ajax_html(html, "123/2024") == []

    def test_sin_tabla_devuelve_lista_vacia(self) -> None:
        assert parsers.parsear_movimientos_de_ajax_html("<html></html>", "1/1") == []
