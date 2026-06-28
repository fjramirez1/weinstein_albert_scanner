"""
Capa de compatibilidad con versiones anteriores.

Este módulo re-exporta las funciones que antes vivían aquí directamente,
ahora organizadas en ``weinstein/indicators.py``. Si tienes código
externo que importa desde ``we_utils``, seguirá funcionando sin cambios.

Para código nuevo, importa directamente desde el paquete:

    from weinstein.indicators import wma, rsc_mansfield, ...
"""

from weinstein.indicators import (  # noqa: F401  (re-exports)
    coppock_curve,
    momentum_vs_wma as calculate_mom,
    rsc_mansfield,
    sp500_alcista,
    vpm5,
    wma,
)