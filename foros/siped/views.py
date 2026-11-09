"""Controladores principales de la aplicación SIPED."""

import csv
import json
import logging
from functools import wraps

from django.contrib import messages
from django.db.models import F
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import gestor_almacenamiento, gestor_tareas, session_manager
from .catalogos.dependencias import DEPENDENCIAS_POR_LOCALIDAD
from .cripto import cifrar_cookies
from .exceptions import SesionSIPEDExpirada
from .fechas import formatear_fecha_hora_intranet
from .fechas import formatear_fecha_intranet
from .forms import (
    BusquedaAvanzadaForm,
    DescargaPublicaForm,
    LoginForm,
    SincronizacionIndividualForm,
)
from .models import (
    DocumentoAdjunto,
    Expediente,
    Movimiento,
    NovedadSIPED,
    ReporteBusqueda,
    SesionSIPED,
)
from .tasks import (
    busqueda_avanzada_task,
    descarga_publica_task,
    sincronizacion_individual_task,
    sincronizacion_publica_task,
    sincronizar_documentos_task,
    sincronizar_expedientes_task,
    sincronizar_movimientos_task,
)

logger = logging.getLogger(__name__)

# R1: mapa centralizado — evita repetir el mismo dict en cuatro funciones distintas
MAPA_FASES = {
    "fase_1":                 "sincronizar_expedientes",
    "fase_2":                 "sincronizar_movimientos",
    "fase_3":                 "sincronizar_documentos",
    "fase_unico":             "sincronizacion_individual",
    "fase_publica":           "sincronizacion_publica",
    "fase_busqueda_avanzada": "busqueda_avanzada",
    "fase_descarga_publica":  "descarga_publica",
}

MAPA_TAREAS_CELERY = {
    "fase_1":       sincronizar_expedientes_task,
    "fase_2":       sincronizar_movimientos_task,
    "fase_3":       sincronizar_documentos_task,
    "fase_publica": sincronizacion_publica_task,
}


def siped_login_required(view_func):
    """Decorador para restringir el acceso a usuarios sin sesión activa en SIPED."""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if (
            "siped_cookies" not in request.session
            or "siped_username" not in request.session
        ):
            messages.warning(request, "Por favor, inicia sesión para acceder a esta página.")
            return redirect("siped:login")
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def _guardar_sesion_siped(username: str, cookies: dict) -> None:
    """
    Persiste la sesión de la intranet para que el polling pueda usarla.

    Las cookies se almacenan cifradas; la contraseña nunca se guarda.
    """
    SesionSIPED.objects.update_or_create(
        username_intranet=username,
        defaults={
            "cookies_cifradas": cifrar_cookies(cookies),
            "estado": SesionSIPED.Estado.ACTIVA,
            "ultimo_error": "",
            "fallos_consecutivos": 0,
            "proximo_intento": None,
        },
    )


def _limpiar_sesion_siped(request) -> None:
    """Elimina las credenciales de la intranet sin cerrar la sesión de Django."""
    username = request.session.get("siped_username")
    request.session.pop("siped_cookies", None)
    request.session.pop("siped_username", None)
    request.session.modified = True

    # Se conserva el registro para que el polling sepa que debe esperar un
    # nuevo login en lugar de seguir intentando con una cookie vencida.
    if username:
        SesionSIPED.objects.filter(username_intranet=username).update(
            estado=SesionSIPED.Estado.EXPIRADA,
            cookies_cifradas="",
        )


def _sesion_remota_valida(request) -> bool:
    """
    Consulta la intranet para confirmar que la cookie almacenada sigue viva.

    Sólo se considera inválida cuando el servidor remoto responde con el login;
    los errores de red no cierran la sesión local.
    """
    cookies = request.session.get("siped_cookies")
    if not cookies:
        return False
    session = session_manager.crear_sesion_con_cookies(cookies)
    return session_manager.verificar_sesion(session)


def _respuesta_sesion_expirada(request):
    """Invalida la sesión local y ordena a HTMX volver al login."""
    _limpiar_sesion_siped(request)
    messages.warning(request, SesionSIPEDExpirada.MENSAJE_POR_DEFECTO)
    response = render(request, "siped/_fragmento_mensajes.html")
    response["HX-Redirect"] = reverse("siped:login")
    return response


