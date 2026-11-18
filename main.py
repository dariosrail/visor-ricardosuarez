# -*- coding: utf-8 -*-
"""
ESTACIONAMIENTO EN EL CELULAR (Flet web) - solo consulta.

Una sola pantalla:
  * Tarjetas arriba: total de caja, efectivo, tarjeta, transferencia, autos adentro
    (con lo que llevan acumulado), convenio hotel y pensionados.
  * Pestañas: 🚗 Adentro · ✅ Cobrados · 📊 Resumen.
  * Periodo: Hoy, Ayer, Turno abierto o un rango de fechas (histórico).
  * Buscador por placa. Se actualiza solo cada 30 segundos.

Varias empresas: la tabla ESTAC_EMPRESAS (en la base de control) guarda a qué base
sincronizada se conecta cada estacionamiento y con qué usuario/clave entra su dueño.
El administrador (APP_USUARIO / APP_CLAVE) ve todas, las da de alta y cambia entre ellas.

Corre en Railway (ver LEEME.md). Variables:
  MYSQL_URL     base de control (o DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME)
  APP_USUARIO   usuario ADMINISTRADOR
  APP_CLAVE     contraseña del administrador (si no hay empresas y no pones clave, entra directo)
  NEGOCIO       nombre que sale arriba     (opcional)
  TZ_NEGOCIO    zona horaria               (opcional, America/Merida)
"""
import os
import threading
import time
from datetime import datetime

import flet as ft

import estac_datos as dat

NEGOCIO = os.getenv("NEGOCIO", "Estacionamiento")
APP_USUARIO = os.getenv("APP_USUARIO", "admin")
APP_CLAVE = os.getenv("APP_CLAVE", "")
CADA_SEGUNDOS = 30

AZUL, VERDE, NARANJA, MORADO, GRIS = "#1A237E", "#2E7D32", "#E65100", "#6A1B9A", "#546E7A"
COLOR_TIPO = {"NORMAL": "#1565C0", "MEDIO DÍA": "#00838F", "DÍA 24 H": "#00695C", "RESTAURANTE": "#AD1457",
              "HOTEL": "#8D6E00", "PENSIONADO": "#4527A0", "BAÑO": "#5D4037", "SERVICIO": "#455A64"}


def dinero(v):
    return f"$ {float(v or 0):,.2f}"


