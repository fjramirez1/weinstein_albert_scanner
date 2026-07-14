"""
Configuración de una ejecución del backtest de cartera.

`StrategyConfig` es el objeto que agrupa TODO lo que se puede variar de
una ejecución a otra sin tocar código:

  - Qué condiciones de entrada/salida están activas y con qué parámetros.
  - El criterio de desempate (ranking) para elegir candidatos cuando hay
    más señales que huecos libres.
  - El número máximo de posiciones simultáneas.
  - El capital inicial.

Para "probar variaciones", basta con construir varios `StrategyConfig` y
pasarlos a `run_portfolio_backtest` (o a `sweep.py` para compararlos
automáticamente en tabla).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backtest.conditions import ENTRY_CONDITIONS, EXIT_CONDITIONS, RANKING_CRITERIA


@dataclass
class ConditionToggle:
    """Estado de una condición dentro de una config concreta."""
    enabled: bool = True
    params: dict = field(default_factory=dict)


@dataclass
class StrategyConfig:
    """
    Configuración completa de una ejecución del backtest de cartera.

    Parameters
    ----------
    name : etiqueta legible de esta configuración (útil en `sweep.py`).
    entry_conditions : {nombre_condición: ConditionToggle}. Cualquier
        condición registrada en `ENTRY_CONDITIONS` que no aparezca aquí
        se asume activa con sus parámetros por defecto. Para desactivar
        una condición, añadirla explícitamente con `enabled=False`.
    exit_conditions : igual que entry_conditions, pero sobre `EXIT_CONDITIONS`.
    ranking_criterion : clave de `RANKING_CRITERIA` usada para desempatar
        candidatos cuando hay más señales de entrada que huecos libres.
    max_positions : nº máximo de posiciones abiertas simultáneas.
    initial_capital : capital inicial de la cartera simulada, en USD.
    """
    name: str = "default"
    entry_conditions: dict[str, ConditionToggle] = field(default_factory=dict)
    exit_conditions: dict[str, ConditionToggle] = field(default_factory=dict)
    ranking_criterion: str = "momentum"
    max_positions: int = 10
    initial_capital: float = 10_000.0

    def __post_init__(self):
        for cname in self.entry_conditions:
            if cname not in ENTRY_CONDITIONS:
                raise ValueError(
                    f"Condición de entrada desconocida: '{cname}'. "
                    f"Disponibles: {list(ENTRY_CONDITIONS)}"
                )
        for cname in self.exit_conditions:
            if cname not in EXIT_CONDITIONS:
                raise ValueError(
                    f"Condición de salida desconocida: '{cname}'. "
                    f"Disponibles: {list(EXIT_CONDITIONS)}"
                )
        if self.ranking_criterion not in RANKING_CRITERIA:
            raise ValueError(
                f"Criterio de desempate desconocido: '{self.ranking_criterion}'. "
                f"Disponibles: {list(RANKING_CRITERIA)}"
            )
        if self.max_positions < 1:
            raise ValueError("max_positions debe ser >= 1")
        if self.initial_capital <= 0:
            raise ValueError("initial_capital debe ser > 0")

    def active_entry_conditions(self) -> dict[str, dict]:
        """Devuelve {nombre: params_efectivos} de las condiciones de entrada activas."""
        result = {}
        for cname, spec in ENTRY_CONDITIONS.items():
            toggle = self.entry_conditions.get(cname, ConditionToggle())
            if toggle.enabled:
                params = {**spec.default_params, **toggle.params}
                result[cname] = params
        return result

    def active_exit_conditions(self) -> dict[str, dict]:
        """Devuelve {nombre: params_efectivos} de las condiciones de salida activas."""
        result = {}
        for cname, spec in EXIT_CONDITIONS.items():
            toggle = self.exit_conditions.get(cname, ConditionToggle())
            if toggle.enabled:
                params = {**spec.default_params, **toggle.params}
                result[cname] = params
        return result

    def describe(self) -> str:
        """Resumen legible de la configuración, para logs y tablas comparativas."""
        entradas = ", ".join(self.active_entry_conditions().keys()) or "(ninguna)"
        salidas = ", ".join(self.active_exit_conditions().keys()) or "(ninguna)"
        return (
            f"[{self.name}] max_pos={self.max_positions} "
            f"capital_inicial=${self.initial_capital:,.0f} "
            f"ranking={self.ranking_criterion} | "
            f"Entrada: {entradas} | Salida: {salidas}"
        )


def default_config(name: str = "default") -> StrategyConfig:
    """Configuración que replica exactamente la estrategia actual (F1-F5 / S1-S2 tal cual)."""
    return StrategyConfig(name=name)