def login_view(request):
    """Maneja la autenticación contra el sistema externo y establece la sesión local."""
    renovar = "renovar" in request.GET

    # Si ya hay una cookie, sólo se reutiliza cuando la intranet confirma que
    # sigue vigente. Antes bastaba con que la clave existiera, lo que dejaba al
    # usuario atrapado con una sesión remota vencida y sin forma de reautenticarse.
    if "siped_cookies" in request.session and not renovar:
        if _sesion_remota_valida(request):
            return redirect("siped:indice")
        _limpiar_sesion_siped(request)
        messages.warning(
            request,
            "La sesión de la intranet expiró. Ingresá tus credenciales nuevamente.",
        )
    elif renovar:
        _limpiar_sesion_siped(request)

    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"]
            password = form.cleaned_data["password"]

            logger.info("Intento de login para usuario: %s", username)
            cookies_dict = session_manager.autenticar_en_siped(username, password)

            if cookies_dict:
                # Rotar el identificador de sesión evita fijación de sesión.
                request.session.cycle_key()
                request.session["siped_cookies"] = cookies_dict
                request.session["siped_username"] = username
                _guardar_sesion_siped(username, cookies_dict)
                logger.info("Login exitoso para usuario: %s", username)
                messages.success(request, f"Bienvenido, {username}! Sesión iniciada.")
                return redirect("siped:indice")

            logger.warning("Login fallido para usuario: %s", username)
            messages.error(request, "Error de autenticación. Usuario o contraseña incorrectos.")
    else:
        form = LoginForm()

    return render(request, "siped/login.html", {"form": form})


@require_POST
@siped_login_required
def logout_view(request):
    """Elimina las credenciales de sesión del usuario actual."""
    username = request.session.get("siped_username")
    _limpiar_sesion_siped(request)
    if username:
        # Un logout explícito corta el polling hasta que el usuario vuelva a
        # iniciar sesión; no se conserva la cookie cifrada.
        SesionSIPED.objects.filter(username_intranet=username).delete()
    # Rota el ID de sesión sin cerrar la sesión de Django del usuario.
    request.session.cycle_key()
    logger.info("Sesión cerrada para usuario: %s", username)
    messages.success(request, "Sesión cerrada exitosamente.")
    return redirect("siped:login")


@siped_login_required
def fragmento_mensajes(request):
    """Renderiza el fragmento HTMX para las notificaciones del sistema."""
    return render(request, "siped/_fragmento_mensajes.html")


