from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    send_file,
    json,
)
from werkzeug.utils import secure_filename
from flask_mysqldb import MySQL
from flask_bcrypt import Bcrypt
from fpdf import FPDF
from datetime import datetime

import MySQLdb.cursors
import subprocess
import os
import requests

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["REPORTES_FOLDER"] = "reportes"
app.secret_key = "your_secret_key"
bcrypt = Bcrypt(app)

# Crear directorios si no existen
if not os.path.exists(app.config["UPLOAD_FOLDER"]):
    os.makedirs(app.config["UPLOAD_FOLDER"])
if not os.path.exists(app.config["REPORTES_FOLDER"]):
    os.makedirs(app.config["REPORTES_FOLDER"])

app.config["MYSQL_HOST"] = "localhost"
app.config["MYSQL_USER"] = "root"
app.config["MYSQL_PASSWORD"] = ""
app.config["MYSQL_DB"] = "camicandy"

mysql = MySQL(app)
bcrypt = Bcrypt(app)


def get_tasa_bcv():
    return requests.get(
        "https://pydolarvenezuela-api.vercel.app/api/v1/dollar/unit/bcv"
    ).json()["price"]


class PDF(FPDF):
    def __init__(self, title):
        super().__init__()
        self.title = title

    def header(self):
        # Rendering logo:
        self.image("static/imagenes/icons/camidark.png", 10, 1, 50)
        # Setting font: helvetica bold 15
        self.set_font("helvetica", "B", 15)

        # Printing title:
        width = self.get_string_width(self.title) + 6
        # Moving cursor to the right:
        self.set_x((210 - width) / 2)
        self.cell(
            width,
            9,
            self.title,
            border=1,
            align="C",
        )
        # print date and hour
        self.cell(0, 10, f"{datetime.now().strftime('%d-%m-%Y %H:%M:%S')}", 0, 1, "R")
        # Performing a line break:
        self.ln(20)

    def footer(self):
        # Position cursor at 1.5 cm from bottom:
        self.set_y(-15)
        # Setting font: helvetica italic 10
        self.set_font("helvetica", "I", 10)
        # Printing page number:
        self.cell(0, 12, f"Página {self.page_no()}/{{nb}}", align="C")


# region Login


@app.route("/", methods=["GET", "POST"])
def login():
    if (
        request.method == "POST"
        and "username" in request.form
        and "password" in request.form
    ):
        username = request.form["username"]
        password = request.form["password"]

        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute(
            "SELECT * FROM usuarios WHERE cedula = %s AND status = 1", (username,)
        )
        user = cursor.fetchone()

        if user and bcrypt.check_password_hash(user["hash_de_contrasena"], password):
            session["loggedin"] = True
            session["id"] = user["id"]
            session["username"] = user["nombre"]
            session["rol"] = user["rol"]
            return redirect(url_for("dashboard"))
        else:
            flash("Usuario o contraseña incorrectos")

    return render_template("login.html")


# region Dashboard


@app.route("/dashboard")
def dashboard():
    if "loggedin" in session:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

        ############### GRÁFICOS
        # Obtener la cantidad de ventas realizadas la última semana
        cursor.execute(
            "SELECT COUNT(*) AS cantidad, DATE(marca_de_tiempo) AS fecha FROM transacciones WHERE (marca_de_tiempo BETWEEN DATE_SUB(NOW(), INTERVAL 1 WEEK) AND NOW()) AND clientes_id IS NOT NULL GROUP BY DATE(marca_de_tiempo) ORDER BY DATE(marca_de_tiempo) ASC;"
        )
        ventas_semana = cursor.fetchall()
        # Formatear las fechas
        for venta in ventas_semana:
            venta["fecha"] = venta["fecha"].strftime("%Y-%m-%d")

        # Obtener el monto total de las transacciones de la última semana
        cursor.execute(
            "SELECT SUM(importe_en_dolares) AS importe_en_dolares, DATE(marca_de_tiempo) AS fecha FROM transacciones WHERE (marca_de_tiempo BETWEEN DATE_SUB(NOW(), INTERVAL 1 WEEK) AND NOW()) AND clientes_id IS NOT NULL GROUP BY DATE(marca_de_tiempo) ORDER BY DATE(marca_de_tiempo) ASC;"
        )
        ingreso_semana = cursor.fetchall()
        for ingreso in ingreso_semana:
            ingreso["fecha"] = ingreso["fecha"].strftime("%Y-%m-%d")
        ########################

        # Obtener la cantidad de productos
        cursor.execute("SELECT COUNT(*) AS total_productos FROM productos")
        total_productos = cursor.fetchone()["total_productos"]

        # Obtener la cantidad de clientes
        cursor.execute("SELECT COUNT(*) AS total_clientes FROM clientes")
        total_clientes = cursor.fetchone()["total_clientes"]

        # Obtener la cantidad de proveedores
        cursor.execute("SELECT COUNT(*) AS total_proveedores FROM proveedores")
        total_proveedores = cursor.fetchone()["total_proveedores"]

        cursor.execute("SELECT COUNT(*) AS total_transacciones FROM transacciones")
        total_transacciones = cursor.fetchone()["total_transacciones"]

        cursor.close()

        return render_template(
            "dashboard.html",
            username=session["username"],
            rol=session["rol"],
            total_productos=total_productos,
            total_clientes=total_clientes,
            total_proveedores=total_proveedores,
            total_transacciones=total_transacciones,
            ventas_semana=ventas_semana,
            ingreso_semana=ingreso_semana,
            current_page="dashboard",
        )
    return redirect(url_for("login"))


# region Productos


