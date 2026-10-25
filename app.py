
import os
import secrets
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import (
    Flask, render_template, request,
    redirect, url_for, flash, session, abort
)
from werkzeug.exceptions import HTTPException
from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)
from mysql.connector import IntegrityError

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


def administrador_requerido(funcion):
    @wraps(funcion)
    @login_requerido
    def decorador(*args, **kwargs):
        if session.get("rol") != "administrador":
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


def validar_datos_servicio(formulario):
    nombre = formulario.get("nombre", "").strip()
    descripcion = formulario.get("descripcion", "").strip()
    precio_texto = formulario.get("precio", "").strip()
    duracion_texto = formulario.get("duracion_minutos", "").strip()

    if not nombre or len(nombre) > 100:
        return None, "El nombre del servicio es obligatorio y debe tener hasta 100 caracteres."

    try:
        precio = Decimal(precio_texto)
        if not precio.is_finite() or precio < 0 or precio > Decimal("99999999.99"):
            raise InvalidOperation
        if precio.as_tuple().exponent < -2:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        return None, "Ingresa un precio válido, no negativo y con máximo dos decimales."

    try:
        duracion = int(duracion_texto)
        if duracion <= 0 or duracion > 2147483647:
            raise ValueError
    except ValueError:
        return None, "La duración debe ser un número entero mayor que cero."

    return (nombre, descripcion or None, format(precio, ".2f"), duracion), None


def validar_datos_barbero(formulario, incluir_contrasena=False):
    nombre = formulario.get("nombre", "").strip()
    apellido = formulario.get("apellido", "").strip()
    correo = formulario.get("correo", "").strip().lower()
    telefono = formulario.get("telefono", "").strip()
    especialidad = formulario.get("especialidad", "").strip()
    contrasena = formulario.get("contrasena", "")

    if not nombre or len(nombre) > 100:
        return None, "El nombre es obligatorio y debe tener hasta 100 caracteres."
    if not apellido or len(apellido) > 100:
        return None, "El apellido es obligatorio y debe tener hasta 100 caracteres."
    partes_correo = correo.split("@")
    if (
        not correo
        or len(correo) > 150
        or len(partes_correo) != 2
        or not all(partes_correo)
        or any(caracter.isspace() for caracter in correo)
    ):
        return None, "Ingresa un correo válido de hasta 150 caracteres."
    if len(telefono) > 20:
        return None, "El teléfono debe tener hasta 20 caracteres."
    if len(especialidad) > 100:
        return None, "La especialidad debe tener hasta 100 caracteres."
    if incluir_contrasena and len(contrasena) < 8:
        return None, "La contraseña inicial debe tener al menos 8 caracteres."

    datos = (nombre, apellido, correo, telefono or None, especialidad or None)
    if incluir_contrasena:
        datos += (contrasena,)
    return datos, None


# Pagina principal
@app.route("/")
def inicio():
    return render_template("index.html")


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


@app.route("/admin/servicios", methods=["GET", "POST"])
@administrador_requerido
def administrar_servicios():
    if request.method == "POST":
        validar_token_csrf()
        datos, error = validar_datos_servicio(request.form)
        if error:
            flash(error, "error")
            return redirect(url_for("administrar_servicios"))

        conexion = None
        cursor = None
        try:
            conexion = obtener_conexion()
            cursor = conexion.cursor()
            cursor.execute(
                """
                INSERT INTO servicios
                    (nombre, descripcion, precio, duracion_minutos)
                VALUES (%s, %s, %s, %s)
                """,
                datos
            )
            conexion.commit()
            flash("El servicio se registró correctamente.", "success")
            return redirect(url_for("administrar_servicios"))
        except Exception:
            if conexion:
                conexion.rollback()
            app.logger.exception("Error al registrar un servicio")
            flash("No se pudo registrar el servicio.", "error")
        finally:
            if cursor:
                cursor.close()
            if conexion and conexion.is_connected():
                conexion.close()

    return cargar_pagina_servicios()


