"""
Tank Cascade Doldurma Hesaplayıcı — Masaüstü Uygulama

İdeal gaz ve reel gaz (CoolProp, N2) cascade filling sonuçlarını
yan yana hesaplar.

Çalıştır:
    python app.py     (gerekirse eksik kütüphaneleri otomatik kurar)

Manuel kurulum:
    pip install -r requirements.txt
"""

import sys
import io
import os
import subprocess
import importlib

# ---------- Bağımlılık bootstrap ----------
REQUIRED = [
    # (import_name, pip_name)
    ("CoolProp", "CoolProp"),
    ("scipy", "scipy"),
    ("numpy", "numpy"),
]


def _missing_packages():
    missing = []
    for mod, pkg in REQUIRED:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(pkg)
    return missing


def _ensure_dependencies():
    """Eksik paketleri pip ile kurmayı dener; başarısızsa Tk uyarısı gösterir."""
    missing = _missing_packages()
    if not missing:
        return True

    msg = (f"Eksik kütüphaneler tespit edildi: {', '.join(missing)}\n"
           f"Kuruluyor (pip install --user)...")
    print(msg, flush=True)

    # Önce pip var mı emin ol
    try:
        import pip  # noqa: F401
    except ImportError:
        try:
            import ensurepip
            ensurepip.bootstrap()
        except Exception as e:
            _show_install_error(
                f"pip bulunamadı ve kurulamadı: {e}\n"
                "Python'u 'pip dahil' olarak yeniden kurmanız gerekebilir."
            )
            return False

    # Kurulum dene: önce --user, olmazsa system-wide
    cmds = [
        [sys.executable, "-m", "pip", "install", "--user", "--upgrade"] + missing,
        [sys.executable, "-m", "pip", "install", "--upgrade"] + missing,
    ]
    last_err = None
    for cmd in cmds:
        try:
            subprocess.check_call(cmd)
            break
        except subprocess.CalledProcessError as e:
            last_err = e
            continue
    else:
        _show_install_error(
            f"Kütüphaneler otomatik kurulamadı.\n\n"
            f"Lütfen elle çalıştırın:\n"
            f"  {sys.executable} -m pip install {' '.join(missing)}\n\n"
            f"Hata: {last_err}"
        )
        return False

    # Yeni kurulan paketler için import path'i tazele
    importlib.invalidate_caches()
    still_missing = _missing_packages()
    if still_missing:
        _show_install_error(
            f"Kurulum tamamlandı ama hâlâ eksik: {still_missing}\n"
            f"Uygulamayı kapatıp yeniden açmayı deneyin."
        )
        return False
    return True


def _show_install_error(text):
    """Konsol veya tkinter uyarısı göster."""
    print(text, file=sys.stderr, flush=True)
    try:
        import tkinter as _tk
        from tkinter import messagebox as _mb
        root = _tk.Tk()
        root.withdraw()
        _mb.showerror("Bağımlılık Hatası", text)
        root.destroy()
    except Exception:
        pass


_ensure_dependencies()
# ---------- /Bağımlılık bootstrap ----------

import tkinter as tk
from tkinter import ttk, messagebox

# Windows konsolu UTF-8
if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                       errors="replace")
    except Exception:
        pass

try:
    import CoolProp.CoolProp as CP
    from scipy.optimize import brentq
    REAL_GAS_OK = True
    REAL_GAS_ERR = None
except Exception as e:
    REAL_GAS_OK = False
    REAL_GAS_ERR = str(e)


BAR_TO_PA = 1e5
L_TO_M3 = 1e-3


# ---------- Termodinamik çekirdek ----------

def rho_real(P_bar, T_K, fluid="Nitrogen"):
    return CP.PropsSI("D", "P", P_bar * BAR_TO_PA, "T", T_K, fluid)


def build_tubes(n200, n300, V_man, order="lowFirst"):
    tubes = []
    if order == "lowFirst":
        for i in range(n200):
            tubes.append({"V_L": V_man, "P_bar": 200.0, "label": f"200 bar #{i+1}"})
        for i in range(n300):
            tubes.append({"V_L": V_man, "P_bar": 300.0, "label": f"300 bar #{i+1}"})
    else:
        for i in range(n300):
            tubes.append({"V_L": V_man, "P_bar": 300.0, "label": f"300 bar #{i+1}"})
        for i in range(n200):
            tubes.append({"V_L": V_man, "P_bar": 200.0, "label": f"200 bar #{i+1}"})
    return tubes