############################# PRODUCTOS ################################
@app.route("/productos", methods=["GET", "POST"])
def productos():
    if "loggedin" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        nombre = request.form["nombre"]
        fecha_de_vencimiento = request.form["fecha_de_vencimiento"]
        cantidad_disponible = request.form["cantidad_disponible"]
        precio_en_dolares = request.form["precio_en_dolares"]

        if (
            nombre
            and fecha_de_vencimiento
            and cantidad_disponible
            and precio_en_dolares
        ):
            cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

            # Verificar si el producto ya existe
            cursor.execute("SELECT * FROM productos WHERE nombre = %s", (nombre,))
            producto_existente = cursor.fetchone()

            if producto_existente:
                if producto_existente["status"] == 0:
                    cursor.execute(
                        "UPDATE productos SET fecha_de_vencimiento = %s, cantidad_disponible = %s, precio_en_dolares = %s, status = 1 WHERE nombre = %s",
                        (
                            fecha_de_vencimiento,
                            cantidad_disponible,
                            precio_en_dolares,
                            nombre,
                        ),
                    )
                    mysql.connection.commit()
                    flash("Producto agregado correctamente.", "success")
                    return redirect(url_for("productos"))
                else:
                    flash("El producto ya existe.", "warning")
            else:
                cursor.execute(
                    "INSERT INTO productos (nombre, fecha_de_vencimiento, cantidad_disponible, precio_en_dolares, status) VALUES (%s, %s, %s, %s, 1)",
                    (
                        nombre,
                        fecha_de_vencimiento,
                        cantidad_disponible,
                        precio_en_dolares,
                    ),
                )
                mysql.connection.commit()
                flash("Producto agregado correctamente.", "success")
                return redirect(url_for("productos"))

            cursor.close()
        else:
            flash("Por favor, complete todos los campos del formulario", "warning")

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM productos WHERE status = 1")
    all_products = cursor.fetchall()
    cursor.close()

    return render_template(
        "productos.html",
        username=session["username"],
        rol=session["rol"],
        productos=all_products,
        current_page="productos",
    )


@app.route("/actualizar_producto", methods=["POST"])
def actualizar_producto():
    # Verificar si el usuario está logueado
    if "loggedin" not in session:
        return redirect(url_for("login"))

    # Obtener los datos del formulario
    producto_id = request.form["producto_id_actualizar"]
    nombre = request.form["nombre_actualizar"]
    fecha_de_vencimiento = request.form["fecha_de_vencimiento_actualizar"]
    cantidad_disponible = request.form["cantidad_disponible_actualizar"]
    precio_en_dolares = request.form["precio_en_dolares_actualizar"]

    # Actualizar la información en la base de datos
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(
        """
        UPDATE productos
        SET nombre = %s, fecha_de_vencimiento = %s, cantidad_disponible = %s,
            precio_en_dolares = %s
        WHERE id = %s
    """,
        (
            nombre,
            fecha_de_vencimiento,
            cantidad_disponible,
            precio_en_dolares,
            producto_id,
        ),
    )
    mysql.connection.commit()
    cursor.close()

    # Redirigir a la página de productos con un mensaje flash
    flash("Producto actualizado correctamente", "success")
    return redirect(url_for("productos"))


@app.route("/eliminar_productos", methods=["POST"])
def eliminar_productos():
    # Verificar si el usuario está logueado
    if "loggedin" not in session:
        return redirect(url_for("login"))

    # Obtener los IDs de los productos a eliminar del formulario
    producto_ids = request.form.getlist("producto_ids")

    # Iterar sobre los IDs de los productos y marcarlos como inactivos en la base de datos
    cursor = mysql.connection.cursor()
    for producto_id in producto_ids:
        cursor.execute(
            "UPDATE productos SET status = %s WHERE id = %s", (False, producto_id)
        )
    mysql.connection.commit()
    cursor.close()

    # Redirigir a la página de productos con un mensaje flash
    flash("Productos eliminados correctamente", "success")
    return redirect(url_for("productos"))


# endregion


# region Clientes
#################################### CLIENTES ################################################


@app.route("/clientes", methods=["GET", "POST"])
def clientes():
    if "loggedin" not in session:
        return redirect(url_for("login"))

    error_messages = []

    if request.method == "POST":
        nombre = request.form["nombre"]
        direccion = request.form["direccion"]
        telefono = request.form["telefono"]
        cedula = request.form["cedula"]

        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

        # Verificar si el cliente ya existe
        cursor.execute("SELECT * FROM clientes WHERE cedula = %s", (cedula,))
        cliente_existente = cursor.fetchone()

        if cliente_existente:
            if cliente_existente["status"] == 0:
                cursor.execute(
                    "UPDATE clientes SET nombre = %s, direccion = %s, telefono = %s, status = 1 WHERE cedula = %s",
                    (nombre, direccion, telefono, cedula),
                )
                mysql.connection.commit()
                flash("Cliente agregado correctamente.", "success")
                return redirect(url_for("clientes"))
            else:
                error_messages.append("El cliente ya existe.")
        else:
            cursor.execute(
                "INSERT INTO clientes (nombre, direccion, telefono, cedula, status) VALUES (%s, %s, %s, %s, 1)",
                (nombre, direccion, telefono, cedula),
            )
            mysql.connection.commit()
            flash("Cliente agregado correctamente.", "success")
            return redirect(url_for("clientes"))

        cursor.close()

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM clientes WHERE status = 1")
    clientes = cursor.fetchall()
    cursor.close()

    return render_template(
        "clientes.html",
        clientes=clientes,
        username=session["username"],
        rol=session["rol"],
        current_page="clientes",
        error_messages=error_messages,
    )


@app.route("/actualizar_cliente", methods=["POST"])
def actualizar_cliente():
    if "loggedin" not in session:
        return redirect(url_for("login"))

    cliente_id = request.form["cliente_id_actualizar"]
    nombre = request.form["nombre_actualizar"]
    direccion = request.form["direccion_actualizar"]
    telefono = request.form["telefono_actualizar"]
    cedula = request.form["cedula_actualizar"]

    error_messages = []

    # Validaciones
    cursor = mysql.connection.cursor()

    # Verificar si el teléfono ya existe y pertenece a otro cliente
    cursor.execute(
        "SELECT * FROM clientes WHERE telefono = %s AND id != %s",
        (telefono, cliente_id),
    )
    cliente_existente_telefono = cursor.fetchone()
    if cliente_existente_telefono:
        error_messages.append("El teléfono ingresado ya pertenece a otro cliente.")

    # Verificar si la cédula ya existe y pertenece a otro cliente
    cursor.execute(
        "SELECT * FROM clientes WHERE cedula = %s AND id != %s", (cedula, cliente_id)
    )
    cliente_existente_cedula = cursor.fetchone()
    if cliente_existente_cedula:
        error_messages.append("La cédula ingresada ya pertenece a otro cliente.")

    cursor.close()

    if error_messages:
        for error in error_messages:
            flash(error, "error")

        return redirect(url_for("clientes"))

    # Actualizar cliente en la base de datos si no hay errores
    cursor = mysql.connection.cursor()
    cursor.execute(
        """
        UPDATE clientes
        SET nombre = %s, direccion = %s, telefono = %s, cedula = %s
        WHERE id = %s
        """,
        (nombre, direccion, telefono, cedula, cliente_id),
    )
    mysql.connection.commit()
    cursor.close()

    flash("Cliente actualizado correctamente", "success")

    # Redirigir a la lista de clientes después de la actualización
    return redirect(url_for("clientes"))