def cargar_pagina_servicios(servicio_edicion=None):
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id_servicio, nombre, descripcion, precio,
                   duracion_minutos, activo
            FROM servicios
            ORDER BY activo DESC, nombre ASC
            """
        )
        servicios = cursor.fetchall()

        if servicio_edicion is not None:
            cursor.execute(
                """
                SELECT id_servicio, nombre, descripcion, precio,
                       duracion_minutos, activo
                FROM servicios
                WHERE id_servicio = %s
                """,
                (servicio_edicion,)
            )
            servicio_edicion = cursor.fetchone()
            if not servicio_edicion:
                abort(404)

        return render_template(
            "admin_servicios.html",
            servicios=servicios,
            servicio_edicion=servicio_edicion
        )
    except HTTPException:
        raise
    except Exception:
        app.logger.exception("Error al cargar la gestión de servicios")
        flash("No se pudo cargar la lista de servicios.", "error")
        return redirect(url_for("panel_barbero"))
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/admin/servicios/<int:id_servicio>/editar", methods=["GET", "POST"])
@administrador_requerido
def editar_servicio(id_servicio):
    if request.method == "POST":
        validar_token_csrf()
        datos, error = validar_datos_servicio(request.form)
        if error:
            flash(error, "error")
            return redirect(
                url_for("editar_servicio", id_servicio=id_servicio)
            )

        conexion = None
        cursor = None
        try:
            conexion = obtener_conexion()
            cursor = conexion.cursor()
            cursor.execute(
                "SELECT id_servicio FROM servicios WHERE id_servicio = %s",
                (id_servicio,)
            )
            if not cursor.fetchone():
                abort(404)
            cursor.execute(
                """
                UPDATE servicios
                SET nombre = %s, descripcion = %s, precio = %s,
                    duracion_minutos = %s
                WHERE id_servicio = %s
                """,
                (*datos, id_servicio)
            )
            conexion.commit()
            flash("El servicio se actualizó correctamente.", "success")
            return redirect(url_for("administrar_servicios"))
        except HTTPException:
            raise
        except Exception:
            if conexion:
                conexion.rollback()
            app.logger.exception("Error al editar un servicio")
            flash("No se pudo actualizar el servicio.", "error")
        finally:
            if cursor:
                cursor.close()
            if conexion and conexion.is_connected():
                conexion.close()

    return cargar_pagina_servicios(id_servicio)


@app.route("/admin/servicios/<int:id_servicio>/estado", methods=["POST"])
@administrador_requerido
def cambiar_estado_servicio(id_servicio):
    validar_token_csrf()
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        cursor.execute(
            "UPDATE servicios SET activo = NOT activo WHERE id_servicio = %s",
            (id_servicio,)
        )
        if cursor.rowcount != 1:
            conexion.rollback()
            abort(404)
        conexion.commit()
        flash("El estado del servicio se actualizó.", "success")
    except HTTPException:
        raise
    except Exception:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al cambiar el estado de un servicio")
        flash("No se pudo cambiar el estado del servicio.", "error")
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()
    return redirect(url_for("administrar_servicios"))


@app.route("/admin/barberos", methods=["GET", "POST"])
@administrador_requerido
def administrar_barberos():
    if request.method == "POST":
        validar_token_csrf()
        datos, error = validar_datos_barbero(request.form, incluir_contrasena=True)
        if error:
            flash(error, "error")
            return redirect(url_for("administrar_barberos"))

        nombre, apellido, correo, telefono, especialidad, contrasena = datos
        conexion = None
        cursor = None
        try:
            conexion = obtener_conexion()
            conexion.start_transaction()
            cursor = conexion.cursor()
            cursor.execute(
                "SELECT id_usuario FROM usuarios WHERE correo = %s",
                (correo,)
            )
            if cursor.fetchone():
                conexion.rollback()
                flash("Ese correo ya está registrado.", "error")
                return redirect(url_for("administrar_barberos"))

            cursor.execute(
                """
                INSERT INTO usuarios
                    (nombre, apellido, correo, telefono, contrasena, rol)
                VALUES (%s, %s, %s, %s, %s, 'barbero')
                """,
                (
                    nombre,
                    apellido,
                    correo,
                    telefono,
                    generate_password_hash(contrasena)
                )
            )
            id_usuario = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO barberos (id_usuario, especialidad)
                VALUES (%s, %s)
                """,
                (id_usuario, especialidad)
            )
            conexion.commit()
            flash("El barbero se registró correctamente.", "success")
            return redirect(url_for("administrar_barberos"))
        except IntegrityError:
            if conexion:
                conexion.rollback()
            flash("Ese correo ya está registrado.", "error")
        except Exception:
            if conexion:
                conexion.rollback()
            app.logger.exception("Error al registrar un barbero")
            flash("No se pudo registrar el barbero.", "error")
        finally:
            if cursor:
                cursor.close()
            if conexion and conexion.is_connected():
                conexion.close()

    return cargar_pagina_barberos()


