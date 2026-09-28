from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import google.generativeai as genai
import PIL.Image
import io, uuid, json, hashlib, requests, base64

app = FastAPI(title="StyleSync Pro")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# === INSERISCI I TUOI DATI QUI ===
genai.configure(api_key="GEMINI_KEY") 
model = genai.GenerativeModel('gemini-3.8-flash')
FIREBASE_URL = "FIREBASE_KEY" 
# =================================

def get_user(username):
    try:
        r = requests.get(f"{FIREBASE_URL}/utenti/{username}.json")
        if r.status_code == 200 and r.json(): return r.json()
    except Exception as e:
        print(f"Errore lettura: {e}")
    return None

def save_user(username, data):
    try:
        r = requests.put(f"{FIREBASE_URL}/utenti/{username}.json", json=data)
        if r.status_code != 200:
            return f"Rifiutato da Firebase: {r.text}"
        return "OK"
    except Exception as e: 
        return f"Errore Python: {str(e)}"

def cripta_password(password: str) -> str: return hashlib.sha256(password.encode()).hexdigest()

@app.post("/register/")
async def register(username: str = Form(...), password: str = Form(...), domanda: str = Form(...), risposta: str = Form(...)):
    user = username.strip().lower()
    if get_user(user): return {"error": "Username già in uso."}
    nuovo_utente = {
        "password": cripta_password(password), 
        "domanda": domanda, 
        "risposta": risposta.strip().lower(), 
        "armadi": {"Casa Principale": []}
    }
    
    # === TRUCCO SPIA ===
    risultato = save_user(user, nuovo_utente)
    if risultato == "OK": 
        return {"message": "Registrazione completata!"}
    
    # Se fallisce, invia l'errore tecnico direttamente all'app
    return {"error": risultato}

@app.post("/login/")
async def login(username: str = Form(...), password: str = Form(...)):
    user = username.strip().lower()
    dati_utente = get_user(user)
    if not dati_utente: return {"error": "Utente non trovato."}
    if dati_utente.get("password") == cripta_password(password): return {"message": "Accesso consentito"}
    return {"error": "Password errata."}
    
@app.post("/reset-password/")
async def reset_password(username: str = Form(...), risposta: str = Form(...), nuova_password: str = Form(...)):
    user = username.strip().lower()
    dati_utente = get_user(user)
    if not dati_utente: return {"error": "Utente non trovato."}
    if dati_utente.get("risposta") == risposta.strip().lower():
        dati_utente["password"] = cripta_password(nuova_password)
        save_user(user, dati_utente)
        return {"message": "Password aggiornata!"}
    return {"error": "Risposta di sicurezza errata."}

@app.get("/get-armadi/")
async def get_armadi(username: str):
    user = username.strip().lower()
    dati_utente = get_user(user)
    if not dati_utente: return {"armadi": {}}
    return {"armadi": dati_utente.get("armadi", {})}

@app.post("/add-armadio/")
async def add_armadio(username: str = Form(...), nome: str = Form(...)):
    user = username.strip().lower()
    dati_utente = get_user(user)
    if not dati_utente: return {"error": "Utente non trovato."}
    if "armadi" not in dati_utente: dati_utente["armadi"] = {}
    if nome not in dati_utente["armadi"]:
        dati_utente["armadi"][nome] = []
        save_user(user, dati_utente)
    return {"message": "Armadio creato!"}