@siped_login_required
def indice(request):
    """Renderiza el panel principal con el estado de tareas y expedientes almacenados."""
    usuario = request.session.get("siped_username")

    # La sesión de Django puede sobrevivir a la cookie de la intranet. Antes de
    # mostrar el panel, confirmamos contra el sistema judicial que sigue activa.
    if not _sesion_remota_valida(request):
        _limpiar_sesion_siped(request)
        messages.warning(request, SesionSIPEDExpirada.MENSAJE_POR_DEFECTO)
        return redirect("siped:login")

    lista_pdf = gestor_almacenamiento.listar_documentos_pdf(usuario)
    lista_busquedas = gestor_almacenamiento.listar_reportes_busqueda(usuario)

    # R12: una sola query en lugar de .exists() + .count() por separado
    total_maestro  = Expediente.objects.filter(usuario_asignado=usuario, origen="PRIVADO").count()
    existe_maestro = total_maestro > 0

    existe_movimientos = Movimiento.objects.filter(
        expediente__usuario_asignado=usuario, expediente__origen="PRIVADO"
    ).exists()

    existe_publico_csv = Expediente.objects.filter(
        usuario_asignado=usuario, origen="PUBLICO"
    ).exists()
    expedientes_disponibles = Expediente.objects.filter(usuario_asignado=usuario).values()

    novedades = (
        NovedadSIPED.objects.filter(usuario_asignado=usuario, procesada=True)
        .select_related("expediente")
        .order_by("-detectada_en")
    )
    total_novedades = novedades.filter(vista=False).count()

    # R1: usar constante de módulo en lugar del dict local
    estados_tareas = {}
    for clave_plantilla, nombre_real in MAPA_FASES.items():
        id_tarea = gestor_tareas.obtener_id_tarea(usuario, nombre_real)
        estados_tareas[clave_plantilla] = gestor_tareas.obtener_estado_tarea(
            id_tarea, usuario, nombre_real
        )

    form_busqueda = BusquedaAvanzadaForm()
    form_individual = SincronizacionIndividualForm(usuario=usuario)
    form_publica = DescargaPublicaForm(usuario=usuario)

    context = {
        "archivos_pdf":            lista_pdf,
        "existe_maestro":          existe_maestro,
        "total_maestro":           total_maestro,
        "existe_movimientos":      existe_movimientos,
        "existe_publico_csv":      existe_publico_csv,
        "lista_busquedas":         lista_busquedas,
        "estados_tareas":          estados_tareas,
        "novedades":               novedades[:10],
        "total_novedades":         total_novedades,
        "username":                usuario,
        "expedientes_disponibles": expedientes_disponibles,
        "form_busqueda":           form_busqueda,
        "form_individual":         form_individual,
        "form_publica":            form_publica,
        # R8: catálogo de dependencias por localidad para el selector dinámico
        "dependencias_json": json.dumps(
            {str(k): v for k, v in DEPENDENCIAS_POR_LOCALIDAD.items()}
        ),
    }
    
    return render(request, "siped/index.html", context)


@require_POST
@siped_login_required
def marcar_novedades_vistas(request):
    """Marca como vistas todas las novedades del polling automático."""
    usuario = request.session.get("siped_username")
    NovedadSIPED.objects.filter(usuario_asignado=usuario, vista=False).update(
        vista=True
    )
    messages.success(request, "Novedades marcadas como vistas.")
    return redirect("siped:indice")


@require_POST
@siped_login_required
def iniciar_fase(request, nombre_fase):
    # R1: usar constantes de módulo en lugar del dict local
    if not _sesion_remota_valida(request):
        return _respuesta_sesion_expirada(request)

    if nombre_fase not in MAPA_TAREAS_CELERY:
        messages.error(request, f"Fase '{nombre_fase}' no reconocida.")
        return render(request, "siped/_fragmento_mensajes.html")

    nombre_real  = MAPA_FASES[nombre_fase]
    tarea_celery = MAPA_TAREAS_CELERY[nombre_fase]
    usuario = request.session["siped_username"]
    
    estado_actual = gestor_tareas.obtener_estado_tarea(
        gestor_tareas.obtener_id_tarea(usuario, nombre_real), usuario, nombre_real
    )

    if estado_actual["estado"] in ["PENDING", "STARTED", "RETRY"]:
        messages.warning(request, f"El proceso {nombre_real.replace('_', ' ')} ya está en curso.")
        return render(request, "siped/_fragmento_mensajes.html")

    tarea = tarea_celery.delay(
        cookies=request.session["siped_cookies"], username=usuario
    )
    gestor_tareas.registrar_tarea_iniciada(usuario, nombre_real, tarea.id)

    messages.success(request, f"Proceso {nombre_real.replace('_', ' ')} iniciado.")
    
    response = render(request, "siped/_fragmento_mensajes.html")
    response["HX-Trigger"] = f"actualizar_estado_{nombre_fase}"
    return response


