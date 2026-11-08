"""Módulo para la sincronización, descarga y consolidación de un expediente privado individual."""

import logging
import re
import time
from io import BytesIO

from pypdf import PdfReader, PdfWriter
import requests
from django.core.files.base import ContentFile

from .. import gestor_almacenamiento, scraper_tasks
from ..exceptions import SesionSIPEDExpirada
from ..models import DocumentoAdjunto, Expediente
from ..utils import manejar_fase_con_sesion

logger = logging.getLogger(__name__)


@manejar_fase_con_sesion("SINCRONIZACION INDIVIDUAL")
def ejecutar_sincronizacion_individual(
    session: requests.Session, nro_expediente_objetivo: str, username: str
) -> str:
    """
    Ejecuta el ciclo completo (movimientos, descargas y consolidación) para un solo expediente.
    """
    try:
        expediente = Expediente.objects.get(
            usuario_asignado=username,
            numero_expediente=nro_expediente_objetivo,
            origen="PRIVADO",
        )
    except Expediente.DoesNotExist:
        return f"Error: El expediente '{nro_expediente_objetivo}' no se encontró en la base de datos."

    logger.info("Iniciando proceso individual para: %s", nro_expediente_objetivo)

    expediente_data = {
        "expediente": expediente.numero_expediente,
        "link_detalle": expediente.link_detalle,
        "dependencia": expediente.dependencia,
        "origen": expediente.origen,
    }

    movimientos_nuevos = scraper_tasks.raspar_movimientos_de_expediente(session, expediente_data)

    if movimientos_nuevos:
        gestor_almacenamiento.guardar_movimientos_lote(username, expediente.numero_expediente, movimientos_nuevos)

    # R4: eliminar documentos individuales previos para evitar que PDFs obsoletos
    # se incluyan en el consolidado (equivalente al os.remove() del sistema Flask)
    DocumentoAdjunto.objects.filter(
        expediente=expediente,
        es_consolidado=False
    ).delete()
    logger.info("Documentos individuales anteriores eliminados para %s", nro_expediente_objetivo)

    movimientos = expediente.movimientos.all().order_by("id")
    descargas = 0
    
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
            # Validación a nivel de archivo individual
            if DocumentoAdjunto.objects.filter(movimiento=mov, nombre_original=pdf_info["nombre"]).exists():
                continue

            url_pdf = pdf_info.get("url")
            if not url_pdf:
                continue

            try:
                contenido_pdf = scraper_tasks.descargar_pdf_en_memoria(session, url_pdf)

                nuevo_doc = DocumentoAdjunto(
                    movimiento=mov,
                    expediente=expediente,
                    nombre_original=pdf_info["nombre"],
                    es_consolidado=False
                )
                nuevo_doc.archivo.save(pdf_info["nombre"], ContentFile(contenido_pdf))

                descargas += 1
                time.sleep(0.3)
            except SesionSIPEDExpirada:
                raise
            except Exception as e:
                logger.error("Error descargando %s: %s", url_pdf, e)

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

            nro_limpio      = expediente.numero_expediente.replace('/', '-')
            caratula_limpia = re.sub(r'[\\/*?:"<>|]', '', expediente.caratula)[:80].strip()
            nombre_consolidado = f"{nro_limpio} - {caratula_limpia}_consolidado.pdf"
            nuevo_consolidado = DocumentoAdjunto(
                expediente=expediente,
                nombre_original=nombre_consolidado,
                es_consolidado=True
            )
            nuevo_consolidado.archivo.save(nombre_consolidado, ContentFile(output_pdf.getvalue()))
        except Exception as e:
            logger.error("Error al consolidar expediente %s: %s", expediente.numero_expediente, e)

    return f"Proceso completado para {nro_expediente_objetivo}. Descargas nuevas: {descargas}."