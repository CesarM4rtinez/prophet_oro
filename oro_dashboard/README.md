# Oro (XAU/USD) — Dashboard Predictivo

Dashboard en Streamlit que convierte `proyecciones_oro_prophet.ipynb` en una app
interactiva: pronostico Prophet, patrones tecnicos, probabilidad historica de
targets, plan de trading para la killzone de Nueva York y una estrategia
institucional SMC/ICT con sesgo diario — todo para XAU/USD via el proxy
`PAXG-USD` (el unico ticker de oro que yfinance sirve con datos reales de spot).

App aislada a proposito: **no** comparte codigo con `eth_dashboard/` (que incluye
una Terminal de Trading conectada a una cuenta real de Capital.com). Esta app no
necesita ningun secreto ni credencial — solo datos publicos de yfinance y el
Excel local del calendario economico.

## Instalacion local

```powershell
cd oro_dashboard
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Ejecutar local

```powershell
.venv\Scripts\streamlit run app.py
```

Se abre en `http://localhost:8501`.

## Desplegar en Streamlit Community Cloud

1. Sube esta carpeta (y `calendario_economico_ftmo/economic_calendar.xlsx`, del
   que depende la pagina "Plan Killzone NY" y la vista diaria de "Probabilidad de
   Targets") al repo de GitHub conectado a Streamlit Cloud.
2. En [share.streamlit.io](https://share.streamlit.io): **New app** → selecciona
   el repo → branch → main file path `oro_dashboard/app.py`.
3. No hace falta configurar Secrets: esta app no usa `.env` ni credenciales.
4. **Riesgo conocido de build**: `prophet` depende de `cmdstanpy`, que compila un
   binario nativo (`cmdstan`) en la primera instalacion — puede tardar varios
   minutos o fallar en runners con recursos limitados. Este proyecto ya incluye
   `packages.txt` con `build-essential` para cubrir el compilador C++ que necesita.
   Si aun asi el build falla o hace timeout, la alternativa documentada por la
   comunidad de Streamlit es reemplazar `requirements.txt` por un `environment.yml`
   que instale `prophet` desde `conda-forge` (ya viene precompilado, sin necesidad
   de compilar cmdstan):

   ```yaml
   name: oro-dashboard
   channels: [conda-forge]
   dependencies:
     - python=3.11
     - streamlit
     - plotly
     - yfinance
     - pandas
     - numpy
     - scipy
     - prophet
     - openpyxl
     - pip
   ```

   Streamlit Community Cloud usa automaticamente `environment.yml` (con conda) en
   vez de `requirements.txt` (con pip) si lo encuentra en la carpeta de la app.

## Paginas

- **Resumen**: precio actual de PAXG-USD y accesos a cada seccion.
- **Pronostico Prophet**: historico diario + prediccion a 30 dias, con boton de
  descarga a Excel (formato listo para Power BI).
- **Patrones Tecnicos**: picos/valles, patron armonico ABCD simplificado y
  hombro-cabeza-hombro (15m).
- **Probabilidad de Targets**: backtest global (intradia o diario), overlay con
  el calendario economico en la vista diaria, y probabilidad condicional por
  regimen de tendencia (compra/venta).
- **Plan Killzone NY**: estadistica historica de la sesion 08:00-12:00
  America/New_York + ticket Entrada/SL/TP para la sesion vigente o la proxima,
  con los eventos economicos de ese dia.
- **Estrategia Institucional (SMC)**: sesgo macro Diario -> estructura/Order
  Blocks en 1h -> Fair Value Gaps + Fibonacci institucional en 5m
  (`core/smc_zones.py`, porteado del motor ya usado en `eth_dashboard`). Un
  quiebre de estructura solo cuenta como "continuo" (señal) despues de que el
  precio lo **retestea**; ademas exige una **barrida de liquidez confirmada**
  (patron AMD) cerca de la ruptura y RR minimo 1:2 antes de listar un setup como
  operable — un spike aislado que revierte de inmediato (barrida de stops) queda
  "sin confirmar", nunca como señal limpia.

## Notas

- El calendario economico (`calendario_economico_ftmo/economic_calendar.xlsx`) es
  un archivo de datos, no de codigo — se actualiza manualmente por fuera de esta
  app y se lee desde la raiz del repo.
- Las celdas del notebook que generaban un GIF animado reflectivo no se portaron:
  su proposito era producir un archivo compartible, redundante frente a un
  grafico interactivo ya actualizado en una app viva.
- La pagina "Estrategia Institucional (SMC)" reemplazo un motor mas simple
  (`core/structure_mtf.py`, eliminado) que confirmaba tendencia con el primer
  cierre mas alla de un swing, sin exigir retest ni barrida de liquidez — eso
  producia señales falsas ante spikes/barridas de stops. El motor actual es el
  mismo que usa `eth_dashboard` para ETH, adaptado a esta app (sin ccxt, sin
  Capital.com). Mejoras futuras no incluidas (existen en `eth_dashboard` si se
  quieren portar despues): divergencia con el indice del dolar (DXY) y un
  clasificador ML como segunda opinion.