@require_POST
@siped_login_required
def iniciar_descarga_unico(request):
    if not _sesion_remota_valida(request):
        return _respuesta_sesion_expirada(request)

    nro_expediente = request.POST.get("expediente_seleccionado")
    nombre_real = "sincronizacion_individual"
    usuario = request.session["siped_username"]
    nombre_fase = "fase_unico"

    if not nro_expediente:
        messages.warning(request, "Debe seleccionar un expediente.")
        return render(request, "siped/_fragmento_mensajes.html")

    estado_actual = gestor_tareas.obtener_estado_tarea(
        gestor_tareas.obtener_id_tarea(usuario, nombre_real), usuario, nombre_real
    )
    
    if estado_actual["estado"] in ["PENDING", "STARTED", "RETRY"]:
        messages.warning(request, "Actualización en curso. Por favor, aguarde.")
        return render(request, "siped/_fragmento_mensajes.html")

    tarea = sincronizacion_individual_task.delay(
        cookies=request.session["siped_cookies"], nro_expediente=nro_expediente, username=usuario
    )
    gestor_tareas.registrar_tarea_iniciada(usuario, nombre_real, tarea.id)

    messages.success(request, f"Actualizando expediente {nro_expediente} en segundo plano...")
    
    response = render(request, "siped/_fragmento_mensajes.html")
    response["HX-Trigger"] = f"actualizar_estado_{nombre_fase}"
    return response


@require_POST
@siped_login_required
def iniciar_busqueda_avanzada(request):
    if not _sesion_remota_valida(request):
        return _respuesta_sesion_expirada(request)

    nombre_real = "busqueda_avanzada"
    usuario = request.session["siped_username"]
    nombre_fase = "fase_busqueda_avanzada"
    
    estado_actual = gestor_tareas.obtener_estado_tarea(
        gestor_tareas.obtener_id_tarea(usuario, nombre_real), usuario, nombre_real
    )

    if estado_actual["estado"] in ["PENDING", "STARTED", "RETRY"]:
        messages.warning(request, "Búsqueda Avanzada en curso.")
        return render(request, "siped/_fragmento_mensajes.html")

    # R2: validar el formulario antes de encolar — evita pasar csrfmiddlewaretoken
    # y campos inválidos directamente al worker de Celery
    form = BusquedaAvanzadaForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Parámetros de búsqueda inválidos. Revise los campos e intente nuevamente.")
        return render(request, "siped/_fragmento_mensajes.html")

    tarea = busqueda_avanzada_task.delay(
        cookies=request.session["siped_cookies"],
        username=usuario,
        filtros=form.cleaned_data,
    )
    gestor_tareas.registrar_tarea_iniciada(usuario, nombre_real, tarea.id)

    messages.success(request, "Búsqueda iniciada.")
    
    response = render(request, "siped/_fragmento_mensajes.html")
    response["HX-Trigger"] = f"actualizar_estado_{nombre_fase}"
    return response


@require_POST
@siped_login_required
def iniciar_descarga_publico(request):
    if not _sesion_remota_valida(request):
        return _respuesta_sesion_expirada(request)

    link_detalle = request.POST.get("link_detalle_seleccionado")
    nombre_real = "descarga_publica"
    usuario = request.session["siped_username"]
    nombre_fase = "fase_descarga_publica"

    if not link_detalle:
        messages.warning(request, "Debe seleccionar un expediente.")
        return render(request, "siped/_fragmento_mensajes.html")

    estado_actual = gestor_tareas.obtener_estado_tarea(
        gestor_tareas.obtener_id_tarea(usuario, nombre_real), usuario, nombre_real
    )
    
    if estado_actual["estado"] in ["PENDING", "STARTED", "RETRY"]:
        messages.warning(request, "Descarga pública en curso.")
        return render(request, "siped/_fragmento_mensajes.html")

    tarea = descarga_publica_task.delay(
        cookies=request.session["siped_cookies"],
        link_detalle=link_detalle,
        username=usuario,
    )
    gestor_tareas.registrar_tarea_iniciada(usuario, nombre_real, tarea.id)

    messages.success(request, "Iniciando descarga pública...")
    
    response = render(request, "siped/_fragmento_mensajes.html")
    response["HX-Trigger"] = f"actualizar_estado_{nombre_fase}"
    return response


@siped_login_required
def opciones_busqueda_avanzada(request):
    usuario = request.session.get("siped_username")
    expedientes = Expediente.objects.filter(
        usuario_asignado=usuario,
        origen__in=["PUBLICO", "BUSQUEDA_AVANZADA"],
    ).order_by(F("fecha_ult_mov").desc(nulls_last=True))

    opciones = ['<option value="">Seleccione un expediente...</option>']
    for exp in expedientes:
        val = exp.link_detalle
        text = f"{exp.numero_expediente} - {exp.caratula}"
        opciones.append(f'<option value="{val}">{text}</option>')

    return HttpResponse("\n".join(opciones))


