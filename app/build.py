# -*- coding: utf-8 -*-
# Robot SOC v2: arma index.html a partir de
#   data/personal.csv      padrón (quién debe hacer SOC y su meta)
#   data/justif_a.csv      Excel de Justificaciones
#   data/justif_b.csv      hoja "DM VACACIONES BAJAS Y ALTAS" de PERSONAL
#   data/soc_hist.json     SOC históricos leídos de los Excel de los formularios (hasta "corte")
#   data/nuevos/*.csv      SOC nuevos que manda Power Automate ("codigo,fecha[,idrespuesta]")
#   data/det_hist.json + data/det_nuevos/*.json + data/areas.json  hojas Análisis / Comentarios / Detalles
import os, io, csv, json, base64, re, glob, datetime, unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP, DATA = os.path.join(ROOT, "app"), os.path.join(ROOT, "data")
MESES = ["","Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio",
         "Agosto","Setiembre","Octubre","Noviembre","Diciembre"]
MIN_WO = 202401

# Motivos que cambian si la persona "existe" en el SOC. Todo lo demás = ausencia de esa semana.
# Igual que el Power BI. OJO: en los Excel "CESADO" se usa como ausencia temporal
# (hay personas marcadas CESADO que siguen haciendo SOC), por eso NO se trata como salida.
SALIDA  = {"DESPIDO"}
ENTRADA = {"CONTRATACION"}

