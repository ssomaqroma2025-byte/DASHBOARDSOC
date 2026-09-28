# -*- coding: utf-8 -*-
# Compara el cumplimiento por planta de una semana: reglas corregidas vs reglas del Power BI.
import io, re, json, csv, sys, unicodedata
from collections import defaultdict

WO = int(sys.argv[1]) if len(sys.argv) > 1 else 202635
t = io.open("index.html", encoding="utf-8").read()
D = json.loads(re.search(r"const DATA=(\{.*?\});\s*//", t, re.S).group(1))
ppl, soc = D["ppl"], D["soc"]
nm = set(D["nm"].get(str(WO), []))

def activo_rng(rng, cod, wo):
    r = rng.get(cod)
    return True if not r else any(a <= wo <= b for a, b in r)

def calc(activo, nmset):
    agg = defaultdict(lambda: [0, 0]); fuera = 0
    for p in ppl:
        if not activo(p["cod"], WO): fuera += 1; continue
        m = 0 if p["cod"] in nmset else p["mb"]
        f = min(soc.get(p["cod"], {}).get(str(WO), 0), m)
        agg[p["pl"]][0] += m; agg[p["pl"]][1] += f
    return agg, fuera

# Reglas del Power BI: solo DESPIDO / CONTRATACION cambian la existencia; lo demás es ausencia de esa semana
def st(s): return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
ev, nm_pbi = defaultdict(list), set()
padset = {p["cod"] for p in ppl}
for fn in ("data/justif_a.csv", "data/justif_b.csv"):
    for r in csv.DictReader(io.open(fn, encoding="utf-8-sig")):
        cod = r["cod"].strip()
        if cod not in padset: continue
        try: a = int(float(r["anio"]))
        except ValueError: continue
        d = re.sub(r"\D", "", r["semana"])
        if not d: continue
        so = a*100 + int(d); mot = st(r["motivo"].strip().upper()) or "JUSTIFICADO"
        if mot == "DESPIDO": ev[cod].append((so, "S"))
        elif mot == "CONTRATACION": ev[cod].append((so, "E"))
        elif so == WO: nm_pbi.add(cod)
def activo_pbi(cod, wo):
    for so, cl in ev.get(cod, []):
        if cl == "S" and wo > so: return False
        if cl == "E" and wo < so: return False
    return True

nuevo, fuera_n = calc(lambda c, w: activo_rng(D["rng"], c, w), nm)
viejo, fuera_v = calc(activo_pbi, nm_pbi)
PBI = {"AGUSTINO": (640, 693), "ÑAÑA": (341, 366), "PROVINCIAS": (32, 33)}
print("Semana %d   (fijos/meta = %%)" % WO)
print("%-11s %-17s %-17s %-17s" % ("Planta", "Power BI", "Regla PBI (web)", "Regla corregida"))
for pl in ("AGUSTINO", "ÑAÑA", "PROVINCIAS"):
    b = PBI.get(pl); v = viejo.get(pl, [0, 0]); n = nuevo.get(pl, [0, 0])
    fmt = lambda f, m: "%d/%d = %.1f%%" % (f, m, 100.0*f/m if m else 0)
    print("%-11s %-17s %-17s %-17s" % (pl, fmt(*b) if b else "-", fmt(v[1], v[0]), fmt(n[1], n[0])))
print("Personas fuera del SOC esa semana: regla PBI %d | regla corregida %d" % (fuera_v, fuera_n))