@app.route("/eliminar_clientes", methods=["POST"])
def eliminar_clientes():
    if "loggedin" not in session:
        return redirect(url_for("login"))

    cliente_ids = request.form.getlist("cliente_ids")
    cursor = mysql.connection.cursor()
    for cliente_id in cliente_ids:
        cursor.execute(
            "UPDATE clientes SET status = %s WHERE id = %s", (False, cliente_id)
        )
    mysql.connection.commit()
    cursor.close()
    flash("Clientes eliminados correctamente", "success")

    return redirect(url_for("clientes"))


@app.route("/realizar_venta", methods=["GET", "POST"])
def realizar_venta():
    if "loggedin" not in session:
        return redirect(url_for("login"))

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Obtener productos activos
    cursor.execute("SELECT * FROM productos WHERE status = 1")
    productos_activos = cursor.fetchall()

    # Obtener clientes activos
    cursor.execute("SELECT * FROM clientes WHERE status = 1")
    clientes_activos = cursor.fetchall()

    # Obtener usuarios activos
    cursor.execute("SELECT * FROM usuarios WHERE status = 1")
    usuarios_activos = cursor.fetchall()

    cursor.close()

    tasa_bcv = get_tasa_bcv()
    today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if request.method == "POST":
        try:
            marca_de_tiempo = request.form["marca_de_tiempo"]
            clientes_id = request.form["clientes_id"]
            usuarios_id = session["id"]
            carrito = json.loads(request.form["carrito"])

            cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

            # Insertar en la tabla transacciones
            cursor.execute(
                """
                INSERT INTO transacciones
                (marca_de_tiempo, tasa_bcv, clientes_id, usuarios_id)
                VALUES (%s, %s, %s, %s)
                """,
                (marca_de_tiempo, tasa_bcv, clientes_id, usuarios_id),
            )
            mysql.connection.commit()

            transaccion_id = cursor.lastrowid

            # Insertar en la tabla transacciones_tiene_productos
            for producto in carrito:
                cursor.execute(
                    """
                    INSERT INTO transacciones_tiene_productos
                    (transacciones_id, productos_id, cantidad)
                    VALUES (%s, %s, %s)
                    """,
                    (transaccion_id, producto["id"], producto["cantidad"]),
                )
                mysql.connection.commit()

            cursor.close()
            flash("Venta realizada correctamente", "success")
            return redirect(url_for("clientes"))

        except Exception as e:
            flash(f"Ocurrió un error: {str(e)}", "error")
            return redirect(url_for("realizar_venta"))

    return render_template(
        "venta.html",
        productos=productos_activos,
        clientes=clientes_activos,
        usuarios=usuarios_activos,
        username=session["username"],
        rol=session["rol"],
        tasa_bcv=tasa_bcv,
        today=today,
        usuario=session["username"],
        current_page="clientes",
    )


# endregion


# region Proveedores
################################## PROVEEDORES ########################################


@app.route("/proveedores", methods=["GET", "POST"])
def proveedores():
    if "loggedin" not in session or session["rol"] != "administrador":
        return redirect(url_for("dashboard"))

    error_messages = []

    if request.method == "POST":
        nombre = request.form["nombre"]
        direccion = request.form["direccion"]
        rif = request.form["rif"]

        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

        # Verificar si el proveedor ya existe
        cursor.execute("SELECT * FROM proveedores WHERE rif = %s", (rif,))
        proveedor_existente = cursor.fetchone()

        if proveedor_existente:
            if proveedor_existente["status"] == 0:
                cursor.execute(
                    "UPDATE proveedores SET nombre = %s, direccion = %s, status = 1 WHERE rif = %s",
                    (nombre, direccion, rif),
                )
                mysql.connection.commit()
                flash("Proveedor añadido correctamente.", "success")
                return redirect(url_for("proveedores"))
            else:
                error_messages.append("El RIF ya pertenece a un proveedor.")
        else:
            cursor.execute(
                "INSERT INTO proveedores (nombre, direccion, rif, status) VALUES (%s, %s, %s, 1)",
                (nombre, direccion, rif),
            )
            mysql.connection.commit()
            flash("Proveedor añadido correctamente.", "success")
            return redirect(url_for("proveedores"))

        cursor.close()

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM proveedores WHERE status = 1")
    proveedores = cursor.fetchall()
    cursor.close()

    return render_template(
        "proveedores.html",
        proveedores=proveedores,
        username=session["username"],
        rol=session["rol"],
        current_page="proveedores",
        error_messages=error_messages,
    )


@app.route("/realizar_compra", methods=["GET", "POST"])
def realizar_compra():
    if "loggedin" not in session:
        return redirect(url_for("login"))

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Obtener productos activos
    cursor.execute("SELECT * FROM productos WHERE status = 1")
    productos_activos = cursor.fetchall()

    # Obtener clientes activos
    cursor.execute("SELECT * FROM proveedores WHERE status = 1")
    proveedores_activos = cursor.fetchall()

    # Obtener usuarios activos
    cursor.execute("SELECT * FROM usuarios WHERE status = 1")
    usuarios_activos = cursor.fetchall()

    cursor.close()

    tasa_bcv = get_tasa_bcv()
    today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if request.method == "POST":
        try:
            marca_de_tiempo = request.form["marca_de_tiempo"]
            proveedores_id = request.form["proveedores_id"]
            usuarios_id = session["id"]
            carrito = json.loads(request.form["carrito"])

            cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

            # Insertar en la tabla transacciones
            cursor.execute(
                """
                INSERT INTO transacciones
                (marca_de_tiempo, tasa_bcv, proveedores_id, usuarios_id)
                VALUES (%s, %s, %s, %s)
                """,
                (marca_de_tiempo, tasa_bcv, proveedores_id, usuarios_id),
            )
            mysql.connection.commit()

            transaccion_id = cursor.lastrowid

            # Insertar en la tabla transacciones_tiene_productos
            for producto in carrito:
                cursor.execute(
                    """
                    INSERT INTO transacciones_tiene_productos
                    (transacciones_id, productos_id, cantidad)
                    VALUES (%s, %s, %s)
                    """,
                    (transaccion_id, producto["id"], producto["cantidad"]),
                )

            mysql.connection.commit()  # Commit final después del bucle

            cursor.close()
            flash("Compra realizada correctamente", "success")
            return redirect(url_for("proveedores"))

        except Exception as e:
            flash(f"Ocurrió un error: {str(e)}", "error")
            return redirect(url_for("realizar_compra"))

    return render_template(
        "compras.html",
        productos=productos_activos,
        proveedores=proveedores_activos,
        usuarios=usuarios_activos,
        username=session["username"],
        rol=session["rol"],
        tasa_bcv=tasa_bcv,
        today=today,
        usuario=session["username"],
        current_page="proveedores",
    )


