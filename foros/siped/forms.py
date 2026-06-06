"""Formularios y validadores para la aplicación SIPED."""

from django import forms

from .catalogos.abogados import ABOGADOS
from .catalogos.localidades import LOCALIDADES
from .catalogos.tipos_juicio import TIPOS_JUICIO
from .models import Expediente


def _obtener_opciones_catalogo(catalogo: dict, texto_vacio: str = "Seleccione...") -> list:
    """Convierte un diccionario de catálogo en una lista de tuplas para ChoiceField."""
    opciones = [("", texto_vacio)]
    for clave, valor in catalogo.items():
        opciones.append((str(clave), str(valor)))
    return opciones


class LoginForm(forms.Form):
    """Formulario de autenticación contra el sistema SIPED."""

    username = forms.CharField(
        label="Usuario (Intranet)",
        max_length=100,
        widget=forms.TextInput(attrs={"class": "form-control", "autofocus": True}),
    )
    password = forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )


class SincronizacionIndividualForm(forms.Form):
    """Formulario para seleccionar un expediente privado y actualizar sus movimientos."""

    expediente_seleccionado = forms.ModelChoiceField(
        queryset=Expediente.objects.none(),
        to_field_name="numero_expediente",
        empty_label="Seleccione un expediente...",
        widget=forms.Select(attrs={"class": "form-select", "required": True}),
    )

    def __init__(self, *args, **kwargs):
        usuario = kwargs.pop("usuario", None)
        super().__init__(*args, **kwargs)
        if usuario:
            self.fields["expediente_seleccionado"].queryset = Expediente.objects.filter(
                usuario_asignado=usuario, origen="PRIVADO"
            )
        
        self.fields["expediente_seleccionado"].label_from_instance = (
            lambda obj: f"{obj.numero_expediente} - {obj.caratula}"
        )


class DescargaPublicaForm(forms.Form):
    """Formulario para seleccionar un expediente público y descargar sus PDFs."""

    link_detalle_seleccionado = forms.ModelChoiceField(
        queryset=Expediente.objects.none(),
        to_field_name="link_detalle",
        empty_label="Seleccione un expediente público...",
        widget=forms.Select(attrs={"class": "form-select", "required": True}),
    )

    def __init__(self, *args, **kwargs):
        usuario = kwargs.pop("usuario", None)
        super().__init__(*args, **kwargs)
        if usuario:
            self.fields["link_detalle_seleccionado"].queryset = Expediente.objects.filter(
                usuario_asignado=usuario, origen__in=["PUBLICO", "BUSQUEDA_AVANZADA"]
            )
            
        self.fields["link_detalle_seleccionado"].label_from_instance = (
            lambda obj: f"{obj.numero_expediente} - {obj.caratula}"
        )


class BusquedaAvanzadaForm(forms.Form):
    """Formulario integral para la búsqueda parametrizada en el sistema judicial."""

    # --- Bloque: Expediente ---
    nro_expediente = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "Ej: 12345"}),
    )
    anio = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "Ej: 2023"}),
    )
    cmb_documental = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "Inc."}),
    )

    # --- Bloque: Carátula ---
    texto = forms.CharField(
        label="Carátula",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm"}),
    )

    # --- Bloque: Abogado ---
    abogado = forms.ChoiceField(
        choices=_obtener_opciones_catalogo(ABOGADOS, "Todos los abogados"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )

    # --- Bloque: Justiciable ---
    dnij = forms.CharField(
        label="DNI",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm"}),
    )
    apellidoj = forms.CharField(
        label="Apellido",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm"}),
    )
    nombresj = forms.CharField(
        label="Nombre",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm"}),
    )

    # --- Bloque: Radicación ---
    id_localidad = forms.ChoiceField(
        label="Localidad",
        choices=_obtener_opciones_catalogo(LOCALIDADES, "Todas las localidades"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select form-select-sm", "id": "id_localidad"}),
    )
    
    id_dependencia = forms.ChoiceField(
        label="Dependencia",
        choices=[("", "Todas las dependencias")],
        required=False,
        widget=forms.Select(attrs={"class": "form-select form-select-sm", "id": "id_dependencia"}),
    )

    # --- Bloque: Tipo de Juicio ---
    juicio = forms.ChoiceField(
        label="Tipo de Juicio",
        choices=_obtener_opciones_catalogo(TIPOS_JUICIO, "Todos los tipos"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )

    # --- Bloque: Rango de Fechas (Desde) ---
    fecha_alta_dia_desde = forms.ChoiceField(
        choices=[("0", "Día")] + [(str(i), str(i).zfill(2)) for i in range(1, 32)],
        required=False,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    fecha_alta_mes_desde = forms.ChoiceField(
        choices=[("", "Mes")] + [(str(i), str(i).zfill(2)) for i in range(1, 13)],
        required=False,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    fecha_alta_anio_desde = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "Año"}),
    )

    # --- Bloque: Rango de Fechas (Hasta) ---
    fecha_alta_dia_hasta = forms.ChoiceField(
        choices=[("0", "Día")] + [(str(i), str(i).zfill(2)) for i in range(1, 32)],
        required=False,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    fecha_alta_mes_hasta = forms.ChoiceField(
        choices=[("", "Mes")] + [(str(i), str(i).zfill(2)) for i in range(1, 13)],
        required=False,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    fecha_alta_anio_hasta = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "Año"}),
    )

    # --- Bloque: Filtros Adicionales ---
    filtro_archivados = forms.ChoiceField(
        choices=[
            ("todos", "Todos"),
            ("no_archivados", "En Letra (No Archivados)"),
            ("archivados", "Archivados"),
        ],
        required=False,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )

    organismo_origen = forms.ChoiceField(
        choices=[
            ("1", "Solo mis expedientes (Privado)"),
            ("2", "Acceso Público (Todos)"),
        ],
        required=False,
        initial="2",
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )

    # --- Bloque: Ordenamiento ---
    ordenar_por = forms.ChoiceField(
        choices=[
            ("expediente", "Número de Expediente"),
            ("fecha_alta", "Fecha de Alta"),
            ("caratula", "Carátula"),
        ],
        required=False,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )

    orden = forms.ChoiceField(
        choices=[("DESC", "Descendente"), ("ASC", "Ascendente")],
        required=False,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )