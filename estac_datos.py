# -*- coding: utf-8 -*-
"""
ESTACIONAMIENTO EN EL CELULAR - datos (sin pantalla).

Lee la MISMA base del estacionamiento (solo consulta, no graba nada):
  ENARMA01  entradas y cobros   status '0' = adentro · '2' = cobrado
  ENARTA01  tarifas             '0000' normal (hora, fraccion, dia, mediodia) · 'HT1' hotel
  ENARDI01  día y turno abiertos (dia = '1900-01-01')

Los importes de los que están adentro se calculan IGUAL que estac_entra_sali_hotel.py
(normal, medio día, día completo, restaurante, hotel y pensionado).
El resumen de caja sigue a estac_movimientos_hotel.py: HOTEL (convenio) y PENSIONADOS
no suman a caja.
"""
import contextvars
import os
import re
from datetime import date, datetime, timedelta
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

import pymysql
from pymysql.cursors import DictCursor

# El servidor de Railway trabaja en UTC: la hora se toma de la zona del negocio
ZONA = ZoneInfo(os.getenv("TZ_NEGOCIO", "America/Merida"))
_zona = contextvars.ContextVar("zona", default=ZONA)     # la de la empresa que se consulta


def zona_de(nombre):
    try:
        return ZoneInfo(nombre) if nombre else ZONA
    except Exception:
        return ZONA


def ahora(zona=None):
    """Hora local del estacionamiento (sin zona, igual que las fechas que graba la PC)."""
    return datetime.now(zona_de(zona) if zona else _zona.get()).replace(tzinfo=None)


# ─────────────────────────────────────────────────────────────
#  CONEXIÓN (variables de Railway)
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
#  MAYÚSCULAS / MINÚSCULAS
#  MySQL en Windows guarda las tablas en minúsculas (enarma01) y la sincronizada en Railway
#  (Linux) sí distingue: ENARMA01 ≠ enarma01. Este cursor busca cómo se llama de verdad
#  cada tabla en esa base y cambia el nombre en la consulta, venga como venga.
# ─────────────────────────────────────────────────────────────
_TABLA = re.compile(r"\b(?:ENAR[A-Z]{2}\d{2}|ESTAC_EMPRESAS)\b", re.IGNORECASE)


class CursorTablas(DictCursor):
    def execute(self, query, args=None):
        con = self.connection
        mapa = getattr(con, "_mapa_tablas", None)
        if mapa is None:
            super().execute("SHOW TABLES")
            mapa = {}
            for r in self.fetchall():
                nombre = list(r.values())[0]
                # si hay doble (ENARMA01 y enarma01 vieja), gana la MAYÚSCULA: es la que
                # llena la sincronizada; la otra solo se usa si es la única que hay
                if nombre.upper() not in mapa or nombre == nombre.upper():
                    mapa[nombre.upper()] = nombre
            con._mapa_tablas = mapa
        if isinstance(query, str):
            query = _TABLA.sub(lambda m: mapa.get(m.group(0).upper(), m.group(0)), query)
            if query.lstrip().upper().startswith("CREATE TABLE"):
                con._mapa_tablas = None            # que vuelva a leer los nombres
        return super().execute(query, args)


def config_mysql():
    """MYSQL_URL / DATABASE_URL (mysql://usuario:clave@host:puerto/base) o DB_HOST, DB_PORT,
    DB_USER, DB_PASSWORD, DB_NAME. En Railway: MYSQL_URL = ${{MySQL.MYSQL_URL}}."""
    url = os.getenv("MYSQL_URL") or os.getenv("DATABASE_URL") or ""
    if url:
        u = urlparse(url)
        datos = dict(host=u.hostname, port=u.port or 3306, user=unquote(u.username or ""),
                     password=unquote(u.password or ""), database=(u.path or "/").lstrip("/"))
    else:
        datos = dict(host=os.getenv("DB_HOST", ""), port=int(os.getenv("DB_PORT", "3306") or 3306),
                     user=os.getenv("DB_USER", ""), password=os.getenv("DB_PASSWORD", ""),
                     database=os.getenv("DB_NAME", ""))
    if not datos["host"] or not datos["database"]:
        raise RuntimeError("Falta la conexión: pon MYSQL_URL (o DB_HOST, DB_USER, DB_PASSWORD, DB_NAME) "
                           "en las variables de Railway.")
    return dict(datos, charset="utf8mb4", cursorclass=CursorTablas, autocommit=True,
                connect_timeout=10, read_timeout=30)


def conectar(cfg=None):
    return pymysql.connect(**(cfg or config_mysql()))


