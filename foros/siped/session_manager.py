"""Módulo para la gestión de sesiones y autenticación en el sistema SIPED."""

import logging
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup
from requests.utils import cookiejar_from_dict, dict_from_cookiejar

from . import constants
from . import parsers
from .exceptions import SesionSIPEDExpirada

logger = logging.getLogger(__name__)

# El login legacy de la intranet siempre apunta a este endpoint.
_PAGINA_LOGIN = "controli2.php"
_CAMPOS_USUARIO = {"usuario", "user", "username"}
_CAMPOS_CLAVE = {"pass", "password", "clave"}


def _es_respuesta_html(respuesta: requests.Response) -> bool:
    """Determina si el cuerpo de la respuesta es HTML parseable."""
    tipo = str(respuesta.headers.get("Content-Type", "")).lower()
    if not tipo:
        return True
    return (
        "html" in tipo
        or "text/plain" in tipo
        or "application/octet-stream" in tipo
    )


def es_pagina_login(respuesta: requests.Response) -> bool:
    """
    Detecta si la intranet respondió con su pantalla de login.

    Una sesión vencida no devuelve 401/403: devuelve HTTP 200 con el formulario
    de acceso. Por eso es imprescindible inspeccionar la respuesta y no sólo el
    status code.
    """
    url_final = str(getattr(respuesta, "url", "") or "").lower()
    if _PAGINA_LOGIN in url_final:
        return True

    contenido = getattr(respuesta, "content", b"") or b""
    if b"%PDF" in contenido[:1024]:
        return False

    for previa in getattr(respuesta, "history", None) or []:
        destino = str(previa.headers.get("Location", "")).lower()
        if _PAGINA_LOGIN in destino:
            return True

    if not _es_respuesta_html(respuesta):
        return False

    html = getattr(respuesta, "text", "") or ""
    if not html.strip():
        return False

    soup = BeautifulSoup(html, "html.parser")

    for form in soup.find_all("form"):
        if _PAGINA_LOGIN in str(form.get("action", "")).lower():
            return True

    campos = {
        str(campo.get("name", "")).lower()
        for campo in soup.find_all("input")
        if campo.get("name")
    }
    if campos.intersection(_CAMPOS_USUARIO) and campos.intersection(_CAMPOS_CLAVE):
        return True

    meta = soup.find(
        "meta", attrs={"http-equiv": lambda valor: valor and valor.lower() == "refresh"}
    )
    if meta and _PAGINA_LOGIN in str(meta.get("content", "")).lower():
        return True

    return False


def verificar_respuesta_autenticada(respuesta: requests.Response) -> None:
    """Lanza SesionSIPEDExpirada si la respuesta es el login de la intranet."""
    if es_pagina_login(respuesta):
        logger.warning("La intranet respondió con el formulario de login.")
        raise SesionSIPEDExpirada()


def verificar_sesion(session: requests.Session, url: Optional[str] = None) -> bool:
    """
    Comprueba contra la intranet que la cookie almacenada siga siendo válida.

    Devuelve False sólo cuando la intranet confirma que la sesión expiró (es
    decir, responde con el login). Ante un error de red devuelve True para no
    cerrar la sesión por un problema transitorio del servidor remoto.
    """
    url_verificacion = url or constants.LISTA_EXPEDIENTES_URL

    try:
        respuesta = session.get(
            url_verificacion,
            params={"inicio": 0},
            timeout=constants.VERIFICACION_TIMEOUT,
        )
        respuesta.raise_for_status()
    except requests.HTTPError as exc:
        respuesta_error = exc.response
        if respuesta_error is not None and respuesta_error.status_code in (401, 403):
            return False
        logger.warning("No se pudo verificar la sesión SIPED: %s", exc)
        return True
    except requests.RequestException as exc:
        logger.warning("No se pudo verificar la sesión SIPED: %s", exc)
        return True

    return not es_pagina_login(respuesta)


def autenticar_en_siped(usuario: str, clave: str) -> Optional[Dict[str, str]]:
    """Intenta autenticar un usuario y clave contra SIPED."""
    if not usuario or not clave:
        logger.error("Credenciales incompletas.")
        return None

    session = requests.Session()
    session.headers.update(constants.BROWSER_HEADERS)

    try:
        logger.info(f"Autenticando usuario: {usuario}.")
        credenciales = {"usuario": usuario, "pass": clave}
        r_login = session.post(constants.LOGIN_URL, data=credenciales)
        r_login.raise_for_status()

        url_inicio = parsers.obtener_url_meta_refresh(
            r_login.text, f"{constants.BASE_URL}/servicios"
        )

        if not url_inicio:
            logger.error("Error de autenticación: Redirección fallida.")
            return None

        r_menu = session.get(url_inicio)
        r_menu.raise_for_status()

        url_token = parsers.obtener_enlace_token_siped(r_menu.text)

        if not url_token:
            logger.error("Token de sesión no encontrado.")
            return None

        r_token_page = session.get(url_token)
        r_token_page.raise_for_status()

        url_dashboard = parsers.obtener_url_meta_refresh(
            r_token_page.text, f"{constants.BASE_URL}/siped"
        )

        if not url_dashboard or "frame_principal.php" not in url_dashboard:
            logger.error("Destino principal inaccesible.")
            return None

        session.get(url_dashboard)

        logger.info(f"Autenticación completada para el usuario: {usuario}.")
        return dict_from_cookiejar(session.cookies)

    except requests.exceptions.RequestException as e:
        logger.error(f"Error de conexión durante la autenticación: {e}")
        return None
    except Exception as e:
        logger.error("Error interno durante la autenticación", exc_info=True)
        return None

def crear_sesion_con_cookies(cookies_dict: Optional[Dict[str, str]]) -> requests.Session:
    """Instancia una nueva sesión HTTP configurada con las cookies proporcionadas."""
    session = requests.Session()
    session.headers.update(constants.BROWSER_HEADERS)
    if cookies_dict:
        session.cookies = cookiejar_from_dict(cookies_dict)
    return session