def find_cheapest(tank, V_man, p200, p300, mode, T_K=293.15,
                   order="lowFirst", max_n200=80, max_n300=40):
    """Hedefe ulaşan en ucuz (n200, n300) kombinasyonunu döndürür.

    mode: 'ideal' veya 'real'.
    Strateji: her n300 için target'a yetecek en küçük n200'ü bul, min cost seç.
    """
    target = tank["P_target_bar"]
    best = None

    for n300 in range(0, max_n300 + 1):
        for n200 in range(0, max_n200 + 1):
            tubes = build_tubes(n200, n300, V_man, order)
            if mode == "ideal":
                P_final, _ = cascade_ideal(tank, tubes)
            else:
                P_final, _ = cascade_real(tank, tubes, T_K=T_K)

            if P_final >= target:
                cost = n200 * p200 + n300 * p300
                if best is None or cost < best["cost"]:
                    best = {
                        "n200": n200, "n300": n300,
                        "cost": cost, "P_final": P_final,
                        "total_tubes": n200 + n300,
                    }
                break  # bu n300 için n200 artırmak sadece pahalılaştırır
        # erken çıkış: n200=0 ile yetiyorsa daha çok n300 = sadece pahalılaşır
        if best is not None and best["n200"] == 0 and best["n300"] == n300:
            break

    return best


def cascade_ideal(tank, tubes):
    """tubes: [{V_L, P_bar, label}], tank: {V_L, P_bar, P_target_bar}"""
    V_t = tank["V_L"]
    P_t = tank["P_bar"]
    P_target = tank["P_target_bar"]

    rows = []
    final_P = P_t
    for i, tube in enumerate(tubes, start=1):
        V_d, P_d, label = tube["V_L"], tube["P_bar"], tube["label"]
        if P_d <= P_t:
            rows.append({
                "step": i, "label": label, "P_d": P_d, "V_d": V_d,
                "P_before": P_t, "P_after": P_t, "dm_kg": 0.0,
                "status": "atlandı (P_tüp ≤ P_tank)"
            })
            continue

        P_eq = (P_t * V_t + P_d * V_d) / (V_t + V_d)
        # ideal kütle: PV = nRT → m = PV·M/(RT)
        M_N2 = 28.0134        # g/mol
        R = 0.0831446         # L·bar/(mol·K)
        T_assume = 293.15
        n_before = P_t * V_t / (R * T_assume)
        n_after = P_eq * V_t / (R * T_assume)
        dm_kg = (n_after - n_before) * M_N2 / 1000.0

        rows.append({
            "step": i, "label": label, "P_d": P_d, "V_d": V_d,
            "P_before": P_t, "P_after": P_eq, "dm_kg": dm_kg,
            "status": "✓ HEDEF" if P_eq >= P_target else ""
        })
        P_t = P_eq
        final_P = P_t
        if P_t >= P_target:
            for j in range(i, len(tubes)):
                t2 = tubes[j]
                rows.append({
                    "step": j + 1, "label": t2["label"], "P_d": t2["P_bar"],
                    "V_d": t2["V_L"], "P_before": P_t, "P_after": P_t,
                    "dm_kg": 0.0, "status": "kullanılmadı"
                })
            break

    return final_P, rows


