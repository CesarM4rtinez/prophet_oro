# Robot Supertrend 10/3 (1h) v2 — GOLD en Capital.com

## Que hace

| Situacion | Accion |
|---|---|
| Supertrend 1h pasa a **verde** (vela cerrada) | Cierra las ventas y **COMPRA** |
| Supertrend 1h pasa a **rojo** (vela cerrada) | Cierra las compras y **VENDE** |
| Sigue del mismo color y el precio avanza 1 ATR | **Agrega** otra posicion (piramidacion), hasta N |
| Sin posicion y el cambio de color fue hace mas de 2 velas | **Espera** el proximo cambio (no entra tarde) |
| Noticia de alto impacto en EE. UU. (±30/45 min) o feriado | **No abre ni agrega**; cerrar si puede |
| Perdida del dia > 3 % o caida > 25 % desde el maximo | **No abre ni agrega** (frenos) |

Cada posicion lleva un stop en el broker = linea Supertrend ∓ 1 ATR, que solo se mueve a favor.

## Tamaño adaptable al capital (`risk.py`)

El riesgo TOTAL abierto es **1,5 % del capital**, repartido entre las N posiciones que
permite el capital:

| Capital | Posiciones simultaneas (N) | Riesgo por posicion |
|---|---|---|
| < $2 000 | 1 | 1,5 % |
| $2 000 – $9 999 | 2 | 0,75 % |
| $10 000 – $49 999 | 3 | 0,5 % |
| ≥ $50 000 | 4 | 0,375 % |

Tamaño de cada posicion = capital × riesgo por posicion ÷ (distancia al stop + costo).
Si la cuenta crece, el tamaño y N crecen; si baja, se achican solos. Si el stop queda tan
lejos que ni el tamaño minimo cabe en el riesgo, **no opera** (no fuerza un tamaño menor).
El tamaño minimo y su paso se leen de las reglas reales del mercado en Capital.com.

Ejemplo: capital $1 000, stop a $30 → riesgo $15 → 0,49 oz. Capital $10 000, stop a $30 →
3 posiciones de $50 de riesgo → hasta 1,65 oz cada una.

## Backtest (research/scaling_1h, 2 años de velas 1h, capital inicial $10 000)

| Variante | GC=F (futuros) | PAXG (spot) |
|---|---|---|
| Version anterior (0,1 oz fijo, siempre en mercado) | +1 %, caida 1 %, PF 1,17 | +4 %, caida 1 %, PF 1,65 |
| **v2** (riesgo 1,5 % + piramidacion + solo en el cambio de color + frenos) | **+47 %, caida 11 %, PF 1,34** | **+116 %, caida 13 %, PF 1,53** |

Probabilidad de cerrar un mes en perdida (Monte Carlo): 33 % (GC=F) y 22 % (PAXG). Solo
gana ~40 % de las operaciones: las ganadoras son mas grandes que las perdedoras. El
filtro de noticias no esta en el backtest (no hay calendario historico gratuito).
Resultados pasados no garantizan los futuros.

## Como se ejecuta: GitHub Actions (forma principal)

El flujo `.github/workflows/robot_supertrend.yml` corre el robot y guarda la memoria de los
frenos (capital al inicio del dia, maximo, pausa) en la cache de GitHub entre ejecuciones.

**Problema:** el horario interno de GitHub no es confiable (el 25/11 ejecuto el robot 2
veces en 8 horas con un cron de 5 minutos). **Solucion:** un servicio externo gratuito
(cron-job.org) le pide a GitHub ejecutar el flujo cada 5 minutos; GitHub atiende esos
pedidos al momento. El cron interno queda de respaldo.

### 1. Crear un token de GitHub solo para disparar el robot
1. GitHub → foto de perfil → **Settings** → **Developer settings** → **Personal access tokens**
   → **Fine-grained tokens** → **Generate new token**.
2. Nombre: `robot-oro-cron`. Expiracion: la que prefieras (al vencer, el robot deja de dispararse
   hasta que lo renueves).
3. **Repository access:** *Only select repositories* → `prophet_oro`.
4. **Permissions → Repository permissions → Actions: Read and write.** Nada mas.
5. Genera y copia el token (empieza con `github_pat_`). Solo sirve para lanzar y ver
   ejecuciones de Actions de este repositorio: no puede leer ni cambiar el codigo.

### 2. Programar la llamada en cron-job.org
1. Crea una cuenta gratuita en cron-job.org → **Create cronjob**.
2. **URL:** `https://api.github.com/repos/CesarM4rtinez/prophet_oro/actions/workflows/robot_supertrend.yml/dispatches`
3. **Schedule:** cada 5 minutos.
4. **Advanced → Request method:** `POST`.
5. **Headers:**
   - `Accept: application/vnd.github+json`
   - `Authorization: Bearer <tu token github_pat_...>`
   - `X-GitHub-Api-Version: 2022-11-28`
6. **Request body:** `{"ref":"main","inputs":{"dry_run":"false"}}`
7. Guarda y usa **Test run**: debe responder `204`, y en la pestaña Actions de GitHub aparece una
   ejecucion "workflow_dispatch". Con `dry_run` en `"true"` puedes probar sin enviar ordenes.

