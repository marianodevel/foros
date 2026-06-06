"""Módulo para la descarga, registro y consolidación de documentos PDF."""

import logging
import time
from io import BytesIO

from pypdf import PdfReader, PdfWriter
import requests
from django.core.files.base import ContentFile

from .. import scraper_tasks
from ..models import DocumentoAdjunto, Expediente
from ..utils import manejar_fase_con_sesion

logger = logging.getLogger(__name__)


@manejar_fase_con_sesion("SINCRONIZACION DE DOCUMENTOS")
def ejecutar_sincronizacion_documentos(session: requests.Session, username: str) -> str:
    """
    Descarga los PDFs individuales faltantes de todos los expedientes privados
    y genera un documento consolidado final por cada expediente.
    """
    expedientes = Expediente.objects.filter(usuario_asignado=username, origen="PRIVADO")
    if not expedientes.exists():
        return "No hay expedientes registrados para procesar."

    contador_descargas = 0
    consolidados = 0

    for exp in expedientes:
        movimientos = exp.movimientos.all().order_by("id")
        nuevas_descargas_exp = 0

        for mov in movimientos:
            link = mov.link_escrito
            if not link or str(link).strip() == "" or str(link).lower() in ["none", "null"]:
                continue

            datos_doc = scraper_tasks.raspar_contenido_documento(session, link)
            if not datos_doc:
                continue

            pdfs_a_procesar = []
            
            url_principal = datos_doc.get("url_pdf_principal")
            if url_principal:
                pdfs_a_procesar.append({
                    "url": url_principal,
                    "nombre": f"mov_{mov.id}_principal.pdf"
                })

            for idx, adj in enumerate(datos_doc.get("adjuntos", [])):
                nombre_limpio = adj.get("nombre", "").lower().replace(".pdf", "").replace(" ", "_")
                pdfs_a_procesar.append({
                    "url": adj.get("url"),
                    "nombre": f"mov_{mov.id}_adj_{idx+1}_{nombre_limpio}.pdf"
                })

            for pdf_info in pdfs_a_procesar:
                # Restauración de la lógica original: Comprobar por archivo específico, no por movimiento.
                if DocumentoAdjunto.objects.filter(movimiento=mov, nombre_original=pdf_info["nombre"]).exists():
                    continue

                url_pdf = pdf_info.get("url")
                if not url_pdf:
                    continue

                try:
                    r_pdf = session.get(url_pdf, timeout=30)
                    r_pdf.raise_for_status()
                    
                    nuevo_doc = DocumentoAdjunto(
                        movimiento=mov,
                        expediente=exp,
                        nombre_original=pdf_info["nombre"],
                        es_consolidado=False
                    )
                    nuevo_doc.archivo.save(pdf_info["nombre"], ContentFile(r_pdf.content))
                    
                    contador_descargas += 1
                    nuevas_descargas_exp += 1
                    time.sleep(0.3)
                except Exception as e:
                    logger.error("Error descargando %s: %s", url_pdf, e)

        doc_consolidado = DocumentoAdjunto.objects.filter(expediente=exp, es_consolidado=True).first()
        docs_individuales = DocumentoAdjunto.objects.filter(
            expediente=exp, es_consolidado=False
        ).order_by("movimiento__id", "id")

        # R5: detectar consolidación interrumpida — hay docs individuales más
        # recientes que el consolidado existente (ejecución previa cortada a mitad)
        consolidacion_incompleta = (
            doc_consolidado
            and docs_individuales.filter(
                fecha_creacion__gt=doc_consolidado.fecha_creacion
            ).exists()
        )

        necesita_consolidar = (
            nuevas_descargas_exp > 0
            or not doc_consolidado
            or consolidacion_incompleta
        )

        if necesita_consolidar and docs_individuales.exists():
            if consolidacion_incompleta:
                logger.warning(
                    "Consolidación incompleta detectada para %s. Regenerando.",
                    exp.numero_expediente,
                )
            try:
                writer = PdfWriter()
                for doc in docs_individuales:
                    reader = PdfReader(BytesIO(doc.archivo.read()))
                    for page in reader.pages:
                        writer.add_page(page)

                output_pdf = BytesIO()
                writer.write(output_pdf)

                if doc_consolidado:
                    doc_consolidado.delete()

                nombre_consolidado = f"{exp.numero_expediente.replace('/', '-')}_consolidado.pdf"
                nuevo_consolidado = DocumentoAdjunto(
                    expediente=exp,
                    nombre_original=nombre_consolidado,
                    es_consolidado=True
                )
                nuevo_consolidado.archivo.save(nombre_consolidado, ContentFile(output_pdf.getvalue()))
                consolidados += 1

            except Exception as e:
                logger.error("Error al consolidar expediente %s: %s", exp.numero_expediente, e)

    return f"Proceso finalizado. PDFs descargados: {contador_descargas}. Expedientes consolidados: {consolidados}."