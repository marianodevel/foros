"""Módulo de análisis HTML para extraer estructuras y datos del sistema judicial."""

import re
import unicodedata
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from . import constants
from .exceptions import PaginaInesperada

_TEXTO_SIN_RESULTADOS = (
    "no se encontr",
    "sin resultado",
    "no hay resultado",
    "no existen resultado",
    "no se registraron",
)


def _parece_pagina_sin_resultados(soup: BeautifulSoup) -> bool:
    """Reconoce páginas legítimas que informan que la consulta no tuvo resultados."""
    texto = soup.get_text(" ", strip=True).lower()
    return any(marca in texto for marca in _TEXTO_SIN_RESULTADOS)


def obtener_url_meta_refresh(html_content: str, base_url: str) -> Optional[str]:
    soup = BeautifulSoup(html_content, "html.parser")
    meta_refresh = soup.find(
        "meta", attrs={"http-equiv": lambda x: x and x.lower() == "refresh"}
    )

    if meta_refresh:
        content = meta_refresh.get("content", "")
        match = re.search(r'url=\s*[\'"]?([^\'">\s]+)', content, re.IGNORECASE)
        if match:
            url_relativa = match.group(1)
            if not base_url.endswith("/"):
                base_url += "/"
            return urljoin(base_url, url_relativa)

    return None


def obtener_enlace_token_siped(html_content: str) -> Optional[str]:
    soup = BeautifulSoup(html_content, "html.parser")
    enlace = soup.find(
        "a",
        href=lambda href: href and "token=" in href.lower() and "siped" in href.lower(),
    )

    if enlace:
        base_url = f"{constants.BASE_URL}/servicios/"
        return urljoin(base_url, enlace.get("href"))

    return None


def encontrar_siguiente_inicio_universal(html_text: str) -> Optional[int]:
    soup = BeautifulSoup(html_text, "html.parser")
    for element in soup.find_all(["button", "a", "input"]):
        texto = element.get_text(strip=True).upper()
        valor = str(element.get("value", "")).upper()

        if "SIGUIENTE" in texto or "SIGUIENTE" in valor:
            contenido_logico = str(element.get("onclick", "")) + str(
                element.get("href", "")
            )
            match = re.search(r"inicio[=\s'\"]+(\d+)", contenido_logico, re.IGNORECASE)

            if not match:
                match = re.search(
                    r"value[=\s'\"]+(\d+)", contenido_logico, re.IGNORECASE
                )

            if match:
                return int(match.group(1))

    return None


def parsear_lista_expedientes(html_content: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html_content, "html.parser")
    tabla = soup.find("table", class_="table-striped")
    expedientes = []

    if not tabla:
        if _parece_pagina_sin_resultados(soup):
            return expedientes
        raise PaginaInesperada(
            "La respuesta no contiene la tabla de expedientes esperada."
        )

    for fila in tabla.find_all("tr"):
        columnas = fila.find_all(["td", "th"])
        if not columnas or columnas[0].name == "th":
            continue

        if len(columnas) >= 6:
            btn_link = columnas[0].find("a", href=True)
            link_detalle = ""
            exp_texto = columnas[0].get_text(strip=True)

            if btn_link:
                link_detalle = btn_link.get("href", "")
            else:
                btn = columnas[0].find("button", onclick=True)
                if btn:
                    match = re.search(r"id=(\d+)", btn.get("onclick", ""))
                    if match:
                        link_detalle = f"ver_detalle.php?id={match.group(1)}"

            expedientes.append(
                {
                    "expediente": exp_texto,
                    "caratula": columnas[1].get_text(strip=True),
                    "partes": columnas[2].get_text(strip=True) if len(columnas) > 2 else "",
                    "estado": columnas[3].get_text(strip=True) if len(columnas) > 3 else "",
                    "fec_ult_mov": columnas[4].get_text(strip=True) if len(columnas) > 4 else "",
                    "localidad": columnas[5].get_text(strip=True) if len(columnas) > 5 else "",
                    "dependencia": columnas[6].get_text(strip=True) if len(columnas) > 6 else "",
                    "secretaria": columnas[7].get_text(strip=True) if len(columnas) > 7 else "",
                    "link_detalle": urljoin(constants.LISTA_EXPEDIENTES_URL, link_detalle) if link_detalle else "",
                }
            )

    return expedientes


