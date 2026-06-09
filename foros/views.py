"""Vistas transversales al proyecto Foros (no pertenecen a ninguna app específica)."""

from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.shortcuts import render

from foros.siped.models import Expediente


@login_required
def dashboard_view(request):
    """
    Dashboard general del estudio. Agrega información de todas las apps
    del proyecto en una vista unificada de estado operativo.

    Actualmente muestra:
    - Expedientes privados de SIPED más recientemente actualizados.

    A medida que se agreguen apps (Agenda, Recordatorios, Contactos),
    este view incorporará sus datos al contexto.
    """
    # Expedientes SIPED: los 8 con actividad más reciente
    try:
        expedientes_recientes = (
            Expediente.objects.filter(
                usuario_asignado=request.user.username,
                origen="PRIVADO",
            )
            .annotate(ultimo_mov=Max("movimientos__id"))
            .order_by("-ultimo_mov")[:8]
        )
        total_expedientes = Expediente.objects.filter(
            usuario_asignado=request.user.username,
            origen="PRIVADO",
        ).count()
    except Exception:
        expedientes_recientes = []
        total_expedientes = 0

    context = {
        "expedientes_recientes": expedientes_recientes,
        "total_expedientes":     total_expedientes,
        "recordatorios":         [],   # placeholder — app Recordatorios pendiente
    }
    return render(request, "pages/dashboard.html", context)
