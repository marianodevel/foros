"""Enrutamiento de la aplicación SIPED."""

from django.urls import path

from . import views

app_name = "siped"

urlpatterns = [
    path("", views.indice, name="indice"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    
    # Endpoints de ejecución de tareas (AJAX/HTMX)
    path("iniciar/<str:nombre_fase>/", views.iniciar_fase, name="iniciar_fase"),
    path("iniciar_descarga_unico/", views.iniciar_descarga_unico, name="iniciar_descarga_unico"),
    path("iniciar_busqueda_avanzada/", views.iniciar_busqueda_avanzada, name="iniciar_busqueda_avanzada"),
    path("iniciar_descarga_publico/", views.iniciar_descarga_publico, name="iniciar_descarga_publico"),
    
    # Novedades del polling automático
    path("novedades/marcar_vistas/", views.marcar_novedades_vistas, name="marcar_novedades_vistas"),

    # Endpoints de estado y fragmentos (AJAX/HTMX)
    path("resetear_estado/<str:nombre_fase>/", views.resetear_estado, name="resetear_estado"),
    path("fragmento/estado/<str:nombre_fase>/", views.fragmento_estado, name="fragmento_estado"),
    path("fragmento/mensajes/", views.fragmento_mensajes, name="fragmento_mensajes"),
    path("fragmento/pdfs/", views.fragmento_pdfs, name="fragmento_pdfs"),
    path("fragmento/busquedas/", views.fragmento_busquedas, name="fragmento_busquedas"),
    path("fragmento/opciones_busqueda_avanzada/", views.opciones_busqueda_avanzada, name="opciones_busqueda_avanzada"),
    
    # Endpoints de descarga de archivos y reportes CSV
    path("descargar/<str:tipo>/<str:nombre_archivo>/", views.descargar_archivo, name="descargar_archivo"),
    path("descargar_por_expediente/<path:nro_expediente>/", views.descargar_por_expediente, name="descargar_por_expediente"),
    path("exportar_maestro/", views.exportar_expedientes_csv, name="exportar_maestro"),
    path("exportar_publicos/", views.exportar_expedientes_publicos_csv, name="exportar_publicos"),
    path("exportar_movimientos_todos/", views.exportar_movimientos_todos, name="exportar_movimientos_todos"),
    path("exportar_movimientos_individual/", views.exportar_movimientos_individual, name="exportar_movimientos_individual"),
    
    # Debug
    path("debug/<path:nro_expediente>/", views.debug_expediente, name="debug_expediente"),

    # PWA móvil
    path("m/login/", views.movel_login, name="movel_login"),
    path("m/logout/", views.movel_logout, name="movel_logout"),
    path("m/", views.movel_index, name="movel_index"),
    path("m/expedientes/", views.movel_dashboard, name="movel_dashboard"),
    path("m/novedades/", views.movel_novedades, name="movel_novedades"),
    path(
        "m/novedades/marcar_vistas/",
        views.movel_marcar_novedades,
        name="movel_marcar_novedades",
    ),
    path("m/sincronizar/", views.movel_sincronizar, name="movel_sincronizar"),
    path(
        "m/fragmento/estado/<str:nombre_fase>/",
        views.movel_fragmento_fase,
        name="movel_fragmento_fase",
    ),
    path(
        "m/iniciar/<str:nombre_fase>/",
        views.iniciar_fase,
        name="movel_iniciar_fase",
    ),
    path("m/perfil/", views.movel_perfil, name="movel_perfil"),
    path("m/sesion/", views.movel_sesion, name="movel_sesion"),
    path(
        "m/push/suscribir/",
        views.movel_push_suscribir,
        name="movel_push_suscribir",
    ),
    path(
        "m/push/desuscribir/",
        views.movel_push_desuscribir,
        name="movel_push_desuscribir",
    ),
    path("m/push/test/", views.movel_push_test, name="movel_push_test"),
    path(
        "manifest.webmanifest",
        views.movel_manifest,
        name="movel_manifest",
    ),
    path("sw.js", views.movel_service_worker, name="movel_service_worker"),
]