@app.route("/actualizar_proveedor", methods=["POST"])
def actualizar_proveedor():
    # Verificar si el usuario está logueado
    if "loggedin" not in session:
        return redirect(url_for("login"))

    # Obtener los datos del formulario
    proveedor_id = request.form["proveedor_id_actualizar"]
    nombre = request.form["nombre_actualizar"]
    direccion = request.form["direccion_actualizar"]
    rif = request.form["rif_actualizar"]

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Verificar si el RIF ya existe y pertenece a otro proveedor
    cursor.execute(
        "SELECT * FROM proveedores WHERE rif = %s AND id != %s", (rif, proveedor_id)
    )
    proveedor_existente = cursor.fetchone()

    if proveedor_existente:
        flash("El RIF ingresado ya pertenece a otro proveedor.", "error")
        cursor.close()
        return redirect(url_for("proveedores"))

    # Actualizar la información en la base de datos
    cursor.execute(
        """
        UPDATE proveedores
        SET nombre = %s, direccion = %s, rif = %s
        WHERE id = %s
    """,
        (nombre, direccion, rif, proveedor_id),
    )
    mysql.connection.commit()
    cursor.close()

    # Redirigir a la página de proveedores con un mensaje flash
    flash("Proveedor actualizado correctamente", "success")
    return redirect(url_for("proveedores"))


@app.route("/eliminar_proveedores", methods=["POST"])
def eliminar_proveedores():
    # Verificar si el usuario está logueado
    if "loggedin" not in session:
        return redirect(url_for("login"))

    # Obtener los IDs de los proveedores a eliminar del formulario
    proveedor_ids = request.form.getlist("proveedor_ids")

    # Iterar sobre los IDs de los proveedores y marcarlos como inactivos en la base de datos
    cursor = mysql.connection.cursor()
    for proveedor_id in proveedor_ids:
        cursor.execute(
            "UPDATE proveedores SET status = %s WHERE id = %s", (False, proveedor_id)
        )
    mysql.connection.commit()
    cursor.close()

    # Redirigir a la página de proveedores con un mensaje flash
    flash("Proveedores eliminados correctamente", "success")
    return redirect(url_for("proveedores"))


# region Contraseña
##################### OLVIDASTE TU CONTRASEÑA ##########################################


@app.route("/recuperar_contrasena", methods=["GET", "POST"])
def recuperar_contrasena():
    if request.method == "POST" and "username" in request.form:
        username = request.form["username"]

        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute(
            "SELECT pregunta_seguridad FROM usuarios WHERE cedula = %s AND status = 1",
            (username,),
        )
        user = cursor.fetchone()

        if user:
            session["recuperar_username"] = username
            session["pregunta_seguridad"] = user["pregunta_seguridad"]
            return redirect(url_for("verificar_respuesta"))
        else:
            flash("Usuario no encontrado")

    return render_template("recuperar_contrasena.html")


@app.route("/verificar_respuesta", methods=["GET", "POST"])
def verificar_respuesta():
    if "recuperar_username" not in session:
        return redirect(url_for("recuperar_contrasena"))

    if request.method == "POST" and "respuesta" in request.form:
        respuesta = request.form["respuesta"]
        username = session["recuperar_username"]

        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute(
            "SELECT * FROM usuarios WHERE cedula = %s AND status = 1;", (username,)
        )
        user = cursor.fetchone()

        if user and bcrypt.check_password_hash(user["respuesta_seguridad"], respuesta):
            return redirect(url_for("cambiar_contrasena"))
        else:
            flash("Respuesta incorrecta")

    return render_template(
        "verificar_respuesta.html", pregunta_secreta=session["pregunta_seguridad"]
    )


@app.route("/cambiar_contrasena", methods=["GET", "POST"])
def cambiar_contrasena():
    if "recuperar_username" not in session:
        return redirect(url_for("recuperar_contrasena"))

    if request.method == "POST" and "nueva_contrasena" in request.form:
        nueva_contrasena = request.form["nueva_contrasena"]
        username = session["recuperar_username"]

        hash_de_nueva_contrasena = bcrypt.generate_password_hash(
            nueva_contrasena
        ).decode("utf-8")

        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute(
            "UPDATE usuarios SET hash_de_contrasena = %s WHERE cedula = %s",
            (hash_de_nueva_contrasena, username),
        )
        mysql.connection.commit()
        cursor.close()

        session.pop("recuperar_username", None)
        session.pop("pregunta_secreta", None)
        flash("Contraseña cambiada correctamente")
        return redirect(url_for("login"))

    return render_template("cambiar_contrasena.html")


# endregion


# region Transacciones
################################### TRANSACCIONES #####################################################


