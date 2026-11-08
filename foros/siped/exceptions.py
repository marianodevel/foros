"""Excepciones específicas de la integración con el sistema judicial SIPED."""


class ErrorSIPED(Exception):
    """Error base de la integración con SIPED."""


class SesionSIPEDExpirada(ErrorSIPED):
    """
    La cookie de la intranet judicial dejó de ser válida.

    El mensaje lleva un prefijo estable para que el resultado de Celery pueda
    reconocerse incluso cuando el backend serializa la excepción como texto.
    """

    PREFIJO = "[SESION_SIPED_EXPIRADA]"
    MENSAJE_POR_DEFECTO = (
        "La sesión de la intranet judicial expiró. Volvé a iniciar sesión."
    )

    def __init__(self, mensaje: str = "") -> None:
        detalle = mensaje.strip()
        # Celery reconstruye la excepción a partir de exc.args, que ya incluye
        # el prefijo. Evitamos duplicarlo al deserializar.
        if detalle.startswith(self.PREFIJO):
            detalle = detalle[len(self.PREFIJO) :].strip()
        super().__init__(f"{self.PREFIJO} {detalle or self.MENSAJE_POR_DEFECTO}")

    @classmethod
    def es_resultado(cls, resultado: object) -> bool:
        """Indica si un resultado de Celery corresponde a una sesión expirada."""
        return cls.PREFIJO in str(resultado or "")

    @classmethod
    def limpiar_mensaje(cls, resultado: object) -> str:
        """Quita el prefijo técnico para mostrar el mensaje al usuario."""
        mensaje = str(resultado or "").replace(cls.PREFIJO, "").strip()
        return mensaje or cls.MENSAJE_POR_DEFECTO


class PaginaInesperada(ErrorSIPED):
    """
    La respuesta no tiene la estructura esperada del sistema judicial.

    Se usa para no confundir "el expediente no tiene datos" con "la página
    recibida no es la que debíamos parsear".
    """
