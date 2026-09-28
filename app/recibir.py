# -*- coding: utf-8 -*-
# Guarda en data/ lo que llega desde Power Automate (repository_dispatch).
# El repositorio es PÚBLICO: solo se guarda lo mismo que muestra la web
# (nada de DNI, respuestas completas ni motivos de justificación como DM).
#   nuevo-soc      payload {"codigo","fecha","resp"[,"r"]} -> data/nuevos/<resp>.csv (+ data/det_nuevos/<resp>.json resumido)
#   carga-soc      payload {"csv": "<codigo,fecha,resp>"}     -> data/nuevos/lote-<run>.csv
#   sync-personal  payload {"csv": "<cod,planta,gerencia,area,nombre,tipo>"} -> data/personal.csv
#   sync-justif    payload {"csv": "<cod,semana,motivo[,anio]>"} -> reemplaza esos años en data/justif_a.csv
#   sync-bajas     igual que sync-justif, para data/justif_b.csv
import os, io, csv, json, re, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, os.path.join(ROOT, "app"))
from respuesta import Lector, motivo_publico

ev = json.load(io.open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8"))
tipo = ev.get("action", "")
pl = ev.get("client_payload") or {}
run = os.environ.get("GITHUB_RUN_ID", "0")
print("Evento:", tipo)          # los logs son públicos: no se imprimen códigos ni nombres

def norm(s): return "" if s is None else str(s).strip()

def leer_csv_texto(txt):
    filas = list(csv.DictReader(io.StringIO(norm(txt).lstrip("﻿"))))
    # nombres de columna sin espacios y en minúscula (Power Automate a veces los cambia)
    return [{norm(k).lower(): norm(v) for k, v in f.items() if k is not None} for f in filas]

def escribir(nombre, cols, filas):
    with io.open(os.path.join(DATA, nombre), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for r in filas: w.writerow([r.get(c, "") for c in cols])
    print("  %s: %d filas" % (nombre, len(filas)))

if tipo == "carga-soc":
    filas = [f for f in leer_csv_texto(pl.get("csv")) if f.get("codigo")]
    os.makedirs(os.path.join(DATA, "nuevos"), exist_ok=True)
    with io.open(os.path.join(DATA, "nuevos", "lote-" + run + ".csv"), "w", encoding="utf-8") as fh:
        for f in filas:
            fh.write("%s,%s,%s\n" % (f["codigo"], f.get("fecha", "")[:19], f.get("resp", "")))
    print("  lote guardado: %d respuestas" % len(filas))

elif tipo == "nuevo-soc":
    cod, fecha, resp = norm(pl.get("codigo")), norm(pl.get("fecha"))[:19], norm(pl.get("resp"))
    if not cod or not fecha: sys.exit("Faltan codigo/fecha en el payload")
    nombre = "r-" + re.sub(r"[^A-Za-z0-9_-]", "", resp)[:80] if resp else "d-" + run
    os.makedirs(os.path.join(DATA, "nuevos"), exist_ok=True)
    io.open(os.path.join(DATA, "nuevos", nombre + ".csv"), "w", encoding="utf-8").write("%s,%s,%s\n" % (cod, fecha, resp))
    print("  SOC guardado:", nombre)
    # respuesta completa -> se resume (planta, área, subárea, turno, C1..C4, comentario) y se descarta el resto
    r = pl.get("r")
    if isinstance(r, str):
        try: r = json.loads(r)
        except ValueError: r = None
    if isinstance(r, dict) and r:
        y = Lector().leer(r)
        if y:
            os.makedirs(os.path.join(DATA, "det_nuevos"), exist_ok=True)
            y.update(codigo=cod, fecha=fecha)
            json.dump(y, io.open(os.path.join(DATA, "det_nuevos", nombre + ".json"), "w", encoding="utf-8"), ensure_ascii=False)
            print("  detalle guardado: %s / %s / C=%d" % (y["pl"], y["ar"], y["k"]))
        else:
            print("  detalle: no se reconoció la planta en la respuesta")

elif tipo.startswith("sync-") and int(pl.get("total") or 1) > 1:
    # Envío en partes (GitHub acepta máx. ~65 000 caracteres por envío). Cada parte se guarda
    # en data/partes/ y cuando llegan todas las del mismo "lote" se juntan y se aplican.
    total, parte = int(pl["total"]), int(pl.get("parte") or 1)
    lote = re.sub(r"[^A-Za-z0-9_-]", "", norm(pl.get("lote")))[:60] or "sinlote"
    carpeta = os.path.join(DATA, "partes"); os.makedirs(carpeta, exist_ok=True)
    io.open(os.path.join(carpeta, "%s_%s_%d.csv" % (tipo, lote, parte)), "w", encoding="utf-8").write(norm(pl.get("csv")))
    tengo = {}
    for f in os.listdir(carpeta):
        m = re.match(r"(sync-[a-z]+)_(.+)_(\d+)\.csv$", f)
        if m and m.group(1) == tipo and m.group(2) == lote: tengo[int(m.group(3))] = f
    print("  parte %d de %d guardada (tengo %d)" % (parte, total, len(tengo)))
    if len(tengo) >= total:
        textos = [io.open(os.path.join(carpeta, tengo[i]), encoding="utf-8").read() for i in sorted(tengo)]
        cab = textos[0].lstrip("﻿").splitlines()[0]
        cuerpo = [l for t in textos for l in t.lstrip("﻿").splitlines()[1:] if l.strip()]
        pl = dict(csv="\n".join([cab] + cuerpo))
        # se borran las partes de este tipo (esta y lotes viejos incompletos)
        for f in os.listdir(carpeta):
            if f.startswith(tipo + "_"):
                for x in (f, f + ".enc"):
                    if os.path.exists(os.path.join(carpeta, x)): os.remove(os.path.join(carpeta, x))
        print("  partes juntas: %d filas" % len(cuerpo))
    else:
        sys.exit(0)   # falta alguna parte: queda guardada y se junta cuando llegue la otra

if tipo == "sync-personal":
    filas = [f for f in leer_csv_texto(pl.get("csv")) if f.get("cod")]
    if len(filas) < 50: sys.exit("PERSONAL con muy pocas filas (%d); no se reemplaza por seguridad" % len(filas))
    escribir("personal.csv", ["cod","planta","gerencia","area","nombre","tipo"], filas)

elif tipo in ("sync-justif", "sync-bajas"):
    hoja = "a" if tipo == "sync-justif" else "b"
    archivo = "justif_a.csv" if hoja == "a" else "justif_b.csv"
    nuevas = [f for f in leer_csv_texto(pl.get("csv")) if f.get("cod")]
    if not nuevas: sys.exit("Payload sin filas")
    # si la hoja no trae año, se asume el año actual (hora Perú)
    anio_hoy = str((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=5)).year)
    for f in nuevas:
        if not re.sub(r"\D", "", f.get("anio", "")): f["anio"] = anio_hoy
        f["motivo"] = motivo_publico(f.get("motivo", ""), hoja)
    anios = {re.sub(r"\D", "", f.get("anio", ""))[:4] for f in nuevas}
    p = os.path.join(DATA, archivo)
    viejas = []
    if os.path.exists(p):
        with io.open(p, encoding="utf-8-sig", newline="") as fh:
            todas = list(csv.DictReader(fh))
        viejas = [r for r in todas if re.sub(r"\D", "", r.get("anio", ""))[:4] not in anios]
        # seguro: si llega mucho menos de lo que ya había para ese año (p. ej. el Excel tenía un filtro
        # puesto y solo se leyó una parte), no se reemplaza nada
        antes = len(todas) - len(viejas)
        if antes >= 100 and len(nuevas) < antes * 0.6:
            sys.exit("Llegaron %d filas y había %d para %s: parece incompleto (¿filtro puesto en el Excel?). No se reemplaza."
                     % (len(nuevas), antes, sorted(anios)))
    escribir(archivo, ["cod","anio","semana","motivo"], viejas + nuevas)
    print("  años reemplazados:", sorted(anios))
elif tipo not in ("carga-soc", "nuevo-soc"):
    print("Evento no reconocido; no se guarda nada.")
