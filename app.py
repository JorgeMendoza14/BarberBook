
import os
import secrets
from functools import wraps

from flask import (
    Flask, render_template, request,
    redirect, url_for, flash, session, abort
)
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


# Pagina principal
@app.route("/")
def inicio():
    return render_template("index.html")


# Registro de clientes
@app.route("/registro", methods=["GET", "POST"])
def registro():

    if request.method == "POST":
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
                SELECT id_usuario, nombre, contrasena, rol
                FROM usuarios
                WHERE correo = %s
                """,
                (correo,)
            )

            usuario = cursor.fetchone()

            if usuario and check_password_hash(
                usuario["contrasena"], contrasena
            ):
                session.clear()
                session["id_usuario"] = usuario["id_usuario"]
                session["nombre"] = usuario["nombre"]
                session["rol"] = usuario["rol"]

                if usuario["rol"] == "cliente":
                    return redirect(url_for("panel_cliente"))

                if usuario["rol"] in ("administrador", "barbero"):
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
@app.route("/panel-cliente")
@login_requerido
def panel_cliente():

    if session.get("rol") != "cliente":
        return "Acceso no autorizado", 403

    return render_template("panel_cliente.html")


# Panel privado de administradores y barberos
@app.route("/panel-barbero")
@login_requerido
def panel_barbero():
    rol = session.get("rol")
    if rol not in ("administrador", "barbero"):
        return "Acceso no autorizado", 403

    conexion = None
    cursor = None

    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        id_barbero = obtener_id_barbero(cursor) if rol == "barbero" else None
        filtro = "" if rol == "administrador" else "WHERE c.id_barbero = %s"
        parametros = () if rol == "administrador" else (id_barbero,)

        cursor.execute(
            f"""
            SELECT
                COUNT(CASE WHEN c.fecha = CURDATE() THEN 1 END) AS citas_hoy,
                COUNT(CASE WHEN c.estado = 'pendiente' THEN 1 END) AS pendientes,
                COUNT(CASE WHEN c.estado = 'confirmada' THEN 1 END) AS confirmadas,
                COUNT(CASE WHEN c.estado = 'completada' THEN 1 END) AS completadas
            FROM citas c
            {filtro}
            """,
            parametros
        )
        estadisticas = cursor.fetchone()

        cursor.execute(
            f"""
            SELECT
                c.id_cita,
                CONCAT(cliente.nombre, ' ', cliente.apellido) AS cliente,
                CONCAT(barbero.nombre, ' ', barbero.apellido) AS barbero,
                servicio.nombre AS servicio,
                DATE_FORMAT(c.fecha, '%d/%m/%Y') AS fecha,
                TIME_FORMAT(c.hora_inicio, '%H:%i') AS hora,
                c.estado
            FROM citas c
            INNER JOIN usuarios cliente ON cliente.id_usuario = c.id_cliente
            INNER JOIN barberos perfil_barbero
                ON perfil_barbero.id_barbero = c.id_barbero
            INNER JOIN usuarios barbero
                ON barbero.id_usuario = perfil_barbero.id_usuario
            INNER JOIN servicios servicio
                ON servicio.id_servicio = c.id_servicio
            {filtro}
            ORDER BY c.fecha DESC, c.hora_inicio DESC, c.fecha_creacion DESC
            """,
            parametros
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
@login_requerido
def actualizar_cita(id_cita, accion):
    rol = session.get("rol")
    if rol not in ("administrador", "barbero"):
        return "Acceso no autorizado", 403

    estados = {"aceptar": "confirmada", "rechazar": "rechazada"}
    if accion not in estados:
        abort(404)

    validar_token_csrf()
    conexion = None
    cursor = None

    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        consulta = """
            UPDATE citas
            SET estado = %s
            WHERE id_cita = %s AND estado = 'pendiente'
        """
        parametros = [estados[accion], id_cita]

        if rol == "barbero":
            id_barbero = obtener_id_barbero(cursor)
            consulta += " AND id_barbero = %s"
            parametros.append(id_barbero)

        cursor.execute(consulta, tuple(parametros))
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


# Cerrar sesion
@app.route("/logout", methods=["POST"])
@login_requerido
def logout():
    session.clear()
    flash("Sesion cerrada correctamente.", "success")
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)
