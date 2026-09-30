# -*- coding: utf-8 -*-
# Cifrado del repositorio público y de la página.
#   python app/cifra.py abrir    data/**/*.enc  -> archivos normales (solo en la máquina del robot, nunca se suben)
#   python app/cifra.py cerrar   archivos normales nuevos o cambiados -> .enc (lo único que se sube a GitHub)
#   python app/cifra.py web      index.html -> site/index.html protegido con la clave de la web
# Claves (Secrets de GitHub): SOC_DATA_KEY = clave de los datos (64 caracteres hex)
#                             CLAVE_WEB    = contraseña que se escribe para ver el dashboard (obligatoria)
import os, io, sys, json, glob, base64, hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
ESTADO = os.path.join(ROOT, ".estado_cifrado.json")   # huellas de lo abierto (no se sube)
ITER_WEB = 250000

def clave_datos():
    k = os.environ.get("SOC_DATA_KEY", "").strip()
    if len(k) != 64: sys.exit("Falta el Secret SOC_DATA_KEY (64 caracteres)")
    return AESGCM(bytes.fromhex(k))

def huella(b): return hashlib.sha256(b).hexdigest()

def abrir():
    aes, estado = clave_datos(), {}
    for f in glob.glob(os.path.join(DATA, "**", "*.enc"), recursive=True):
        b = open(f, "rb").read()
        plano = aes.decrypt(b[:12], b[12:], None)
        destino = f[:-4]
        open(destino, "wb").write(plano)
        estado[os.path.relpath(destino, ROOT)] = huella(plano)
    json.dump(estado, open(ESTADO, "w"))
    print("abiertos: %d archivos" % len(estado))

def cerrar():
    aes = clave_datos()
    estado = json.load(open(ESTADO)) if os.path.exists(ESTADO) else {}
    n = 0
    for f in glob.glob(os.path.join(DATA, "**", "*"), recursive=True):
        if os.path.isdir(f) or f.endswith(".enc"): continue
        plano = open(f, "rb").read()
        if estado.get(os.path.relpath(f, ROOT)) == huella(plano): continue   # sin cambios
        nonce = os.urandom(12)
        open(f + ".enc", "wb").write(nonce + aes.encrypt(nonce, plano, None))
        n += 1
    print("cifrados (nuevos o cambiados): %d archivos" % n)

PAGINA = r"""<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard SOC</title>
<style>
  :root{--bg:#e9edf1;--card:#fff;--ink:#0f2733;--muted:#5c6b76;--brand:#118DFF;--line:#dbe2e8;--red:#EF3642}
  @media (prefers-color-scheme:dark){:root{--bg:#0e161c;--card:#16212a;--ink:#e8eef2;--muted:#93a3ae;--brand:#37a9e0;--line:#26333d}}
  *{box-sizing:border-box} body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
    background:var(--bg);color:var(--ink);font-family:"Segoe UI",system-ui,sans-serif;padding:16px}
  form{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:26px 24px;width:100%;max-width:340px;
    box-shadow:0 6px 24px rgba(15,39,51,.12);display:flex;flex-direction:column;gap:12px}
  h1{margin:0;color:var(--brand);font-size:1.35rem} p{margin:0;color:var(--muted);font-size:.85rem}
  input[type=password]{padding:10px 12px;border:1px solid var(--line);border-radius:8px;font-size:1rem;background:var(--card);color:var(--ink)}
  button{padding:10px;border:0;border-radius:8px;background:var(--brand);color:#fff;font-weight:700;font-size:.95rem;cursor:pointer}
  label{font-size:.8rem;color:var(--muted);display:flex;gap:6px;align-items:center} #err{color:var(--red);font-size:.8rem;min-height:1em}
</style>
<form id="f"><h1>Dashboard SOC</h1><p>QROMA · SSOMA. Ingresa la clave para ver el dashboard.</p>
<input type="password" id="k" placeholder="Clave" autocomplete="current-password" autofocus>
<label><input type="checkbox" id="rec"> Recordar en este equipo</label>
<button>Entrar</button><div id="err"></div></form>
<script>
const P=@@PAQUETE@@;
const b64=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
async function abrir(clave){
  const base=await crypto.subtle.importKey('raw',new TextEncoder().encode(clave),'PBKDF2',false,['deriveKey']);
  const key=await crypto.subtle.deriveKey({name:'PBKDF2',salt:b64(P.s),iterations:P.i,hash:'SHA-256'},base,{name:'AES-GCM',length:256},false,['decrypt']);
  const html=new TextDecoder().decode(await crypto.subtle.decrypt({name:'AES-GCM',iv:b64(P.n)},key,b64(P.c)));
  document.open();document.write(html);document.close();
}
// clave recordada en este equipo, o la de esta pestaña (el botón Actualizar recarga sin volver a pedirla)
let guardada=null; try{guardada=localStorage.getItem('socClave')||sessionStorage.getItem('socClaveSesion');}catch(e){}
if(guardada) abrir(guardada).catch(()=>{try{localStorage.removeItem('socClave');sessionStorage.removeItem('socClaveSesion');}catch(e){}});
document.getElementById('f').addEventListener('submit',async e=>{e.preventDefault();
  const k=document.getElementById('k').value; document.getElementById('err').textContent='Abriendo…';
  try{try{sessionStorage.setItem('socClaveSesion',k);}catch(e){} await abrir(k); if(document.getElementById('rec').checked){try{localStorage.setItem('socClave',k);}catch(e){}}}
  catch(x){document.getElementById('err').textContent='Clave incorrecta.';}});
</script>
"""

def web():
    clave = os.environ.get("CLAVE_WEB", "")
    html = io.open(os.path.join(ROOT, "index.html"), encoding="utf-8").read().encode("utf-8")
    os.makedirs(os.path.join(ROOT, "site"), exist_ok=True)
    if len(clave) < 8: sys.exit("Falta el Secret CLAVE_WEB (mínimo 8 caracteres): la web es pública y no se publica sin clave")
    sal, nonce = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=sal, iterations=ITER_WEB).derive(clave.encode("utf-8"))
    c = AESGCM(key).encrypt(nonce, html, None)
    e = lambda b: base64.b64encode(b).decode()
    paquete = json.dumps(dict(s=e(sal), n=e(nonce), c=e(c), i=ITER_WEB))
    io.open(os.path.join(ROOT, "site", "index.html"), "w", encoding="utf-8").write(PAGINA.replace("@@PAQUETE@@", paquete))
    print("site/index.html protegido con clave (%d KB)" % (len(paquete) // 1024))

if __name__ == "__main__":
    {"abrir": abrir, "cerrar": cerrar, "web": web}[sys.argv[1]]()