# ─────────────────────────────────────────────────────────────
#  EMPRESAS (varios estacionamientos con la misma app)
#  La tabla ESTAC_EMPRESAS vive en la base de control (la de las variables de Railway).
#  Cada renglón dice a qué base sincronizada se conecta esa empresa:
#    host vacío  → mismo servidor de control, solo cambia la base (varias bases en un MySQL)
#    host lleno  → otro servidor (otro MySQL de Railway, por ejemplo)
#  Si la tabla está vacía, la app trabaja como antes: con la base de control.
# ─────────────────────────────────────────────────────────────
SQL_EMPRESAS = """
CREATE TABLE IF NOT EXISTS ESTAC_EMPRESAS (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    clave        VARCHAR(20)  NOT NULL UNIQUE,
    nombre       VARCHAR(80)  NOT NULL,
    host         VARCHAR(120) NOT NULL DEFAULT '',
    puerto       INT          NOT NULL DEFAULT 3306,
    usuario_db   VARCHAR(60)  NOT NULL DEFAULT '',
    clave_db     VARCHAR(120) NOT NULL DEFAULT '',
    base         VARCHAR(64)  NOT NULL DEFAULT '',
    usuario_app  VARCHAR(40)  NOT NULL DEFAULT '',
    clave_app    VARCHAR(60)  NOT NULL DEFAULT '',
    zona         VARCHAR(40)  NOT NULL DEFAULT 'America/Merida',
    activo       CHAR(1)      NOT NULL DEFAULT '1',
    creado       DATETIME     DEFAULT CURRENT_TIMESTAMP
) DEFAULT CHARSET=utf8mb4
"""
CAMPOS_EMPRESA = ("clave", "nombre", "host", "puerto", "usuario_db", "clave_db", "base",
                  "usuario_app", "clave_app", "zona", "activo")


def preparar_empresas():
    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(SQL_EMPRESAS)
    finally:
        conn.close()


def empresas(solo_activas=False):
    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(SQL_EMPRESAS)
            cur.execute("SELECT * FROM ESTAC_EMPRESAS" + (" WHERE activo='1'" if solo_activas else "")
                        + " ORDER BY nombre")
            return list(cur.fetchall())
    finally:
        conn.close()


def guardar_empresa(datos, id_=None):
    valores = [str(datos.get(c) or "").strip() for c in CAMPOS_EMPRESA]
    valores[CAMPOS_EMPRESA.index("puerto")] = int(datos.get("puerto") or 3306)
    valores[0] = valores[0].upper()
    if not valores[0] or not datos.get("nombre"):
        raise ValueError("La clave y el nombre son obligatorios.")
    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(SQL_EMPRESAS)
            if id_:
                cur.execute("UPDATE ESTAC_EMPRESAS SET " + ", ".join(f"{c}=%s" for c in CAMPOS_EMPRESA)
                            + " WHERE id=%s", valores + [id_])
            else:
                cur.execute(f"INSERT INTO ESTAC_EMPRESAS ({', '.join(CAMPOS_EMPRESA)}) "
                            f"VALUES ({', '.join(['%s'] * len(CAMPOS_EMPRESA))})", valores)
    finally:
        conn.close()


def borrar_empresa(id_):
    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ESTAC_EMPRESAS WHERE id=%s", (id_,))
    finally:
        conn.close()


def config_empresa(e):
    """Conexión de una empresa; lo que venga vacío se toma de la base de control."""
    cfg = config_mysql()
    if (e.get("host") or "").strip():
        cfg.update(host=e["host"].strip(), port=int(e.get("puerto") or 3306),
                   user=e.get("usuario_db") or cfg["user"], password=e.get("clave_db") or "")
    if (e.get("base") or "").strip():
        cfg["database"] = e["base"].strip()
    return cfg


def probar_empresa(e):
    """Regresa (ok, mensaje): conecta y revisa que existan las tablas del estacionamiento."""
    try:
        conn = conectar(config_empresa(e))
    except Exception as ex:
        return False, f"No conecta: {ex}"
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) n FROM ENARMA01 WHERE status='0'")
            n = cur.fetchone()["n"]
        return True, f"Conecta bien · {n} vehículos adentro"
    except Exception as ex:
        return False, f"Conecta, pero no encuentro ENARMA01 (¿ya sincronizó?): {ex}"
    finally:
        conn.close()


def validar_usuario(usuario, clave):
    """Empresas activas cuyo usuario/clave de la app coinciden."""
    u = (usuario or "").strip().lower()
    return [e for e in empresas(solo_activas=True)
            if (e.get("usuario_app") or "").strip().lower() == u and (e.get("clave_app") or "") == clave]