@require_POST
@siped_login_required
def resetear_estado(request, nombre_fase):
    usuario = request.session.get("siped_username")
    nombre_real = MAPA_FASES.get(nombre_fase, nombre_fase)

    gestor_tareas.resetear_id_tarea(usuario, nombre_real)

    # Devolver el div del estado vacío con el mismo id para que HTMX
    # lo reemplace y el aviso desaparezca visualmente sin recargar la página
    return HttpResponse(f'<div id="estado_{nombre_fase}"></div>')


@siped_login_required
def fragmento_estado(request, nombre_fase):
    usuario = request.session.get("siped_username")
    # R1: usar constante de módulo en lugar del dict local
    nombre_real = MAPA_FASES.get(nombre_fase, nombre_fase)
    
    estado = gestor_tareas.obtener_estado_tarea(
        gestor_tareas.obtener_id_tarea(usuario, nombre_real), usuario, nombre_real
    )

    if estado.get("sesion_expirada"):
        _limpiar_sesion_siped(request)
        messages.warning(
            request,
            estado.get("resultado") or SesionSIPEDExpirada.MENSAJE_POR_DEFECTO,
        )
        response = render(request, "siped/_fragmento_mensajes.html")
        response["HX-Redirect"] = reverse("siped:login")
        return response

    response = render(request, "siped/_fragmento_estado.html", {"id_fase": nombre_fase, "estado": estado})
    
    if estado.get("recargar"):
        if nombre_fase == "fase_1":
            response["HX-Refresh"] = "true"
        else:
            response["HX-Trigger"] = "actualizar_listas"
        
    return response


@siped_login_required
def fragmento_pdfs(request):
    usuario = request.session.get("siped_username")
    lista_pdf = gestor_almacenamiento.listar_documentos_pdf(usuario)
    return render(request, "siped/_fragmento_pdfs.html", {"archivos_pdf": lista_pdf})


@siped_login_required
def fragmento_busquedas(request):
    usuario = request.session.get("siped_username")
    lista_busquedas = gestor_almacenamiento.listar_reportes_busqueda(usuario)
    return render(request, "siped/_fragmento_busquedas.html", {"lista_busquedas": lista_busquedas})


@siped_login_required
def descargar_archivo(request, tipo, nombre_archivo):
    usuario = request.session.get("siped_username")
    
    if tipo == "documentos":
        doc = DocumentoAdjunto.objects.filter(
            expediente__usuario_asignado=usuario, 
            nombre_original=nombre_archivo
        ).first()
        if doc and doc.archivo:
            return FileResponse(doc.archivo.open(), as_attachment=True, filename=nombre_archivo)
            
    elif tipo == "maestro" and nombre_archivo.startswith("busqueda_"):
        reporte = ReporteBusqueda.objects.filter(
            usuario_asignado=usuario, 
            archivo_csv__endswith=nombre_archivo
        ).first()
        if reporte and reporte.archivo_csv:
            return FileResponse(reporte.archivo_csv.open(), as_attachment=True, filename=nombre_archivo)

    raise Http404("El archivo solicitado no existe o no tiene permisos para acceder.")


@siped_login_required
def validar_descarga_expediente(request):
    """
    Endpoint intermedio de HTMX que verifica si el PDF existe sin recargar la página.
    Si existe, dispara un evento JS para forzar la descarga.
    Si no existe, devuelve una alerta en crudo para ser inyectada en el toast container.
    """
    usuario = request.session.get("siped_username")
    nro_expediente = request.GET.get("expediente_seleccionado")

    if not nro_expediente:
        messages.warning(request, "Debe seleccionar un expediente de la lista.")
        return render(request, "siped/_fragmento_mensajes.html")

    doc = DocumentoAdjunto.objects.filter(
        expediente__usuario_asignado=usuario,
        expediente__numero_expediente=nro_expediente,
        es_consolidado=True
    ).first()

    if not doc or not doc.archivo:
        messages.warning(
            request, 
            f"No hay documento consolidado para el expediente {nro_expediente}. Ejecute la sincronización primero."
        )
        return render(request, "siped/_fragmento_mensajes.html")

    # Si todo es correcto, devolvemos un 200 vacío pero inyectamos la orden de descarga en las cabeceras.
    response = HttpResponse()
    url_descarga = reverse("siped:descargar_por_expediente", args=[nro_expediente])
    response["HX-Trigger"] = json.dumps({"iniciar_descarga_archivo": url_descarga})
    return response


