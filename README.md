# Binance Export – Saldos y Operaciones

Sistema para traer saldos y operaciones de tu cuenta de Binance (Spot,
Margin, Futuros USDT-M, depósitos, retiros y operaciones fiat), filtrar
por rango de fechas y exportar todo a CSV. Incluye:

- `cli.py` – script de línea de comandos para exportar CSV directamente.
- `app.py` – dashboard web (Streamlit) con filtros de fecha, tablas,
  gráficos y botones de descarga.
- Módulos reutilizables (`binance_api.py`, `fetchers/`, `symbols.py`,
  `export.py`) que puedes usar por separado si quieres integrarlo en otra
  cosa.

## 1. Requisitos previos

1. Python 3.10+.
2. Una **API Key de Binance de solo lectura**. En Binance → API Management:
   - Crea una key y **desactiva** los permisos de "Enable Spot & Margin
     Trading" y "Enable Futures" (déjala solo con permisos de lectura).
   - Si puedes, restringe la key por IP.
   - Nunca compartas el API Secret; trátalo como una contraseña.
3. Instalar dependencias:

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # En Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

## 2. Configurar credenciales

Copia `.env.example` a `.env` y rellena tus datos:

```bash
cp .env.example .env
```

```
BINANCE_API_KEY=tu_api_key
BINANCE_API_SECRET=tu_api_secret
```

El archivo `.env` **no se sube a git** (ya está en `.gitignore`) y solo se
lee en tu máquina/servidor. Nunca pegues tus credenciales en un chat, un
issue de GitHub o un mensaje.

## 3. Uso por línea de comandos (CLI)

```bash
# Exporta TODO (saldos, histórico, operaciones spot, depósitos, retiros, fiat)
python cli.py --types all --start 2023-01-01 --end 2024-12-31 --output ./exports

# Solo saldos actuales
python cli.py --types balances

# Solo operaciones, en un mercado y rango concretos
python cli.py --types trades --market SPOT --start 2024-01-01 --end 2024-06-30

# Indicando símbolos manualmente (si el auto-descubrimiento no encuentra
# algún par que sí operaste)
python cli.py --types trades --symbols BTCUSDT,ETHUSDT,SOLUSDT
```

Los CSV se guardan en la carpeta indicada por `--output` (por defecto
`./exports`): `saldos_actuales.csv`, `balances_historicos.csv`,
`operaciones.csv`, `depositos.csv`, `retiros.csv`, `fiat.csv`.

## 4. Uso como dashboard web

```bash
streamlit run app.py
```

Se abre en `http://localhost:8501`. Desde la barra lateral puedes:

- Pegar tus credenciales solo para esa sesión (si no usaste `.env`).
- Elegir el rango de fechas (Desde/Hasta).
- Elegir el mercado (Spot/Margin/Futuros) para las operaciones.
- Indicar símbolos manuales o dejar que se auto-descubran.
- Ver tablas y gráficos, y descargar cada dataset como CSV.

## 5. Desplegarlo

### Opción A: Streamlit Community Cloud (gratis, más simple)

1. Sube este proyecto a un repositorio de GitHub **sin el archivo `.env`**
   (el `.gitignore` ya lo excluye).
2. Entra a https://share.streamlit.io, conecta el repo y elige `app.py`
   como archivo principal.
3. En "Secrets" del proyecto (Settings → Secrets), añade:

   ```toml
   BINANCE_API_KEY = "tu_api_key"
   BINANCE_API_SECRET = "tu_api_secret"
   ```

   Streamlit los expone como variables de entorno automáticamente.
4. Despliega. Ojo: la app quedará accesible por URL (puedes ponerla en
   privada en la configuración de la app) — al ser datos financieros
   personales, se recomienda mantenerla privada o protegida.

### Opción B: Docker (tu propio servidor / VPS)

```bash
docker build -t binance-export .
docker run -p 8501:8501 \
  -e BINANCE_API_KEY=tu_api_key \
  -e BINANCE_API_SECRET=tu_api_secret \
  binance-export
```

Abre `http://localhost:8501` (o la IP del servidor). Si lo expones a
Internet, ponlo detrás de HTTPS + autenticación (por ejemplo con un
reverse proxy como Caddy/Nginx + Basic Auth, o una VPN).

### Opción C: Solo CLI en un cron/tarea programada

Puedes programar `cli.py` con cron (Linux/Mac) o el Programador de tareas
(Windows) para que te genere los CSV periódicamente, por ejemplo cada
noche, dejándolos en una carpeta que sincronices con Drive/Dropbox.

## 6. Notas y limitaciones importantes

- **Rate limits de Binance**: el sistema reintenta automáticamente con
  backoff ante 429/418, pero cuentas con muchísimos símbolos/operaciones
  pueden tardar varios minutos en un histórico completo.
- **Histórico de saldos**: Binance solo conserva "account snapshots"
  diarios de los últimos ~30-90 días. Para tener histórico de saldos más
  atrás, hay que ir generando estos CSV periódicamente y acumularlos.
- **Descubrimiento de símbolos**: como Binance no ofrece "todas mis
  operaciones en todos los pares" en un solo endpoint, el sistema detecta
  automáticamente qué activos has tenido/movido y prueba combinaciones
  con las monedas de cotización más comunes (USDT, BTC, ETH, etc. —
  configurable en `config.py`). Si operaste un par muy poco común que no
  se detecta, indícalo manualmente con `--symbols` (CLI) o en el campo de
  símbolos manuales (dashboard).
- **Margin/Futuros opcionales**: si tu cuenta no tiene Margin o Futuros
  habilitados, esas secciones simplemente devuelven vacío sin romper el
  resto del sistema.
- Todas las fechas en los CSV usan **UTC**. La columna `datetime_utc` se
  añade automáticamente a partir de los timestamps en milisegundos.

## 7. Estructura del proyecto

```
binance_export/
├── app.py                 # Dashboard Streamlit
├── cli.py                 # CLI de exportación
├── binance_api.py         # Cliente HTTP firmado (HMAC) de bajo nivel
├── config.py               # Carga de credenciales y configuración
├── symbols.py              # Auto-descubrimiento de símbolos
├── export.py               # Conversión a DataFrame y CSV
├── fetchers/
│   ├── balances.py         # Saldos actuales + histórico (snapshot)
│   ├── trades.py           # Operaciones spot/margin/futuros
│   └── transfers.py        # Depósitos, retiros, fiat
├── requirements.txt
├── Dockerfile
├── .env.example
└── .gitignore
```
