"""
Cascade Filling — Reel Gaz (CoolProp, N2, izotermik)

Kurulum:
    pip install CoolProp scipy

Çalıştır:
    python cascade_real_gas.py
"""

import sys
import io

# Windows konsolunda UTF-8 zorla (cp1254 sorunu için)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import CoolProp.CoolProp as CP
from scipy.optimize import brentq

T = 293.15            # K (oda sıcaklığı)
FLUID = "Nitrogen"
BAR_TO_PA = 1e5
L_TO_M3 = 1e-3


# --- Örnek girdi -----------------------------------------------------------
TUBES = [
    {"V_L": 800, "P_bar": 200},
    {"V_L": 800, "P_bar": 200},
    {"V_L": 800, "P_bar": 200},
    {"V_L": 800, "P_bar": 300},
]
TANK = {"V_L": 3250, "P_bar": 1, "P_target_bar": 250}
# ---------------------------------------------------------------------------


def rho(P_bar: float) -> float:
    """N2 yoğunluğu [kg/m³] verilen basınç [bar] ve T'de."""
    return CP.PropsSI("D", "P", P_bar * BAR_TO_PA, "T", T, FLUID)


def mass_kg(V_L: float, P_bar: float) -> float:
    return rho(P_bar) * V_L * L_TO_M3


def equilibrium_pressure(m_total_kg: float, V_total_L: float,
                          P_lo: float = 0.01, P_hi: float = 1000.0) -> float:
    """rho(P_eq) * V_total = m_total denkleminden P_eq'yi bul (brentq)."""
    target_rho = m_total_kg / (V_total_L * L_TO_M3)
    f = lambda P_bar: rho(P_bar) - target_rho
    return brentq(f, P_lo, P_hi, xtol=1e-6)


def cascade_real(tubes, tank, verbose=True):
    V_t = tank["V_L"]
    P_t = tank["P_bar"]
    P_target = tank["P_target_bar"]
    m_t = mass_kg(V_t, P_t)

    indexed = list(enumerate(tubes, start=1))
    indexed.sort(key=lambda x: x[1]["P_bar"])  # küçükten büyüğe

    if verbose:
        print("=" * 70)
        print(f"REEL GAZ (CoolProp, {FLUID}, T = {T} K)")
        print("=" * 70)
        print(f"Tank: V = {V_t} L, P0 = {P_t} bar, hedef = {P_target} bar")
        print(f"Tank başlangıç kütlesi: {m_t:.3f} kg")
        print(f"Tüp sırası (basınca göre): {[i for i, _ in indexed]}\n")
        print(f"{'Adım':<5}{'Tüp':<5}{'V (L)':<8}{'P_tüp':<9}"
              f"{'P_önce':<10}{'P_sonra':<10}{'Δm (kg)':<10}{'Durum'}")
        print("-" * 70)

    step = 0
    for idx, tube in indexed:
        V_d, P_d = tube["V_L"], tube["P_bar"]

        if P_d <= P_t:
            if verbose:
                print(f"{'-':<5}{idx:<5}{V_d:<8}{P_d:<9}"
                      f"{P_t:<10.2f}{'-':<10}{'-':<10}atlandı (P_tüp ≤ P_tank)")
            continue

        m_d = mass_kg(V_d, P_d)
        m_total = m_t + m_d
        V_total = V_t + V_d
        P_eq = equilibrium_pressure(m_total, V_total)

        if P_eq > P_target:
            if verbose:
                print(f"{'-':<5}{idx:<5}{V_d:<8}{P_d:<9}"
                      f"{P_t:<10.2f}{P_eq:<10.2f}{'-':<10}"
                      f"atlandı (denge {P_eq:.1f} > hedef)")
            continue

        # tüpü kullan
        step += 1
        m_tank_new = rho(P_eq) * V_t * L_TO_M3
        dm_kg = m_tank_new - m_t

        if verbose:
            mark = "✓ HEDEF" if P_eq >= P_target else ""
            print(f"{step:<5}{idx:<5}{V_d:<8}{P_d:<9}"
                  f"{P_t:<10.2f}{P_eq:<10.2f}{dm_kg:<10.3f}{mark}")

        P_t = P_eq
        m_t = m_tank_new

        if P_t >= P_target:
            break

    if verbose:
        print("-" * 70)
        if P_t >= P_target:
            print(f"✓ Hedefe ulaşıldı. Final basınç: {P_t:.2f} bar")
        else:
            print(f"✗ Hedefe ulaşılamadı. Final: {P_t:.2f} bar "
                  f"(eksik {P_target - P_t:.2f} bar)")

    return P_t


def cascade_ideal(tubes, tank, verbose=False):
    """Aynı algoritma, ideal gaz (P3 = (P1V1+P2V2)/(V1+V2))."""
    V_t = tank["V_L"]
    P_t = tank["P_bar"]
    P_target = tank["P_target_bar"]

    indexed = list(enumerate(tubes, start=1))
    indexed.sort(key=lambda x: x[1]["P_bar"])

    if verbose:
        print("\n" + "=" * 70)
        print("İDEAL GAZ (referans)")
        print("=" * 70)

    for idx, tube in indexed:
        V_d, P_d = tube["V_L"], tube["P_bar"]
        if P_d <= P_t:
            continue
        P_eq = (P_t * V_t + P_d * V_d) / (V_t + V_d)
        if P_eq > P_target:
            continue
        if verbose:
            print(f"  Tüp {idx}: {P_t:.2f} → {P_eq:.2f} bar")
        P_t = P_eq
        if P_t >= P_target:
            break

    return P_t


def main():
    P_real = cascade_real(TUBES, TANK, verbose=True)
    P_ideal = cascade_ideal(TUBES, TANK, verbose=False)

    print()
    print("=" * 70)
    print("KARŞILAŞTIRMA")
    print("=" * 70)
    print(f"İdeal gaz final basınç : {P_ideal:8.2f} bar")
    print(f"Reel gaz  final basınç : {P_real:8.2f} bar")
    diff = P_ideal - P_real
    pct = 100.0 * diff / P_real if P_real != 0 else float("nan")
    print(f"Fark (ideal − reel)    : {diff:+8.2f} bar  ({pct:+.2f} %)")
    print()
    print("Not: pozitif fark → ideal gaz reel gaza göre basıncı abartıyor.")
    print("Yüksek basınçta N₂ sıkıştırılabilirlik faktörü Z > 1 olduğundan")
    print("aynı kütle için reel gaz daha yüksek basınç verebilir; cascade")
    print("denkliklerinde ise ideal gaz transferi olduğundan fazla gösterir.")


if __name__ == "__main__":
    main()
