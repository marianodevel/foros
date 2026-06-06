"""Módulo para la gestión de sesiones y autenticación en el sistema SIPED."""

import logging
from typing import Dict, Optional
import requests
from requests.utils import cookiejar_from_dict, dict_from_cookiejar

from . import constants
# Nota: parsers.py deberá ser movido a foros/siped/parsers.py en el próximo paso
from . import parsers 

logger = logging.getLogger(__name__)

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