@app.route("/transacciones", methods=["GET", "POST"])
def transacciones():
    if "loggedin" not in session:
        return redirect(url_for("login"))

    fecha_inicio = request.form.get("fecha_inicio")
    fecha_fin = request.form.get("fecha_fin")

    cursor = mysql.connection.cursor()

    if fecha_inicio and fecha_fin:
        query = """
        SELECT t.id, t.marca_de_tiempo, t.importe_en_dolares, t.tasa_bcv, 
               t.clientes_id, t.proveedores_id, t.usuarios_id, 
               tp.productos_id, tp.cantidad,
               c.nombre AS cliente, prov.nombre AS proveedor, u.nombre AS usuario
        FROM transacciones t
        LEFT JOIN transacciones_tiene_productos tp ON t.id = tp.transacciones_id
        LEFT JOIN clientes c ON t.clientes_id = c.id
        LEFT JOIN proveedores prov ON t.proveedores_id = prov.id
        LEFT JOIN usuarios u ON t.usuarios_id = u.id
        WHERE t.marca_de_tiempo BETWEEN %s AND %s
        ORDER BY t.marca_de_tiempo DESC;
        """
        cursor.execute(query, (fecha_inicio, fecha_fin))
    else:
        query = """
        SELECT t.id, t.marca_de_tiempo, t.importe_en_dolares, t.tasa_bcv, 
               t.clientes_id, t.proveedores_id, t.usuarios_id, 
               tp.productos_id, tp.cantidad,
               c.nombre AS cliente, prov.nombre AS proveedor, u.nombre AS usuario
        FROM transacciones t
        LEFT JOIN transacciones_tiene_productos tp ON t.id = tp.transacciones_id
        LEFT JOIN clientes c ON t.clientes_id = c.id
        LEFT JOIN proveedores prov ON t.proveedores_id = prov.id
        LEFT JOIN usuarios u ON t.usuarios_id = u.id
        ORDER BY t.marca_de_tiempo DESC;
        """
        cursor.execute(query)

    # Obtener los resultados como tuplas
    transacciones = cursor.fetchall()

    # Convertir las tuplas a diccionarios si es necesario
    transacciones_dict = []
    for transaccion in transacciones:
        transaccion_dict = {
            "id": transaccion[0],
            "marca_de_tiempo": transaccion[1],
            "importe_en_dolares": transaccion[2],
            "tasa_bcv": transaccion[3],
            "clientes_id": transaccion[4],
            "proveedores_id": transaccion[5],
            "usuarios_id": transaccion[6],
            "productos_id": transaccion[7],
            "cantidad": transaccion[8],
            "cliente": transaccion[9],
            "proveedor": transaccion[10],
            "usuario": transaccion[11],
        }
        transacciones_dict.append(transaccion_dict)

    cursor.close()

    return render_template(
        "transacciones.html",
        username=session["username"],
        rol=session["rol"],
        transacciones=transacciones_dict,
        current_page="transacciones",
    )


def generar_reporte_pdf(transaccion, productos):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    # Encabezado del reporte
    pdf.cell(200, 10, f"Transacción ID: {transaccion[0]}", ln=True)
    pdf.cell(200, 10, f"Marca de tiempo: {transaccion[1]}", ln=True)
    pdf.cell(200, 10, f"Importe en dólares: {transaccion[2]}", ln=True)
    pdf.cell(200, 10, f"Tasa BCV: {transaccion[3]}", ln=True)
    pdf.cell(
        200, 10, f"Cliente: {transaccion[4] if transaccion[4] else 'N/A'}", ln=True
    )
    pdf.cell(
        200, 10, f"Proveedor: {transaccion[5] if transaccion[5] else 'N/A'}", ln=True
    )
    pdf.cell(200, 10, f"Realizada por: {transaccion[6]}", ln=True)
    pdf.ln(10)

    # Detalles de los productos
    pdf.set_font("Arial", "B", 12)
    pdf.cell(200, 10, "Productos Comprados:", ln=True)
    pdf.set_font("Arial", size=12)

    for producto in productos:
        pdf.cell(200, 10, f"Producto ID: {producto[0]}", ln=True)
        pdf.cell(200, 10, f"Cantidad: {producto[1]}", ln=True)
        pdf.ln(5)

    # Guardar y devolver el archivo PDF
    filename = f"reporte_transaccion_{transaccion[0]}.pdf"
    pdf.output(filename)

    return filename


@app.route("/generar_reporte/<int:transaccion_id>", methods=["POST"])
def generar_reporte(transaccion_id):
    if "loggedin" not in session:
        return redirect(url_for("login"))

    cursor = mysql.connection.cursor()

    # Obtener detalles de la transacción
    cursor.execute("SELECT * FROM transacciones WHERE id = %s", (transaccion_id,))
    transaccion = cursor.fetchone()

    # Obtener detalles de los productos comprados en esa transacción
    cursor.execute(
        """
        SELECT tp.productos_id, tp.cantidad 
        FROM transacciones_tiene_productos tp
        WHERE tp.transacciones_id = %s
    """,
        (transaccion_id,),
    )
    productos = cursor.fetchall()

    cursor.close()

    # Generar el reporte PDF
    pdf = generar_reporte_pdf(transaccion, productos)

    # Enviar el archivo PDF como una descarga
    return send_file(pdf, as_attachment=True, mimetype="application/pdf")


# region Reportes
################################### REPORTES ##########################################


@app.route("/reportes")
def reportes():
    if "loggedin" in session and session["rol"] == "administrador":
        return render_template(
            "reportes.html",
            username=session["username"],
            rol=session["rol"],
            reportes=reportes,
            current_page="reportes",
        )

    return redirect(url_for("dashboard"))


@app.route("/productos_reporte", methods=["GET"])
def productos_reporte():
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM productos")
    productos = cursor.fetchall()
    cursor.close()

    if not productos:
        return redirect(url_for("reportes"))

    # init pdf engine
    pdf = PDF(title="Reporte de productos")
    pdf.add_page()
    pdf.set_font("Times", size=14)

    # format data
    for producto in productos:
        producto["precio_en_bolivares"] = float(
            f"{float(producto['precio_en_dolares']) * get_tasa_bcv():,.2f}"
        )
        producto["status"] = "Activo" if producto["status"] else "Inactivo"
        producto["cantidad_disponible"] = f"{producto['cantidad_disponible']} unidades"
        producto["precio_en_bolivares"] = f"Bs. {producto['precio_en_bolivares']}"
        producto["precio_en_dolares"] = f"${producto['precio_en_dolares']}"
        producto["fecha_de_vencimiento"] = producto["fecha_de_vencimiento"].strftime(
            "%Y-%m-%d"
        )

    # order of columns in table
    desired_order = {
        "nombre": "Nombre",
        "cantidad_disponible": "Cantidad disponible",
        "precio_en_dolares": "Precio en dólares",
        "precio_en_bolivares": "Precio en bolívares",
        "fecha_de_vencimiento": "Fecha de vencimiento",
        "status": "Estado",
    }
    ordered_productos = [
        {desired_order[key]: producto[key] for key in desired_order}
        for producto in productos
    ]

    # create report
    with pdf.table() as table:
        # header
        header_row = table.row()
        for cell in desired_order.values():
            header_row.cell(
                str(cell),
                align="C",
            )

        # content
        for data_row in ordered_productos:
            row = table.row()
            for i, datum in enumerate(data_row):
                # imprimir el nombre del producto en negrita y a la izquierda
                if i == 0:
                    pdf.set_font("Times", "B", 14)
                    row.cell(
                        str(data_row[datum]),
                        align="L",
                    )
                    pdf.set_font("Times", size=14)
                else:
                    row.cell(
                        str(data_row[datum]),
                        align="R",
                    )

    # save report
    filename = f"{datetime.now().strftime('%Y-%m-%d')}_productos.pdf"
    filepath = f"{app.config['REPORTES_FOLDER']}/{filename}"
    pdf.output(filepath)

    return send_file(filepath, as_attachment=True, mimetype="application/pdf")


