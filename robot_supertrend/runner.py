"""Ejecucion continua del robot: revisa cada minuto, en tu PC o en un servidor.

Por que existe: GitHub Actions NO cumple sus horarios programados (el 25/11 corrio el
robot 2 veces en 8 horas con un cron de 5 minutos) y sus terminos no permiten usarlo
como servidor permanente. Este proceso mantiene la sesion de Capital.com abierta, la
renueva si expira y ejecuta `bot.run` cada RUNNER_INTERVAL_SECONDS (60 por defecto).

Uso:
    1. Copia robot_supertrend/.env.example a robot_supertrend/.env y completa tus datos
       (ese archivo esta en .gitignore: nunca se sube a GitHub).
    2. pip install -r robot_supertrend/requirements.txt
    3. python robot_supertrend/runner.py           (Ctrl+C para detenerlo)

Mientras este runner este activo, pon BOT_ENABLED=false en las variables de GitHub
para que GitHub Actions no opere en paralelo.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_env_file(path: Path) -> None:
    """Lector minimo de .env (CLAVE=valor); no pisa variables ya definidas."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    load_env_file(HERE / ".env")
    os.environ.setdefault("BOT_STATE_FILE", str(HERE / "robot_state.json"))
    sys.path.insert(0, str(HERE))
    import bot
    from news import fetch_calendar

    s = bot.Settings.from_env()
    pre = bot.check_preconditions(s)
    if pre:
        print(pre["detalle"])
        return 1
    interval = int(os.environ.get("RUNNER_INTERVAL_SECONDS", "60") or 60)
    api, calendar, calendar_at, last_text = None, None, 0.0, ""
    print(f"Robot continuo · {s.environment} · {s.epic} · cada {interval}s · Ctrl+C para detener")
    while True:
        try:
            if api is None:
                api = bot.CapitalAPI(s)
                api.login()
                print(f"[{datetime.now():%H:%M:%S}] sesion iniciada · cuenta {api.account_label}")
            if calendar is None or time.time() - calendar_at > 3600:  # calendario: una vez por hora
                calendar, calendar_at = fetch_calendar(), time.time()
            d = bot.run(s, now=datetime.now(timezone.utc), api=api, calendar=calendar)
            text = bot._summary(d)
            # Solo imprime cuando algo cambia (decision, ordenes o noticias), no cada minuto.
            key = d.get("decision", "") + str(d.get("ejecutado")) + d.get("news", {}).get("reason", "")
            if key != last_text:
                print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{text}")
                last_text = key
        except KeyboardInterrupt:
            break
        except Exception as exc:  # sesion expirada, red caida, etc.: reconecta en la proxima vuelta
            print(f"[{datetime.now():%H:%M:%S}] ERROR: {exc} — reintento en {interval}s")
            api = None
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            break
    if api is not None:
        api.logout()
    print("Robot detenido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
