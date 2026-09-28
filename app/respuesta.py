# -*- coding: utf-8 -*-
# Lee una respuesta completa del formulario (la "r" que manda Power Automate).
# Forms manda cada respuesta con el código interno de la pregunta (r0bee1e...), así que
# data/preguntas.json traduce código -> título, y con el título se aplica la misma lógica
# que el Power BI con el Excel: planta, área, subárea, turno, C1..C4 y "Detalla lo observado".
# Solo se guarda eso: el DNI, nombres y demás respuestas NO se guardan (el repo es público).
import io, json, os, re, unicodedata, urllib.request

PREGUNTAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "preguntas.json")
# formularios (se leen de la página pública del formulario, sin clave)
FORMS_API = ("https://forms.cloud.microsoft/formapi/api/faed75e0-b942-4b73-85ac-7a32b852ceb8/groups/"
             "a5dfd224-344b-4802-8da8-498d39bf7718/light/runtimeFormsWithResponses(%%27%s%%27)"
             "?%%24expand=questions(%%24expand=choices)&%%24top=0")
FORMULARIOS = ["4HXt-kK5c0uFrHoyuFLOuCTS36VLNAJIjahJjTm_dxhUM1FERzdMNDhIVTZPVDFWQ0JZS1ZGUkNLMyQlQCN0PWcu",   # Agustino
               "4HXt-kK5c0uFrHoyuFLOuCTS36VLNAJIjahJjTm_dxhURFA1VzFTOTIzT05MRkMyTFlQQlVSMTE2NyQlQCN0PWcu"]   # Ñaña y Provincia
VAL = {"SEGURO": 0, "INSEGURO": 1}          # otro / vacío = 2 (NO SE OBSERVÓ)
BASURA = {"", ".", "..", "...", "0", ",", "-"}

def norm(s): return "" if s is None else re.sub(r"\s+", " ", str(s).replace("\xa0", " ")).strip()
def key(s):
    s = unicodedata.normalize("NFD", norm(s).upper())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")

def planta_de(v):
    k = key(v)
    if k.startswith("AGUSTINO"): return "AGUSTINO"
    if k.startswith("NANA"): return "ÑAÑA"
    return "PROVINCIAS" if k else ""

def bajar_preguntas():
    """Vuelve a leer las preguntas de los 2 formularios (por si agregaron preguntas nuevas)."""
    m = {}
    for fid in FORMULARIOS:
        req = urllib.request.Request(FORMS_API % fid, headers={"User-Agent": "Mozilla/5.0"})
        for q in json.load(urllib.request.urlopen(req, timeout=60))["form"]["questions"]:
            m[q["id"]] = q["title"]
    json.dump(m, io.open(PREGUNTAS, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    return m

class Lector:
    def __init__(self, vocab=None):
        self.q = json.load(io.open(PREGUNTAS, encoding="utf-8")) if os.path.exists(PREGUNTAS) else {}

    def leer(self, r):
        """Devuelve dict(pl, ar, sub, t, k, com) o None si no se reconoce la planta."""
        r = {k: v for k, v in (r or {}).items() if isinstance(v, (str, int, float)) and norm(v)}
        if any(re.match(r"r[0-9a-f]{32}$", k) and k not in self.q for k in r):   # pregunta nueva en el formulario
            try: self.q = bajar_preguntas()
            except Exception as e: print("  (no se pudo actualizar el mapa de preguntas: %s)" % e)
        t = {key(self.q.get(k, k)): norm(v) for k, v in r.items()}      # título -> respuesta
        def por(prefijo): return next((v for tk, v in t.items() if tk.startswith(key(prefijo))), "")
        pl = planta_de(por("SELECCIONA LA PLANTA"))
        if not pl: return None
        if pl == "AGUSTINO": ar = por("SELECCIONA EL AREA OBSERVADA - AGUSTINO")
        elif pl == "ÑAÑA":   ar = por("SELECCIONA EL AREA OBSERVADA - NANA")
        else:                ar = por("SELECCIONE LA PROVINCIA")
        ar = ar or "(sin área)"
        sub = por("SUBAREA") or ar
        tt = re.search(r"\d", por("SELECCIONA EL TURNO"))
        comp = {}
        for tk, v in t.items():
            mm = re.search(r"COMPORTAMIENTO\s*0?([1-4])(?!\d)", tk)
            if mm and v: comp.setdefault(int(mm.group(1)), v)
        k = sum(VAL.get(key(comp.get(p, "")), 2) * 3 ** (p - 1) for p in (1, 2, 3, 4))
        com = por("DETALLA LO OBSERVADO")
        return dict(pl=pl, ar=ar, sub=sub, t=int(tt.group()) if tt else 0, k=k,
                    com="" if com in BASURA else com)

def motivo_publico(motivo, hoja):
    """El motivo real (DM, vacaciones...) no se publica: solo si es salida, entrada o justificado."""
    if hoja == "a": return "J"
    m = key(motivo)
    return m if m in ("DESPIDO", "CONTRATACION") else "J"
