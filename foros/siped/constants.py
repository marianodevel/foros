"""Configuraciones globales y constantes de la aplicación SIPED."""

from django.conf import settings
import os

# Rutas base de SIPED
BASE_URL = "https://intranet.jussantacruz.gob.ar"
LOGIN_URL = f"{BASE_URL}/servicios/controli2.php"
LISTA_EXPEDIENTES_URL = f"{BASE_URL}/siped/expediente/buscar/submit_buscar_abogado.php"
AJAX_MOVIMIENTOS_URL = f"{BASE_URL}/siped/expediente/buscar/ver_mas_escritosAjax.php"

# Tiempo máximo para comprobar si la sesión de la intranet sigue viva.
VERIFICACION_TIMEOUT = 15

# Polling automático de cambios en la lista maestra.
POLLING_INTERVALO_MINUTOS = 30
POLLING_JITTER_MAXIMO = 300  # segundos de dispersión al encolar cada usuario
POLLING_BLOQUEO_MINUTOS = 25  # duración del bloqueo por usuario
POLLING_MAX_EXPEDIENTES = 50  # expedientes con movimientos a refrescar por corrida
POLLING_ESPERA_MINIMA = 0.5
POLLING_ESPERA_MAXIMA = 1.5

# Directorios de salida (Utilizamos el MEDIA_ROOT configurado por cookiecutter-django)
# Si no está en MEDIA_ROOT, podemos usar el directorio ROOT del proyecto.
DATA_ROOT_DIR = os.path.join(str(settings.APPS_DIR), "siped", "datos_usuarios")
LISTA_EXPEDIENTES_CSV = "expedientes_completos.csv"
MOVIMIENTOS_OUTPUT_DIR = "movimientos_expedientes"
DOCUMENTOS_OUTPUT_DIR = "documentos_expedientes"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange=vb3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
}