def parsear_detalle_para_ajax_params(html_detalle: str) -> Dict[str, str]:
    soup = BeautifulSoup(html_detalle, "html.parser")
    params = {}

    input_id = soup.find("input", {"name": "id"}) or soup.find("input", {"name": "exp_id"})
    if input_id:
        params["exp_id"] = input_id.get("value", "")

    scripts = soup.find_all("script")
    for script in scripts:
        if script.string:
            match_dep = re.search(r"dependencia_ide=(\d+)", script.string)
            if match_dep:
                params["dependencia_ide"] = match_dep.group(1)

            match_fuero = re.search(r"tj_fuero=(\d+)", script.string)
            if match_fuero:
                params["tj_fuero"] = match_fuero.group(1)

            match_org = re.search(r"exp_organismo_origen=(\d+)", script.string)
            if match_org:
                params["exp_organismo_origen"] = match_org.group(1)

    return params


_CAMPOS_MOVIMIENTO_POR_ENCABEZADO = {
    "nombre": "codigo_escrito",
    "tasa": "tasa",
    "fecha presentacion": "fecha_presentacion",
    "tipo": "tipo",
    "estado": "estado",
    "generado por": "generado_por",
    "descripcion/detalle": "descripcion",
    "fecha firma": "fecha_firma",
    "fecha publicacion": "fecha_publicacion",
}

# Orden vigente de la tabla de movimientos. Se usa como respaldo cuando la
# respuesta no trae encabezados reconocibles.
_COLUMNAS_MOVIMIENTO_POR_DEFECTO = {
    "codigo_escrito": 1,
    "tasa": 2,
    "fecha_presentacion": 3,
    "tipo": 4,
    "estado": 5,
    "generado_por": 6,
    "descripcion": 7,
    "fecha_firma": 8,
    "fecha_publicacion": 9,
}


def _normalizar_encabezado(texto: str) -> str:
    """Pasa a minúsculas y quita tildes para comparar encabezados."""
    sin_tildes = "".join(
        caracter
        for caracter in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(caracter)
    )
    return " ".join(sin_tildes.casefold().split())


def _mapa_columnas_movimiento(tabla: BeautifulSoup) -> dict[str, int]:
    """
    Devuelve el índice de cada campo según los ``<th>`` de la tabla.

    La intranet agregó la columna ``Fecha Firma`` y desplazó ``Fecha
    Publicación``. Mapear por nombre evita que el próximo cambio de orden vuelva
    a mezclar los datos. Si no hay encabezados reconocibles se usa el orden
    conocido como respaldo.
    """
    for fila in tabla.find_all("tr"):
        encabezados = fila.find_all("th")
        if not encabezados:
            continue

        mapa = {}
        for indice, celda in enumerate(encabezados):
            campo = _CAMPOS_MOVIMIENTO_POR_ENCABEZADO.get(
                _normalizar_encabezado(celda.get_text(" ", strip=True)),
            )
            if campo:
                mapa[campo] = indice

        if {"tipo", "estado", "fecha_publicacion"}.issubset(mapa):
            return mapa

    return dict(_COLUMNAS_MOVIMIENTO_POR_DEFECTO)


def _texto_columna(columnas, indice: int | None) -> str:
    """Devuelve el texto de una celda o cadena vacía si no existe."""
    if indice is None or indice >= len(columnas):
        return ""

    return columnas[indice].get_text(strip=True)


def parsear_movimientos_de_ajax_html(
    html_content: str,
    expediente_nro: str,
) -> list[dict[str, str]]:
    soup = BeautifulSoup(html_content, "html.parser")
    tabla = soup.find("table", class_="table-hover") or soup.find("table")
    movimientos = []

    if not tabla:
        return movimientos

    columnas_por_campo = _mapa_columnas_movimiento(tabla)
    maximo_indice = max(columnas_por_campo.values())

    for fila in tabla.find_all("tr"):
        columnas = fila.find_all(["td", "th"])
        if not columnas or columnas[0].name == "th":
            continue
        if len(columnas) <= maximo_indice:
            continue

        textos = {
            campo: _texto_columna(columnas, indice)
            for campo, indice in columnas_por_campo.items()
        }
        # Una tabla vieja puede no traer todas las columnas; completamos con
        # vacío para que el resto del parseo no dependa del layout.
        for campo in _COLUMNAS_MOVIMIENTO_POR_DEFECTO:
            textos.setdefault(campo, "")

        btn_link = fila.find("form", action=True)
        link_escrito = ""
        codigo_escrito = ""

        if btn_link:
            link_escrito = btn_link.get("action", "")
            btn_submit = btn_link.find("input", type="submit")
            if btn_submit:
                codigo_escrito = btn_submit.get("value", "").strip()

        indice_descripcion = columnas_por_campo.get("descripcion")
        if indice_descripcion is None:
            descripcion = ""
        else:
            font_tag = columnas[indice_descripcion].find("font", title=True)
            descripcion = (
                font_tag.get("title", "").strip()
                if font_tag
                else textos["descripcion"]
            )

        movimientos.append(
            {
                "expediente_nro": expediente_nro,
                "codigo_escrito": codigo_escrito or textos["codigo_escrito"],
                "tasa": textos["tasa"],
                "fecha_presentacion": textos["fecha_presentacion"],
                "tipo": textos["tipo"],
                "estado": textos["estado"],
                "generado_por": textos["generado_por"],
                "descripcion": descripcion,
                "fecha_firma": textos["fecha_firma"],
                "fecha_publicacion": textos["fecha_publicacion"],
                "link_escrito": (
                    urljoin(constants.AJAX_MOVIMIENTOS_URL, link_escrito)
                    if link_escrito
                    else ""
                ),
            },
        )

    return movimientos


