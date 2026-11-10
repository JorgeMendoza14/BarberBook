
import os
import secrets
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request,
    redirect, url_for, flash, session, abort, jsonify
)
from werkzeug.exceptions import HTTPException
from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from config import obtener_conexion

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

if not app.secret_key:
    raise RuntimeError("Configura SECRET_KEY en el archivo .env")


# Proteger las paginas privadas
def login_requerido(funcion):
    @wraps(funcion)
    def decorador(*args, **kwargs):
        if "id_usuario" not in session:
            flash("Debes iniciar sesion.", "error")
            return redirect(url_for("login"))
        return funcion(*args, **kwargs)
    return decorador


def barbero_requerido(funcion):
    @wraps(funcion)
    @login_requerido
    def decorador(*args, **kwargs):
        if session.get("rol") != "barbero":
            abort(403)
        return funcion(*args, **kwargs)
    return decorador


def cliente_requerido(funcion):
    @wraps(funcion)
    @login_requerido
    def decorador(*args, **kwargs):
        if session.get("rol") != "cliente":
            abort(403)
        return funcion(*args, **kwargs)
    return decorador


def obtener_token_csrf():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def validar_token_csrf():
    token_sesion = session.get("_csrf_token")
    token_formulario = request.form.get("csrf_token", "")
    if (
        not token_sesion
        or not token_formulario
        or not secrets.compare_digest(token_sesion, token_formulario)
    ):
        abort(400, description="Token CSRF inválido o ausente.")


def obtener_id_barbero(cursor):
    cursor.execute(
        """
        SELECT id_barbero
        FROM barberos
        WHERE id_usuario = %s AND activo = TRUE
        """,
        (session["id_usuario"],)
    )
    barbero = cursor.fetchone()
    return barbero["id_barbero"] if barbero else None


@app.context_processor
def exponer_token_csrf():
    return {"csrf_token": obtener_token_csrf}


# Barberos y servicios activos para llenar los <select> del formulario
def obtener_opciones_cita(cursor):
    cursor.execute(
        """
        SELECT b.id_barbero, CONCAT(u.nombre, ' ', u.apellido) AS nombre,
               b.especialidad
        FROM barberos b
        INNER JOIN usuarios u ON u.id_usuario = b.id_usuario
        WHERE b.activo = TRUE
        ORDER BY u.nombre, u.apellido
        """
    )
    barberos = cursor.fetchall()

    cursor.execute(
        """
        SELECT id_servicio, nombre, precio, duracion_minutos
        FROM servicios
        WHERE activo = TRUE
        ORDER BY nombre
        """
    )
    servicios = cursor.fetchall()
    return barberos, servicios


# Revisa que la cita se pueda guardar. Devuelve (datos, error).
# id_cita_actual se usa al editar, para no chocar la cita consigo misma.
def validar_datos_cita(cursor, formulario, id_cita_actual=None):
    observaciones = formulario.get("observaciones", "").strip()

    try:
        id_barbero = int(formulario.get("id_barbero", ""))
        id_servicio = int(formulario.get("id_servicio", ""))
    except ValueError:
        return None, "Selecciona un barbero y un servicio."

    try:
        fecha = date.fromisoformat(formulario.get("fecha", ""))
        hora_inicio = datetime.strptime(
            formulario.get("hora", ""), "%H:%M"
        ).time()
    except ValueError:
        return None, "Ingresa una fecha y una hora válidas."

    inicio = datetime.combine(fecha, hora_inicio)
    if inicio <= datetime.now():
        return None, "La cita debe ser en una fecha y hora futura."

    # El servicio debe existir y estar activo
    cursor.execute(
        """
        SELECT duracion_minutos FROM servicios
        WHERE id_servicio = %s AND activo = TRUE
        """,
        (id_servicio,)
    )
    servicio = cursor.fetchone()
    if not servicio:
        return None, "El servicio seleccionado no está disponible."

    # El barbero debe existir y estar activo
    cursor.execute(
        "SELECT id_barbero FROM barberos WHERE id_barbero = %s AND activo = TRUE",
        (id_barbero,)
    )
    if not cursor.fetchone():
        return None, "El barbero seleccionado no está disponible."

    # La hora de fin depende de cuanto dura el servicio
    fin = inicio + timedelta(minutes=servicio["duracion_minutos"])
    if fin.date() != fecha:
        return None, "La cita debe terminar el mismo día."
    hora_fin = fin.time()

    # La cita debe estar dentro del horario de trabajo del barbero
    # (1 = lunes ... 7 = domingo)
    cursor.execute(
        """
        SELECT id_horario FROM horarios
        WHERE id_barbero = %s AND dia_semana = %s
          AND hora_inicio <= %s AND hora_fin >= %s
        """,
        (id_barbero, fecha.isoweekday(), hora_inicio, hora_fin)
    )
    if not cursor.fetchone():
        return None, "El barbero no atiende en ese día u horario."

    # El barbero no debe tener un bloqueo en ese horario
    cursor.execute(
        """
        SELECT id_bloqueo FROM bloqueos_horario
        WHERE id_barbero = %s AND fecha = %s
          AND hora_inicio < %s AND hora_fin > %s
        """,
        (id_barbero, fecha, hora_fin, hora_inicio)
    )
    if cursor.fetchone():
        return None, "El barbero no está disponible en ese horario."

    # No debe cruzarse con otra cita pendiente o confirmada del barbero
    cursor.execute(
        """
        SELECT id_cita FROM citas
        WHERE id_barbero = %s AND fecha = %s
          AND estado IN ('pendiente', 'confirmada')
          AND hora_inicio < %s AND hora_fin > %s
          AND id_cita <> %s
        """,
        (id_barbero, fecha, hora_fin, hora_inicio, id_cita_actual or 0)
    )
    if cursor.fetchone():
        return None, "Ese horario ya está ocupado. Elige otra hora."

    datos = (
        id_barbero, id_servicio, fecha,
        hora_inicio, hora_fin, observaciones or None
    )
    return datos, None


