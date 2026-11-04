"""
Descargador reanudable de la caché del backtest (tarea R3 de la hoja de ruta).

Sustituye al antiguo ``launcher.py`` (que relanzaba el backtest completo cada
61 minutos solo para sortear el límite horario de Tiingo). Puebla
`backtest/.cache/` con la MISMA clave (ticker, periodo) que usa
`backtest/data_cache.py::get_cached_weekly`, así que después
``prepare_universe(period=..., universe=...)`` lee todo de la caché.

Uso
---
    python -m backtest.download_data --period 10y --universe historical
    python -m backtest.download_data --period 10y --universe historical --wait
    python -m backtest.download_data --tiingo-budget 40   # tope propio opcional por clave y hora

Fases
-----
1. **yfinance** (sin límite horario, ~10 hilos con los reintentos de
   `download_weekly`): ^GSPC, SPY, los ETFs sectoriales y todos los tickers
   del universo. Lo que yfinance no sirve (delistados, histórico
   insuficiente) queda "pendiente de Tiingo" en el fichero de estado; en
   ejecuciones posteriores no se vuelve a pedir a yfinance.
2. **Tiingo** (plan gratuito: ~50 peticiones/hora, ~1000/día, 500 símbolos
   distintos/mes por cuenta). Por defecto NO hay presupuesto propio: se pide
   hasta que Tiingo responde con su error de límite, que bloquea esa clave y
   pasa a la siguiente (`weinstein/data.py`); solo se para cuando todas están
   limitadas. Nuestro contador no coincide con el de Tiingo, así que la
   respuesta de Tiingo es la única fuente de verdad. ``--tiingo-budget`` /
   ``--tiingo-daily-budget`` fijan un tope propio opcional (por clave). Al
   pararse: sin ``--wait`` se imprime un resumen y el comando para reanudar;
   con ``--wait`` duerme (unos minutos tras un límite horario) y continúa
   hasta que no quede nada pendiente.

Un ticker limitado NUNCA se marca como `.nodata`; solo se marca cuando Tiingo
responde de verdad sin datos (y el ticker ya no es constituyente). Los
fallos transitorios (red, HTTP 5xx) lo dejan pendiente.

Estado persistente
------------------
`backtest/.cache/descarga_estado.json` (ignorado por git junto con toda la
caché): peticiones a Tiingo usadas en la hora / día actuales (compartidas
entre procesos del descargador), bloqueo vigente por límite, y por periodo
los tickers pendientes de Tiingo, los obtenidos vía Tiingo y los vigentes
sin datos (que no reciben `.nodata`; se reintentan cada semana nueva).
Peticiones hechas por otros procesos (p.ej. el fallback dentro de un
backtest) no se cuentan aquí; si agotan el cupo, Tiingo responde con límite
y se detecta igualmente.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

if __package__ in (None, ""):
    # Ejecutado como `python backtest/download_data.py`: añadir la raíz del
    # proyecto al path para poder importar `backtest` y `weinstein`.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

from backtest import data_cache  # noqa: E402
from weinstein import data as wdata  # noqa: E402
from weinstein.config import SECTOR_ETF_PROXIES, SECTOR_TO_ETF, SP500_INDEX  # noqa: E402
from weinstein.data import (  # noqa: E402
    TiingoBudgetExhaustedError,
    TiingoRateLimitError,
    TiingoUnavailableError,
    last_closed_friday,
)

DEFAULT_PERIOD = "10y"
# Sin tope propio por defecto: manda la respuesta de límite de Tiingo.
DEFAULT_TIINGO_BUDGET: int | None = None
DEFAULT_TIINGO_DAILY_BUDGET: int | None = None
YF_WORKERS = 10
YF_RETRY_WORKERS = 3
MAX_CONSECUTIVE_TRANSIENT = 3       # fallos de red seguidos de Tiingo antes de parar
STATE_FILENAME = "descarga_estado.json"
BENCHMARK_TICKER = "SPY"            # mismo que backtest.portfolio_backtest.BENCHMARK_TICKER


# ── Estado persistente ────────────────────────────────────────────────

def _state_path() -> Path:
    # Se resuelve en cada llamada para que los tests puedan redirigir
    # `data_cache.CACHE_DIR` a tmp_path con monkeypatch.
    return data_cache.CACHE_DIR / STATE_FILENAME


def _hour_key(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H")


def _day_key(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")


def _month_key(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m")


def load_state() -> dict:
    path = _state_path()
    state: dict = {}
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  ⚠ Estado de descarga ilegible ({exc}); se empieza de cero.", file=sys.stderr)
            state = {}
    state.setdefault("tiingo", {})
    state.setdefault("periodos", {})
    return state


def save_state(state: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    # En Windows el reemplazo falla con PermissionError si otro proceso (el
    # antivirus, un lector) tiene abierto el destino en ese instante.
    for intento in range(10):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if intento == 9:
                raise
            time.sleep(0.05 * (intento + 1))


def _period_state(state: dict, period: str) -> dict:
    ps = state["periodos"].setdefault(period, {})
    ps.setdefault("pendientes_tiingo", [])
    ps.setdefault("via_tiingo", [])
    ps.setdefault("vigentes_sin_datos", {})
    return ps


def _tiingo_usage(state: dict, now: float) -> tuple[int, int]:
    """Peticiones ya usadas (hora actual, día actual), reseteando ventanas pasadas."""
    t = state["tiingo"]
    if t.get("hora") != _hour_key(now):
        t["hora"] = _hour_key(now)
        t["peticiones_hora"] = 0
    if t.get("dia") != _day_key(now):
        t["dia"] = _day_key(now)
        t["peticiones_dia"] = 0
    if t.get("mes") != _month_key(now):
        t["mes"] = _month_key(now)
        t["simbolos_mes"] = []
    return int(t.get("peticiones_hora", 0)), int(t.get("peticiones_dia", 0))


def _add_usage(state: dict, now: float, n: int, symbol: str | None = None) -> None:
    _tiingo_usage(state, now)
    t = state["tiingo"]
    t["peticiones_hora"] = int(t.get("peticiones_hora", 0)) + n
    t["peticiones_dia"] = int(t.get("peticiones_dia", 0)) + n
    if symbol and symbol not in t["simbolos_mes"]:
        t["simbolos_mes"].append(symbol)


def _fmt_epoch(ts: float) -> str:
    if ts == float("inf"):
        return "sin fecha conocida"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


# ── Universo ──────────────────────────────────────────────────────────

def extra_tickers() -> list[str]:
    """Series auxiliares siempre necesarias: índice, benchmark, ETFs sectoriales y sus sustitutos."""
    return [SP500_INDEX, BENCHMARK_TICKER] + sorted(set(SECTOR_TO_ETF.values()) | set(SECTOR_ETF_PROXIES.values()))


def build_universe(period: str, universe: str, desde: str | None = None) -> tuple[list[str], set[str]]:
    """
    Devuelve (símbolos del universo, constituyentes actuales). Para
    "historical" reutiliza `_build_historical_universe_rows` de
    `portfolio_backtest.py` (misma unión que usará `prepare_universe`), que
    necesita el cierre del ^GSPC: por eso se descarga antes.
    """
    from weinstein.data import load_sp500_tickers

    current = set(load_sp500_tickers()["Symbol"])
    if universe == "current":
        return sorted(current), current

    from backtest.portfolio_backtest import _build_historical_universe_rows

    sp500 = data_cache.get_cached_weekly(SP500_INDEX, period, False, True)
    if sp500 is None:
        print("  ✗ No se pudo obtener ^GSPC (necesario para el calendario histórico).")
        sys.exit(1)
    rows, _calendar, _unknown = _build_historical_universe_rows(period, sp500["Close"].squeeze(), desde=desde)
    return sorted(rows["Symbol"]), current


# ── Fase 1: yfinance ──────────────────────────────────────────────────

def _yf_one(ticker: str, period: str, max_retries: int | None):
    kwargs = {"period": period, "use_tiingo": False}
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
    try:
        return wdata.download_weekly(ticker, **kwargs)
    except Exception as exc:  # nunca debe tumbar la fase entera
        print(f"  ⚠ [{ticker}] error inesperado en yfinance: {exc}", file=sys.stderr)
        return None


def phase_yfinance(
    tickers: list[str],
    current: set[str],
    period: str,
    state: dict,
    workers: int = YF_WORKERS,
) -> dict:
    """
    Descarga con yfinance lo que falte o esté caducado. Lo que yfinance no
    sirve pasa a `pendientes_tiingo`. Devuelve contadores de la fase.
    """
    ps = _period_state(state, period)
    pend = set(ps["pendientes_tiingo"])
    lcf = str(last_closed_friday().date())

    todo: list[str] = []
    stale: set[str] = set()
    for t in tickers:
        st = data_cache.cache_status(t, period, t in current)
        if st in ("ok", "nodata"):
            continue
        if st == "falta" and t in pend and t not in current:
            continue  # delistado que yfinance ya no sirvió: va directo a Tiingo
        if st == "falta" and ps["vigentes_sin_datos"].get(t) == lcf:
            continue  # vigente sin datos en ninguna fuente esta semana
        if st == "caducado":
            stale.add(t)
        todo.append(t)

    stats = {"intentados": len(todo), "descargados": 0, "a_tiingo": 0, "caducados_sin_refrescar": 0}
    if not todo:
        print("  ✓ Nada que descargar con yfinance (todo en caché).")
        return stats

    print(f"  → {len(todo)} tickers a descargar con yfinance ({workers} hilos)...")
    failed: list[str] = []

    def run_pool(items: list[str], n_workers: int, max_retries: int | None) -> list[str]:
        fallidos: list[str] = []
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futs = {pool.submit(_yf_one, t, period, max_retries): t for t in items}
            for i, fut in enumerate(as_completed(futs), 1):
                t = futs[fut]
                df = fut.result()
                if df is not None and data_cache.save_cached(t, period, df) is not None:
                    stats["descargados"] += 1
                else:
                    fallidos.append(t)
                if i % 100 == 0:
                    print(f"  … {i}/{len(items)} | OK: {stats['descargados']}")
        return fallidos

    failed = run_pool(todo, workers, None)
    if failed:
        # Segunda pasada suave (pocos hilos, un intento) para descartar
        # fallos por saturación de Yahoo antes de gastar cupo de Tiingo.
        print(f"  → Segunda pasada yfinance para {len(failed)} fallidos ({YF_RETRY_WORKERS} hilos)...")
        failed = run_pool(sorted(failed), YF_RETRY_WORKERS, 1)

    for t in failed:
        if t in stale:
            stats["caducados_sin_refrescar"] += 1  # se conserva la caché antigua
            continue
        if t not in pend:
            ps["pendientes_tiingo"].append(t)
            pend.add(t)
        stats["a_tiingo"] += 1
    ps["pendientes_tiingo"].sort()
    save_state(state)
    print(f"  ✓ yfinance: {stats['descargados']} descargados | {stats['a_tiingo']} pendientes de Tiingo"
          + (f" | {stats['caducados_sin_refrescar']} caducados sin refrescar" if stats["caducados_sin_refrescar"] else ""))
    return stats


# ── Fase 2: Tiingo ────────────────────────────────────────────────────

def _pending_tiingo(state: dict, period: str, current: set[str], universe_set: set[str]) -> list[str]:
    """Pendientes que siguen sin caché (descarta los ya resueltos por otra vía)."""
    ps = _period_state(state, period)
    lcf = str(last_closed_friday().date())
    out = []
    for t in ps["pendientes_tiingo"]:
        if t not in universe_set:
            continue
        if data_cache.cache_status(t, period, t in current) in ("ok", "nodata", "caducado"):
            continue
        if ps["vigentes_sin_datos"].get(t) == lcf:
            continue
        out.append(t)
    return out


def _requests_needed(ticker: str) -> int:
    # El reintento con alias conocido consume una petición más.
    return 2 if ticker.strip().upper() in wdata._KNOWN_TICKER_RENAMES else 1


def phase_tiingo(
    tickers: list[str],
    current: set[str],
    period: str,
    state: dict,
    budget: int | None = DEFAULT_TIINGO_BUDGET,
    daily_budget: int | None = DEFAULT_TIINGO_DAILY_BUDGET,
    wait: bool = False,
    sleep=time.sleep,
    clock=time.time,
) -> dict:
    """
    Procesa los pendientes de Tiingo respetando el presupuesto por hora y
    por día. Devuelve contadores y el motivo de parada ("completado",
    "presupuesto", "limite", "mes", "sin_api_key", "token", "red").
    """
    ps = _period_state(state, period)
    universe_set = set(tickers)
    stats = {"peticiones": 0, "ok": 0, "sin_datos": 0, "parada": "completado", "reanudar_en": None}

    from weinstein.config import TIINGO_FALLBACK_ENABLED

    pending = _pending_tiingo(state, period, current, universe_set)
    if not pending:
        print("  ✓ Nada pendiente de Tiingo.")
        return stats
    if not TIINGO_FALLBACK_ENABLED or not wdata._tiingo_api_key():
        print("  ⚠ Tiingo no disponible (TIINGO_FALLBACK_ENABLED=False o falta TIINGO_API_KEY): "
              f"{len(pending)} tickers quedan pendientes.")
        stats["parada"] = "sin_api_key"
        return stats

    lcf = str(last_closed_friday().date())
    consecutive_transient = 0

    # Presupuestos por clave: con N API keys el total de la ventana es N veces
    # mayor (cada clave tiene su propio límite en Tiingo).
    n_keys = max(1, wdata.tiingo_key_count())
    budget = budget * n_keys if budget is not None else None
    daily_budget = daily_budget * n_keys if daily_budget is not None else None
    print(f"  → {n_keys} API key(s) de Tiingo | tope propio: "
          + (f"{budget}/hora" if budget is not None else "ninguno (manda el límite de Tiingo)"))

    while pending:
        now = clock()
        t_state = state["tiingo"]
        blocked_until = t_state.get("bloqueado_hasta")
        used_h, used_d = _tiingo_usage(state, now)

        resume_at = None
        if blocked_until is not None and now < blocked_until:
            resume_at = blocked_until
            motivo = t_state.get("motivo")
            stats["parada"] = motivo if motivo in ("mes", "presupuesto", "reintento") else "limite"
        elif daily_budget is not None and used_d >= daily_budget:
            resume_at = wdata.next_day_window(now)
            stats["parada"] = "presupuesto"
        elif budget is not None and used_h >= budget:
            resume_at = wdata.next_hour_window(now)
            stats["parada"] = "presupuesto"

        if resume_at is not None:
            stats["reanudar_en"] = resume_at
            save_state(state)
            if not wait or stats["parada"] == "mes" or resume_at == float("inf"):
                break
            print(f"  ⏸ Tiingo: {stats['parada']} ({used_h} peticiones esta hora, {used_d} hoy). "
                  f"Esperando hasta {_fmt_epoch(resume_at)} | pendientes: {len(pending)}")
            sleep(max(1.0, resume_at - clock()))
            continue

        t_state.pop("bloqueado_hasta", None)
        t_state.pop("motivo", None)
        restantes = [b - u for b, u in ((budget, used_h), (daily_budget, used_d)) if b is not None]
        window_budget = min(restantes) if restantes else None
        wdata.reset_tiingo_state()
        wdata.set_tiingo_budget(window_budget)
        print("  → Tiingo: ventana con "
              + (f"{window_budget} peticiones disponibles" if window_budget is not None else "sin tope propio")
              + f" | pendientes: {len(pending)}")

        stop_reason = None
        for t in list(pending):
            if window_budget is not None:
                if wdata.tiingo_requests_made() >= window_budget:
                    break
                if wdata.tiingo_requests_made() + _requests_needed(t) > window_budget:
                    continue  # no cabe con su alias: se intenta en la siguiente ventana
            before = wdata.tiingo_requests_made()
            try:
                df = wdata.download_weekly_tiingo(t, period_years=wdata.period_to_years(period),
                                                  raise_on_error=True)
            except TiingoBudgetExhaustedError:
                df, stop_reason = None, "presupuesto"
            except TiingoRateLimitError as exc:
                t_state["bloqueado_hasta"] = exc.bloqueado_hasta
                t_state["motivo"] = exc.motivo
                df, stop_reason = None, "limite"
            except TiingoUnavailableError as exc:
                df = None
                if exc.motivo == "token":
                    stop_reason = "token"
                else:
                    consecutive_transient += 1
                    if consecutive_transient >= MAX_CONSECUTIVE_TRANSIENT:
                        stop_reason = "red"
                made = wdata.tiingo_requests_made() - before
                _add_usage(state, clock(), made, t)
                stats["peticiones"] += made
                save_state(state)
                if stop_reason:
                    break
                continue  # queda pendiente

            made = wdata.tiingo_requests_made() - before
            _add_usage(state, clock(), made, t if made else None)
            stats["peticiones"] += made
            if stop_reason:
                save_state(state)
                break

            consecutive_transient = 0
            pending.remove(t)
            if t in ps["pendientes_tiingo"]:
                ps["pendientes_tiingo"].remove(t)
            if df is not None and data_cache.save_cached(t, period, df) is not None:
                if t not in ps["via_tiingo"]:
                    ps["via_tiingo"].append(t)
                    ps["via_tiingo"].sort()
                ps["vigentes_sin_datos"].pop(t, None)
                stats["ok"] += 1
            else:
                stats["sin_datos"] += 1
                if t in current:
                    # Un vigente nunca recibe `.nodata` (ver data_cache.py).
                    ps["vigentes_sin_datos"][t] = lcf
                    ps["pendientes_tiingo"].append(t)  # se reintentará otra semana
                    ps["pendientes_tiingo"].sort()
                else:
                    data_cache.mark_nodata(t, period)
            save_state(state)

        wdata.reset_tiingo_state()
        if stop_reason in ("token", "red"):
            stats["parada"] = stop_reason
            break
        if stop_reason is None and pending:
            # Ventana gastada (tope propio) o quedan tickers con fallos
            # transitorios: no se reintenta enseguida, para no entrar en un
            # bucle sin progreso.
            if window_budget is not None:
                t_state["bloqueado_hasta"] = wdata.next_hour_window(clock())
                t_state["motivo"] = "presupuesto"
            else:
                t_state["bloqueado_hasta"] = clock() + wdata.TIINGO_LIMIT_RETRY_S
                t_state["motivo"] = "reintento"
        # La siguiente vuelta del while calcula la ventana de reanudación
        # (y espera si --wait).

    if not pending:
        stats["parada"] = "completado"
        stats["reanudar_en"] = None
    save_state(state)
    return stats


# ── Informe de cobertura ──────────────────────────────────────────────

def coverage(tickers: list[str], current: set[str], period: str, state: dict) -> dict:
    ps = _period_state(state, period)
    via_tiingo = set(ps["via_tiingo"])
    lcf = str(last_closed_friday().date())
    rep = {"yfinance": [], "tiingo": [], "sin_datos": [], "pendientes": []}
    for t in tickers:
        is_cur = t in current
        st = data_cache.cache_status(t, period, is_cur)
        if st in ("ok", "caducado"):
            rep["tiingo" if t in via_tiingo else "yfinance"].append(t)
        elif st == "nodata" or (is_cur and ps["vigentes_sin_datos"].get(t) == lcf):
            rep["sin_datos"].append(t)
        else:
            rep["pendientes"].append(t)
    return rep


def resume_command(period: str, universe: str, budget: int | None, daily_budget: int | None, wait: bool,
                   desde: str | None = None) -> str:
    cmd = f"python -m backtest.download_data --period {period} --universe {universe}"
    if desde is not None:
        cmd += f" --desde {desde}"
    if budget is not None:
        cmd += f" --tiingo-budget {budget}"
    if daily_budget is not None:
        cmd += f" --tiingo-daily-budget {daily_budget}"
    if wait:
        cmd += " --wait"
    return cmd


def print_report(
    universe_tickers: list[str],
    extras: list[str],
    current: set[str],
    period: str,
    universe: str,
    state: dict,
    tiingo_stats: dict,
    budget: int | None,
    daily_budget: int | None,
    desde: str | None = None,
) -> dict:
    rep = coverage(universe_tickers, current, period, state)
    rep_extra = coverage(extras, set(extras), period, state)
    used_h, used_d = _tiingo_usage(state, time.time())
    t_state = state["tiingo"]

    print("\n" + "=" * 70)
    print(f"  COBERTURA DE LA CACHÉ  (periodo {period}, universo {universe})")
    print("=" * 70)
    print(f"  Tickers en el universo:        {len(universe_tickers)}")
    print(f"  Con datos vía yfinance:        {len(rep['yfinance'])}")
    print(f"  Con datos vía Tiingo:          {len(rep['tiingo'])}")
    print(f"  Sin datos (permanente):        {len(rep['sin_datos'])}")
    print(f"  Pendientes (Tiingo):           {len(rep['pendientes'])}")
    faltan_extra = rep_extra["pendientes"] + rep_extra["sin_datos"]
    print(f"  Series auxiliares (^GSPC, SPY, ETFs): {len(extras) - len(faltan_extra)}/{len(extras)}"
          + (f"  FALTAN: {', '.join(faltan_extra)}" if faltan_extra else ""))
    print(f"  Peticiones Tiingo en esta ejecución: {tiingo_stats.get('peticiones', 0)} | "
          f"hora actual: {used_h} | hoy: {used_d} | "
          f"símbolos distintos este mes: {len(t_state.get('simbolos_mes', []))}/500")
    if rep["sin_datos"]:
        print(f"\n  Sin datos ({len(rep['sin_datos'])}): {' '.join(rep['sin_datos'])}")
    if rep["pendientes"]:
        muestra = " ".join(rep["pendientes"][:40]) + (" …" if len(rep["pendientes"]) > 40 else "")
        print(f"\n  Pendientes ({len(rep['pendientes'])}): {muestra}")

    parada = tiingo_stats.get("parada")
    if rep["pendientes"]:
        print()
        if parada == "mes":
            print("  ⚠ Tiingo: límite MENSUAL de símbolos alcanzado; reanudar el mes que viene.")
        elif parada == "token":
            print("  ✗ Tiingo rechazó el token (HTTP 401): revisa TIINGO_API_KEY en .env.")
        elif parada == "sin_api_key":
            print("  ⚠ Falta TIINGO_API_KEY (o el fallback está desactivado).")
        elif parada == "red":
            print("  ⚠ Errores de red seguidos con Tiingo; reintentar más tarde.")
        elif tiingo_stats.get("reanudar_en"):
            print(f"  ⏸ Cupo de Tiingo agotado ({parada}); la siguiente ventana abre "
                  f"{_fmt_epoch(tiingo_stats['reanudar_en'])}.")
        print("  Para reanudar (una ventana):")
        print(f"    {resume_command(period, universe, budget, daily_budget, False, desde)}")
        print("  Para seguir solo hasta terminar (duerme entre ventanas):")
        print(f"    {resume_command(period, universe, budget, daily_budget, True, desde)}")
    else:
        print("\n  ✓ No queda nada pendiente: la caché está completa para este universo.")
    print("=" * 70)
    return rep


# ── CLI ───────────────────────────────────────────────────────────────

def run(
    period: str = DEFAULT_PERIOD,
    universe: str = "historical",
    budget: int | None = DEFAULT_TIINGO_BUDGET,
    daily_budget: int | None = DEFAULT_TIINGO_DAILY_BUDGET,
    wait: bool = False,
    workers: int = YF_WORKERS,
    skip_tiingo: bool = False,
    desde: str | None = None,
) -> dict:
    state = load_state()
    extras = extra_tickers()

    print(f"\n[1/3] Series auxiliares ({', '.join(extras)}) con yfinance...")
    phase_yfinance(extras, set(extras), period, state, workers=workers)

    print(f"\n[2/3] Universo '{universe}' y descarga con yfinance...")
    universe_tickers, current = build_universe(period, universe, desde=desde)
    print(f"  ✓ {len(universe_tickers)} tickers en el universo ({len(current)} constituyentes actuales)")
    phase_yfinance(universe_tickers, current, period, state, workers=workers)

    all_tickers = extras + [t for t in universe_tickers if t not in set(extras)]
    all_current = current | set(extras)
    if skip_tiingo:
        print("\n[3/3] Tiingo omitido (--skip-tiingo).")
        tiingo_stats = {"peticiones": 0, "parada": "omitido", "reanudar_en": None}
    else:
        print(f"\n[3/3] Tiingo{' (esperando entre ventanas)' if wait else ''}...")
        try:
            tiingo_stats = phase_tiingo(all_tickers, all_current, period, state,
                                        budget=budget, daily_budget=daily_budget, wait=wait)
        except KeyboardInterrupt:
            save_state(state)
            print("\n  ⏹ Interrumpido; el progreso está guardado.")
            tiingo_stats = {"peticiones": 0, "parada": "interrumpido", "reanudar_en": None}

    return print_report(universe_tickers, extras, current, period, universe, state,
                        tiingo_stats, budget, daily_budget, desde=desde)


def main(argv: list[str] | None = None) -> int:
    # Con la salida redirigida a un fichero (típico de una ejecución larga con
    # --wait), Windows usa cp1252 y los símbolos ✓/⚠ romperían el proceso.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(
        prog="python -m backtest.download_data",
        description="Descarga reanudable de la caché del backtest (yfinance + Tiingo con presupuesto horario).",
    )
    parser.add_argument("--period", default=DEFAULT_PERIOD, help=f"Periodo yfinance (clave de caché). Por defecto {DEFAULT_PERIOD}.")
    parser.add_argument("--universe", choices=["historical", "current"], default="historical")
    parser.add_argument("--tiingo-budget", type=int, default=DEFAULT_TIINGO_BUDGET,
                        help="Tope propio opcional de peticiones a Tiingo por clave y hora de reloj. "
                             "Por defecto ninguno: se para cuando Tiingo responde con su límite.")
    parser.add_argument("--tiingo-daily-budget", type=int, default=DEFAULT_TIINGO_DAILY_BUDGET,
                        help="Tope propio opcional por clave y día UTC (por defecto ninguno).")
    parser.add_argument("--wait", action="store_true",
                        help="Si Tiingo limita todas las claves, dormir y reintentar hasta terminar.")
    parser.add_argument("--workers", type=int, default=YF_WORKERS, help=f"Hilos para yfinance (por defecto {YF_WORKERS}).")
    parser.add_argument("--skip-tiingo", action="store_true", help="Solo fase yfinance.")
    parser.add_argument("--desde", default=None, metavar="AAAA-MM-DD",
                        help="Universo histórico: solo tickers que estuvieron en el índice desde esta fecha "
                             "(necesario con --period max).")
    args = parser.parse_args(argv)

    rep = run(period=args.period, universe=args.universe, budget=args.tiingo_budget,
              daily_budget=args.tiingo_daily_budget, wait=args.wait, workers=args.workers,
              skip_tiingo=args.skip_tiingo, desde=args.desde)
    return 0 if not rep["pendientes"] else 2


if __name__ == "__main__":
    # Permite también `python backtest/download_data.py` desde la raíz.
    sys.exit(main())
