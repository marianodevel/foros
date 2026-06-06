"""Modelos de base de datos para la aplicación SIPED."""

from django.db import models


class Expediente(models.Model):
    """Modelo que representa un expediente judicial en el sistema."""

    usuario_asignado = models.CharField(max_length=50, db_index=True)
    numero_expediente = models.CharField(max_length=50)
    caratula = models.CharField(max_length=255)
    partes = models.CharField(max_length=255, null=True, blank=True)
    estado = models.CharField(max_length=100, null=True, blank=True)
    fec_ult_mov = models.CharField(max_length=20, null=True, blank=True)
    localidad = models.CharField(max_length=255, null=True, blank=True)
    dependencia = models.CharField(max_length=255, null=True, blank=True)
    secretaria = models.CharField(max_length=255, null=True, blank=True)
    link_detalle = models.CharField(max_length=500, null=True, blank=True)
    origen = models.CharField(max_length=50, default="PRIVADO", db_index=True)

    class Meta:
        db_table = "expedientes"

    def __str__(self) -> str:
        return f"{self.numero_expediente} ({self.usuario_asignado}) - {self.origen}"


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
    fecha_publicacion = models.CharField(max_length=50, null=True, blank=True)
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