def normalizar_url_pdf(url_sucia: str, tipo: str = "principal") -> str:
    """Reescribe las direcciones relativas y absolutas del motor legacy de renderizado."""
    base_resolve_url = f"{constants.BASE_URL}/siped/expediente/buscar/"
    url_resuelta = urljoin(base_resolve_url, url_sucia)

    # Parche crítico originario del sistema SIPED
    if "pdfabogado.php" in url_resuelta and "agrega_plantilla" not in url_resuelta:
        url_resuelta = url_resuelta.replace("pdfabogado.php", "siped/agrega_plantilla/")

    return url_resuelta


def parsear_pagina_documento(html_content: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html_content, "html.parser")
    data = {"url_pdf_principal": None, "adjuntos": [], "firmantes": []}

    link_principal = soup.find("a", href=re.compile(r"pdfabogado|descargar", re.IGNORECASE))
    if link_principal:
        data["url_pdf_principal"] = normalizar_url_pdf(link_principal.get("href"), "principal")

    for a_tag in soup.find_all("a", href=re.compile(r"ver_adjunto_escrito\.php")):
        data["adjuntos"].append(
            {
                "nombre": a_tag.get_text(strip=True),
                "url": normalizar_url_pdf(a_tag.get("href"), "adjunto"),
            }
        )

    firmantes_td = soup.find(lambda tag: tag.name == "td" and "Firmado electr" in tag.text)
    if firmantes_td:
        tabla_firmas = firmantes_td.find_parent("table")
        if tabla_firmas:
            filas = tabla_firmas.find_all("tr")
            if len(filas) >= 3:
                cols = filas[2].find_all("td")
                if len(cols) >= 3:
                    data["firmantes"].append(
                        {
                            "cargo": cols[0].get_text(strip=True),
                            "nombre": cols[1].get_text(strip=True),
                            "fecha": cols[2].get_text(strip=True),
                        }
                    )

    return data


def parsear_lista_publica(html_content: str) -> List[Dict[str, Optional[str]]]:
    soup = BeautifulSoup(html_content, "html.parser")
    tabla = soup.find("table", class_="table-striped")
    expedientes = []

    if not tabla:
        if _parece_pagina_sin_resultados(soup):
            return expedientes
        raise PaginaInesperada(
            "La respuesta no contiene la tabla pública de expedientes esperada."
        )

    for fila in tabla.find_all("tr"):
        columnas = fila.find_all(["td", "th"])
        if not columnas or columnas[0].name == "th":
            continue

        if len(columnas) >= 7:
            btn_link = columnas[0].find("button", onclick=True)
            exp_id = link_detalle = None

            if btn_link:
                match = re.search(r"id=(\d+)", btn_link.get("onclick", ""))
                if match:
                    exp_id = match.group(1)
                    link_detalle = f"../expediente/expediente/buscar/DetalleExpediente.php?id={exp_id}"

            expedientes.append(
                {
                    "exp_id": exp_id,
                    "expediente": columnas[0].get_text(strip=True),
                    "caratula": columnas[1].get_text(strip=True),
                    "partes_count": columnas[2].get_text(strip=True),
                    "fecha_alta": columnas[3].get_text(strip=True),
                    "localidad": columnas[4].get_text(strip=True),
                    "dependencia": columnas[5].get_text(strip=True),
                    "secretaria": columnas[6].get_text(strip=True),
                    "link_detalle": urljoin(constants.LISTA_EXPEDIENTES_URL, link_detalle) if link_detalle else None,
                }
            )

    return expedientes