@app.route("/clientes_reporte", methods=["GET"])
def clientes_reporte():
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM clientes")
    clientes = cursor.fetchall()
    cursor.close()

    if not clientes:
        return redirect(url_for("reportes"))

    # init pdf engine
    pdf = PDF(title="Reporte de clientes")
    pdf.add_page()
    pdf.set_font("Times", size=14)

    # format data
    for cliente in clientes:
        cliente["status"] = "Activo" if cliente["status"] else "Inactivo"

    # order of columns in table
    desired_order = {
        "nombre": "Nombre",
        "cedula": "Cédula",
        "direccion": "Dirección",
        "telefono": "Teléfono",
        "status": "Estado",
    }
    ordered_clientes = [
        {desired_order[key]: cliente[key] for key in desired_order}
        for cliente in clientes
    ]

    # create report
    with pdf.table() as table:
        # header
        header_row = table.row()
        for cell in desired_order.values():
            header_row.cell(
                str(cell),
                align="C",
            )

        # content
        for data_row in ordered_clientes:
            row = table.row()
            for i, datum in enumerate(data_row):
                # imprimir el nombre del cliente en negrita y a la izquierda
                if i == 0:
                    pdf.set_font("Times", "B", 14)
                    row.cell(
                        str(data_row[datum]),
                        align="L",
                    )
                    pdf.set_font("Times", size=14)
                else:
                    row.cell(
                        str(data_row[datum]),
                        align="R",
                    )

    # save report
    filename = f"{datetime.now().strftime('%Y-%m-%d')}_clientes.pdf"
    filepath = f"{app.config['REPORTES_FOLDER']}/{filename}"
    pdf.output(filepath)

    return send_file(filepath, as_attachment=True, mimetype="application/pdf")


@app.route("/proveedores_reporte", methods=["GET"])
def proveedores_reporte():
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM proveedores")
    proveedores = cursor.fetchall()
    cursor.close()

    if not proveedores:
        return redirect(url_for("reportes"))

    # init pdf engine
    pdf = PDF(title="Reporte de proveedores")
    pdf.add_page()
    pdf.set_font("Times", size=14)

    # format data
    for proveedor in proveedores:
        proveedor["status"] = "Activo" if proveedor["status"] else "Inactivo"

    # order of columns in table
    desired_order = {
        "nombre": "Nombre",
        "rif": "RIF",
        "direccion": "Dirección",
        "status": "Estado",
    }
    ordered_clientes = [
        {desired_order[key]: proveedor[key] for key in desired_order}
        for proveedor in proveedores
    ]

    # create report
    with pdf.table() as table:
        # header
        header_row = table.row()
        for cell in desired_order.values():
            header_row.cell(
                str(cell),
                align="C",
            )

        # content
        for data_row in ordered_clientes:
            row = table.row()
            for i, datum in enumerate(data_row):
                # imprimir el nombre del cliente en negrita y a la izquierda
                if i == 0:
                    pdf.set_font("Times", "B", 14)
                    row.cell(
                        str(data_row[datum]),
                        align="L",
                    )
                    pdf.set_font("Times", size=14)
                else:
                    row.cell(
                        str(data_row[datum]),
                        align="R",
                    )

    # save report
    filename = f"{datetime.now().strftime('%Y-%m-%d')}_proveedores.pdf"
    filepath = f"{app.config['REPORTES_FOLDER']}/{filename}"
    pdf.output(filepath)

    return send_file(filepath, as_attachment=True, mimetype="application/pdf")


@app.route("/usuarios_reporte", methods=["GET"])
def usuarios_reporte():
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM usuarios")
    usuarios = cursor.fetchall()
    cursor.close()

    if not usuarios:
        return redirect(url_for("reportes"))

    # init pdf engine
    pdf = PDF(title="Reporte de usuarios")
    pdf.add_page()
    pdf.set_font("Times", size=14)

    # format data
    for proveedor in usuarios:
        proveedor["status"] = "Activo" if proveedor["status"] else "Inactivo"

    # order of columns in table
    desired_order = {
        "nombre": "Nombre",
        "cedula": "Cédula",
        "rol": "Rol",
        "status": "Estado",
    }
    ordered_clientes = [
        {desired_order[key]: proveedor[key] for key in desired_order}
        for proveedor in usuarios
    ]

    # create report
    with pdf.table() as table:
        # header
        header_row = table.row()
        for cell in desired_order.values():
            header_row.cell(
                str(cell),
                align="C",
            )

        # content
        for data_row in ordered_clientes:
            row = table.row()
            for i, datum in enumerate(data_row):
                # imprimir el nombre del cliente en negrita y a la izquierda
                if i == 0:
                    pdf.set_font("Times", "B", 14)
                    row.cell(
                        str(data_row[datum]),
                        align="L",
                    )
                    pdf.set_font("Times", size=14)
                else:
                    row.cell(
                        str(data_row[datum]),
                        align="R",
                    )

    # save report
    filename = f"{datetime.now().strftime('%Y-%m-%d')}_usuarios.pdf"
    filepath = f"{app.config['REPORTES_FOLDER']}/{filename}"
    pdf.output(filepath)

    return send_file(filepath, as_attachment=True, mimetype="application/pdf")


