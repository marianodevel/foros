"""Módulo para la descarga y registro de documentos de un expediente público."""

import logging
import time
from io import BytesIO

from pypdf import PdfReader, PdfWriter
import requests
from django.core.files.base import ContentFile

from .. import gestor_almacenamiento, scraper_tasks
from ..models import DocumentoAdjunto, Expediente
from ..utils import manejar_fase_con_sesion

logger = logging.getLogger(__name__)


@manejar_fase_con_sesion("DESCARGA PUBLICA")
def ejecutar_descarga_publica(
    session: requests.Session, link_detalle_objetivo: str, username: str
) -> str:
    try:
        expediente = Expediente.objects.get(
            usuario_asignado=username,
            link_detalle=link_detalle_objetivo,
            origen__in=["PUBLICO", "BUSQUEDA_AVANZADA"],
        )
    except Expediente.DoesNotExist:
        return "Error: El expediente no se encontró en la base de datos."

    logger.info("Iniciando proceso para expediente público: %s", expediente.numero_expediente)

    expediente_data = {
        "expediente": expediente.numero_expediente,
        "link_detalle": expediente.link_detalle,
        "dependencia": expediente.dependencia,
        "origen": expediente.origen,
    }

    movimientos_nuevos = scraper_tasks.raspar_movimientos_de_expediente(session, expediente_data)

    if movimientos_nuevos:
        gestor_almacenamiento.guardar_movimientos_lote(username, expediente.numero_expediente, movimientos_nuevos)

    movimientos = expediente.movimientos.all().order_by("id")
    contador_descargas = 0

    for mov in movimientos:
        link = mov.link_escrito
        if not link or str(link).strip() == "" or str(link).lower() in ["none", "null"]:
            continue

        datos_documento = scraper_tasks.raspar_contenido_documento(session, link)
        if not datos_documento:
            continue

        pdfs_a_procesar = []
        
        url_principal = datos_documento.get("url_pdf_principal")
        if url_principal:
            pdfs_a_procesar.append({
                "url": url_principal, 
                "nombre_base": f"pub_{mov.id}_principal"
            })

        for idx, adj in enumerate(datos_documento.get("adjuntos", [])):
            nombre_limpio = adj.get("nombre", "").lower().replace(".pdf", "").replace(" ", "_")
            pdfs_a_procesar.append({
                "url": adj.get("url"),
                "nombre_base": f"pub_{mov.id}_adj_{idx + 1}_{nombre_limpio}",
            })

        for pdf_info in pdfs_a_procesar:
            nombre_archivo_final = f"{pdf_info['nombre_base']}.pdf"
            
            # Validación a nivel de archivo individual
            if DocumentoAdjunto.objects.filter(movimiento=mov, nombre_original=nombre_archivo_final).exists():
                continue

            url_pdf = pdf_info.get("url")
            if not url_pdf:
                continue

            try:
                r_pdf = session.get(url_pdf, timeout=30)
                r_pdf.raise_for_status()

                nuevo_documento = DocumentoAdjunto(
                    movimiento=mov,
                    expediente=expediente,
                    nombre_original=nombre_archivo_final,
                    es_consolidado=False,
                )
                nuevo_documento.archivo.save(nombre_archivo_final, ContentFile(r_pdf.content))
                
                contador_descargas += 1
                time.sleep(0.3)
            except Exception as e:
                logger.error("Error procesando documento del movimiento %s: %s", mov.id, e)

    # Consolidación
    docs_individuales = DocumentoAdjunto.objects.filter(
        expediente=expediente, es_consolidado=False
    ).order_by("movimiento__id", "id")

    if docs_individuales.exists():
        try:
            writer = PdfWriter()
            for doc in docs_individuales:
                reader = PdfReader(BytesIO(doc.archivo.read()))
                for page in reader.pages:
                    writer.add_page(page)

            output_pdf = BytesIO()
            writer.write(output_pdf)

            DocumentoAdjunto.objects.filter(expediente=expediente, es_consolidado=True).delete()

            nombre_consolidado = f"pub_{expediente.numero_expediente.replace('/', '-')}_consolidado.pdf"
            nuevo_consolidado = DocumentoAdjunto(
                expediente=expediente,
                nombre_original=nombre_consolidado,
                es_consolidado=True
            )
            nuevo_consolidado.archivo.save(nombre_consolidado, ContentFile(output_pdf.getvalue()))
        except Exception as e:
            logger.error("Error al consolidar expediente público %s: %s", expediente.numero_expediente, e)

    return f"Proceso completado para {expediente.numero_expediente}. Descargas: {contador_descargas}."