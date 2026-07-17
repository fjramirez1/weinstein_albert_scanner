import subprocess
import sys
import time
from datetime import datetime

while True:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Ejecutando backtest...")
    print(sys.executable)
    subprocess.run([
        sys.executable,
        "-m", "weinstein",
        "portfolio-backtest",
        "--universe", "historical",
        "--export", "historial/backtests/detalle_operaciones.csv"
    ])

    print("Esperando 1h 1min...\n")
    time.sleep(3660)