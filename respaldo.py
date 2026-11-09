# Genera un respaldo completo (estructura + datos) de la base de datos
# usando mysqldump. El archivo se guarda en la carpeta respaldos/
#
# Uso:  python respaldo.py
#
# Si Windows no encuentra mysqldump, agrega en el archivo .env la ruta, por ejemplo:
#   MYSQLDUMP_PATH=C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe
#   (con XAMPP suele ser C:\xampp\mysql\bin\mysqldump.exe)

import os
import subprocess
import tempfile
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

mysqldump = os.getenv("MYSQLDUMP_PATH", "mysqldump")
base_datos = os.getenv("DB_NAME", "barberbook")

carpeta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "respaldos")
os.makedirs(carpeta, exist_ok=True)

fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
archivo = os.path.join(carpeta, f"respaldo_{base_datos}_{fecha}.sql")

# La contraseña se escribe en un archivo temporal de opciones para que
# no aparezca en el comando ni en la lista de procesos del sistema.
opciones = tempfile.NamedTemporaryFile(
    "w", suffix=".cnf", delete=False, encoding="utf-8"
)
opciones.write("[client]\n")
opciones.write(f'password="{os.getenv("DB_PASSWORD", "")}"\n')
opciones.close()

comando = [
    mysqldump,
    f"--defaults-extra-file={opciones.name}",
    "--host", os.getenv("DB_HOST", "localhost"),
    "--port", os.getenv("DB_PORT", "3306"),
    "--user", os.getenv("DB_USER", "root"),
    "--routines",
    "--triggers",
    "--databases", base_datos,
    "--result-file", archivo,
]

try:
    subprocess.run(comando, check=True)
    print(f"Respaldo creado correctamente: {archivo}")
except FileNotFoundError:
    print("No se encontró mysqldump. Agrega MYSQLDUMP_PATH en el archivo .env")
except subprocess.CalledProcessError:
    print("No se pudo crear el respaldo. Revisa los datos de conexión del .env")
finally:
    os.remove(opciones.name)