DIAS_SEMANA = {
    1: "Lunes", 2: "Martes", 3: "Miércoles", 4: "Jueves",
    5: "Viernes", 6: "Sábado", 7: "Domingo"
}

# Cada cuantos minutos se ofrece una hora para reservar
INTERVALO_MINUTOS = 30


# MySQL devuelve las columnas TIME como timedelta.
# Esta funcion lo pasa a minutos desde las 00:00 para poder comparar.
def a_minutos(valor):
    if isinstance(valor, timedelta):
        return int(valor.total_seconds() // 60)
    return valor.hour * 60 + valor.minute


def minutos_a_texto(minutos):
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


# Horario semanal de un barbero, listo para mostrar en pantalla
def obtener_horario_semana(cursor, id_barbero):
    cursor.execute(
        """
        SELECT dia_semana, hora_inicio, hora_fin
        FROM horarios
        WHERE id_barbero = %s
        ORDER BY dia_semana, hora_inicio
        """,
        (id_barbero,)
    )
    return [
        {
            "dia": DIAS_SEMANA[fila["dia_semana"]],
            "inicio": minutos_a_texto(a_minutos(fila["hora_inicio"])),
            "fin": minutos_a_texto(a_minutos(fila["hora_fin"])),
        }
        for fila in cursor.fetchall()
    ]


# Calcula las horas libres de un barbero en una fecha:
# toma su horario de ese dia y quita las horas que chocan con
# otras citas o con bloqueos.
def calcular_horas_disponibles(cursor, id_barbero, fecha, duracion,
                               id_cita_actual=None):
    cursor.execute(
        """
        SELECT hora_inicio, hora_fin FROM horarios
        WHERE id_barbero = %s AND dia_semana = %s
        ORDER BY hora_inicio
        """,
        (id_barbero, fecha.isoweekday())
    )
    turnos = cursor.fetchall()

    # Horas ocupadas: citas pendientes/confirmadas y bloqueos
    cursor.execute(
        """
        SELECT hora_inicio, hora_fin FROM citas
        WHERE id_barbero = %s AND fecha = %s
          AND estado IN ('pendiente', 'confirmada')
          AND id_cita <> %s
        UNION ALL
        SELECT hora_inicio, hora_fin FROM bloqueos_horario
        WHERE id_barbero = %s AND fecha = %s
        """,
        (id_barbero, fecha, id_cita_actual or 0, id_barbero, fecha)
    )
    ocupadas = [
        (a_minutos(fila["hora_inicio"]), a_minutos(fila["hora_fin"]))
        for fila in cursor.fetchall()
    ]

    ahora = datetime.now()
    minimo = -1
    if fecha == ahora.date():
        minimo = ahora.hour * 60 + ahora.minute
    elif fecha < ahora.date():
        return []

    horas = []
    for turno in turnos:
        inicio = a_minutos(turno["hora_inicio"])
        fin = a_minutos(turno["hora_fin"])
        while inicio + duracion <= fin:
            termina = inicio + duracion
            libre = all(
                not (inicio < o_fin and termina > o_inicio)
                for o_inicio, o_fin in ocupadas
            )
            if libre and inicio > minimo:
                horas.append(minutos_a_texto(inicio))
            inicio += INTERVALO_MINUTOS
    return horas


# Pagina principal
@app.route("/")
def inicio():
    servicios = []
    barberos = []
    conexion = None
    cursor = None

    # Los servicios y barberos de la portada se leen de la base de datos
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT nombre, descripcion, precio, duracion_minutos
            FROM servicios
            WHERE activo = TRUE
            ORDER BY precio
            """
        )
        servicios = cursor.fetchall()

        cursor.execute(
            """
            SELECT b.id_barbero, u.nombre, u.apellido,
                   b.especialidad, b.descripcion
            FROM barberos b
            INNER JOIN usuarios u ON u.id_usuario = b.id_usuario
            WHERE b.activo = TRUE
            ORDER BY u.nombre
            """
        )
        barberos = cursor.fetchall()
        for barbero in barberos:
            barbero["horario"] = obtener_horario_semana(
                cursor, barbero["id_barbero"]
            )
    except Exception:
        app.logger.exception("Error al cargar los datos de la portada")
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()

    return render_template(
        "index.html", servicios=servicios, barberos=barberos
    )


# Registro de clientes
@app.route("/registro", methods=["GET", "POST"])
def registro():

    if request.method == "POST":
        validar_token_csrf()
        nombre = request.form.get("nombre", "").strip()
        apellido = request.form.get("apellido", "").strip()
        correo = request.form.get("correo", "").strip().lower()
        telefono = request.form.get("telefono", "").strip()
        contrasena = request.form.get("contrasena", "")

        if not all([nombre, apellido, correo, contrasena]):
            flash("Completa los campos obligatorios.", "error")
            return redirect(url_for("registro"))

        if len(contrasena) < 8:
            flash("La contraseña debe tener al menos 8 caracteres.", "error")
            return redirect(url_for("registro"))

        conexion = None
        cursor = None

        try:
            conexion = obtener_conexion()
            cursor = conexion.cursor()

            cursor.execute(
                "SELECT id_usuario FROM usuarios WHERE correo = %s",
                (correo,)
            )

            if cursor.fetchone():
                flash("Este correo ya esta registrado.", "error")
                return redirect(url_for("registro"))

            contrasena_hash = generate_password_hash(contrasena)

            sql = """
                INSERT INTO usuarios
                (nombre, apellido, correo, telefono, contrasena, rol)
                VALUES (%s, %s, %s, %s, %s, 'cliente')
            """

            cursor.execute(
                sql,
                (nombre, apellido, correo, telefono, contrasena_hash)
            )

            conexion.commit()

            flash("Cuenta creada correctamente.", "success")
            return redirect(url_for("login"))

        except Exception:
            if conexion:
                conexion.rollback()
            app.logger.exception("Error al registrar usuario")
            flash("No se pudo completar el registro.", "error")

        finally:
            if cursor:
                cursor.close()
            if conexion and conexion.is_connected():
                conexion.close()

    return render_template("registro.html")


# Inicio de sesion
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        correo = request.form.get("correo", "").strip().lower()
        contrasena = request.form.get("contrasena", "")

        conexion = None
        cursor = None

        try:
            conexion = obtener_conexion()
            cursor = conexion.cursor(dictionary=True)

            cursor.execute(
                """
                SELECT u.id_usuario, u.nombre, u.contrasena, u.rol,
                       b.activo AS barbero_activo
                FROM usuarios u
                LEFT JOIN barberos b ON b.id_usuario = u.id_usuario
                WHERE u.correo = %s
                """,
                (correo,)
            )

            usuario = cursor.fetchone()

            if usuario and check_password_hash(
                usuario["contrasena"], contrasena
            ):
                if usuario["rol"] == "barbero" and not usuario["barbero_activo"]:
                    flash("La cuenta de barbero está desactivada.", "error")
                    return redirect(url_for("login"))

                session.clear()
                session["id_usuario"] = usuario["id_usuario"]
                session["nombre"] = usuario["nombre"]
                session["rol"] = usuario["rol"]

                if usuario["rol"] == "cliente":
                    return redirect(url_for("panel_cliente"))

                if usuario["rol"] == "barbero":
                    return redirect(url_for("panel_barbero"))

                session.clear()
                flash("No tienes un rol autorizado para acceder.", "error")
                return redirect(url_for("login"))

            flash("Correo o contraseña incorrectos.", "error")

        except Exception:
            app.logger.exception("Error al iniciar sesion")
            flash("No se pudo iniciar sesion.", "error")

        finally:
            if cursor:
                cursor.close()
            if conexion and conexion.is_connected():
                conexion.close()

    return render_template("login.html")


# Panel privado del cliente
# Funciona igual que la pagina principal del video: muestra el
# formulario para agregar y la tabla con todos los registros.
@app.route("/panel-cliente")
@cliente_requerido
def panel_cliente():
    conexion = None
    cursor = None

    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                c.id_cita,
                CONCAT(u.nombre, ' ', u.apellido) AS barbero,
                s.nombre AS servicio,
                s.precio,
                DATE_FORMAT(c.fecha, '%d/%m/%Y') AS fecha,
                TIME_FORMAT(c.hora_inicio, '%H:%i') AS hora,
                c.estado,
                c.observaciones
            FROM citas c
            INNER JOIN barberos b ON b.id_barbero = c.id_barbero
            INNER JOIN usuarios u ON u.id_usuario = b.id_usuario
            INNER JOIN servicios s ON s.id_servicio = c.id_servicio
            WHERE c.id_cliente = %s
            ORDER BY c.fecha DESC, c.hora_inicio DESC
            """,
            (session["id_usuario"],)
        )
        citas = cursor.fetchall()
        barberos, servicios = obtener_opciones_cita(cursor)

        return render_template(
            "panel_cliente.html",
            citas=citas,
            barberos=barberos,
            servicios=servicios,
            hoy=date.today().isoformat()
        )

    except Exception:
        app.logger.exception("Error al cargar el panel del cliente")
        flash("No se pudo cargar tu panel. Inténtalo de nuevo.", "error")
        return redirect(url_for("inicio"))

    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


