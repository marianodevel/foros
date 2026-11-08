# Guía para agentes

## Stack

Este proyecto es una aplicación **cookiecutter-django** y se ejecuta con **Docker**. No asumas un virtualenv del host ni dependencias instaladas globalmente.

Servicios definidos en `docker-compose.local.yml`: `django`, `postgres`, `redis`, `mailpit`, `celeryworker`, `celerybeat`, `flower`.

## Tests: siempre con Docker

Ejecutá los tests a través del stack de Docker, no con un Python del host:

```bash
docker compose -f docker-compose.local.yml run --rm django pytest
docker compose -f docker-compose.local.yml run --rm django pytest foros/siped/tests/
docker compose -f docker-compose.local.yml run --rm django pytest -k sesion -x
docker compose -f docker-compose.local.yml run --rm django python ./manage.py check
docker compose -f docker-compose.local.yml run --rm django python ./manage.py makemigrations --check --dry-run
```

Si `just` está instalado en el host, los atajos equivalentes son `just pytest <args>` y `just manage <args>`. Si no lo está, usá directamente `docker compose`.

La imagen se construye con `just build` y el stack se levanta con `just up` (`just down` para bajarlo). Los tests usan la base PostgreSQL del compose, no SQLite.

### Por qué

- La configuración local depende de las variables de `.envs/.local/` que `docker compose` inyecta vía `env_file`.
- El Python del host puede tener problemas propios (por ejemplo, `pyexpat` roto por `libexpat`) que no existen dentro de la imagen.
- El proyecto es cookiecutter-django: los comandos y settings (`config.settings.local`, `config.settings.test`) están pensados para ese flujo.

## Convenciones

- Ejecutá `ruff` (configurado en `pyproject.toml`) antes de commitear.
- Los mensajes y la UI del dominio SIPED están en español; mantené ese idioma.
- Ante cambios de modelos, verificá con `just manage makemigrations --check --dry-run`.

## SIPED

- La validez de la sesión la decide la respuesta de la intranet, no la mera presencia de `siped_cookies`: una cookie vencida devuelve HTTP 200 con el formulario de login.
- Las excepciones de dominio viven en `foros/siped/exceptions.py` (`SesionSIPEDExpirada`, `PaginaInesperada`) y deben propagarse hasta el estado de Celery, no silenciarse.
- Los tests de la integración están en `foros/siped/tests/`.
