from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
# Importiamo new_session per usare il modello super leggero!
from rembg import remove, new_session 
import google.generativeai as genai
import PIL.Image
import io, uuid, json, os, hashlib

app = FastAPI(title="StyleSync Pro - Optimized")

os.makedirs("immagini_armadio", exist_ok=True)
app.mount("/immagini", StaticFiles(directory="immagini_armadio"), name="immagini")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# INSERISCI LA TUA CHIAVE
genai.configure(api_key="GEMINI_KEY") 
model = genai.GenerativeModel('gemini-3.8-flash')

# === IL TRUCCO PER NON FAR CRASHARE RENDER ===
# Carichiamo il modello "u2netp" (Pocket). Pesa solo 4MB invece di 180MB!
rembg_session = new_session("u2netp")

DB_FILE = "database.json"

def carica_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f: return json.load(f)
        except: return {}
    return {}

def salva_db():
    with open(DB_FILE, "w") as f: json.dump(database_utenti, f, indent=4)

database_utenti = carica_db()
def cripta_password(password: str) -> str: return hashlib.sha256(password.encode()).hexdigest()

# === SISTEMA DI AUTENTICAZIONE COMPLETO ===
@app.post("/register/")
async def register(username: str = Form(...), password: str = Form(...), domanda: str = Form(...), risposta: str = Form(...)):
    user = username.strip().lower()
    if user in database_utenti:
        return {"error": "Username già in uso. Scegline un altro."}
    
    database_utenti[user] = {
        "password": cripta_password(password),
        "domanda": domanda,
        "risposta": risposta.strip().lower(),
        "armadi": {"Casa Principale": []}
    }
    salva_db()
    return {"message": "Registrazione completata!"}

@app.post("/login/")
async def login(username: str = Form(...), password: str = Form(...)):
    user = username.strip().lower()
    if user not in database_utenti: return {"error": "Utente non trovato."}
    if database_utenti[user]["password"] == cripta_password(password):
        return {"message": "Accesso consentito"}
    return {"error": "Password errata."}

@app.post("/recover-password/")
async def recover(username: str = Form(...), risposta: str = Form(...), nuova_password: str = Form(...)):
    user = username.strip().lower()
    if user not in database_utenti: return {"error": "Utente non trovato."}
    if database_utenti[user].get("risposta", "") == risposta.strip().lower():
        database_utenti[user]["password"] = cripta_password(nuova_password)
        salva_db()
        return {"message": "Password aggiornata con successo!"}
    return {"error": "Risposta di sicurezza errata."}

# === GESTIONE ARMADI E OUTFIT ===
@app.get("/get-armadi/")
async def get_armadi(username: str):
    user = username.strip().lower()
    return {"armadi": database_utenti.get(user, {}).get("armadi", {})}

@app.post("/add-armadio/")
async def add_armadio(username: str = Form(...), nome: str = Form(...)):
    user = username.strip().lower()
    if user in database_utenti:
        if nome not in database_utenti[user]["armadi"]:
            database_utenti[user]["armadi"][nome] = []
            salva_db()
        return {"message": "Armadio creato!", "nomi_armadi": list(database_utenti[user]["armadi"].keys())}
    return {"error": "Utente non valido."}

@app.post("/upload-clothes/")
async def upload_clothes(file: UploadFile = File(...), username: str = Form(...), nome_armadio: str = Form("Casa Principale")):
    user = username.strip().lower()
    input_image = await file.read()
    
    try:
        # Usiamo la sessione ultra-leggera qui!
        output_image = remove(input_image, session=rembg_session)
    except:
        return {"error": "Errore rimozione sfondo."}
    
    item_id = str(uuid.uuid4())[:8]
    filename = f"{item_id}.png"
    with open(f"immagini_armadio/{filename}", "wb") as f: f.write(output_image)
        
    img = PIL.Image.open(io.BytesIO(output_image))
    prompt = "Guarda questo capo. Rispondi SOLO in JSON con: 'nome' e 'colore'."
    try:
        response = model.generate_content([prompt, img])
        dati_capo = json.loads(response.text.replace("```json", "").replace("```", "").strip())
    except:
        dati_capo = {"nome": "Capo", "colore": "Sconosciuto"}
        
    capo = {"id": item_id, "nome": dati_capo.get("nome", "Capo"), "colore": dati_capo.get("colore", ""), "url_immagine": f"/immagini/{filename}"}
    
    if nome_armadio not in database_utenti[user]["armadi"]: database_utenti[user]["armadi"][nome_armadio] = []
    database_utenti[user]["armadi"][nome_armadio].append(capo)
    salva_db()
    
    return {"message": "Aggiunto!", "capo": capo}

@app.post("/move-item/")
async def move_item(username: str = Form(...), item_id: str = Form(...), da_armadio: str = Form(...), a_armadio: str = Form(...)):
    user = username.strip().lower()
    armadi = database_utenti[user]["armadi"]
    capo_da_spostare = next((c for c in armadi[da_armadio] if c["id"] == item_id), None)
    if capo_da_spostare:
        armadi[da_armadio].remove(capo_da_spostare)
        armadi[a_armadio].append(capo_da_spostare)
        salva_db()
        return {"message": "Spostamento completato!"}
    return {"error": "Errore spostamento."}

@app.get("/generate-outfits/")
async def generate_outfits(username: str, aesthetic: str = "Y2K", nome_armadio: str = "Casa Principale"):
    user = username.strip().lower()
    armadio_scelto = database_utenti[user]["armadi"].get(nome_armadio, [])
    if len(armadio_scelto) < 2: return {"error": f"Carica almeno 2 capi in '{nome_armadio}'!"}
        
    prompt = f"Sei uno stilista. Crea 3 outfit stile {aesthetic} usando SOLO questi capi: {json.dumps(armadio_scelto)}. Rispondi in JSON con lista 'outfits' ('titolo' e 'capi_ids')."
    try:
        response = model.generate_content(prompt)
        outfits_dati = json.loads(response.text.replace("```json", "").replace("```", "").strip())
        risultato = [{"titolo": out["titolo"], "capi": [c for c in armadio_scelto if c["id"] in out["capi_ids"]]} for out in outfits_dati["outfits"]]
        return {"outfits": risultato}
    except:
        return {"error": "Errore nella generazione AI. Riprova."}