@siped_login_required
def descargar_por_expediente(request, nro_expediente):
    """Descarga directa (sólo accesible si el validador lo permitió o navegando manualmente)."""
    usuario = request.session.get("siped_username")
    
    doc = DocumentoAdjunto.objects.filter(
        expediente__usuario_asignado=usuario,
        expediente__numero_expediente=nro_expediente,
        es_consolidado=True
    ).first()
    
    if not doc or not doc.archivo:
        messages.error(request, "El archivo solicitado ya no se encuentra disponible.")
        return redirect("siped:indice")
        
    return FileResponse(doc.archivo.open(), as_attachment=True, filename=doc.nombre_original)


@siped_login_required
def exportar_expedientes_csv(request):
    usuario = request.session.get("siped_username")
    expedientes = Expediente.objects.filter(usuario_asignado=usuario, origen="PRIVADO").order_by("numero_expediente")

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="lista_expedientes_privados.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Numero Expediente', 'Caratula', 'Dependencia', 
        'Secretaria', 'Estado', 'Ultimo Movimiento', 'Localidad'
    ])

    for exp in expedientes:
        writer.writerow([
            exp.numero_expediente,
            exp.caratula,
            exp.dependencia,
            exp.secretaria,
            exp.estado,
            formatear_fecha_intranet(exp.fecha_ult_mov),
            exp.localidad
        ])

    return response


@siped_login_required
def exportar_expedientes_publicos_csv(request):
    """Exporta como CSV todos los expedientes de origen PUBLICO y BUSQUEDA_AVANZADA."""
    usuario = request.session.get("siped_username")
    expedientes = Expediente.objects.filter(
        usuario_asignado=usuario,
        origen__in=["PUBLICO", "BUSQUEDA_AVANZADA"],
    ).order_by("origen", "numero_expediente")

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="expedientes_publicos.csv"'

    writer = csv.writer(response)
    writer.writerow([
        "Numero Expediente", "Caratula", "Localidad",
        "Dependencia", "Secretaria", "Fecha Alta", "Origen",
    ])
    for exp in expedientes:
        writer.writerow([
            exp.numero_expediente,
            exp.caratula,
            exp.localidad,
            exp.dependencia,
            exp.secretaria,
            formatear_fecha_intranet(exp.fecha_ult_mov),
            exp.origen,
        ])

    return response


_COLUMNAS_MOVIMIENTOS_CSV = [
    "Expediente",
    "Codigo Escrito",
    "Fecha Presentacion",
    "Tipo",
    "Estado",
    "Generado Por",
    "Descripcion",
    "Fecha Firma",
    "Fecha Publicacion",
    "Link PDF",
]


def _fila_movimiento_csv(mov: Movimiento) -> list[str]:
    """Devuelve una fila de movimiento con las columnas reales de la intranet."""
    return [
        mov.expediente.numero_expediente,
        mov.codigo_escrito or "",
        formatear_fecha_hora_intranet(mov.fecha_presentacion),
        mov.tipo or "",
        mov.estado or "",
        mov.generado_por or "",
        mov.descripcion or "",
        formatear_fecha_hora_intranet(mov.fecha_firma),
        formatear_fecha_hora_intranet(mov.fecha_publicacion),
        mov.link_escrito or "",
    ]


@siped_login_required
def exportar_movimientos_todos(request):
    usuario = request.session.get("siped_username")
    movimientos = (
        Movimiento.objects.filter(
            expediente__usuario_asignado=usuario,
            expediente__origen="PRIVADO",
        )
        .select_related("expediente")
        .order_by("expediente__numero_expediente", "-id")
    )

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        'attachment; filename="historial_movimientos_completo.csv"'
    )

    writer = csv.writer(response)
    writer.writerow(_COLUMNAS_MOVIMIENTOS_CSV)

    for mov in movimientos:
        writer.writerow(_fila_movimiento_csv(mov))

    return response


