
from config import obtener_conexion

conexion = None
cursor = None

try:
    conexion = obtener_conexion()
    print("Conexion exitosa con MySQL")

    cursor = conexion.cursor()
    cursor.execute("SHOW TABLES")

    tablas = cursor.fetchall()

    print("\nTablas de BarberBook:")
    for tabla in tablas:
        print("-", tabla[0])

    print(f"\nTotal de tablas: {len(tablas)}")

except Exception as error:
    print("Error de conexion:", error)

finally:
    if cursor is not None:
        cursor.close()

    if conexion is not None and conexion.is_connected():
        conexion.close()