def cascade_real(tank, tubes, T_K=293.15, fluid="Nitrogen"):
    V_t = tank["V_L"]
    P_t = tank["P_bar"]
    P_target = tank["P_target_bar"]

    m_t = rho_real(P_t, T_K, fluid) * V_t * L_TO_M3
    rows = []
    final_P = P_t

    for i, tube in enumerate(tubes, start=1):
        V_d, P_d, label = tube["V_L"], tube["P_bar"], tube["label"]
        if P_d <= P_t:
            rows.append({
                "step": i, "label": label, "P_d": P_d, "V_d": V_d,
                "P_before": P_t, "P_after": P_t, "dm_kg": 0.0,
                "status": "atlandı (P_tüp ≤ P_tank)"
            })
            continue

        m_d = rho_real(P_d, T_K, fluid) * V_d * L_TO_M3
        m_total = m_t + m_d
        V_total = V_t + V_d
        target_rho = m_total / (V_total * L_TO_M3)

        f = lambda P: rho_real(P, T_K, fluid) - target_rho
        try:
            P_eq = brentq(f, 0.01, 1500.0, xtol=1e-6)
        except ValueError:
            rows.append({
                "step": i, "label": label, "P_d": P_d, "V_d": V_d,
                "P_before": P_t, "P_after": P_t, "dm_kg": 0.0,
                "status": "brentq aralık hatası"
            })
            continue

        m_tank_new = rho_real(P_eq, T_K, fluid) * V_t * L_TO_M3
        dm_kg = m_tank_new - m_t

        rows.append({
            "step": i, "label": label, "P_d": P_d, "V_d": V_d,
            "P_before": P_t, "P_after": P_eq, "dm_kg": dm_kg,
            "status": "✓ HEDEF" if P_eq >= P_target else ""
        })
        P_t = P_eq
        m_t = m_tank_new
        final_P = P_t

        if P_t >= P_target:
            for j in range(i, len(tubes)):
                t2 = tubes[j]
                rows.append({
                    "step": j + 1, "label": t2["label"], "P_d": t2["P_bar"],
                    "V_d": t2["V_L"], "P_before": P_t, "P_after": P_t,
                    "dm_kg": 0.0, "status": "kullanılmadı"
                })
            break

    return final_P, rows