def main(page: ft.Page):
    page.title = NEGOCIO
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = "#ECEFF1"
    page.padding = 0
    page.theme = ft.Theme(color_scheme_seed=AZUL)

    estado = {"modo": "hoy", "desde": dat.ahora().date(), "hasta": dat.ahora().date(),
              "datos": None, "vivo": True, "ocupado": False, "hilo": False,
              "empresa": None, "admin": False, "opciones": []}

    def aviso(texto, error=False):
        page.open(ft.SnackBar(ft.Text(texto), bgcolor="#B71C1C" if error else None))

    # ───────────────────────── tarjetas ─────────────────────────
    def tarjeta(titulo, valor, sub="", color=AZUL, col=6):
        return ft.Container(
            col={"xs": col, "sm": 3},
            bgcolor="white", border_radius=12, padding=12,
            border=ft.border.only(left=ft.BorderSide(5, color)),
            content=ft.Column([
                ft.Text(titulo, size=12, color=GRIS, weight=ft.FontWeight.W_600),
                ft.Text(valor, size=20, weight=ft.FontWeight.BOLD, color=color),
                ft.Text(sub, size=11, color=GRIS) if sub else ft.Container(height=0),
            ], spacing=2))

    fila_tarjetas = ft.ResponsiveRow(spacing=8, run_spacing=8)

    # ───────────────────────── renglones ─────────────────────────
    def chip(tipo):
        return ft.Container(ft.Text(tipo, size=11, color="white", weight=ft.FontWeight.BOLD),
                            bgcolor=COLOR_TIPO.get(tipo, GRIS), border_radius=10,
                            padding=ft.padding.symmetric(vertical=2, horizontal=8))

    def renglon_adentro(x):
        entrada = dat.a_datetime(x.get("fechae"))
        return ft.Container(
            bgcolor="white", border_radius=10, padding=10,
            content=ft.Row([
                ft.Column([
                    ft.Row([ft.Text(str(x.get("placas") or ""), size=17, weight=ft.FontWeight.BOLD),
                            chip(x["tipo"])], spacing=8, wrap=True),
                    ft.Text(f"Entró {entrada:%d/%m %H:%M}" if entrada else "", size=12, color=GRIS),
                    ft.Text(f"⏱ {x['tiempo']}   ·   {x['folio_txt']}", size=12, color=GRIS),
                ], spacing=2, expand=True),
                ft.Column([ft.Text(dinero(x["importe"]), size=17, weight=ft.FontWeight.BOLD, color=NARANJA),
                           ft.Text("lleva", size=11, color=GRIS)],
                          horizontal_alignment=ft.CrossAxisAlignment.END, spacing=0),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER))

    def renglon_cobrado(x):
        sale = dat.a_datetime(x.get("fechas"))
        formas = [(n, dat.num(x.get(k))) for n, k in (("Efe", "efectivo"), ("Tar", "tarjeta"),
                                                      ("Tra", "transferencia"))]
        pago = " · ".join(f"{n} {dinero(v)}" for n, v in formas if v) or (
            "Convenio" if x["tipo"] == "HOTEL" else "Sin cobro" if x["tipo"] == "PENSIONADO" else "")
        return ft.Container(
            bgcolor="white", border_radius=10, padding=10,
            content=ft.Row([
                ft.Column([
                    ft.Row([ft.Text(str(x.get("placas") or ""), size=16, weight=ft.FontWeight.BOLD),
                            chip(x["tipo"])], spacing=8, wrap=True),
                    ft.Text((f"Salió {sale:%d/%m %H:%M}" if sale else "") + f"   ·   ⏱ {x.get('tiempo') or '--'}",
                            size=12, color=GRIS),
                    ft.Text(pago, size=12, color=GRIS),
                ], spacing=2, expand=True),
                ft.Text(dinero(x.get("importe")), size=16, weight=ft.FontWeight.BOLD,
                        color=VERDE if x["tipo"] not in ("HOTEL", "PENSIONADO") else GRIS),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER))

    lista_adentro = ft.ListView(expand=True, spacing=6, padding=10)
    lista_cobrados = ft.ListView(expand=True, spacing=6, padding=10)
    vista_resumen = ft.ListView(expand=True, spacing=8, padding=10)

    buscar = ft.TextField(hint_text="Buscar placa…", prefix_icon=ft.Icons.SEARCH, dense=True,
                          bgcolor="white", border_radius=10, expand=True,
                          capitalization=ft.TextCapitalization.CHARACTERS,
                          on_change=lambda e: pintar())

    # ───────────────────────── resumen ─────────────────────────
    def renglon_res(nombre, valor, color=AZUL, negrita=False):
        return ft.Row([ft.Text(nombre, size=15, expand=True, weight=ft.FontWeight.BOLD if negrita else None),
                       ft.Text(valor, size=15, color=color, weight=ft.FontWeight.BOLD)])

    def caja_res(titulo, filas):
        return ft.Container(bgcolor="white", border_radius=12, padding=14,
                            content=ft.Column([ft.Text(titulo, size=13, color=GRIS, weight=ft.FontWeight.BOLD),
                                               ft.Divider(height=6)] + filas, spacing=6))

    def pintar_resumen(d):
        r = d["resumen"]
        vista_resumen.controls = [
            caja_res(f"CAJA · {d['titulo']}", [
                renglon_res("💵 Efectivo", dinero(r["efectivo"]), VERDE),
                renglon_res("💳 Tarjeta", dinero(r["tarjeta"]), AZUL),
                renglon_res("📱 Transferencia", dinero(r["transferencia"]), MORADO),
                ft.Divider(height=4),
                renglon_res(f"TOTAL CAJA ({r['tickets_caja']} tickets)", dinero(r["caja"]), VERDE, True),
            ]),
            caja_res("POR TIPO (caja)", [
                renglon_res(f"{tipo}  ({n})", dinero(imp), COLOR_TIPO.get(tipo, GRIS))
                for tipo, (n, imp) in sorted(r["por_tipo"].items(), key=lambda kv: -kv[1][1])
            ] or [ft.Text("Sin cobros en el periodo", color=GRIS)]),
            caja_res("NO SUMAN A CAJA", [
                renglon_res(f"🏨 Convenio hotel ({r['tickets_hotel']})", dinero(r["hotel"]), COLOR_TIPO["HOTEL"]),
                renglon_res("🅿 Pensionados", f"{r['pensionados']} mov.", COLOR_TIPO["PENSIONADO"]),
            ]),
            caja_res("AHORITA ADENTRO", [
                renglon_res(f"🚗 Vehículos ({r['adentro']})", dinero(r["adentro_estimado"]), NARANJA),
                ft.Text("Lo que llevan acumulado si salieran en este momento.", size=11, color=GRIS),
            ]),
        ]

    # ───────────────────────── pintar todo ─────────────────────────
    tabs = ft.Tabs(selected_index=0, expand=1, animation_duration=150, tabs=[
        ft.Tab(text="🚗 Adentro", content=lista_adentro),
        ft.Tab(text="✅ Cobrados", content=lista_cobrados),
        ft.Tab(text="📊 Resumen", content=vista_resumen),
    ])
    lb_periodo = ft.Text("", size=13, color="white")
    lb_hora = ft.Text("", size=11, color="#C5CAE9")

    def pintar():
        d = estado["datos"]
        if not d:
            return
        filtro = (buscar.value or "").strip().upper()
        dentro = [x for x in d["adentro"] if filtro in str(x.get("placas") or "").upper()]
        fuera = [x for x in d["cobrados"] if filtro in str(x.get("placas") or "").upper()]
        r = d["resumen"]
        fila_tarjetas.controls = [
            tarjeta("Total caja", dinero(r["caja"]), f"{r['tickets_caja']} tickets", VERDE),
            tarjeta("Efectivo", dinero(r["efectivo"]), color=VERDE),
            tarjeta("Tarjeta", dinero(r["tarjeta"]), color=AZUL),
            tarjeta("Transferencia", dinero(r["transferencia"]), color=MORADO),
            tarjeta("Adentro", f"{r['adentro']} autos", dinero(r["adentro_estimado"]) + " acumulado", NARANJA),
            tarjeta("Convenio hotel", dinero(r["hotel"]), f"{r['tickets_hotel']} mov. · no es caja",
                    COLOR_TIPO["HOTEL"]),
        ]
        lista_adentro.controls = [renglon_adentro(x) for x in dentro] or [
            ft.Text("No hay vehículos adentro." if not filtro else "Sin coincidencias.", color=GRIS)]
        lista_cobrados.controls = [renglon_cobrado(x) for x in fuera] or [
            ft.Text("Sin cobros en el periodo." if not filtro else "Sin coincidencias.", color=GRIS)]
        tabs.tabs[0].text = f"🚗 Adentro ({len(dentro)})"
        tabs.tabs[1].text = f"✅ Cobrados ({len(fuera)})"
        pintar_resumen(d)
        ses = d["sesion"]
        lb_periodo.value = d["titulo"] + (f"   ·   Turno abierto {ses['turno']:02d} ({ses['dia']})" if ses else "")
        lb_hora.value = f"Actualizado {d['hora']:%H:%M:%S}"
        page.update()

    def cargar(e=None):
        if estado["ocupado"]:
            return
        estado["ocupado"] = True
        barra.visible = True
        page.update()
        try:
            estado["datos"] = dat.consultar(estado["modo"], estado["desde"], estado["hasta"],
                                            estado["empresa"])
            pintar()
        except Exception as ex:
            aviso(f"No pude leer la base: {ex}", True)
        finally:
            estado["ocupado"] = False
            barra.visible = False
            page.update()

    # ───────────────────────── periodo ─────────────────────────
    def elegir_fecha(cual):
        def cambio(e):
            if e.control.value:
                estado[cual] = e.control.value.date()
                bt_desde.text = f"Del {estado['desde']:%d/%m/%Y}"
                bt_hasta.text = f"Al {estado['hasta']:%d/%m/%Y}"
                cargar()
        hoy = dat.ahora()
        page.open(ft.DatePicker(first_date=hoy.replace(year=hoy.year - 5), last_date=hoy,
                                value=datetime.combine(estado[cual], datetime.min.time()), on_change=cambio,
                                help_text="Fecha", cancel_text="Cancelar", confirm_text="Aceptar"))

    bt_desde = ft.OutlinedButton(f"Del {estado['desde']:%d/%m/%Y}", icon=ft.Icons.CALENDAR_MONTH,
                                 on_click=lambda e: elegir_fecha("desde"))
    bt_hasta = ft.OutlinedButton(f"Al {estado['hasta']:%d/%m/%Y}", icon=ft.Icons.CALENDAR_MONTH,
                                 on_click=lambda e: elegir_fecha("hasta"))
    fila_rango = ft.Row([bt_desde, bt_hasta], wrap=True, visible=False)

    def cambiar_modo(e):
        estado["modo"] = periodo.value
        fila_rango.visible = periodo.value == "rango"
        cargar()

    periodo = ft.Dropdown(value="hoy", dense=True, bgcolor="white", border_radius=10, width=170,
                          options=[ft.dropdown.Option("hoy", "Hoy"), ft.dropdown.Option("ayer", "Ayer"),
                                   ft.dropdown.Option("turno", "Turno abierto"),
                                   ft.dropdown.Option("rango", "Rango de fechas")],
                          on_change=cambiar_modo)

    barra = ft.ProgressBar(visible=False, color=NARANJA, bgcolor="#C5CAE9")

    lb_negocio = ft.Text(f"🅿 {NEGOCIO}", size=19, weight=ft.FontWeight.BOLD, color="white")
    bt_empresas = ft.IconButton(ft.Icons.SWAP_HORIZ, icon_color="white", tooltip="Cambiar empresa",
                                on_click=lambda e: elegir_empresa(), visible=False)
    encabezado = ft.Container(
        bgcolor=AZUL, padding=ft.padding.only(left=14, top=12, right=4, bottom=10),
        content=ft.Row([
            ft.Column([lb_negocio, lb_periodo, lb_hora], spacing=1, expand=True),
            bt_empresas,
            ft.IconButton(ft.Icons.REFRESH, icon_color="white", tooltip="Actualizar", on_click=cargar),
            ft.IconButton(ft.Icons.LOGOUT, icon_color="white", tooltip="Salir", on_click=lambda e: salir()),
        ], spacing=0))

    cuerpo = ft.Column([
        encabezado, barra,
        ft.Container(padding=ft.padding.only(left=10, top=10, right=10, bottom=0), content=ft.Column([
            ft.Row([periodo, buscar], spacing=8),
            fila_rango,
            fila_tarjetas,
        ], spacing=8)),
        tabs,
    ], expand=True, spacing=0)

    # ───────────────────────── entrar ─────────────────────────
    def mostrar_app(empresa=None):
        estado["empresa"] = empresa
        estado["datos"] = None
        page.session.set("empresa", empresa)
        lb_negocio.value = f"🅿 {empresa['nombre'] if empresa else NEGOCIO}"
        page.title = empresa["nombre"] if empresa else NEGOCIO
        bt_empresas.visible = estado["admin"] or len(estado["opciones"]) > 1
        hoy = dat.ahora(empresa.get("zona") if empresa else None).date()
        estado.update(desde=hoy, hasta=hoy)
        bt_desde.text, bt_hasta.text = f"Del {hoy:%d/%m/%Y}", f"Al {hoy:%d/%m/%Y}"
        lista_adentro.controls.clear()
        lista_cobrados.controls.clear()
        vista_resumen.controls.clear()
        fila_tarjetas.controls.clear()
        page.controls.clear()
        page.add(ft.SafeArea(cuerpo, expand=True))
        cargar()

        def refresco():                       # cada 30 s (el tiempo de los que están adentro avanza)
            while estado["vivo"]:
                time.sleep(CADA_SEGUNDOS)
                if estado["vivo"] and not estado["ocupado"] and estado["datos"] is not None:
                    try:
                        cargar()
                    except Exception:
                        pass
        if not estado["hilo"]:
            estado["hilo"] = True
            threading.Thread(target=refresco, daemon=True).start()

    def al_cerrar(e):
        estado["vivo"] = False

    page.on_disconnect = al_cerrar

    def pantalla(contenido, ancho=340):
        estado["datos"] = None                 # que el refresco no pinte encima
        page.controls.clear()
        page.add(ft.SafeArea(ft.Container(
            alignment=ft.alignment.top_center, expand=True, padding=12,
            content=ft.Container(width=ancho, bgcolor="white", border_radius=16, padding=20,
                                 content=contenido)), expand=True))
        page.update()

    def salir():
        page.session.clear()
        estado.update(admin=False, opciones=[], empresa=None, datos=None)
        login()

    # ─────────────── elegir empresa (admin o usuario con varias) ───────────────
    def elegir_empresa():
        try:
            lista = dat.empresas(solo_activas=not estado["admin"]) if estado["admin"] else estado["opciones"]
        except Exception as ex:
            aviso(f"No pude leer las empresas: {ex}", True)
            return
        filas = []
        for emp in lista:
            activa = (emp.get("activo") or "1") == "1"
            filas.append(ft.ListTile(
                leading=ft.Icon(ft.Icons.LOCAL_PARKING, color=AZUL if activa else GRIS),
                title=ft.Text(emp["nombre"], weight=ft.FontWeight.BOLD, color=None if activa else GRIS),
                subtitle=ft.Text(f"{emp['clave']} · {emp.get('base') or 'base de control'}"
                                 + ("" if activa else " · INACTIVA"), size=12),
                trailing=ft.IconButton(ft.Icons.EDIT, tooltip="Editar",
                                       on_click=lambda e, x=emp: editar_empresa(x)) if estado["admin"] else None,
                on_click=lambda e, x=emp: mostrar_app(x)))
        if estado["admin"]:
            filas.append(ft.ListTile(leading=ft.Icon(ft.Icons.STORAGE, color=GRIS),
                                     title=ft.Text("Base de control"),
                                     subtitle=ft.Text("La de las variables de Railway", size=12),
                                     on_click=lambda e: mostrar_app(None)))
        pantalla(ft.Column([
            ft.Row([ft.Text("Empresas", size=20, weight=ft.FontWeight.BOLD, color=AZUL, expand=True),
                    ft.IconButton(ft.Icons.LOGOUT, tooltip="Salir", on_click=lambda e: salir())]),
            ft.Text("Toca una para ver su estacionamiento.", color=GRIS, size=12),
            ft.Column(filas or [ft.Text("Todavía no hay empresas.", color=GRIS)], spacing=0,
                      scroll=ft.ScrollMode.AUTO),
            ft.FilledButton("➕ Nueva empresa", on_click=lambda e: editar_empresa(None),
                            visible=estado["admin"], width=300),
        ], spacing=8, scroll=ft.ScrollMode.AUTO), ancho=420)

    # ─────────────── alta / cambio de empresa (solo admin) ───────────────
    ZONAS = ["America/Merida", "America/Cancun", "America/Mexico_City", "America/Monterrey",
             "America/Chihuahua", "America/Mazatlan", "America/Hermosillo", "America/Tijuana"]

    def editar_empresa(emp):
        emp = emp or {}
        def campo(nombre, etiqueta, **kw):
            return ft.TextField(label=etiqueta, value=str(emp.get(nombre) if emp.get(nombre) is not None else ""),
                                dense=True, **kw)
        c = {
            "clave": campo("clave", "Clave (ej. EST01)", capitalization=ft.TextCapitalization.CHARACTERS),
            "nombre": campo("nombre", "Nombre del estacionamiento"),
            "host": campo("host", "Servidor MySQL (vacío = el de control)"),
            "puerto": campo("puerto", "Puerto", keyboard_type=ft.KeyboardType.NUMBER),
            "usuario_db": campo("usuario_db", "Usuario MySQL"),
            "clave_db": campo("clave_db", "Contraseña MySQL", password=True, can_reveal_password=True),
            "base": campo("base", "Base de datos sincronizada"),
            "usuario_app": campo("usuario_app", "Usuario para entrar (el dueño)"),
            "clave_app": campo("clave_app", "Contraseña para entrar", password=True, can_reveal_password=True),
        }
        if not c["puerto"].value:
            c["puerto"].value = "3306"
        dd_zona = ft.Dropdown(label="Zona horaria", dense=True, value=emp.get("zona") or ZONAS[0],
                              options=[ft.dropdown.Option(z) for z in ZONAS])
        sw_activo = ft.Switch(label="Activa", value=(emp.get("activo") or "1") == "1")
        lb_prueba = ft.Text("", size=12)

        def datos():
            d = {k: v.value for k, v in c.items()}
            d.update(zona=dd_zona.value, activo="1" if sw_activo.value else "0")
            return d

        def probar(e):
            lb_prueba.value, lb_prueba.color = "Probando…", GRIS
            page.update()
            ok, msg = dat.probar_empresa(datos())
            lb_prueba.value, lb_prueba.color = ("✅ " if ok else "❌ ") + msg, VERDE if ok else "#B71C1C"
            page.update()

        def guardar(e):
            try:
                dat.guardar_empresa(datos(), emp.get("id"))
            except Exception as ex:
                lb_prueba.value, lb_prueba.color = f"❌ {ex}", "#B71C1C"
                page.update()
                return
            aviso("Empresa guardada.")
            elegir_empresa()

        def borrar(e):
            def si(ev):
                page.close(dlg)
                dat.borrar_empresa(emp["id"])
                aviso("Empresa borrada.")
                elegir_empresa()
            dlg = ft.AlertDialog(title=ft.Text("¿Borrar empresa?"),
                                 content=ft.Text(f"{emp.get('nombre')} — solo se borra de la app, "
                                                 "su base no se toca."),
                                 actions=[ft.TextButton("Cancelar", on_click=lambda ev: page.close(dlg)),
                                          ft.TextButton("Borrar", on_click=si)])
            page.open(dlg)

        pantalla(ft.Column([
            ft.Text("Editar empresa" if emp else "Nueva empresa", size=20, weight=ft.FontWeight.BOLD, color=AZUL),
            c["clave"], c["nombre"],
            ft.Text("Conexión a su base sincronizada", size=12, color=GRIS, weight=ft.FontWeight.BOLD),
            c["host"], c["puerto"], c["usuario_db"], c["clave_db"], c["base"],
            ft.Text("Acceso del dueño", size=12, color=GRIS, weight=ft.FontWeight.BOLD),
            c["usuario_app"], c["clave_app"], dd_zona, sw_activo, lb_prueba,
            ft.Row([ft.OutlinedButton("Probar conexión", icon=ft.Icons.WIFI_TETHERING, on_click=probar),
                    ft.FilledButton("Guardar", icon=ft.Icons.SAVE, on_click=guardar)], wrap=True),
            ft.Row([ft.TextButton("← Regresar", on_click=lambda e: elegir_empresa()),
                    ft.TextButton("Borrar", icon=ft.Icons.DELETE, icon_color="#B71C1C",
                                  on_click=borrar, visible=bool(emp.get("id")))],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ], spacing=10, scroll=ft.ScrollMode.AUTO), ancho=420)

    # ─────────────── login ───────────────
    def login():
        tx_user = ft.TextField(label="Usuario", value="", autofocus=True, width=280)
        tx_pass = ft.TextField(label="Contraseña", password=True, can_reveal_password=True, width=280)
        lb_err = ft.Text("", color="#B71C1C")

        def entrar(e):
            usuario, clave = tx_user.value.strip(), tx_pass.value
            if APP_CLAVE and usuario.lower() == APP_USUARIO.lower() and clave == APP_CLAVE:
                estado["admin"] = True
                page.session.set("admin", True)
                elegir_empresa()
                return
            try:
                encontradas = dat.validar_usuario(usuario, clave)
            except Exception as ex:
                encontradas = []
                lb_err.value = f"No pude revisar: {ex}"
            if len(encontradas) == 1:
                estado["opciones"] = encontradas
                mostrar_app(encontradas[0])
            elif encontradas:
                estado["opciones"] = encontradas
                elegir_empresa()
            else:
                lb_err.value = lb_err.value or "Usuario o contraseña incorrectos."
                tx_pass.value = ""
                page.update()
                lb_err.value = ""

        tx_pass.on_submit = entrar
        pantalla(ft.Column([
            ft.Text(f"🅿 {NEGOCIO}", size=22, weight=ft.FontWeight.BOLD, color=AZUL),
            ft.Text("Consulta de caja y vehículos", color=GRIS),
            tx_user, tx_pass, lb_err,
            ft.FilledButton("Entrar", width=280, height=46, on_click=entrar),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12))

    # ─────────────── arranque ───────────────
    try:
        hay_empresas = bool(dat.empresas())
    except Exception:
        hay_empresas = False
    if page.session.get("admin"):
        estado["admin"] = True
        elegir_empresa()
    elif not APP_CLAVE and not hay_empresas:
        mostrar_app(None)                      # como antes: una sola base, sin login
    else:
        login()


# Servidor web (Railway): FastAPI + uvicorn escuchando en 0.0.0.0:$PORT
try:
    import flet_web.fastapi as flet_fastapi
except ImportError:                      # versiones que lo exponen como flet.fastapi
    import flet.fastapi as flet_fastapi

app = flet_fastapi.app(main)

if __name__ == "__main__":
    import uvicorn
    puerto = int(os.getenv("PORT", "8550"))
    print(f"Estacionamiento cel escuchando en 0.0.0.0:{puerto}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=puerto, proxy_headers=True, forwarded_allow_ips="*")
