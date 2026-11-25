# Robot Supertrend 10/3 (1h) — GOLD en Capital.com

Opera el CFD **GOLD** de Capital.com con el Supertrend de TradingView
(Longitud ATR **10**, Factor **3**, "Espere al cierre de los intervalos de tiempo"):

| Supertrend | Accion del robot |
|---|---|
| Pasa a **verde** | Cierra la venta (si hay) y **COMPRA** |
| Pasa a **rojo** | Cierra la compra (si hay) y **VENDE** |
| Sigue del mismo color | No hace nada (solo sube/baja el stop de emergencia a favor) |

- Corre en **GitHub Actions** cada hora, 3 minutos despues del cierre de la vela 1h
  (GitHub puede retrasarlo unos minutos).
- Usa las velas 1h **del propio Capital.com** (precio bid, el de su grafico) y el mismo
  codigo de Supertrend que el dashboard (`oro_dashboard/core/supertrend.py`).
- Por que 1h: en el backtest del dashboard la regla gano en 1h (profit factor ~1,4 en
  2 años) y **perdio** en 15m y 5m.
- Stop de emergencia en el broker: linea Supertrend ∓ 1 ATR, por si una ejecucion falla.
- Valores iniciales: **cuenta DEMO**, subcuenta **"dm"** y **0,1 oz** por operacion.

## Configuracion (una sola vez)

1. **Regenera tu clave API** en Capital.com (Settings → API integrations). La anterior
   quedo expuesta en un chat; borrala.
2. En GitHub: **Settings → Secrets and variables → Actions**.
   - Pestaña **Secrets** → *New repository secret*:

     | Nombre | Valor |
     |---|---|
     | `CAPITAL_API_KEY` | la clave API nueva |
     | `CAPITAL_IDENTIFIER` | el **email** con el que inicias sesion en Capital.com |
     | `CAPITAL_PASSWORD` | la contraseña personalizada que pusiste al crear la clave API |

   - Pestaña **Variables** → *New repository variable*:

     | Nombre | Valor | Para que |
     |---|---|---|
     | `BOT_ENABLED` | `true` | interruptor general (`false` = apagado) |
     | `CAPITAL_ENV` | `DEMO` | `LIVE` solo cuando decidas dinero real |
     | `BOT_SIZE` | `0.1` | onzas por operacion |
     | `CAPITAL_ACCOUNT_NAME` | (opcional) nombre exacto de otra subcuenta | por defecto el robot usa la subcuenta **dm** |

3. **Prueba en simulacion:** pestaña **Actions** → *Robot Supertrend GOLD* → **Run workflow**
   con "Simulacion" marcado. Revisa el resumen: color, accion que tomaria y stop.
4. **Primera orden en demo:** Run workflow con "Simulacion" desmarcado.
5. Desde ahi corre solo cada hora. Cada ejecucion deja un resumen en la pestaña Actions.

## Pasar a dinero real (cuando tu decidas)

Variables `CAPITAL_ENV = LIVE` **y** `BOT_ALLOW_LIVE = true` (las dos; con solo una el robot
se niega a operar), y `CAPITAL_ACCOUNT_NAME` con el nombre de la subcuenta real: si no la
cambias, el robot buscara "dm" en la cuenta real y, si no existe, se detiene sin operar.

## Importante

- El robot gestiona **todas** las posiciones de GOLD en la cuenta elegida. No operes GOLD a
  mano en esa misma cuenta.
- Si al encenderlo la ultima señal tiene mas de 3 velas, espera al proximo cambio de color en
  vez de entrar a mitad de una tendencia (`BOT_MAX_SIGNAL_AGE`).
- GitHub desactiva los workflows programados tras 60 dias sin actividad en el repositorio;
  si eso pasa, lo reactivas desde la pestaña Actions.
- El backtest no garantiza resultados futuros. Con 1 oz la caida maxima historica fue ~$988;
  con 0,1 oz, ~$99.

## Pruebas locales (sin red, API simulada)

```bash
pip install -r robot_supertrend/requirements.txt pytest
python -m pytest robot_supertrend/tests -q
```