@siped_login_required
def exportar_movimientos_individual(request):
    usuario = request.session.get("siped_username")
    nro_exp = request.GET.get("exp")

    if not nro_exp:
        messages.warning(request, "Debe especificar un expediente.")
        return redirect("siped:indice")

    movimientos = Movimiento.objects.filter(
        expediente__usuario_asignado=usuario,
        expediente__numero_expediente=nro_exp,
    ).order_by("-id")

    nombre_seguro = nro_exp.replace("/", "-").replace("\\", "-")
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="movimientos_{nombre_seguro}.csv"'
    )

    writer = csv.writer(response)
    writer.writerow(_COLUMNAS_MOVIMIENTOS_CSV)

    for mov in movimientos:
        writer.writerow(_fila_movimiento_csv(mov))

    return response


@siped_login_required
def dashboard(request):
    """
    Vista de resumen ejecutivo: lista todos los expedientes privados del usuario
    con sus movimientos y documentos adjuntos, organizados en un acordeón.
    Ordenados por actividad más reciente primero.
    """
    from django.db.models import Max

    usuario = request.session.get("siped_username")
    expedientes = (
        Expediente.objects.filter(usuario_asignado=usuario, origen="PRIVADO")
        .prefetch_related("movimientos__documentos")
        .annotate(ultimo_movimiento_id=Max("movimientos__id"))
        .order_by("-ultimo_movimiento_id")
    )

    novedades = (
        NovedadSIPED.objects.filter(usuario_asignado=usuario, procesada=True)
        .select_related("expediente")
        .order_by("-detectada_en")
    )
    return render(request, "siped/dashboard.html", {
        "expedientes": expedientes,
        "novedades": novedades[:10],
        "total_novedades": novedades.filter(vista=False).count(),
        "username": usuario,
    })


from django.conf import settings

@siped_login_required
def debug_expediente(request, nro_expediente):
    # R10: solo accesible en entornos de desarrollo o para usuarios staff
    if not settings.DEBUG and not request.user.is_staff:
        raise Http404
    usuario = request.session.get("siped_username")
    try:
        exp = Expediente.objects.get(usuario_asignado=usuario, numero_expediente=nro_expediente)
        movs = exp.movimientos.all().order_by("-id")[:15]
        
        html = "<div style='font-family: sans-serif; padding: 20px;'>"
        html += f"<h2>Diagnóstico de Expediente: {nro_expediente}</h2>"
        html += f"<p><strong>Total de movimientos registrados en la BD:</strong> {exp.movimientos.count()}</p>"
        html += "<h3>Últimos 15 movimientos:</h3>"
        html += "<table border='1' cellpadding='8' style='border-collapse: collapse; text-align: left;'>"
        html += (
            "<tr style='background-color: #f2f2f2;'>"
            "<th>Código</th><th>Fecha</th><th>Tiene Link PDF</th>"
            "<th>Tipo</th><th>Estado</th><th>Generado por</th>"
            "<th>Descripción</th></tr>"
        )

        for m in movs:
            tiene_link = "SÍ" if m.link_escrito else "NO"
            color = "green" if tiene_link == "SÍ" else "red"
            fecha = (
                m.fecha_presentacion
                or m.fecha_firma
                or m.fecha_publicacion
                or "sin fecha"
            )
            html += (
                f"<tr><td>{m.codigo_escrito}</td><td>{fecha}</td>"
                f"<td style='color: {color}; font-weight: bold;'>{tiene_link}</td>"
                f"<td>{m.tipo}</td><td>{m.estado}</td>"
                f"<td>{m.generado_por}</td><td>{m.descripcion}</td></tr>"
            )

        html += "</table></div>"
        return HttpResponse(html)
        
    except Expediente.DoesNotExist:
        return HttpResponse(f"Expediente '{nro_expediente}' no encontrado en la base de datos para el usuario '{usuario}'.")