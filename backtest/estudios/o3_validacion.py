"""
O3 (docs/HOJA_DE_RUTA.md): validación fuera de muestra, UNA sola vez, en el
tramo 2023-01-06 → 2026-10-30, que no se usó en O2.

El candidato y las hipótesis están pre-registrados en docs/BITACORA.md
(2026-11-03 (14)) antes de ejecutar este script:

- Candidato: reglas "sin F5 ni S2" + ranking VPM5.
- H1: la mediana con ranking aleatorio de "sin F5" y "sin F5 ni S2" supera
  a la de producción.
- H2: VPM5 supera la mediana del azar en la mayoría de los conjuntos; MOM no.
- H3: el candidato supera al baseline de producción (MOM) en CAGR y Sharpe.

Uso (lee la caché de 10 años):
    python -m backtest.estudios.o3_validacion

Escribe historial/backtests/o3_validacion.csv y o3_validacion_resumen.csv.
"""
from backtest.estudios.o2_barrido import (
    OFF,
    ON,
    SIN_F5,
    SIN_S2,
    _resumen_r3,
    _variantes_con_azar,
    ejecutar,
)

INICIO, FIN = "2023-01-06", "2026-10-30"
SALIDA = "historial/backtests/o3_validacion{sufijo}.csv"

REGLAS_O3: dict[str, dict] = {
    "produccion": {},
    "f5b": dict(entry_conditions={"F5_mercado_alcista": OFF, "F5b_mercado_no_bajista": ON}),
    "f5_off": dict(entry_conditions=SIN_F5),
    "f5_off_s2_off": dict(entry_conditions=SIN_F5, exit_conditions=SIN_S2),
}
CANDIDATO = "f5_off_s2_off|vpm5"
BASELINE = "produccion|momentum"


def main() -> None:
    df = ejecutar(_variantes_con_azar(REGLAS_O3), INICIO, FIN)
    df.to_csv(SALIDA.format(sufijo=""), index=False, encoding="utf-8-sig")
    resumen = _resumen_r3(df)
    resumen.to_csv(SALIDA.format(sufijo="_resumen"), index=False, encoding="utf-8-sig")
    print("\nRanking real frente a rankings aleatorios (pct = % de semillas que supera):")
    print(resumen.to_string(index=False))

    filas = df.set_index("variante")
    medianas = resumen.set_index("reglas")["azar_CAGR_mediana"]
    h1 = all(medianas[r] > medianas["produccion"] for r in ("f5_off", "f5_off_s2_off"))
    h2_vpm5 = int((resumen["vpm5_pct"] > 50).sum())
    h2_mom = int((resumen["momentum_pct"] > 50).sum())
    cand, base = filas.loc[CANDIDATO], filas.loc[BASELINE]
    h3 = cand["CAGR%"] > base["CAGR%"] and cand["Sharpe"] > base["Sharpe"]
    spy = filas.loc["SPY"]

    print(f"\nH1 (sin filtro de mercado > producción, mediana del azar): {'SÍ' if h1 else 'NO'}")
    print(f"H2 (VPM5 > mediana del azar en {h2_vpm5}/{len(resumen)} conjuntos; MOM en {h2_mom}/{len(resumen)})")
    print(f"H3 (candidato > baseline en CAGR y Sharpe): {'SÍ' if h3 else 'NO'}")
    for nombre, f in (("candidato " + CANDIDATO, cand), ("baseline " + BASELINE, base), ("SPY", spy)):
        print(f"  {nombre:<32} CAGR {f['CAGR%']:>6}%  Sharpe {f['Sharpe']:>5}  DD {f['DD%']:>7}%")


if __name__ == "__main__":
    main()