@app.post("/upload-clothes/")
async def upload_clothes(file: UploadFile = File(...), username: str = Form(...), nome_armadio: str = Form("Casa Principale")):
    user = username.strip().lower()
    dati_utente = get_user(user)
    if not dati_utente: return {"error": "Utente non trovato."}
    
    raw_bytes = await file.read()
    try:
        img_originale = PIL.Image.open(io.BytesIO(raw_bytes))
        if img_originale.mode in ("RGBA", "P"): img_originale = img_originale.convert("RGB")
        img_originale.thumbnail((500, 500)) 
        compresso_io = io.BytesIO()
        img_originale.save(compresso_io, format="JPEG", quality=75) 
        img_base64 = base64.b64encode(compresso_io.getvalue()).decode('utf-8')
    except: return {"error": "Errore lettura immagine."}
    
    item_id = str(uuid.uuid4())[:8]
    prompt = "Identify this clothing item. Reply ONLY with a raw JSON object containing: 'nome' (e.g. Jeans, Camicia) and 'colore'."
    try:
        img_per_gemini = PIL.Image.open(io.BytesIO(compresso_io.getvalue()))
        response = model.generate_content([prompt, img_per_gemini], generation_config={"response_mime_type": "application/json"})
        dati_capo = json.loads(response.text)
    except: dati_capo = {"nome": "Capo", "colore": "Sconosciuto"}
        
    capo = {"id": item_id, "nome": dati_capo.get("nome", "Capo"), "colore": dati_capo.get("colore", ""), "stato": "disponibile", "base64": img_base64}
    
    if "armadi" not in dati_utente: dati_utente["armadi"] = {}
    if nome_armadio not in dati_utente["armadi"]: dati_utente["armadi"][nome_armadio] = []
    
    if isinstance(dati_utente["armadi"][nome_armadio], dict):
        dati_utente["armadi"][nome_armadio] = list(dati_utente["armadi"][nome_armadio].values())
    if not isinstance(dati_utente["armadi"][nome_armadio], list):
        dati_utente["armadi"][nome_armadio] = []
        
    dati_utente["armadi"][nome_armadio].append(capo)
    save_user(user, dati_utente)
    return {"message": "Aggiunto!", "capo": capo}

@app.post("/manage-item/")
async def manage_item(username: str = Form(...), item_id: str = Form(...), armadio_attuale: str = Form(...), azione: str = Form(...), nuovo_valore: str = Form(None)):
    user = username.strip().lower()
    dati_utente = get_user(user)
    if not dati_utente: return {"error": "Utente non trovato."}
    
    armadi = dati_utente.get("armadi", {})
    if armadio_attuale not in armadi: return {"error": "Armadio inesistente."}
    
    lista_capi = armadi[armadio_attuale]
    if isinstance(lista_capi, dict): lista_capi = list(lista_capi.values())
    
    capo_target = next((c for c in lista_capi if c and c.get("id") == item_id), None)
    if not capo_target: return {"error": "Capo non trovato."}
    
    if azione == "elimina": lista_capi.remove(capo_target)
    elif azione == "rinomina": capo_target["nome"] = nuovo_valore
    elif azione == "lavanderia": capo_target["stato"] = "lavare" if capo_target.get("stato") == "disponibile" else "disponibile"
    elif azione == "sposta":
        lista_capi.remove(capo_target)
        if nuovo_valore not in armadi: armadi[nuovo_valore] = []
        if isinstance(armadi[nuovo_valore], dict): armadi[nuovo_valore] = list(armadi[nuovo_valore].values())
        armadi[nuovo_valore].append(capo_target)
        
    armadi[armadio_attuale] = lista_capi
    dati_utente["armadi"] = armadi
    save_user(user, dati_utente)
    return {"message": "Azione completata!"}

@app.get("/generate-outfits/")
async def generate_outfits(username: str, aesthetic: str = "Y2K", nome_armadio: str = "Casa Principale", capo_forzato_id: str = None):
    user = username.strip().lower()
    dati_utente = get_user(user)
    if not dati_utente: return {"error": "Utente non trovato."}
    
    lista_capi = dati_utente.get("armadi", {}).get(nome_armadio, [])
    if isinstance(lista_capi, dict): lista_capi = list(lista_capi.values())
    
    armadio_scelto = [c for c in lista_capi if c and (c.get("stato", "disponibile") == "disponibile" or c.get("id") == capo_forzato_id)]
    if len(armadio_scelto) < 2: return {"error": "Pochi capi disponibili."}
    
    capi_per_prompt = [{"id": c["id"], "nome": c.get("nome"), "colore": c.get("colore")} for c in armadio_scelto]
    prompt = f"Crea 3 outfit stile {aesthetic} usando SOLO questi capi: {json.dumps(capi_per_prompt)}. "
    if capo_forzato_id: prompt += f"DEVI assolutamente includere il capo con ID {capo_forzato_id} in tutti gli outfit. "
    prompt += "Rispondi in JSON puro con lista 'outfits' ('titolo' e 'capi_ids')."
    
    try:
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        outfits_dati = json.loads(response.text)
        return {"outfits": [{"titolo": out["titolo"], "capi": [c for c in armadio_scelto if c["id"] in out["capi_ids"]]} for out in outfits_dati["outfits"]]}
    except: return {"error": "Errore AI."}

@app.get("/")
async def sveglia(): return {"status": "Online h24!"}