def num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def a_datetime(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    texto = str(v or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto[:19], fmt)
        except ValueError:
            pass
    return None


# ─────────────────────────────────────────────────────────────
#  TARIFAS Y CÁLCULO (igual que estac_entra_sali_hotel.py)
# ─────────────────────────────────────────────────────────────
class Tarifas:
    def __init__(self, hora=0, fraccion=0, dia=0, mediodia=0, hotel_dia=200.0, hotel_mediodia=150.0):
        self.hora, self.fraccion = float(hora), float(fraccion)
        self.dia, self.mediodia = float(dia), float(mediodia)
        self.hotel_dia, self.hotel_mediodia = float(hotel_dia), float(hotel_mediodia)

    @classmethod
    def leer(cls, cur):
        t = cls()
        cur.execute("SELECT codigo, hora, fraccion, dia, mediodia FROM ENARTA01 "
                    "WHERE UPPER(TRIM(codigo)) IN ('0000', 'HT1')")
        for r in cur.fetchall():
            codigo = str(r["codigo"] or "").strip().upper()
            if codigo == "0000":
                t.hora, t.fraccion = num(r["hora"]), num(r["fraccion"])
                t.dia, t.mediodia = num(r["dia"]), num(r["mediodia"])
            elif codigo == "HT1":
                t.hotel_dia = num(r["dia"]) or 200.0
                t.hotel_mediodia = num(r["mediodia"]) or 150.0
        return t

    # --- cada modalidad ---
    def normal(self, seg):
        minutos = seg // 60
        if minutos <= 60:
            return self.hora
        p = self.hora + ((minutos - 60) // 60 * self.hora)
        if (minutos - 60) % 60 > 0:
            p += self.fraccion
        return p

    def excedente(self, seg):
        """Después del bloque: por hora; lo que sobre hasta 30 min = media hora, más = hora."""
        seg = max(0, int(seg))
        if seg <= 0:
            return 0.0
        horas, resto = divmod(seg, 3600)
        importe = horas * self.hora
        if resto > 0:
            importe += self.fraccion if resto <= 30 * 60 else self.hora
        return float(importe)

    def modalidad(self, seg, tipo):
        if tipo == "MD":
            return self.mediodia + self.excedente(seg - 12 * 3600)
        return self.dia + self.excedente(seg - 24 * 3600)            # DIA

    def restaurante(self, seg):
        return 0.0 if seg <= 2 * 3600 else self.excedente(seg - 2 * 3600)

    def hotel(self, seg):
        dias, resto = divmod(seg, 24 * 3600)
        importe = dias * self.hotel_dia
        if resto > 0:
            importe += self.hotel_mediodia if resto <= 12 * 3600 + 15 * 60 else self.hotel_dia
        elif dias == 0 and seg > 0:
            importe = self.hotel_mediodia
        return importe


def tiempo_txt(seg):
    h, resto = divmod(max(0, int(seg)), 3600)
    m, s = divmod(resto, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def tipo_de(r):
    """Tipo para mostrar y su clave: NORMAL, MD, DIA, REST, HOTEL, PENSIONADO, BAÑO, SERVICIO."""
    if "PENS:" in str(r.get("observaciones") or ""):
        return "PENSIONADO"
    t = str(r.get("tipo_servicio") or "").strip().upper()
    return {"0000": "NORMAL", "": "NORMAL", "MD": "MEDIO DÍA", "DIA": "DÍA 24 H", "REST": "RESTAURANTE",
            "HOTEL": "HOTEL", "PENSIONADO": "PENSIONADO", "BANO": "BAÑO"}.get(t, "SERVICIO")


def cobro_estimado(r, tarifas, momento=None):
    """(tiempo, importe) de un vehículo que sigue adentro, como lo calcula la PC."""
    entrada = a_datetime(r.get("fechae"))
    if not entrada:
        return "--", 0.0
    seg = max(0, int(((momento or ahora()) - entrada).total_seconds()))
    t = str(r.get("tipo_servicio") or "").strip().upper()
    if "PENS:" in str(r.get("observaciones") or ""):
        return tiempo_txt(seg), 0.0
    if t == "HOTEL":
        return tiempo_txt(seg), tarifas.hotel(seg)
    if t in ("MD", "DIA"):
        return tiempo_txt(seg), tarifas.modalidad(seg, t)
    if t == "REST":
        return tiempo_txt(seg), tarifas.restaurante(seg)
    return tiempo_txt(seg), tarifas.normal(seg)


# ─────────────────────────────────────────────────────────────
#  CONSULTAS
# ─────────────────────────────────────────────────────────────
def sesion_actual(cur):
    """{'dia': 'AAAA-MM-DD', 'turno': 1, 'cajero': '0001', 'clave': 'AAAA-MM-DD01'} o None."""
    cur.execute("SELECT dia_trabajo, turno, cajero FROM ENARDI01 WHERE dia = '1900-01-01' LIMIT 1")
    r = cur.fetchone()
    if not r or not r.get("dia_trabajo"):
        return None
    dia = str(r["dia_trabajo"])[:10]
    turno = int(num(r["turno"]))
    return {"dia": dia, "turno": turno, "cajero": str(r.get("cajero") or ""), "clave": f"{dia}{turno:02d}"}


def adentro(cur, tarifas):
    cur.execute("""SELECT id, serie, folio, placas, fechae, turno, tipo_servicio, observaciones
                   FROM ENARMA01 WHERE status = '0' ORDER BY fechae""")
    momento = ahora()
    res = []
    for r in cur.fetchall():
        tiempo, importe = cobro_estimado(r, tarifas, momento)
        res.append(dict(r, tipo=tipo_de(r), tiempo=tiempo, importe=importe,
                        folio_txt=f"{r.get('serie') or '00'}-{int(num(r.get('folio'))):06d}"))
    return res


def cobrados(cur, desde=None, hasta=None, turno=None):
    """Cobrados (status '2') por rango de fechas de salida, o de un turno ('AAAA-MM-DD01')."""
    campos = ("id, serie, folio, placas, tipo_servicio, observaciones, importe, efectivo, tarjeta, "
              "transferencia, fechae, fechas, horas, tiempo, turno, cajero")
    if turno:
        cur.execute(f"SELECT {campos} FROM ENARMA01 WHERE status = '2' AND turno = %s "
                    "ORDER BY fechas DESC, id DESC", (turno,))
    else:
        cur.execute(f"SELECT {campos} FROM ENARMA01 WHERE status = '2' AND fechas >= %s AND fechas < %s "
                    "ORDER BY fechas DESC, id DESC",
                    (datetime(desde.year, desde.month, desde.day),
                     datetime(hasta.year, hasta.month, hasta.day) + timedelta(days=1)))
    res = []
    for r in cur.fetchall():
        res.append(dict(r, tipo=tipo_de(r),
                        folio_txt=f"{r.get('serie') or '00'}-{int(num(r.get('folio'))):06d}"))
    return res


def resumen(lista_cobrados, lista_adentro):
    """Totales como estac_movimientos_hotel.py: hotel y pensionados NO suman a caja."""
    r = {"caja": 0.0, "efectivo": 0.0, "tarjeta": 0.0, "transferencia": 0.0, "tickets_caja": 0,
         "hotel": 0.0, "tickets_hotel": 0, "pensionados": 0, "por_tipo": {},
         "adentro": len(lista_adentro), "adentro_estimado": sum(x["importe"] for x in lista_adentro)}
    for x in lista_cobrados:
        tipo = x["tipo"]
        imp = num(x.get("importe"))
        if tipo == "HOTEL":
            r["hotel"] += imp
            r["tickets_hotel"] += 1
            continue
        if tipo == "PENSIONADO":
            r["pensionados"] += 1
            continue
        r["caja"] += imp
        r["efectivo"] += num(x.get("efectivo"))
        r["tarjeta"] += num(x.get("tarjeta"))
        r["transferencia"] += num(x.get("transferencia"))
        r["tickets_caja"] += 1
        t = r["por_tipo"].setdefault(tipo, [0, 0.0])
        t[0] += 1
        t[1] += imp
    return r


def consultar(modo, desde=None, hasta=None, empresa=None):
    """Todo lo de la pantalla en una sola conexión.
    modo: 'hoy', 'ayer', 'turno' (turno abierto) o 'rango' (desde / hasta).
    empresa: renglón de ESTAC_EMPRESAS (None = base de control)."""
    token = _zona.set(zona_de(empresa.get("zona")) if empresa else ZONA)
    try:
        return _consultar(modo, desde, hasta, config_empresa(empresa) if empresa else None)
    finally:
        _zona.reset(token)


def _consultar(modo, desde, hasta, cfg):
    conn = conectar(cfg)
    try:
        with conn.cursor() as cur:
            tarifas = Tarifas.leer(cur)
            ses = sesion_actual(cur)
            hoy = ahora().date()
            if modo == "turno" and ses:
                titulo = f"Turno {ses['turno']:02d} del {ses['dia']}"
                lista = cobrados(cur, turno=ses["clave"])
            else:
                if modo == "ayer":
                    desde = hasta = hoy - timedelta(days=1)
                elif modo == "rango" and desde and hasta:
                    desde, hasta = min(desde, hasta), max(desde, hasta)
                else:
                    desde = hasta = hoy
                titulo = (f"{desde:%d/%m/%Y}" if desde == hasta
                          else f"{desde:%d/%m/%Y} al {hasta:%d/%m/%Y}")
                lista = cobrados(cur, desde, hasta)
            dentro = adentro(cur, tarifas)
    finally:
        conn.close()
    return {"titulo": titulo, "sesion": ses, "adentro": dentro, "cobrados": lista,
            "resumen": resumen(lista, dentro), "hora": ahora()}
