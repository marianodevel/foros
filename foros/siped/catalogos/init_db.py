"""
Script de inicialización de la base de datos.
Crea las tablas y esquemas definidos en los modelos utilizando el contexto 
de la aplicación Flask. 

Nota operativa: Se requiere el uso de 'uv' para la gestión del entorno virtual 
y dependencias. Ejecutar mediante: 'uv run python script/init_db.py'.
"""

import sys
import os

# Incorpora el directorio raíz del proyecto al PYTHONPATH para resolver módulos
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from extensions import db
import models  # Se importa para que SQLAlchemy registre los metadatos de las clases
from logger import get_logger

logger = get_logger(__name__)


def inicializar_base_datos() -> None:
    """
    Genera el esquema de la base de datos a partir de los modelos registrados.
    Establece el contexto de la aplicación necesario para la operación del ORM.
    """
    logger.info("Iniciando configuración y creación de la base de datos local.")
    
    with app.app_context():
        try:
            db.create_all()
            logger.info("Esquema de base de datos instanciado correctamente.")
        except Exception as e:
            logger.error(f"Excepción crítica al intentar generar las tablas: {e}", exc_info=True)
            sys.exit(1)


if __name__ == "__main__":
    inicializar_base_datos()