# Agregar una cita (en el video es la ruta /add_contact)
@app.route("/citas/agregar", methods=["POST"])
@cliente_requerido
def agregar_cita():
    validar_token_csrf()
    conexion = None
    cursor = None

    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        datos, error = validar_datos_cita(cursor, request.form)
        if error:
            flash(error, "error")
            return redirect(url_for("panel_cliente"))

        cursor.execute(
            """
            INSERT INTO citas
                (id_cliente, id_barbero, id_servicio, fecha,
                 hora_inicio, hora_fin, observaciones)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (session["id_usuario"], *datos)
        )
        id_cita = cursor.lastrowid

        # Avisar al barbero que tiene una nueva reserva
        cursor.execute(
            """
            INSERT INTO notificaciones (id_usuario, id_cita, mensaje)
            SELECT id_usuario, %s, %s
            FROM barberos
            WHERE id_barbero = %s
            """,
            (
                id_cita,
                f"{session['nombre']} reservó una cita para el "
                f"{datos[2].strftime('%d/%m/%Y')} a las "
                f"{datos[3].strftime('%H:%M')}.",
                datos[0]
            )
        )

        conexion.commit()
        flash("Cita reservada correctamente.", "success")

    except Exception:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al agregar una cita")
        flash("No se pudo reservar la cita.", "error")

    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()

    return redirect(url_for("panel_cliente"))


# Mostrar el formulario para editar una cita
# (en el video es la ruta /edit/<id>)
@app.route("/citas/editar/<int:id_cita>")
@cliente_requerido
def editar_cita(id_cita):
    conexion = None
    cursor = None

    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        # CORRECCION DEL ERROR DEL VIDEO:
        # En el video se escribe:  cur.execute('... id = %s', (id))
        # Pero (id) NO es una tupla, los parentesis solos no hacen nada.
        # Si id es el texto "14", la libreria del video (flask_mysqldb)
        # lo recorre letra por letra como si fueran dos parametros
        # ("1" y "4") y la consulta falla con cualquier id de dos o mas
        # cifras. Con mysql-connector (la que usamos aqui) falla siempre,
        # porque exige una tupla, lista o diccionario.
        # Lo correcto es poner una coma para crear una tupla de un
        # solo elemento: (id_cita,)
        cursor.execute(
            """
            SELECT
                id_cita, id_cliente, id_barbero, id_servicio, estado,
                observaciones,
                DATE_FORMAT(fecha, '%Y-%m-%d') AS fecha,
                TIME_FORMAT(hora_inicio, '%H:%i') AS hora
            FROM citas
            WHERE id_cita = %s
            """,
            (id_cita,)
        )
        cita = cursor.fetchone()

        if not cita:
            abort(404)
        if cita["id_cliente"] != session["id_usuario"]:
            abort(403)
        if cita["estado"] != "pendiente":
            flash("Solo puedes editar citas pendientes.", "error")
            return redirect(url_for("panel_cliente"))

        barberos, servicios = obtener_opciones_cita(cursor)

        return render_template(
            "editar_cita.html",
            cita=cita,
            barberos=barberos,
            servicios=servicios,
            hoy=date.today().isoformat()
        )

    except HTTPException:
        raise
    except Exception:
        app.logger.exception("Error al cargar una cita")
        flash("No se pudo cargar la cita.", "error")
        return redirect(url_for("panel_cliente"))

    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


# Guardar los cambios de una cita (en el video es la ruta /update/<id>)
@app.route("/citas/actualizar/<int:id_cita>", methods=["POST"])
@cliente_requerido
def actualizar_cita_cliente(id_cita):
    validar_token_csrf()
    conexion = None
    cursor = None

    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        datos, error = validar_datos_cita(cursor, request.form, id_cita)
        if error:
            flash(error, "error")
            return redirect(url_for("editar_cita", id_cita=id_cita))

        cursor.execute(
            """
            UPDATE citas
            SET id_barbero = %s, id_servicio = %s, fecha = %s,
                hora_inicio = %s, hora_fin = %s, observaciones = %s
            WHERE id_cita = %s AND id_cliente = %s AND estado = 'pendiente'
            """,
            (*datos, id_cita, session["id_usuario"])
        )

        if cursor.rowcount != 1:
            conexion.rollback()
            flash("La cita no existe o ya no se puede editar.", "error")
        else:
            conexion.commit()
            flash("Cita actualizada correctamente.", "success")

    except Exception:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al actualizar una cita")
        flash("No se pudo actualizar la cita.", "error")

    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()

    return redirect(url_for("panel_cliente"))


# Eliminar una cita (en el video es la ruta /delete/<id>)
# En el video el SQL se arma con .format(id), lo que permite
# inyeccion SQL. Aqui se usa %s para que MySQL reciba el valor
# por separado. Ademas se usa POST con token CSRF en vez de un
# enlace GET, para que nadie pueda borrar citas con un link.
@app.route("/citas/eliminar/<int:id_cita>", methods=["POST"])
@cliente_requerido
def eliminar_cita(id_cita):
    validar_token_csrf()
    conexion = None
    cursor = None

    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()

        cursor.execute(
            """
            DELETE FROM citas
            WHERE id_cita = %s AND id_cliente = %s
              AND estado IN ('pendiente', 'rechazada', 'cancelada')
            """,
            (id_cita, session["id_usuario"])
        )

        if cursor.rowcount != 1:
            conexion.rollback()
            flash("No puedes eliminar esta cita.", "error")
        else:
            conexion.commit()
            flash("Cita eliminada correctamente.", "success")

    except Exception:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al eliminar una cita")
        flash("No se pudo eliminar la cita.", "error")

    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()

    return redirect(url_for("panel_cliente"))


# Panel privado del barbero: solo ve sus propias citas
@app.route("/panel-barbero")
@barbero_requerido
def panel_barbero():
    conexion = None
    cursor = None

    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        id_barbero = obtener_id_barbero(cursor)

        cursor.execute(
            """
            SELECT
                COUNT(CASE WHEN fecha = CURDATE() THEN 1 END) AS citas_hoy,
                COUNT(CASE WHEN estado = 'pendiente' THEN 1 END) AS pendientes,
                COUNT(CASE WHEN estado = 'confirmada' THEN 1 END) AS confirmadas,
                COUNT(CASE WHEN estado = 'completada' THEN 1 END) AS completadas
            FROM citas
            WHERE id_barbero = %s
            """,
            (id_barbero,)
        )
        estadisticas = cursor.fetchone()

        cursor.execute(
            """
            SELECT
                c.id_cita,
                CONCAT(u.nombre, ' ', u.apellido) AS cliente,
                s.nombre AS servicio,
                DATE_FORMAT(c.fecha, '%d/%m/%Y') AS fecha,
                TIME_FORMAT(c.hora_inicio, '%H:%i') AS hora,
                c.estado
            FROM citas c
            INNER JOIN usuarios u ON u.id_usuario = c.id_cliente
            INNER JOIN servicios s ON s.id_servicio = c.id_servicio
            WHERE c.id_barbero = %s
            ORDER BY c.fecha DESC, c.hora_inicio DESC
            """,
            (id_barbero,)
        )
        citas = cursor.fetchall()

        return render_template(
            "panel_barbero.html",
            estadisticas=estadisticas,
            citas=citas
        )

    except Exception:
        app.logger.exception("Error al cargar el panel de barberos")
        flash("No se pudo cargar el panel. Inténtalo de nuevo.", "error")
        return redirect(url_for("inicio"))

    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route(
    "/panel-barbero/citas/<int:id_cita>/<accion>",
    methods=["POST"]
)
@barbero_requerido
def actualizar_cita(id_cita, accion):
    estados = {"aceptar": "confirmada", "rechazar": "rechazada"}
    if accion not in estados:
        abort(404)

    validar_token_csrf()
    conexion = None
    cursor = None

    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        id_barbero = obtener_id_barbero(cursor)

        # Solo se puede cambiar una cita pendiente del propio barbero
        cursor.execute(
            """
            UPDATE citas
            SET estado = %s
            WHERE id_cita = %s AND id_barbero = %s AND estado = 'pendiente'
            """,
            (estados[accion], id_cita, id_barbero)
        )
        if cursor.rowcount != 1:
            conexion.rollback()
            flash(
                "La cita no está pendiente o no tienes permiso para modificarla.",
                "error"
            )
        else:
            conexion.commit()
            flash("El estado de la cita se actualizó correctamente.", "success")

    except Exception:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al actualizar una cita")
        flash("No se pudo actualizar la cita. Inténtalo de nuevo.", "error")

    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()

    return redirect(url_for("panel_barbero"))


# Devuelve en JSON las horas libres de un barbero para una fecha.
# La usa el formulario de reserva (static/js/reservas.js).
@app.route("/citas/disponibilidad")
@cliente_requerido
def disponibilidad():
    try:
        id_barbero = int(request.args.get("id_barbero", ""))
        id_servicio = int(request.args.get("id_servicio", ""))
        fecha = date.fromisoformat(request.args.get("fecha", ""))
        id_cita = int(request.args.get("id_cita") or 0)
    except ValueError:
        return jsonify({"horas": [], "horario": [],
                        "mensaje": "Elige barbero, servicio y fecha."})

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT duracion_minutos FROM servicios
            WHERE id_servicio = %s AND activo = TRUE
            """,
            (id_servicio,)
        )
        servicio = cursor.fetchone()
        if not servicio:
            return jsonify({"horas": [], "horario": [],
                            "mensaje": "El servicio no está disponible."})

        horario = obtener_horario_semana(cursor, id_barbero)
        horas = calcular_horas_disponibles(
            cursor, id_barbero, fecha,
            servicio["duracion_minutos"], id_cita
        )

        dias_que_atiende = [turno["dia"] for turno in horario]
        if not horario:
            mensaje = "Este barbero aún no tiene horarios registrados."
        elif DIAS_SEMANA[fecha.isoweekday()] not in dias_que_atiende:
            mensaje = "El barbero no atiende ese día. Prueba con otra fecha."
        elif not horas:
            mensaje = "No hay horas libres ese día. Prueba con otra fecha."
        else:
            mensaje = ""

        return jsonify({"horas": horas, "horario": horario,
                        "mensaje": mensaje})

    except Exception:
        app.logger.exception("Error al consultar la disponibilidad")
        return jsonify({"horas": [], "horario": [],
                        "mensaje": "No se pudo consultar la disponibilidad."}), 500

    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


# Cerrar sesion
@app.route("/logout", methods=["POST"])
@login_requerido
def logout():
    validar_token_csrf()
    session.clear()
    flash("Sesion cerrada correctamente.", "success")
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)
