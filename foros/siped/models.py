"""Modelos de base de datos para la aplicación SIPED."""

from django.db import models


class Expediente(models.Model):
    """Modelo que representa un expediente judicial en el sistema."""

    usuario_asignado = models.CharField(max_length=50, db_index=True)
    numero_expediente = models.CharField(max_length=50)
    caratula = models.CharField(max_length=255)
    partes = models.CharField(max_length=255, null=True, blank=True)
    estado = models.CharField(max_length=100, null=True, blank=True)
    fecha_ult_mov = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Último movimiento según la intranet, ya convertido a fecha.",
    )
    localidad = models.CharField(max_length=255, null=True, blank=True)
    dependencia = models.CharField(max_length=255, null=True, blank=True)
    secretaria = models.CharField(max_length=255, null=True, blank=True)
    link_detalle = models.CharField(max_length=500, null=True, blank=True)
    origen = models.CharField(max_length=50, default="PRIVADO", db_index=True)

    class Meta:
        db_table = "expedientes"

    def __str__(self) -> str:
        return f"{self.numero_expediente} ({self.usuario_asignado}) - {self.origen}"


class SesionSIPED(models.Model):
    """
    Sesión de la intranet persistida para poder consultarla desde Celery.

    Las cookies se guardan cifradas y nunca se almacena la contraseña. La
    clave es el usuario de la intranet, que es el mismo identificador que usa
    ``Expediente.usuario_asignado``.
    """

    class Estado(models.TextChoices):
        ACTIVA = "ACTIVA", "Activa"
        EXPIRADA = "EXPIRADA", "Expirada"

    username_intranet = models.CharField(max_length=50, unique=True, db_index=True)
    cookies_cifradas = models.TextField(blank=True)
    estado = models.CharField(
        max_length=10,
        choices=Estado.choices,
        default=Estado.ACTIVA,
        db_index=True,
    )
    actualizado_en = models.DateTimeField(auto_now=True)
    ultimo_polling = models.DateTimeField(null=True, blank=True)
    ultimo_error = models.TextField(blank=True)
    fallos_consecutivos = models.PositiveIntegerField(default=0)
    proximo_intento = models.DateTimeField(null=True, blank=True)
    bloqueado_hasta = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sesiones_siped"
        verbose_name = "sesión de SIPED"
        verbose_name_plural = "sesiones de SIPED"

    def __str__(self) -> str:
        return f"{self.username_intranet} ({self.get_estado_display()})"


class NovedadSIPED(models.Model):
    """
    Cambio detectado por el polling automático.

    También funciona como cola de trabajo: ``procesada=False`` indica que los
    movimientos del expediente todavía deben refrescarse. ``vista`` controla
    el aviso en la interfaz.
    """

    class Tipo(models.TextChoices):
        EXPEDIENTE_NUEVO = "EXPEDIENTE_NUEVO", "Expediente nuevo"
        MOVIMIENTOS_NUEVOS = "MOVIMIENTOS_NUEVOS", "Movimientos nuevos"

    usuario_asignado = models.CharField(max_length=50, db_index=True)
    expediente = models.ForeignKey(
        Expediente, on_delete=models.CASCADE, related_name="novedades"
    )
    tipo = models.CharField(max_length=25, choices=Tipo.choices)
    cantidad_movimientos = models.PositiveIntegerField(default=0)
    detalle = models.CharField(max_length=255, blank=True)
    detectada_en = models.DateTimeField(auto_now_add=True)
    procesada = models.BooleanField(default=False, db_index=True)
    vista = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "novedades_siped"
        ordering = ["-detectada_en"]
        verbose_name = "novedad de SIPED"
        verbose_name_plural = "novedades de SIPED"

    def __str__(self) -> str:
        return f"{self.expediente.numero_expediente} - {self.get_tipo_display()}"


class Movimiento(models.Model):
    """Modelo que representa un movimiento o escrito dentro de un expediente."""

    expediente = models.ForeignKey(
        Expediente, on_delete=models.CASCADE, related_name="movimientos"
    )
    fecha_presentacion = models.CharField(max_length=50, null=True, blank=True)
    nombre_escrito = models.CharField(max_length=255, null=True, blank=True)
    tipo = models.CharField(max_length=255, null=True, blank=True)
    estado = models.CharField(max_length=100, null=True, blank=True)
    generado_por = models.CharField(max_length=255, null=True, blank=True)
    descripcion = models.TextField(null=True, blank=True)
    fecha_firma = models.CharField(max_length=50, null=True, blank=True)
    fecha_publicacion = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Publicación en la intranet (hora de Argentina), ya convertida.",
    )
    link_escrito = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        db_table = "movimientos"

    def __str__(self) -> str:
        return f"{self.nombre_escrito} - {self.fecha_presentacion}"


class DocumentoAdjunto(models.Model):
    """
    Modelo para administrar de forma segura los archivos físicos (PDFs) 
    extraídos o fusionados del sistema judicial.
    """

    movimiento = models.ForeignKey(
        Movimiento, on_delete=models.CASCADE, related_name="documentos", null=True, blank=True
    )
    expediente = models.ForeignKey(
        Expediente, on_delete=models.CASCADE, related_name="documentos_consolidados", null=True, blank=True
    )
    archivo = models.FileField(upload_to="siped/documentos/")
    nombre_original = models.CharField(max_length=255)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    es_consolidado = models.BooleanField(
        default=False, 
        help_text="Indica si es un PDF fusionado que contiene múltiples movimientos."
    )

    class Meta:
        db_table = "documentos_adjuntos"

    def __str__(self) -> str:
        return f"Documento: {self.nombre_original}"


class ReporteBusqueda(models.Model):
    """
    Modelo para registrar las búsquedas avanzadas realizadas y almacenar
    el archivo CSV resultante de forma persistente e indexada.
    """

    usuario_asignado = models.CharField(max_length=50, db_index=True)
    parametros_busqueda = models.JSONField(
        help_text="Diccionario con los filtros exactos aplicados en la consulta."
    )
    archivo_csv = models.FileField(upload_to="siped/busquedas/")
    fecha_generacion = models.DateTimeField(auto_now_add=True)
    cantidad_resultados = models.IntegerField(default=0)

    class Meta:
        db_table = "reportes_busqueda"
        ordering = ["-fecha_generacion"]

    def __str__(self) -> str:
        return f"Búsqueda de {self.usuario_asignado} ({self.fecha_generacion})"