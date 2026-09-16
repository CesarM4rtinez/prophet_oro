# ETH Trading Dashboard

Dashboard local en Streamlit que convierte los notebooks de analisis de ETH/USD
(`proyecciones_eth_prophet.ipynb`, `zonas_alta_probabilidad_smc_eth.ipynb`,
`scalping_eth_analisis_tecnico.ipynb`) en una app interactiva con datos en tiempo
real (yfinance o ccxt) y una Terminal de Trading conectada a Capital.com.

## Instalacion

Esta app tiene su propio entorno virtual, independiente del `env/` de los notebooks:

```powershell
cd eth_dashboard
python -m venv .venv          # si no existe todavia
.venv\Scripts\pip install -r requirements.txt
```

## Configuracion

Copia `.env.example` a `.env` y completa tus credenciales de Capital.com
(ya viene creado con las que compartiste; **rota la contraseña en capital.com**,
ya que quedo expuesta en el chat donde se genero este proyecto).

## Ejecutar

```powershell
.venv\Scripts\streamlit run app.py
```

Se abre en `http://localhost:8501`.

## Paginas

- **Resumen**: precio actual, fuente de datos activa y accesos a cada seccion.
- **Pronostico Prophet**: historico diario + prediccion a 30 dias.
- **Patrones Tecnicos**: picos/valles, patron ABCD, hombro-cabeza-hombro.
- **Probabilidad de Targets**: backtest de probabilidad global y por regimen de tendencia.
- **Zonas SMC**: swings, ruptura de estructura (BOS), order blocks y tasa de continuacion.
- **Scalping + Monte Carlo**: scorecard multi-indicador, confluencia multi-timeframe y proyeccion GBM.
- **Terminal de Trading**: conexion a Capital.com (Demo/Real, cuenta parametrizable),
  monitor de velas en vivo, posiciones abiertas, ordenes manuales y motor semi-automatico
  (desarmado por defecto, nunca persiste entre reinicios).

## Notas de seguridad

- El motor automatico de la Terminal de Trading esta **desarmado por defecto** y
  requiere confirmacion escrita ("ARMAR") para activarse en cuenta **real**.
- Las ordenes manuales en cuenta real requieren un checkbox de confirmacion adicional.
- `.env` nunca se sube a git (esta cubierto por el `.gitignore` de la raiz del repo).
- Prueba siempre primero en el entorno **Demo** antes de operar en cuenta real.