# ---------- UI ----------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Tank Cascade Doldurma Hesaplayıcı")
        self.geometry("1480x820")
        self.configure(bg="#0f1419")

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background="#0f1419", foreground="#e8eef2",
                        fieldbackground="#1a2230", bordercolor="#2a3441")
        style.configure("TLabel", background="#0f1419", foreground="#e8eef2")
        style.configure("Header.TLabel", foreground="#4ec9b0",
                        font=("Segoe UI", 14, "bold"))
        style.configure("Sub.TLabel", foreground="#9cdcfe",
                        font=("Segoe UI", 11, "bold"))
        style.configure("Small.TLabel", foreground="#8a96a3",
                        font=("Segoe UI", 8))
        style.configure("TFrame", background="#0f1419")
        style.configure("Card.TFrame", background="#1a2230")
        style.configure("Card.TLabel", background="#1a2230", foreground="#e8eef2")
        style.configure("CardSub.TLabel", background="#1a2230", foreground="#9cdcfe",
                        font=("Segoe UI", 10, "bold"))
        style.configure("CardSmall.TLabel", background="#1a2230", foreground="#8a96a3",
                        font=("Segoe UI", 8))
        style.configure("TEntry", fieldbackground="#1a2230",
                        foreground="#e8eef2", insertcolor="#e8eef2")
        style.configure("Accent.TButton",
                        background="#4ec9b0", foreground="#0f1419",
                        font=("Segoe UI", 10, "bold"), padding=8)
        style.map("Accent.TButton", background=[("active", "#6edcc4")])
        style.configure("Treeview", background="#1a2230",
                        fieldbackground="#1a2230", foreground="#e8eef2",
                        rowheight=22, font=("Consolas", 9))
        style.configure("Treeview.Heading", background="#232d3d",
                        foreground="#9cdcfe", font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#2a3441")])

        self._build()
        self.calculate()

    def _build(self):
        ttk.Label(self, text="Tank Cascade Doldurma Hesaplayıcı",
                  style="Header.TLabel").pack(anchor="w", padx=16, pady=(12, 0))
        ttk.Label(self, text="İdeal Gaz + Reel Gaz (CoolProp, N₂, izotermik)",
                  style="Small.TLabel").pack(anchor="w", padx=16, pady=(0, 8))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=16, pady=8)

        # Sol: girdiler
        left = ttk.Frame(body, style="Card.TFrame")
        left.pack(side="left", fill="y", padx=(0, 12))

        ttk.Label(left, text="Parametreler", style="CardSub.TLabel"
                  ).grid(row=0, column=0, columnspan=2, sticky="w",
                         padx=12, pady=(12, 8))

        self.vars = {}
        fields = [
            ("tank_V", "Tank hacmi (L)", "3250", "650 × 5"),
            ("tank_P0", "Tank başlangıç P (bar)", "1", "1 atm ≈ 1 bar"),
            ("tank_Pt", "Hedef basınç (bar)", "250", ""),
            ("man_V", "Manifold hacmi (L)", "800", "16 × 50"),
            ("n200", "200 bar manifold sayısı", "3", ""),
            ("n300", "300 bar manifold sayısı", "1", ""),
            ("p200", "200 bar fiyat (TL)", "4000", ""),
            ("p300", "300 bar fiyat (TL)", "100000", ""),
            ("T", "Sıcaklık (K)", "293.15", "Reel gaz için"),
        ]
        for i, (key, label, default, hint) in enumerate(fields, start=1):
            ttk.Label(left, text=label, style="Card.TLabel").grid(
                row=i, column=0, sticky="w", padx=(12, 8), pady=2)
            v = tk.StringVar(value=default)
            self.vars[key] = v
            ttk.Entry(left, textvariable=v, width=14).grid(
                row=i, column=1, sticky="ew", padx=(0, 12), pady=2)
            if hint:
                ttk.Label(left, text=hint, style="CardSmall.TLabel").grid(
                    row=i, column=2, sticky="w", padx=(0, 12))

        ttk.Label(left, text="Cascade sırası", style="Card.TLabel").grid(
            row=len(fields) + 1, column=0, sticky="w", padx=(12, 8), pady=(8, 2))
        self.order = tk.StringVar(value="lowFirst")
        order_box = ttk.Combobox(left, textvariable=self.order, state="readonly",
                                  values=["lowFirst", "highFirst"], width=12)
        order_box.grid(row=len(fields) + 1, column=1, sticky="ew",
                       padx=(0, 12), pady=(8, 2))
        ttk.Label(left, text="(düşük→yüksek / yüksek→düşük)",
                  style="CardSmall.TLabel").grid(
            row=len(fields) + 1, column=2, sticky="w", padx=(0, 12))

        ttk.Button(left, text="HESAPLA", style="Accent.TButton",
                   command=self.calculate).grid(
            row=len(fields) + 2, column=0, columnspan=3,
            sticky="ew", padx=12, pady=(16, 6))

        ttk.Button(left, text="OPTİMUM BUL (en ucuz)",
                   style="Accent.TButton",
                   command=self.find_optimum).grid(
            row=len(fields) + 3, column=0, columnspan=3,
            sticky="ew", padx=12, pady=(0, 12))

        ttk.Label(left,
                  text="Hedefe ulaşan en ucuz (n200, n300) kombinasyonunu\n"
                       "ideal ve reel gaz için ayrı ayrı arar.",
                  style="CardSmall.TLabel", wraplength=240).grid(
            row=len(fields) + 4, column=0, columnspan=3,
            sticky="w", padx=12, pady=(0, 8))

        if not REAL_GAS_OK:
            ttk.Label(left,
                      text=f"⚠ CoolProp yok — sadece ideal gaz çalışır.\n{REAL_GAS_ERR}",
                      style="CardSmall.TLabel", wraplength=240).grid(
                row=len(fields) + 5, column=0, columnspan=3,
                sticky="w", padx=12, pady=(0, 12))

        # Sağ: sonuçlar
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)

        # Üst özet kartı
        self.summary = ttk.Frame(right, style="Card.TFrame")
        self.summary.pack(fill="x", pady=(0, 12))

        # İki kolon: ideal / reel
        cols = ttk.Frame(right)
        cols.pack(fill="both", expand=True)

        ideal_box = ttk.Frame(cols, style="Card.TFrame")
        ideal_box.pack(side="left", fill="both", expand=True, padx=(0, 6))
        ttk.Label(ideal_box, text="İDEAL GAZ", style="CardSub.TLabel").pack(
            anchor="w", padx=12, pady=(10, 4))
        self.opt_ideal = ttk.Frame(ideal_box, style="Card.TFrame")
        self.opt_ideal.pack(fill="x", padx=12, pady=(0, 6))
        self._render_opt_placeholder(self.opt_ideal)
        self.tree_ideal = self._make_tree(ideal_box)

        real_box = ttk.Frame(cols, style="Card.TFrame")
        real_box.pack(side="left", fill="both", expand=True, padx=(6, 0))
        ttk.Label(real_box, text="REEL GAZ (CoolProp, N₂)",
                  style="CardSub.TLabel").pack(anchor="w", padx=12, pady=(10, 4))
        self.opt_real = ttk.Frame(real_box, style="Card.TFrame")
        self.opt_real.pack(fill="x", padx=12, pady=(0, 6))
        self._render_opt_placeholder(self.opt_real)
        self.tree_real = self._make_tree(real_box)

    def _render_opt_placeholder(self, parent):
        for w in parent.winfo_children():
            w.destroy()
        ttk.Label(parent,
                  text="Optimum: — (OPTİMUM BUL'a basın)",
                  style="CardSmall.TLabel").pack(anchor="w", padx=2, pady=2)

    def _render_optimum(self, parent, label, best, target, mode_key):
        for w in parent.winfo_children():
            w.destroy()
        ttk.Label(parent, text=f"OPTİMUM ({label})",
                  style="CardSub.TLabel",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=2)

        if best is None:
            ttk.Label(parent,
                      text="Hedefe ulaşan kombinasyon bulunamadı "
                           "(max 80×200 + 40×300).",
                      style="CardSmall.TLabel", wraplength=520).pack(
                anchor="w", padx=2, pady=(2, 4))
            return

        # Detay satırları
        line1 = (f"200 bar × {best['n200']}   +   300 bar × {best['n300']}     "
                 f"=   {best['total_tubes']} manifold")
        ttk.Label(parent, text=line1, style="Card.TLabel",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=2, pady=(2, 0))

        cost_str = f"{best['cost']:,.0f} TL".replace(",", ".")
        line2 = (f"Maliyet: {cost_str}     ·     "
                 f"Final: {best['P_final']:.2f} bar     ·     "
                 f"Hedef: {target:.0f} bar")
        ttk.Label(parent, text=line2, style="CardSmall.TLabel").pack(
            anchor="w", padx=2, pady=(2, 4))

        def apply():
            self.vars["n200"].set(str(best["n200"]))
            self.vars["n300"].set(str(best["n300"]))
            self.calculate()

        ttk.Button(parent, text=f"{label} optimumunu uygula",
                   style="Accent.TButton", command=apply).pack(
            anchor="w", padx=2, pady=(2, 6))

    def _make_tree(self, parent):
        cols = ("step", "label", "P_d", "P_before", "P_after", "dm_kg", "status")
        widths = {"step": 32, "label": 72, "P_d": 52, "P_before": 64,
                  "P_after": 64, "dm_kg": 74, "status": 170}
        headings = {"step": "#", "label": "Tüp", "P_d": "P_tüp",
                    "P_before": "P_önce", "P_after": "P_sonra",
                    "dm_kg": "Δm (kg)", "status": "Durum"}
        wrapper = ttk.Frame(parent, style="Card.TFrame")
        wrapper.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        tree = ttk.Treeview(wrapper, columns=cols, show="headings", height=18)
        for c in cols:
            tree.heading(c, text=headings[c])
            tree.column(c, width=widths[c], anchor="w", stretch=False)
        tree.tag_configure("ok", background="#1f3530")
        tree.tag_configure("skip", foreground="#8a96a3")
        hsb = ttk.Scrollbar(wrapper, orient="horizontal", command=tree.xview)
        tree.configure(xscrollcommand=hsb.set)
        tree.pack(side="top", fill="both", expand=True)
        hsb.pack(side="bottom", fill="x")
        return tree

    def _read_inputs(self):
        try:
            tank = {
                "V_L": float(self.vars["tank_V"].get()),
                "P_bar": float(self.vars["tank_P0"].get()),
                "P_target_bar": float(self.vars["tank_Pt"].get()),
            }
            V_man = float(self.vars["man_V"].get())
            n200 = int(self.vars["n200"].get())
            n300 = int(self.vars["n300"].get())
            p200 = float(self.vars["p200"].get())
            p300 = float(self.vars["p300"].get())
            T_K = float(self.vars["T"].get())
        except ValueError as e:
            raise ValueError(f"Sayısal girdi hatası: {e}")

        order = self.order.get()
        tubes = []
        if order == "lowFirst":
            for i in range(n200):
                tubes.append({"V_L": V_man, "P_bar": 200.0,
                              "label": f"200 bar #{i+1}"})
            for i in range(n300):
                tubes.append({"V_L": V_man, "P_bar": 300.0,
                              "label": f"300 bar #{i+1}"})
        else:
            for i in range(n300):
                tubes.append({"V_L": V_man, "P_bar": 300.0,
                              "label": f"300 bar #{i+1}"})
            for i in range(n200):
                tubes.append({"V_L": V_man, "P_bar": 200.0,
                              "label": f"200 bar #{i+1}"})

        return tank, tubes, p200, p300, n200, n300, T_K

    def _fill_tree(self, tree, rows):
        for item in tree.get_children():
            tree.delete(item)
        for r in rows:
            tags = ()
            if "HEDEF" in r["status"]:
                tags = ("ok",)
            elif "kullanılmadı" in r["status"] or "atlandı" in r["status"]:
                tags = ("skip",)
            tree.insert("", "end", values=(
                r["step"], r["label"], f"{r['P_d']:.0f}",
                f"{r['P_before']:.2f}", f"{r['P_after']:.2f}",
                f"{r['dm_kg']:.3f}", r["status"]
            ), tags=tags)

    def _render_summary(self, tank, P_ideal, P_real, total_cost,
                        n200, n300, real_ok):
        for w in self.summary.winfo_children():
            w.destroy()

        def card(parent, label, value, sub=""):
            f = ttk.Frame(parent, style="Card.TFrame")
            f.pack(side="left", fill="x", expand=True, padx=6, pady=10)
            ttk.Label(f, text=label, style="CardSmall.TLabel").pack(
                anchor="w", padx=10)
            ttk.Label(f, text=value, style="Card.TLabel",
                      font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=10)
            if sub:
                ttk.Label(f, text=sub, style="CardSmall.TLabel").pack(
                    anchor="w", padx=10)

        target = tank["P_target_bar"]
        card(self.summary, "Toplam Maliyet",
             f"{total_cost:,.0f} TL".replace(",", "."),
             f"{n200}×200 + {n300}×300")
        card(self.summary, "İdeal Gaz Final",
             f"{P_ideal:.2f} bar",
             "✓ Hedef" if P_ideal >= target else f"✗ eksik {target - P_ideal:.1f}")
        if real_ok:
            card(self.summary, "Reel Gaz Final",
                 f"{P_real:.2f} bar",
                 "✓ Hedef" if P_real >= target else f"✗ eksik {target - P_real:.1f}")
            diff = P_ideal - P_real
            pct = 100.0 * diff / P_real if P_real else 0.0
            card(self.summary, "İdeal − Reel",
                 f"{diff:+.2f} bar", f"{pct:+.2f} %")
        else:
            card(self.summary, "Reel Gaz", "yok",
                 "CoolProp kurulu değil")
            card(self.summary, "Hedef", f"{target} bar", "")

    def _render_optimum_summary(self, tank, ideal_best, real_best):
        for w in self.summary.winfo_children():
            w.destroy()

        def card(parent, label, value, sub=""):
            f = ttk.Frame(parent, style="Card.TFrame")
            f.pack(side="left", fill="x", expand=True, padx=6, pady=10)
            ttk.Label(f, text=label, style="CardSmall.TLabel").pack(
                anchor="w", padx=10)
            ttk.Label(f, text=value, style="Card.TLabel",
                      font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=10)
            if sub:
                ttk.Label(f, text=sub, style="CardSmall.TLabel").pack(
                    anchor="w", padx=10)

        target = tank["P_target_bar"]

        if ideal_best:
            cost_str = f"{ideal_best['cost']:,.0f} TL".replace(",", ".")
            card(self.summary, "İDEAL OPTİMUM",
                 cost_str,
                 f"{ideal_best['n200']}×200 + {ideal_best['n300']}×300  =  "
                 f"{ideal_best['total_tubes']} manifold")
            card(self.summary, "İdeal Final",
                 f"{ideal_best['P_final']:.2f} bar",
                 f"hedef {target:.0f} bar")
        else:
            card(self.summary, "İDEAL OPTİMUM", "—", "bulunamadı")
            card(self.summary, "İdeal Final", "—", "")

        if real_best:
            cost_str = f"{real_best['cost']:,.0f} TL".replace(",", ".")
            card(self.summary, "REEL OPTİMUM",
                 cost_str,
                 f"{real_best['n200']}×200 + {real_best['n300']}×300  =  "
                 f"{real_best['total_tubes']} manifold")
            card(self.summary, "Reel Final",
                 f"{real_best['P_final']:.2f} bar",
                 f"hedef {target:.0f} bar")
        elif REAL_GAS_OK:
            card(self.summary, "REEL OPTİMUM", "—", "bulunamadı")
            card(self.summary, "Reel Final", "—", "")
        else:
            card(self.summary, "REEL OPTİMUM", "—", "CoolProp yok")
            card(self.summary, "Reel Final", "—", "")

    def calculate(self):
        try:
            tank, tubes, p200, p300, n200, n300, T_K = self._read_inputs()
        except ValueError as e:
            messagebox.showerror("Girdi hatası", str(e))
            return

        total_cost = n200 * p200 + n300 * p300

        P_ideal, rows_ideal = cascade_ideal(tank, tubes)
        self._fill_tree(self.tree_ideal, rows_ideal)

        if REAL_GAS_OK:
            try:
                P_real, rows_real = cascade_real(tank, tubes, T_K=T_K)
                self._fill_tree(self.tree_real, rows_real)
            except Exception as e:
                messagebox.showerror("Reel gaz hatası", str(e))
                P_real = float("nan")
        else:
            P_real = float("nan")
            for item in self.tree_real.get_children():
                self.tree_real.delete(item)
            self.tree_real.insert("", "end", values=(
                "—", "CoolProp yok", "—", "—", "—", "—",
                "pip install CoolProp"))

        self._render_summary(tank, P_ideal, P_real, total_cost,
                             n200, n300, REAL_GAS_OK)

    def find_optimum(self):
        try:
            tank, _, p200, p300, _, _, T_K = self._read_inputs()
            V_man = float(self.vars["man_V"].get())
        except ValueError as e:
            messagebox.showerror("Girdi hatası", str(e))
            return
        order = self.order.get()

        if tank["P_target_bar"] >= 300:
            messagebox.showwarning("Uyarı",
                "Hedef ≥ 300 bar — 300 bar manifoldlarla asimptotik olarak\n"
                "300 bar'a yaklaşılır, hedef ulaşılamayabilir.")

        self.config(cursor="watch")
        self.update()
        try:
            ideal_best = find_cheapest(tank, V_man, p200, p300,
                                        mode="ideal", T_K=T_K, order=order)
            real_best = None
            if REAL_GAS_OK:
                real_best = find_cheapest(tank, V_man, p200, p300,
                                           mode="real", T_K=T_K, order=order)
        finally:
            self.config(cursor="")

        target = tank["P_target_bar"]
        self._render_optimum(self.opt_ideal, "İDEAL", ideal_best, target, "ideal")
        if REAL_GAS_OK:
            self._render_optimum(self.opt_real, "REEL", real_best, target, "real")
        else:
            for w in self.opt_real.winfo_children():
                w.destroy()
            ttk.Label(self.opt_real,
                      text="Reel gaz optimumu yok — CoolProp kurulu değil.",
                      style="CardSmall.TLabel").pack(anchor="w", padx=2, pady=4)

        # Her iki tabloya kendi optimum rotasını yaz
        if ideal_best is not None:
            tubes_i = build_tubes(ideal_best["n200"], ideal_best["n300"],
                                   V_man, order)
            _, rows_i = cascade_ideal(tank, tubes_i)
            self._fill_tree(self.tree_ideal, rows_i)
        if REAL_GAS_OK and real_best is not None:
            tubes_r = build_tubes(real_best["n200"], real_best["n300"],
                                   V_man, order)
            _, rows_r = cascade_real(tank, tubes_r, T_K=T_K)
            self._fill_tree(self.tree_real, rows_r)

        # Özet kartlarını optimum moduna göre yenile (her modun kendi maliyeti)
        self._render_optimum_summary(tank, ideal_best, real_best)


if __name__ == "__main__":
    App().mainloop()
