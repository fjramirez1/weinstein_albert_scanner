"""
Motor de simulación de cartera para el backtest Weinstein-Albert.

Modelo de cartera (acordado explícitamente con el usuario)
-------------------------------------------------------------
- Capital inicial configurable (por defecto $10.000).
- Máximo `max_positions` posiciones abiertas simultáneamente (por
  defecto 10).
- Cada semana de calendario del S&P 500:
    1. Se evalúan PRIMERO las salidas (S1-S2, OR) de las posiciones
       abiertas esa semana. Las que cumplen cualquier condición activa
       se cierran al precio de cierre de esa semana, liberando efectivo
       y un hueco.
    2. Con los huecos YA liberados por el paso anterior, se evalúan las
       entradas (F1-F5, AND) sobre todo el universo. Los candidatos que
       cumplen todas las condiciones activas se ordenan por el criterio
       de desempate configurado (de mayor a menor) y se abren posiciones
       nuevas hasta llenar los huecos libres. Es decir: una salida y una
       entrada SÍ pueden ocurrir en la misma semana (acordado).
    3. Tamaño de cada posición nueva = valor total de cartera EN ESE
       INSTANTE (efectivo + valor a mercado de las posiciones que siguen
       abiertas) dividido entre `max_positions`. El valor de cartera NO
       se recalcula por el movimiento de precio de posiciones que siguen
       abiertas entre una entrada y otra dentro de la misma semana — solo
       cambia cuando se abre o se cierra una posición (según lo acordado:
       "el valor de cartera actual solo se modifica cuando se cierra una
       posición, no cuando todavía está abierta"). No hay rebalanceos
       entre posiciones ya abiertas. Nunca se invierte más efectivo del
       disponible: si el tamaño teórico (cartera/N) supera el efectivo
       disponible, se invierte solo el efectivo disponible (esto solo
       puede ocurrir si ya hay huecos libres sin usar por falta de
       candidatos previos, ya que en el caso normal cartera/N con huecos
       llenos consistentemente es <= efectivo).
- Sin fricción: sin comisiones ni slippage, precio de cierre exacto.
- Sin apalancamiento ni posiciones cortas.

Nota sobre "valor de cartera" usado para dimensionar
------------------------------------------------------
El enunciado acordado es: "el capital de entrada por entrada sea el valor
de cartera actual / 10 [max_positions]. Pero el valor de cartera actual
solo se modifica cuando se cierra una posición, no cuando todavía está
abierta." Esto se traduce en mantener una variable `capital_disponible`
(efectivo) y una variable `valor_cartera_referencia` que se actualiza:
  - Al cerrar una posición: se suma el efectivo recibido (precio de
    salida × nº acciones) tanto a `capital_disponible` como, por tanto,
    a `valor_cartera_referencia` (que es efectivo + coste histórico de
    las posiciones abiertas restantes, no su valor a mercado fluctuante).
  - Al abrir una posición: se resta el capital invertido de
    `capital_disponible`; `valor_cartera_referencia` no cambia por abrir
    (es una redistribución interna, no un cambio de valor total).
Esto evita que las posiciones abiertas "inflen" o "desinflen" el tamaño
de la siguiente entrada por simple fluctuación de precio no realizada,
que es precisamente lo que se pidió evitar.
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
        """Estadísticas agregadas de la simulación."""
        cerradas = self.closed_trades
        n = len(cerradas)

        capital_inicial = self.config.initial_capital
        valor_final = (
            self.equity_curve[-1].valor_cartera if self.equity_curve else capital_inicial
        )
        rentabilidad_total_pct = ((valor_final / capital_inicial) - 1.0) * 100.0

        if not self.equity_curve:
            n_semanas = 0
        else:
            n_semanas = len(self.equity_curve)
        anos = n_semanas / 52.0 if n_semanas > 0 else 0.0
        cagr_pct = (
            (((valor_final / capital_inicial) ** (1.0 / anos)) - 1.0) * 100.0
            if anos > 0 and valor_final > 0
            else None
        )

        # Max drawdown sobre la curva de equity (valor de cartera semanal).
        if self.equity_curve:
            equity = np.array([p.valor_cartera for p in self.equity_curve], dtype=float)
            running_max = np.maximum.accumulate(equity)
            drawdowns = (equity - running_max) / running_max * 100.0
            max_dd_pct = float(drawdowns.min())
        else:
            max_dd_pct = None

        if n == 0:
            return {
                "capital_inicial": capital_inicial,
                "capital_final": round(valor_final, 2),
                "rentabilidad_total_pct": round(rentabilidad_total_pct, 2),
                "cagr_pct": round(cagr_pct, 2) if cagr_pct is not None else None,
                "max_drawdown_pct": round(max_dd_pct, 2) if max_dd_pct is not None else None,
                "n_operaciones_cerradas": 0,
                "n_operaciones_abiertas_al_final": len(self.open_positions_at_end),
                "win_rate_pct": None,
                "retorno_medio_pct": None,
                "retorno_mediana_pct": None,
                "profit_factor": None,
                "mejor_operacion_pct": None,
                "peor_operacion_pct": None,
                "semanas_medias_en_pos": None,
                "sharpe_aprox": None,
                "pct_semanas_invertido": None,
            }

        retornos = np.array([t.retorno_pct for t in cerradas], dtype=float)
        ganadoras = retornos[retornos > 0]
        perdedoras = retornos[retornos <= 0]

        suma_ganancias = float(ganadoras.sum()) if len(ganadoras) else 0.0
        suma_perdidas = float(-perdedoras.sum()) if len(perdedoras) else 0.0
        profit_factor = (suma_ganancias / suma_perdidas) if suma_perdidas > 0 else None

        # Sharpe aproximado: sobre retornos semanales de la equity curve
        # (no anualizado con precisión de mercado real, es una referencia
        # orientativa para comparar configuraciones entre sí, no una cifra
        # de nivel institucional).
        sharpe = None
        if len(self.equity_curve) > 2:
            equity_vals = np.array([p.valor_cartera for p in self.equity_curve], dtype=float)
            weekly_rets = np.diff(equity_vals) / equity_vals[:-1]
            if weekly_rets.std() > 0:
                sharpe = float(np.mean(weekly_rets) / weekly_rets.std() * np.sqrt(52))

        pct_semanas_invertido = None
        if self.equity_curve:
            semanas_con_posicion = sum(1 for p in self.equity_curve if p.n_posiciones_abiertas > 0)
            pct_semanas_invertido = round(100.0 * semanas_con_posicion / len(self.equity_curve), 1)

        return {
            "capital_inicial": capital_inicial,
            "capital_final": round(valor_final, 2),
            "rentabilidad_total_pct": round(rentabilidad_total_pct, 2),
            "cagr_pct": round(cagr_pct, 2) if cagr_pct is not None else None,
            "max_drawdown_pct": round(max_dd_pct, 2) if max_dd_pct is not None else None,
            "n_operaciones_cerradas": n,
            "n_operaciones_abiertas_al_final": len(self.open_positions_at_end),
            "win_rate_pct": round(100.0 * len(ganadoras) / n, 1),
            "retorno_medio_pct": round(float(retornos.mean()), 2),
            "retorno_mediana_pct": round(float(np.median(retornos)), 2),
            "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
            "mejor_operacion_pct": round(float(retornos.max()), 2),
            "peor_operacion_pct": round(float(retornos.min()), 2),
            "semanas_medias_en_pos": round(float(np.mean([t.semanas_en_pos for t in cerradas])), 1),
            "sharpe_aprox": round(sharpe, 2) if sharpe is not None else None,
            "pct_semanas_invertido": pct_semanas_invertido,
        }


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
