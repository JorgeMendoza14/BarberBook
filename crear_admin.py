
from getpass import getpass
from werkzeug.security import generate_password_hash
from mysql.connector import IntegrityError

from config import obtener_conexion

conexion = None
cursor = None

try:
    print("=== Crear administrador BarberBook ===")

    nombre = input("Nombre: ").strip()
    apellido = input("Apellido: ").strip()
    correo = input("Correo: ").strip().lower()
    contrasena = getpass("Contraseña: ")

    if not all([nombre, apellido, correo]):
        raise ValueError("Todos los campos son obligatorios.")

    if len(contrasena) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres.")

    conexion = obtener_conexion()
    cursor = conexion.cursor()

    cursor.execute("""
        INSERT INTO usuarios
        (nombre, apellido, correo, contrasena, rol)
        VALUES (%s, %s, %s, %s, 'administrador')
    """, (
        nombre,
        apellido,
        correo,
        generate_password_hash(contrasena)
    ))

    conexion.commit()
    print("Administrador creado correctamente.")

except IntegrityError:
    if conexion:
        conexion.rollback()
    print("Ese correo ya está registrado.")

except (ValueError, Exception) as error:
    if conexion:
        conexion.rollback()
    print("No se pudo crear el administrador:", error)

finally:
    if cursor:
        cursor.close()
    if conexion and conexion.is_connected():
        conexion.close()
