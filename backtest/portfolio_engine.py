"""
Motor de simulación de cartera para el backtest Weinstein-Albert.

Modelo de cartera
-----------------
- Capital inicial configurable (por defecto $10.000) y máximo
  `max_positions` posiciones abiertas simultáneamente (por defecto 10).
- Las señales se evalúan con el CIERRE de cada semana (vela etiquetada en
  viernes, ver `weinstein/data.py::normalize_weekly_bars`).
- Ejecución (`StrategyConfig.execution`):
    - "next_open" (por defecto): las órdenes generadas por la señal de la
      semana t se ejecutan a la APERTURA de la semana t+1. Es lo que se
      puede hacer de verdad: el escáner se ejecuta en fin de semana y la
      orden entra el lunes.
    - "close": se ejecutan al cierre de la propia semana t (modelo
      antiguo, optimista: usa un precio que ya se conocía al calcular la
      señal). Se conserva solo para comparar.
- Orden de eventos de cada semana:
    1. Cierres forzosos de posiciones cuyo ticker ya no tiene datos
       (delisting: fusión, quiebra, exclusión). Se cierran al último
       precio conocido con motivo `SIN_DATOS`.
    2. Salidas (S1-S2, OR) y después entradas (F1-F5, AND, ordenadas por
       el criterio de desempate) hasta llenar huecos. Una salida y una
       entrada pueden ocurrir en la misma semana: el hueco liberado se
       reutiliza.
    3. Valoración de la cartera al cierre (huecos de precio puntuales se
       valoran con el último precio conocido).
- Tamaño de cada posición nueva = `valor_cartera_referencia / max_positions`,
  acotado al efectivo disponible. `valor_cartera_referencia` es efectivo +
  coste histórico de las posiciones abiertas: solo cambia al cerrar una
  posición (P&L realizado), nunca por fluctuación no realizada (acordado
  con el usuario). Sin rebalanceos.
- Costes: `cost_pct` % del importe en cada compra y en cada venta
  (comisión + deslizamiento). Sin apalancamiento ni cortos.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backtest.conditions import ENTRY_CONDITIONS, EXIT_CONDITIONS, RANKING_CRITERIA, TickerContext
from backtest.strategy_config import StrategyConfig


# ── Estructuras de resultado ────────────────────────────────────────────

@dataclass
class ClosedTrade:
    ticker: str
    sector: str
    fecha_entrada: pd.Timestamp
    precio_entrada: float
    n_acciones: float
    capital_invertido: float
    fecha_salida: pd.Timestamp
    precio_salida: float
    motivo_salida: str
    semanas_en_pos: int
    retorno_pct: float
    pnl_usd: float


@dataclass
class OpenPosition:
    ticker: str
    sector: str
    fecha_entrada: pd.Timestamp
    precio_entrada: float
    n_acciones: float
    capital_invertido: float
    idx_entrada: int


@dataclass
class EquityPoint:
    fecha: pd.Timestamp
    valor_cartera: float          # efectivo + valor a mercado de posiciones abiertas
    capital_disponible: float
    n_posiciones_abiertas: int


@dataclass
class PortfolioBacktestResult:
    config: StrategyConfig
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    open_positions_at_end: list[OpenPosition] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    tickers_procesados: int = 0
    tickers_sin_datos: int = 0
    semanas_simuladas: int = 0
    costes_totales: float = 0.0
    # Serie de cierre del benchmark (buy & hold) para comparar en el mismo
    # tramo que la equity curve. None → no se calculan métricas de benchmark.
    benchmark_close: pd.Series | None = None

    def to_trades_dataframe(self) -> pd.DataFrame:
        if not self.closed_trades:
            return pd.DataFrame()
        rows = [
            {
                "Ticker": t.ticker,
                "Sector": t.sector,
                "Fecha Entrada": t.fecha_entrada,
                "Precio Entrada": t.precio_entrada,
                "Nº Acciones": round(t.n_acciones, 4),
                "Capital Invertido": round(t.capital_invertido, 2),
                "Fecha Salida": t.fecha_salida,
                "Precio Salida": t.precio_salida,
                "Motivo Salida": t.motivo_salida,
                "Semanas en Pos.": t.semanas_en_pos,
                "Retorno %": t.retorno_pct,
                "P&L USD": round(t.pnl_usd, 2),
            }
            for t in self.closed_trades
        ]
        return pd.DataFrame(rows)

    def to_equity_dataframe(self) -> pd.DataFrame:
        if not self.equity_curve:
            return pd.DataFrame()
        rows = [
            {
                "Fecha": p.fecha,
                "Valor Cartera": round(p.valor_cartera, 2),
                "Capital Disponible": round(p.capital_disponible, 2),
                "Nº Posiciones": p.n_posiciones_abiertas,
            }
            for p in self.equity_curve
        ]
        return pd.DataFrame(rows)

    def metrics(self) -> dict:
        """Estadísticas agregadas de la simulación (y del benchmark si lo hay)."""
        cerradas = self.closed_trades
        n = len(cerradas)

        capital_inicial = self.config.initial_capital
        equity = pd.Series(
            [p.valor_cartera for p in self.equity_curve],
            index=pd.DatetimeIndex([p.fecha for p in self.equity_curve]),
            dtype=float,
        )
        valor_final = float(equity.iloc[-1]) if len(equity) else capital_inicial
        rentabilidad_total_pct = ((valor_final / capital_inicial) - 1.0) * 100.0

        # CAGR sobre el tiempo REAL transcurrido. El primer punto de la curva
        # es el inicio de la simulación, así que el calentamiento de
        # indicadores no cuenta si la simulación arranca después de él (ver
        # `start` en run_portfolio_backtest).
        cagr_pct = _cagr_pct(capital_inicial, valor_final, equity.index)

        pct_semanas_invertido = None
        if self.equity_curve:
            semanas_con_posicion = sum(1 for p in self.equity_curve if p.n_posiciones_abiertas > 0)
            pct_semanas_invertido = round(100.0 * semanas_con_posicion / len(self.equity_curve), 1)

        out = {
            "capital_inicial": capital_inicial,
            "capital_final": round(valor_final, 2),
            "rentabilidad_total_pct": round(rentabilidad_total_pct, 2),
            "cagr_pct": _round(cagr_pct),
            "max_drawdown_pct": _round(_max_drawdown_pct(equity)),
            "sharpe_aprox": _round(_sharpe(equity)),
            "n_operaciones_cerradas": n,
            "n_operaciones_abiertas_al_final": len(self.open_positions_at_end),
            "win_rate_pct": None,
            "retorno_medio_pct": None,
            "retorno_mediana_pct": None,
            "profit_factor": None,
            "mejor_operacion_pct": None,
            "peor_operacion_pct": None,
            "semanas_medias_en_pos": None,
            "pct_pnl_top5": None,
            "pct_semanas_invertido": pct_semanas_invertido,
            "costes_totales_usd": round(self.costes_totales, 2),
        }
        out.update(self._benchmark_metrics(equity.index, cagr_pct))

        if n == 0:
            return out

        retornos = np.array([t.retorno_pct for t in cerradas], dtype=float)
        pnl = np.array([t.pnl_usd for t in cerradas], dtype=float)

        # Profit factor en dólares (no en suma de %): una operación del 50 %
        # con poco capital no debe pesar igual que una del 50 % con mucho.
        ganancias = float(pnl[pnl > 0].sum())
        perdidas = float(-pnl[pnl <= 0].sum())
        profit_factor = (ganancias / perdidas) if perdidas > 0 else None

        # Concentración en outliers: % del P&L total que aportan las 5
        # mejores operaciones (>100 % => el resto pierde en conjunto).
        pnl_total = float(pnl.sum())
        top5 = float(np.sort(pnl)[-5:].sum())
        pct_top5 = (100.0 * top5 / pnl_total) if pnl_total > 0 else None

        out.update({
            "win_rate_pct": round(100.0 * float((retornos > 0).sum()) / n, 1),
            "retorno_medio_pct": round(float(retornos.mean()), 2),
            "retorno_mediana_pct": round(float(np.median(retornos)), 2),
            "profit_factor": _round(profit_factor),
            "mejor_operacion_pct": round(float(retornos.max()), 2),
            "peor_operacion_pct": round(float(retornos.min()), 2),
            "semanas_medias_en_pos": round(float(np.mean([t.semanas_en_pos for t in cerradas])), 1),
            "pct_pnl_top5": _round(pct_top5, 1),
        })
        return out

    def _benchmark_metrics(self, fechas: pd.DatetimeIndex, cagr_estrategia: float | None) -> dict:
        """Buy & hold del benchmark en exactamente las mismas fechas que la equity curve."""
        vacio = {
            "benchmark_rentabilidad_pct": None,
            "benchmark_cagr_pct": None,
            "benchmark_max_drawdown_pct": None,
            "benchmark_sharpe_aprox": None,
            "exceso_cagr_pct": None,
        }
        if self.benchmark_close is None or len(fechas) < 2:
            return vacio
        bench = self.benchmark_close.reindex(fechas).ffill().dropna()
        if len(bench) < 2:
            return vacio
        rent = (float(bench.iloc[-1]) / float(bench.iloc[0]) - 1.0) * 100.0
        cagr = _cagr_pct(float(bench.iloc[0]), float(bench.iloc[-1]), bench.index)
        exceso = (cagr_estrategia - cagr) if cagr_estrategia is not None and cagr is not None else None
        return {
            "benchmark_rentabilidad_pct": round(rent, 2),
            "benchmark_cagr_pct": _round(cagr),
            "benchmark_max_drawdown_pct": _round(_max_drawdown_pct(bench)),
            "benchmark_sharpe_aprox": _round(_sharpe(bench)),
            "exceso_cagr_pct": _round(exceso),
        }


def _round(value: float | None, decimals: int = 2) -> float | None:
    return round(value, decimals) if value is not None else None


def _cagr_pct(valor_inicial: float, valor_final: float, fechas: pd.DatetimeIndex) -> float | None:
    if len(fechas) < 2 or valor_inicial <= 0 or valor_final <= 0:
        return None
    anos = (fechas[-1] - fechas[0]).days / 365.25
    if anos <= 0:
        return None
    return ((valor_final / valor_inicial) ** (1.0 / anos) - 1.0) * 100.0


def _max_drawdown_pct(serie: pd.Series) -> float | None:
    if len(serie) == 0:
        return None
    vals = serie.to_numpy(dtype=float)
    running_max = np.maximum.accumulate(vals)
    return float(((vals - running_max) / running_max * 100.0).min())


def _sharpe(serie: pd.Series) -> float | None:
    """
    Sharpe aproximado sobre retornos semanales (sin tipo libre de riesgo,
    x raíz de 52). Referencia para comparar configuraciones entre sí, no
    una cifra de nivel institucional.
    """
    if len(serie) <= 2:
        return None
    vals = serie.to_numpy(dtype=float)
    rets = np.diff(vals) / vals[:-1]
    if rets.std() <= 0:
        return None
    return float(np.mean(rets) / rets.std() * np.sqrt(52))


# ── Evaluación vectorizada de condiciones sobre un ticker ──────────────

def evaluate_entry_mask(ctx: TickerContext, config: StrategyConfig, extra: dict) -> pd.Series:
    """AND de todas las condiciones de entrada activas, precalculado para todo el histórico del ticker."""
    active = config.active_entry_conditions()
    if not active:
        return pd.Series(False, index=ctx.close.index)

    mask = pd.Series(True, index=ctx.close.index)
    for cname, params in active.items():
        spec = ENTRY_CONDITIONS[cname]
        call_params = dict(params)
        if cname == "F5_mercado_alcista":
            call_params["coppock_bullish_aligned"] = extra.get("coppock_bullish")
        cond_mask = spec.func(ctx, **call_params)
        mask &= cond_mask.reindex(ctx.close.index).fillna(False)
    return mask


def evaluate_exit_masks(ctx: TickerContext, config: StrategyConfig, extra: dict) -> dict[str, pd.Series]:
    """Devuelve {nombre_condición: máscara bool} para cada condición de salida activa (sin combinar; el motor hace el OR y arma el motivo)."""
    active = config.active_exit_conditions()
    result = {}
    for cname, params in active.items():
        spec = EXIT_CONDITIONS[cname]
        call_params = dict(params)
        if cname == "S2_mercado_bajista":
            call_params["coppock_bearish_aligned"] = extra.get("coppock_bearish")
        result[cname] = spec.func(ctx, **call_params).reindex(ctx.close.index).fillna(False)
    return result