def norm(s): return "" if s is None else str(s).strip()
def sin_tildes(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
def leer_csv(nombre):
    p = os.path.join(DATA, nombre)
    if not os.path.exists(p): return []
    with io.open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

peru_now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(hours=5)
iy, iw, _ = peru_now.date().isocalendar()
CUR_WO = iy*100 + iw

# ---------- 1) Padrón ----------
# Excepción del PBI (META SOC AJUSTADA): estos empleados tienen meta 1 por semana, no 3
META_1 = {"5671", "11630", "1400"}
ppl, padset = [], set()
for r in leer_csv("personal.csv"):
    cod = norm(r.get("cod"))
    if not cod or cod in padset: continue
    padset.add(cod)
    tipo = norm(r.get("tipo"))
    ppl.append(dict(cod=cod, pl=norm(r.get("planta")).upper(), ge=norm(r.get("gerencia")),
                    ar=norm(r.get("area")), nom=norm(r.get("nombre")), tp=tipo,
                    mb=1 if cod in META_1 else 3 if tipo.upper() == "EMPLEADO" else 1))

# ---------- 2) SOC: historia + nuevos ----------
hist = json.load(io.open(os.path.join(DATA, "soc_hist.json"), encoding="utf-8"))
corte = hist.get("corte") or "0000-00-00T00:00:00"
soc = {c: dict(v) for c, v in hist["soc"].items() if c in padset}

def parse_fecha(s):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", norm(s))
    return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None

nuevos = aplicados = 0
vistos = set()
for f in sorted(glob.glob(os.path.join(DATA, "nuevos", "*.csv"))):
    for line in io.open(f, encoding="utf-8-sig"):
        p = [x.strip() for x in line.strip().split(",")]
        if len(p) < 2 or not p[0].isdigit(): continue
        cod, fecha = p[0], p[1]
        resp = p[2] if len(p) > 2 and p[2] else None
        nuevos += 1
        if resp:                                   # la misma respuesta nunca se cuenta 2 veces
            if resp in vistos: continue
            vistos.add(resp)
        # ya incluido en la historia (respuestas hasta la hora de corte)
        # (los registros viejos sin hora del mismo día del corte ya vienen dentro del Excel)
        if ("T" in fecha and fecha <= corte) or ("T" not in fecha and fecha <= corte[:10]): continue
        d = parse_fecha(fecha)
        if not d or cod not in padset: continue
        a, w, _ = d.isocalendar()
        wo = str(a*100 + w)
        soc.setdefault(cod, {})
        soc[cod][wo] = soc[cod].get(wo, 0) + 1
        aplicados += 1

# ---------- 3) Semanas visibles ----------
wos = {int(w) for v in soc.values() for w in v}
wos.add(CUR_WO)
weeks = []
for wo in sorted(w for w in wos if MIN_WO <= w <= CUR_WO):
    try: th = datetime.date.fromisocalendar(wo//100, wo%100, 4)
    except ValueError: continue
    weeks.append(dict(wo=wo, anio=wo//100, sem=wo%100, mesN=MESES[th.month], mesO=(wo//100)*100+th.month))
wset = {w["wo"] for w in weeks}

# ---------- 4) Justificaciones, entradas y salidas ----------
eventos = {}   # cod -> [(semana, clase)]
nm = {}        # semana -> códigos justificados esa semana (meta 0, aparecen con "—")
# Excel de Justificaciones (hoja 1): cualquier motivo = justificado esa semana.
# Hoja de bajas/altas de PERSONAL: DESPIDO = sale, CONTRATACION = entra, lo demás = justificado.
for hoja, r in [("a", x) for x in leer_csv("justif_a.csv")] + [("b", x) for x in leer_csv("justif_b.csv")]:
    cod = norm(r.get("cod"))
    if cod not in padset: continue
    try: anio = int(float(norm(r.get("anio"))))
    except ValueError: continue
    dig = re.sub(r"\D", "", norm(r.get("semana")))
    if not dig or not (2020 <= anio <= 2035): continue
    sem = int(dig)
    if not 1 <= sem <= 53: continue
    so = anio*100 + sem
    mot = sin_tildes(norm(r.get("motivo")).upper()) or "JUSTIFICADO"
    if hoja == "a":      mot = "JUSTIFICADO"
    if mot in SALIDA:    eventos.setdefault(cod, []).append((so, "S"))
    elif mot in ENTRADA: eventos.setdefault(cod, []).append((so, "E"))
    elif so in wset:     nm.setdefault(str(so), set()).add(cod)

# rng[cod] = periodos [desde, hasta] en que la persona SÍ existe en el SOC.
# Entrada en semana X: cuenta desde X. Salida en semana X: cuenta hasta X y desde X+1 ya no.
rng = {}
for cod, evs in eventos.items():
    evs.sort()
    activo = evs[0][1] == "S"
    ini = 0 if activo else None
    per = []
    for so, cl in evs:
        if cl == "E" and not activo: ini, activo = so, True
        elif cl == "S" and activo:   per.append([ini, so]); activo = False
    if activo: per.append([ini, 999999])
    rng[cod] = per

base = dict(generado=peru_now.strftime("%d/%m/%Y %I:%M %p"), corte=corte,
            ppl=ppl, soc=soc, nm={k: sorted(v) for k, v in nm.items()}, rng=rng, weeks=weeks)

# ---------- 5) Detalle de cada SOC (Análisis / Comentarios / Detalles) ----------
#   data/det_hist.json   respuestas de los Excel de los formularios (tools/build_det.py)
#   data/det_nuevos/*.json  respuestas completas que manda Power Automate (clave "r")
#   data/areas.json      catálogo AREAS Y SUBAREAS (gerencia + títulos de C1..C4)
def key(s):
    s = unicodedata.normalize("NFD", re.sub(r"\s+", " ", norm(s).replace("\xa0", " ")).upper())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")

det = json.load(io.open(os.path.join(DATA, "det_hist.json"), encoding="utf-8"))
cat = json.load(io.open(os.path.join(DATA, "areas.json"), encoding="utf-8"))
voc = det["vocab"]
pidx = {p["cod"]: i for i, p in enumerate(ppl)}
ubs, ubi = [], {}
def ub_id(pl, ar, sub):
    k = (key(pl), key(ar), key(sub))
    if k not in ubi: ubi[k] = len(ubs); ubs.append([pl, ar, sub])
    return ubi[k]
D3 = dict(w=[], u=[], t=[], p=[], k=[], m=[], com=[])
def agregar(wo, u, t, cod, k, com):
    if cod not in pidx or not (MIN_WO <= wo <= CUR_WO): return
    D3["w"].append(wo); D3["u"].append(u); D3["t"].append(t); D3["p"].append(pidx[cod]); D3["k"].append(k)
    if com: D3["m"].append(len(D3["com"])); D3["com"].append(com)
    else: D3["m"].append(-1)
for i in range(len(det["w"])):
    pl, ar, sub = det["ub"][det["u"][i]]
    m = det["m"][i]
    agregar(det["w"][i], ub_id(pl, ar, sub), det["t"][i], det["c"][i], det["k"][i], det["com"][m] if m >= 0 else "")

# respuestas nuevas (ya resumidas por recibir.py; las antiguas con "r" completa se leen igual)
import sys; sys.path.insert(0, APP)
from respuesta import Lector
lector = Lector()
det_nuevos = det_ok = 0
for f in sorted(glob.glob(os.path.join(DATA, "det_nuevos", "*.json"))):
    try: xs = json.load(io.open(f, encoding="utf-8"))
    except ValueError: continue
    for x in (xs if isinstance(xs, list) else [xs]):     # un archivo = una respuesta (o una lista, en la migración)
        det_nuevos += 1
        fecha = norm(x.get("fecha"))
        if fecha <= det.get("corte", ""): continue                      # ya está en el Excel histórico
        if "pl" not in x:
            r = x.get("r") or {}
            if isinstance(r, str):
                try: r = json.loads(r)
                except ValueError: r = {}
            y = lector.leer(r)
            if not y: continue
            x.update(y)
        d = parse_fecha(fecha)
        if not d: continue
        a, w, _ = d.isocalendar()
        agregar(a * 100 + w, ub_id(x["pl"], x["ar"], x["sub"]), int(x.get("t") or 0), norm(x.get("codigo")),
                int(x.get("k") or 0), norm(x.get("com")))
        det_ok += 1

# catálogo: gerencia del área observada y títulos de C1..C4 (versión actual y 4 antiguas, igual que el PBI)
catk = {(key(c["pl"]), key(c["ar"]), key(c["sub"])): c for c in cat}
gerk = {}
for c in cat: gerk.setdefault((key(c["pl"]), key(c["ar"])), c["ger"])
T, Ti, tu = [], {}, []
def tid(s):
    if not s: return -1
    if s not in Ti: Ti[s] = len(T); T.append(s)
    return Ti[s]
for u in ubs:
    c = catk.get((key(u[0]), key(u[1]), key(u[2])))
    u.append(gerk.get((key(u[0]), key(u[1])), ""))
    tu.append([[tid(t) for t in v] for v in c["t"]] if c else [])
D3.update(ub=ubs, T=T, tu=tu)

# ---------- 5) Armar index.html ----------
tpl = io.open(os.path.join(APP, "page_template.html"), encoding="utf-8").read()
IMG = {"@@IMG_LOGO@@":("logo.jpg","image/jpeg"), "@@IMG_ESQUINA@@":("esquina.png","image/png"),
       "@@IMG_INSPIRA@@":("inspira.png","image/png"), "@@IMG_ESCUDO@@":("escudo.png","image/png"),
       "@@IMG_WORKER@@":("worker.png","image/png")}
for k, (fn, mt) in IMG.items():
    b = open(os.path.join(APP, "img", fn), "rb").read()
    tpl = tpl.replace(k, "data:%s;base64,%s" % (mt, base64.b64encode(b).decode()))
tpl = tpl.replace("@@DATA@@", json.dumps(base, ensure_ascii=False))
tpl = tpl.replace("@@DATA3@@", json.dumps(D3, ensure_ascii=False, separators=(",", ":")))
io.open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8").write(tpl)
print("index.html armado | padrón %d | con entradas/salidas %d | SOC nuevos %d (aplicados %d) | semana actual %d"
      % (len(ppl), len(rng), nuevos, aplicados, CUR_WO))
print("detalle: %d SOC del padrón, %d comentarios | respuestas completas nuevas %d (leídas %d)"
      % (len(D3["w"]), len(D3["com"]), det_nuevos, det_ok))
