# Estacionamiento en el celular (Flet + Railway)

App web **solo de consulta**: vehículos adentro (con lo que llevan acumulado), cobrados,
y resumen de caja (efectivo, tarjeta, transferencia; hotel y pensionados aparte),
de hoy, ayer, el turno abierto o un rango de fechas.

## Archivos
- `main.py` – la pantalla (Flet).
- `estac_datos.py` – consultas y cálculo de importes (igual que estac_entra_sali_hotel.py).
- `requirements.txt`, `Procfile`, `.python-version` – para Railway.

## 1. Subir a GitHub
1. En github.com → **New repository** → nombre `estac-cel` → **Private** → Create.
2. **Add file → Upload files** → arrastra los archivos de esta carpeta → **Commit changes**.

## 2. Publicar en Railway
1. En tu proyecto de Railway (donde está el MySQL) → **+ Create → GitHub Repo** → elige `estac-cel`.
2. En el servicio nuevo → **Variables** → agrega:
   - `MYSQL_URL` = `${{MySQL.MYSQL_URL}}`  (así usa la conexión interna de Railway)
   - `APP_USUARIO` = el usuario para entrar (ej. `dueno`)
   - `APP_CLAVE` = la contraseña para entrar
   - `NEGOCIO` = nombre que sale arriba (opcional)
3. **Settings → Networking → Generate Domain** (aquí sí es dominio web).
4. Abre la dirección `https://….up.railway.app` en el celular → menú del navegador →
   **Agregar a pantalla de inicio**.

## Varias empresas
- La tabla `ESTAC_EMPRESAS` se crea sola en la base de control (la de las variables).
- Entras con `APP_USUARIO` / `APP_CLAVE` = **administrador**: ves todas las empresas,
  das de alta con **➕ Nueva empresa**, pruebas la conexión y cambias entre ellas (botón ⇄).
- Cada empresa trae:
  - a qué base sincronizada se conecta (host vacío = mismo servidor, solo otra base),
  - el usuario y contraseña de su dueño: él entra directo a SU estacionamiento y no ve los demás,
  - su zona horaria (Mérida, Cancún, CDMX…).
- Si la tabla está vacía funciona como antes, con la base de control.

## Ojo
- Lee la base que le pongas en `MYSQL_URL`. Si la PC del estacionamiento trabaja con su MySQL
  local, en Railway debe estar la **base sincronizada** (estac_sync.py en el servidor).
- La hora se calcula con `TZ_NEGOCIO` (por defecto `America/Merida`).