### 3. Variables de GitHub
`BOT_ENABLED = true` y `CAPITAL_ENV = DEMO` (Settings → Secrets and variables → Actions →
Variables), mas los 3 Secrets de Capital.com. Si `CAPITAL_ACCOUNT_NAME` no existe, el robot
usa la subcuenta `dm`.

**Reanudar tras el freno de caida maxima:** Actions → **Caches** → borra las entradas
`robot-state-...`.

### Alternativa: ejecucion continua en una PC o servidor (`runner.py`)
Si algun dia prefieres no depender de GitHub: copia `.env.example` como `.env`, completa las
claves y ejecuta `python robot_supertrend/runner.py` (revisa cada minuto con la sesion
abierta). En ese caso pon `BOT_ENABLED = false` en GitHub para no operar dos veces.

## Variables (todas opcionales salvo las claves)

| Variable | Defecto | Para que |
|---|---|---|
| `CAPITAL_API_KEY`, `CAPITAL_IDENTIFIER`, `CAPITAL_PASSWORD` | — | credenciales (Secrets o `.env`) |
| `CAPITAL_ENV` / `BOT_ALLOW_LIVE` | `DEMO` / `false` | LIVE exige las dos |
| `CAPITAL_ACCOUNT_NAME` | `dm` (en Actions) | subcuenta del robot |
| `BOT_ENABLED` / `BOT_DRY_RUN` | `false` / `false` | interruptor / simulacion |
| `RISK_TOTAL_PCT` | `1.5` | riesgo total abierto (% del capital) |
| `RISK_MAX_UNITS` | — | tope manual de posiciones simultaneas |
| `RISK_ADD_EVERY_ATR` | `1.0` | avance necesario para agregar una posicion |
| `RISK_STOP_ATR` | `1.0` | distancia del stop mas alla de la linea |
| `RISK_DAILY_LOSS_PCT` / `RISK_MAX_DRAWDOWN_PCT` | `3` / `25` | frenos |
| `BOT_MAX_SIGNAL_AGE` | `2` | velas tras el cambio de color en las que aun entra |
| `BOT_SIZING` / `BOT_SIZE` | `risk` / `0.1` | `fixed` vuelve al tamaño fijo |
| `NEWS_FILTER`, `NEWS_MINUTES_BEFORE`, `NEWS_MINUTES_AFTER` | `true`, `30`, `45` | filtro de noticias |

Para reanudar tras el freno de caida maxima: en Actions borra las caches `robot-state-...`
(con `runner.py`, borra la clave `"halted"` de `robot_state.json`).

## Noticias (`news.py`)

- Fuente: calendario economico semanal de Forex Factory (faireconomy.media), que agenda las
  publicaciones oficiales (BLS, BEA, Reserva Federal, Tesoro, Census, ISM) con su impacto.
  Usa los eventos de USD de impacto alto, mas los de impacto medio que mueven al oro (PCE,
  PPI, ventas minoristas, ISM, Beige Book...) y los feriados de EE. UU.
- Si el calendario no responde, bloquea por precaucion las ventanas habituales de
  08:30, 10:00 y 14:00 de Nueva York.
- **No adivina la direccion de una noticia**: el resultado no se conoce antes y la primera
  reaccion suele revertirse (25/11: el PCE tiro el oro −$90 y en 4 horas rebotó +$119). El
  robot se aparta del evento y deja que el Supertrend 1h, con velas cerradas, refleje la
  direccion que eligio el mercado.

## Skills de day-trader-skill: que se reutilizo

| Skill | ¿Sirve para oro / Capital.com? | Uso en v2 |
|---|---|---|
| trader-risk | Si (reglas) | Stop obligatorio, limite de perdida diaria, tope de posiciones, margen, salir nunca bloqueado → `risk.py` y frenos |
| trader-budget | Si (reglas) | Tamaño por riesgo maximo; si el stop no cabe, no opera → `risk.position_size` |
| trader-exit | Si (reglas) | Stop en multiplos de ATR → stop = linea ∓ 1 ATR |
| trader-timemachine | Si | Monte Carlo: ya en el dashboard; aqui, probabilidad de perder un mes en el backtest |
| trader-entry | Si (principio) | Solo velas cerradas (ya estaba) |
| trader-news | Parcial | Regla "titulares no son hechos, sin predicciones" y etiquetas macro; sus fuentes son de acciones (8-K) → se uso el calendario economico |
| trader-alerts | Parcial | Feriados de EE. UU. y horario → bloqueo en feriados |
| trader-broker | No (Alpaca/IBKR) | Se mantiene su principio: demo por defecto y doble llave para real |
| trader-scanner | No (acciones de EE. UU.) | — |
| trader-analyst | No (reportes de empresas en la SEC) | — |
| trader-pelosi | No (operaciones del Congreso) | — |

## Pruebas (sin red)

```bash
pip install -r robot_supertrend/requirements.txt pytest
python -m pytest robot_supertrend/tests -q
```

18 pruebas: vuelta en ambos sentidos, tamaño por riesgo, reparto por N, piramidacion (una
por vela, tope N), cuenta pequeña, noticias (bloqueo, fuera de ventana, feriado, calendario
caido), frenos diario y de caida maxima, simulacion y bloqueo de LIVE.