@app.route("/ventas_reporte", methods=["GET"])
def ventas_reporte():
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM transacciones WHERE clientes_id IS NOT NULL")
    ventas = cursor.fetchall()

    if not ventas:
        return redirect(url_for("reportes"))

    # init pdf engine
    pdf = PDF(title="Reporte de ventas")
    pdf.add_page()
    pdf.set_font("Times", size=14)

    # format data
    for venta in ventas:
        venta["importe_en_bolivares"] = (
            f"Bs. {float(venta['importe_en_dolares']) * get_tasa_bcv():.2f}"
        )
        venta["importe_en_dolares"] = f"$ {venta['importe_en_dolares']}"
        venta["marca_de_tiempo"] = venta["marca_de_tiempo"].strftime(
            "%d-%m-%Y %H:%M:%S"
        )
        venta["tasa_bcv"] = f"Bs. {venta['tasa_bcv']:.2f}"
        cursor.execute(
            "SELECT nombre FROM usuarios WHERE id = %s", (venta["usuarios_id"],)
        )
        venta["usuarios_id"] = cursor.fetchone()["nombre"]
        cursor.execute(
            "SELECT nombre FROM clientes WHERE id = %s", (venta["clientes_id"],)
        )
        venta["clientes_id"] = cursor.fetchone()["nombre"]

    cursor.close()

    # order of columns in table
    desired_order = {
        "marca_de_tiempo": "Marca de tiempo",
        "tasa_bcv": "Tasa BCV",
        "importe_en_dolares": "Importe en dólares",
        "clientes_id": "Cliente",
        "usuarios_id": "Ejecutado por",
    }
    ordered_clientes = [
        {desired_order[key]: venta[key] for key in desired_order} for venta in ventas
    ]

    # create report
    with pdf.table() as table:
        # header
        header_row = table.row()
        for cell in desired_order.values():
            header_row.cell(
                str(cell),
                align="C",
            )

        # content
        for data_row in ordered_clientes:
            row = table.row()
            for i, datum in enumerate(data_row):
                # imprimir el nombre del cliente en negrita y a la izquierda
                if i == 0:
                    pdf.set_font("Times", "B", 14)
                    row.cell(
                        str(data_row[datum]),
                        align="L",
                    )
                    pdf.set_font("Times", size=14)
                else:
                    row.cell(
                        str(data_row[datum]),
                        align="R",
                    )

    # save report
    filename = f"{datetime.now().strftime('%Y-%m-%d')}_ventas.pdf"
    filepath = f"{app.config['REPORTES_FOLDER']}/{filename}"
    pdf.output(filepath)

    return send_file(filepath, as_attachment=True, mimetype="application/pdf")


@app.route("/compras_reporte", methods=["GET"])
def compras_reporte():
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM transacciones WHERE proveedores_id IS NOT NULL")
    compras = cursor.fetchall()

    if not compras:
        return redirect(url_for("reportes"))

    # init pdf engine
    pdf = PDF(title="Reporte de compras")
    pdf.add_page()
    pdf.set_font("Times", size=14)

    # format data
    for compra in compras:
        compra["importe_en_bolivares"] = (
            f"Bs. {float(compra['importe_en_dolares']) * get_tasa_bcv():.2f}"
        )
        compra["importe_en_dolares"] = f"$ {compra['importe_en_dolares']}"
        compra["marca_de_tiempo"] = compra["marca_de_tiempo"].strftime(
            "%d-%m-%Y %H:%M:%S"
        )
        compra["tasa_bcv"] = f"Bs. {compra['tasa_bcv']:.2f}"
        cursor.execute(
            "SELECT nombre FROM usuarios WHERE id = %s", (compra["usuarios_id"],)
        )
        compra["usuarios_id"] = cursor.fetchone()["nombre"]
        cursor.execute(
            "SELECT nombre FROM proveedores WHERE id = %s", (compra["proveedores_id"],)
        )
        compra["proveedores_id"] = cursor.fetchone()["nombre"]

    cursor.close()

    # order of columns in table
    desired_order = {
        "marca_de_tiempo": "Marca de tiempo",
        "tasa_bcv": "Tasa BCV",
        "importe_en_dolares": "Importe en dólares",
        "proveedores_id": "Proveedor",
        "usuarios_id": "Ejecutado por",
    }
    ordered_clientes = [
        {desired_order[key]: compra[key] for key in desired_order} for compra in compras
    ]

    # create report
    with pdf.table() as table:
        # header
        header_row = table.row()
        for cell in desired_order.values():
            header_row.cell(
                str(cell),
                align="C",
            )

        # content
        for data_row in ordered_clientes:
            row = table.row()
            for i, datum in enumerate(data_row):
                # imprimir el nombre del cliente en negrita y a la izquierda
                if i == 0:
                    pdf.set_font("Times", "B", 14)
                    row.cell(
                        str(data_row[datum]),
                        align="L",
                    )
                    pdf.set_font("Times", size=14)
                else:
                    row.cell(
                        str(data_row[datum]),
                        align="R",
                    )

    # save report
    filename = f"{datetime.now().strftime('%Y-%m-%d')}_compras.pdf"
    filepath = f"{app.config['REPORTES_FOLDER']}/{filename}"
    pdf.output(filepath)

    return send_file(filepath, as_attachment=True, mimetype="application/pdf")


# endregion


# region Herramientas
################################### HERRAMIENTAS ######################################


@app.route("/herramientas")
def herramientas():
    if "loggedin" not in session or session["rol"] != "administrador":
        return redirect(url_for("dashboard"))

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM usuarios")
    all_users = cursor.fetchall()
    cursor.close()

    return render_template(
        "herramientas.html",
        username=session["username"],
        rol=session["rol"],
        usuarios=all_users,
        herramientas=herramientas,
        current_page="herramientas",
    )


@app.route("/agregar_empleado", methods=["GET", "POST"])
def agregar_empleado():
    if request.method == "POST":
        cedula = request.form["cedula"]
        nombre = request.form["nombre"]
        rol = request.form["rol"]
        hash_de_contrasena = bcrypt.generate_password_hash(
            request.form["hash_contrasena"]
        ).decode("utf-8")
        pregunta_seguridad = request.form["pregunta_seguridad"]
        respuesta_seguridad = bcrypt.generate_password_hash(
            request.form["respuesta_seguridad"]
        ).decode("utf-8")

        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

        # Verificar si el empleado ya existe
        cursor.execute("SELECT * FROM usuarios WHERE cedula = %s", (cedula,))
        empleado_existente = cursor.fetchone()

        if empleado_existente:
            if empleado_existente["status"] == 0:
                cursor.execute(
                    "UPDATE usuarios SET nombre = %s, rol = %s, hash_de_contrasena = %s, pregunta_seguridad = %s, respuesta_seguridad = %s, status = 1 WHERE cedula = %s",
                    (
                        nombre,
                        rol,
                        hash_de_contrasena,
                        pregunta_seguridad,
                        respuesta_seguridad,
                        cedula,
                    ),
                )
                mysql.connection.commit()
                flash("Empleado actualizado y reactivado correctamente", "success")
            else:
                flash("El empleado ya existe y está activo.", "warning")
        else:
            cursor.execute(
                "INSERT INTO usuarios (cedula, nombre, rol, hash_de_contrasena, pregunta_seguridad, respuesta_seguridad, status) VALUES (%s, %s, %s, %s, %s, %s, 1)",
                (
                    cedula,
                    nombre,
                    rol,
                    hash_de_contrasena,
                    pregunta_seguridad,
                    respuesta_seguridad,
                ),
            )
            mysql.connection.commit()
            flash("Empleado agregado correctamente", "success")

        cursor.close()

        return redirect(url_for("herramientas"))

    return render_template("herramientas.html")


