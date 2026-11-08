"""Cifrado simétrico de las cookies de la intranet judicial."""

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken
from django.conf import settings


class ErrorCifrado(Exception):
    """No se pudo cifrar o descifrar el material sensible."""


def _fernet() -> Fernet:
    """
    Deriva una clave Fernet estable a partir de ``SECRET_KEY``.

    Cambiar ``SECRET_KEY`` invalida las cookies guardadas, lo que fuerza un
    nuevo login contra la intranet (comportamiento deseado ante una rotación
    de secretos).
    """
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def cifrar_cookies(cookies: dict[str, Any]) -> str:
    """Serializa y cifra el diccionario de cookies de la intranet."""
    try:
        payload = json.dumps(cookies, separators=(",", ":"), ensure_ascii=False)
        return _fernet().encrypt(payload.encode("utf-8")).decode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ErrorCifrado("No se pudieron cifrar las cookies de SIPED.") from exc


def descifrar_cookies(token: str) -> dict[str, Any]:
    """Descifra el token almacenado y devuelve el diccionario de cookies."""
    if not token:
        raise ErrorCifrado("No hay cookies de SIPED almacenadas.")
    try:
        payload = _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
        datos = json.loads(payload)
    except (InvalidToken, ValueError, TypeError) as exc:
        raise ErrorCifrado(
            "Las cookies almacenadas de SIPED no se pudieron descifrar.",
        ) from exc

    if not isinstance(datos, dict):
        raise ErrorCifrado("El contenido cifrado de SIPED no es un diccionario.")
    return datos