def cargar_pagina_barberos(barbero_edicion=None):
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT b.id_barbero, u.id_usuario, u.nombre, u.apellido,
                   u.correo, u.telefono, b.especialidad, b.activo
            FROM barberos b
            INNER JOIN usuarios u ON u.id_usuario = b.id_usuario
            WHERE u.rol = 'barbero'
            ORDER BY b.activo DESC, u.apellido ASC, u.nombre ASC
            """
        )
        barberos = cursor.fetchall()

        if barbero_edicion is not None:
            cursor.execute(
                """
                SELECT b.id_barbero, u.id_usuario, u.nombre, u.apellido,
                       u.correo, u.telefono, b.especialidad, b.activo
                FROM barberos b
                INNER JOIN usuarios u ON u.id_usuario = b.id_usuario
                WHERE b.id_barbero = %s AND u.rol = 'barbero'
                """,
                (barbero_edicion,)
            )
            barbero_edicion = cursor.fetchone()
            if not barbero_edicion:
                abort(404)

        return render_template(
            "admin_barberos.html",
            barberos=barberos,
            barbero_edicion=barbero_edicion
        )
    except HTTPException:
        raise
    except Exception:
        app.logger.exception("Error al cargar la gestión de barberos")
        flash("No se pudo cargar la lista de barberos.", "error")
        return redirect(url_for("panel_barbero"))
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/admin/barberos/<int:id_barbero>/editar", methods=["GET", "POST"])
@administrador_requerido
def editar_barbero(id_barbero):
    if request.method == "POST":
        validar_token_csrf()
        datos, error = validar_datos_barbero(request.form)
        if error:
            flash(error, "error")
            return redirect(url_for("editar_barbero", id_barbero=id_barbero))

        nombre, apellido, correo, telefono, especialidad = datos
        conexion = None
        cursor = None
        try:
            conexion = obtener_conexion()
            conexion.start_transaction()
            cursor = conexion.cursor()
            cursor.execute(
                """
                SELECT u.id_usuario
                FROM barberos b
                INNER JOIN usuarios u ON u.id_usuario = b.id_usuario
                WHERE b.id_barbero = %s AND u.rol = 'barbero'
                FOR UPDATE
                """,
                (id_barbero,)
            )
            usuario = cursor.fetchone()
            if not usuario:
                conexion.rollback()
                abort(404)

            id_usuario = usuario[0]
            cursor.execute(
                """
                SELECT id_usuario FROM usuarios
                WHERE correo = %s AND id_usuario <> %s
                """,
                (correo, id_usuario)
            )
            if cursor.fetchone():
                conexion.rollback()
                flash("Ese correo ya pertenece a otra cuenta.", "error")
                return redirect(url_for("editar_barbero", id_barbero=id_barbero))

            cursor.execute(
                """
                UPDATE usuarios
                SET nombre = %s, apellido = %s, correo = %s, telefono = %s
                WHERE id_usuario = %s AND rol = 'barbero'
                """,
                (nombre, apellido, correo, telefono, id_usuario)
            )
            cursor.execute(
                "UPDATE barberos SET especialidad = %s WHERE id_barbero = %s",
                (especialidad, id_barbero)
            )
            conexion.commit()
            flash("Los datos del barbero se actualizaron.", "success")
            return redirect(url_for("administrar_barberos"))
        except IntegrityError:
            if conexion:
                conexion.rollback()
            flash("Ese correo ya pertenece a otra cuenta.", "error")
        except HTTPException:
            raise
        except Exception:
            if conexion:
                conexion.rollback()
            app.logger.exception("Error al editar un barbero")
            flash("No se pudieron actualizar los datos del barbero.", "error")
        finally:
            if cursor:
                cursor.close()
            if conexion and conexion.is_connected():
                conexion.close()

    return cargar_pagina_barberos(id_barbero)


@app.route("/admin/barberos/<int:id_barbero>/estado", methods=["POST"])
@administrador_requerido
def cambiar_estado_barbero(id_barbero):
    validar_token_csrf()
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        cursor.execute(
            """
            UPDATE barberos b
            INNER JOIN usuarios u ON u.id_usuario = b.id_usuario
            SET b.activo = NOT b.activo
            WHERE b.id_barbero = %s AND u.rol = 'barbero'
            """,
            (id_barbero,)
        )
        if cursor.rowcount != 1:
            conexion.rollback()
            abort(404)
        conexion.commit()
        flash("El estado del barbero se actualizó.", "success")
    except HTTPException:
        raise
    except Exception:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al cambiar el estado de un barbero")
        flash("No se pudo cambiar el estado del barbero.", "error")
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()
    return redirect(url_for("administrar_barberos"))


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