@app.route("/actualizar_empleado", methods=["POST"])
def actualizar_empleado():
    if "loggedin" not in session:
        return redirect(url_for("login"))

    empleado_id = request.form.get("empleado_id_actualizar")
    cedula = request.form["cedula_actualizar"]
    nombre = request.form["nombre_actualizar"]
    rol = request.form["rol_actualizar"]
    status = request.form["status_actualizar"]

    try:
        cursor = mysql.connection.cursor()
        cursor.execute(
            """
            UPDATE usuarios
            SET cedula = %s, nombre = %s, rol = %s, status = %s
            WHERE id = %s
            """,
            (cedula, nombre, rol, status, empleado_id),
        )
        mysql.connection.commit()
        cursor.close()

        flash("Empleado actualizado correctamente", "success")
        return redirect(url_for("herramientas"))

    except MySQLdb.Error as e:
        flash(f"Error al actualizar empleado: {str(e)}", "error")
        return redirect(url_for("herramientas"))

    finally:
        cursor.close()


@app.route("/eliminar_usuarios", methods=["POST"])
def eliminar_usuarios():
    # Verificar si el usuario está logueado
    if "loggedin" not in session:
        return redirect(url_for("login"))

    # Obtener los IDs de los usuarios a eliminar del formulario
    usuario_ids = request.form.getlist("empleado_ids")

    if not usuario_ids:
        flash("Seleccione al menos un empleado para eliminar.", "error")
        return redirect(url_for("herramientas"))

    # Conectar a la base de datos y eliminar los usuarios seleccionados
    try:
        cursor = mysql.connection.cursor()

        for usuario_id in usuario_ids:
            cursor.execute(
                "UPDATE usuarios SET status = %s WHERE id = %s", (0, usuario_id)
            )

        mysql.connection.commit()
        cursor.close()

        flash("Usuarios eliminados correctamente", "success")
        return redirect(url_for("herramientas"))

    except MySQLdb.Error as e:
        flash(f"Error al eliminar usuarios: {str(e)}", "error")
        return redirect(url_for("herramientas"))

    finally:
        cursor.close()


@app.route("/listar_empleados", methods=["GET", "POST"])
def listar_empleados():
    if "loggedin" not in session:
        return redirect(url_for("login"))

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    if request.method == "POST" and "buscar_empleado" in request.form:
        termino_busqueda = request.form["buscar_empleado"]
        query = """
            SELECT * FROM usuarios
            WHERE rol = 'empleado' AND status = 1
            AND (id LIKE %s OR nombre LIKE %s OR cedula LIKE %s);
        """
        cursor.execute(
            query,
            (
                "%" + termino_busqueda + "%",
                "%" + termino_busqueda + "%",
                "%" + termino_busqueda + "%",
            ),
        )
    else:
        query = "SELECT * FROM usuarios WHERE rol = 'empleado' AND status = 1;"
        cursor.execute(query)

    empleados = cursor.fetchall()
    cursor.close()

    return render_template(
        "herramientas.html",
        username=session.get("username"),
        rol=session.get("rol"),
        empleados=empleados,
    )


# region BACKUP
@app.route("/respaldar_base", methods=["POST"])
def respaldar_base():
    NOMBRE = "camicandy.sql"

    base = subprocess.run(
        ["C:\\xampp\\mysql\\bin\\mysqldump.exe", "camicandy", "-u", "root"],
        capture_output=True,
        text=True,
    ).stdout

    # with open(NOMBRE, mode="w") as f:
    #    f.write(base)

    return send_file(NOMBRE, as_attachment=True)


# region RESTORE
@app.route("/recuperar_base", methods=["POST"])
def recuperar_base():
    if request.method == "GET":
        return redirect(url_for("herramientas"))
    else:
        if "file" not in request.files:
            flash("No file part", "danger")
            return redirect(url_for("herramientas"))
        file = request.files["file"]
        if file.filename == "":
            flash("No selected file", "danger")
            return redirect(request.url)

        if file and file.filename.rsplit(".", 1)[1].lower() == "sql":
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)
            flash("File uploaded", "success")

            try:
                # Dropear db vieja
                subprocess.run(
                    [
                        "C:\\xampp\\mysql\\bin\\mysqladmin.exe",
                        "-f",
                        "-u",
                        "root",
                        "drop",
                        "camicandy",
                    ],
                    check=True,
                )

                # Crear db de nuevo
                subprocess.run(
                    [
                        "C:\\xampp\\mysql\\bin\\mysqladmin.exe",
                        "-u",
                        "root",
                        "create",
                        "camicandy",
                    ],
                    check=True,
                )

                # Restaurar db
                abs_filepath = os.path.abspath(filepath)
                with open(abs_filepath, "r") as file:
                    subprocess.run(
                        ["C:\\xampp\\mysql\\bin\\mysql.exe", "-u", "root", "camicandy"],
                        stdin=file,
                        check=True,
                    )

                flash("Database restored successfully", "success")
            except subprocess.CalledProcessError as e:
                flash(f"An error occurred: {e}", "error")
                return redirect(url_for("herramientas"))

            # Mantenerse en la sección de herramientas
            return redirect(url_for("herramientas"))
        else:
            flash("Invalid file type", "danger")
            return redirect(request.url)


@app.route("/buscar_productos", methods=["GET"])
def buscar_productos():
    if "loggedin" not in session:
        return redirect(url_for("login"))

    criterio = request.args.get("criterio", "")

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(
        "SELECT * FROM productos WHERE nombre LIKE %s AND status = %s",
        ("%" + criterio + "%", True),
    )
    productos = cursor.fetchall()
    cursor.close()

    return render_template(
        "venta.html",
        productos=productos,
        username=session["username"],
        rol=session["rol"],
    )


# region CERRAR SESION
@app.route("/logout")
def logout():
    session.pop("loggedin", None)
    session.pop("id", None)
    session.pop("username", None)
    session.pop("rol", None)
    return redirect(url_for("login"))


@app.errorhandler(404)
def page_not_found(e):
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(debug=True)
