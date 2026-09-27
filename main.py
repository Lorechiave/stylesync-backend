from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from rembg import remove
import google.generativeai as genai
import PIL.Image
import io
import uuid
import json
import os
import hashlib

app = FastAPI(title="StyleSync Premium")

os.makedirs("immagini_armadio", exist_ok=True)
app.mount("/immagini", StaticFiles(directory="immagini_armadio"), name="immagini")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ==========================================
# CHIAVE GEMINI
# ==========================================
genai.configure(api_key="GEMINI_KEY") # Inserisci la tua API Key
model = genai.GenerativeModel('gemini-3.8-flash')

database_utenti = {}

def cripta_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def assicura_utente(username: str):
    """Previene crash se il server si riavvia mentre un utente è già loggato nell'app"""
    if username not in database_utenti:
        database_utenti[username] = {"password": "", "armadi": {"Casa Principale": []}}

@app.post("/login/")
async def login(username: str = Form(...), password: str = Form(...)):
    username = username.strip().lower()
    pw_hash = cripta_password(password)
    
    if username not in database_utenti:
        database_utenti[username] = {"password": pw_hash, "armadi": {"Casa Principale": []}}
        return {"message": "Account creato", "status": "nuovo"}
    else:
        if database_utenti[username]["password"] == pw_hash or database_utenti[username]["password"] == "":
            database_utenti[username]["password"] = pw_hash # Aggiorna la password in caso di riavvio
            return {"message": "Accesso consentito", "status": "esistente"}
        else:
            return {"error": "Password errata"}

@app.get("/get-armadi/")
async def get_armadi(username: str):
    username = username.strip().lower()
    assicura_utente(username)
    return {"armadi": database_utenti[username]["armadi"]}

@app.post("/add-armadio/")
async def add_armadio(username: str = Form(...), nome: str = Form(...)):
    username = username.strip().lower()
    assicura_utente(username)
    if nome not in database_utenti[username]["armadi"]:
        database_utenti[username]["armadi"][nome] = []
    return {"message": "Armadio creato!", "nomi_armadi": list(database_utenti[username]["armadi"].keys())}

@app.post("/upload-clothes/")
async def upload_clothes(file: UploadFile = File(...), username: str = Form(...), nome_armadio: str = Form("Casa Principale")):
    username = username.strip().lower()
    assicura_utente(username)
    
    input_image = await file.read()
    output_image = remove(input_image)
    
    item_id = str(uuid.uuid4())[:8]
    filename = f"{item_id}.png"
    filepath = f"immagini_armadio/{filename}"
    with open(filepath, "wb") as f:
        f.write(output_image)
        
    img = PIL.Image.open(io.BytesIO(output_image))
    prompt = "Guarda questo capo di abbigliamento. Rispondi SOLO con un formato JSON valido con due chiavi: 'nome' (es. Maglione, Jeans) e 'colore' (es. Rosso, Blu)."
    response = model.generate_content([prompt, img])
    
    dati_capo = json.loads(response.text.replace("```json", "").replace("```", "").strip())
    capo = {
        "id": item_id,
        "nome": dati_capo["nome"],
        "colore": dati_capo["colore"],
        "url_immagine": f"http://localhost:8000/immagini/{filename}" # Cambia localhost col tuo IP per il telefono
    }
    
    if nome_armadio not in database_utenti[username]["armadi"]:
        database_utenti[username]["armadi"][nome_armadio] = []
    database_utenti[username]["armadi"][nome_armadio].append(capo)
    
    return {"message": "Capo aggiunto!", "capo": capo}

@app.post("/move-item/")
async def move_item(username: str = Form(...), item_id: str = Form(...), da_armadio: str = Form(...), a_armadio: str = Form(...)):
    username = username.strip().lower()
    assicura_utente(username)
    armadi_utente = database_utenti[username]["armadi"]
    
    if da_armadio in armadi_utente and a_armadio in armadi_utente:
        capo_da_spostare = next((c for c in armadi_utente[da_armadio] if c["id"] == item_id), None)
        if capo_da_spostare:
            armadi_utente[da_armadio].remove(capo_da_spostare)
            armadi_utente[a_armadio].append(capo_da_spostare)
            return {"message": "Spostamento completato!"}
    return {"error": "Errore durante lo spostamento."}

@app.get("/generate-outfits/")
async def generate_outfits(username: str, aesthetic: str = "Y2K", nome_armadio: str = "Casa Principale"):
    username = username.strip().lower()
    assicura_utente(username)
    armadio_scelto = database_utenti[username]["armadi"].get(nome_armadio, [])
    
    if len(armadio_scelto) < 2:
        return {"error": f"Carica almeno 2 capi in '{nome_armadio}' per creare un outfit!"}
        
    prompt = f"Sei uno stilista. Crea 3 outfit stile {aesthetic} usando SOLO questi capi: {json.dumps(armadio_scelto)}. Rispondi SOLO in JSON con lista 'outfits' (ogni outfit ha 'titolo' e lista 'capi_ids')."
    
    response = model.generate_content(prompt)
    outfits_dati = json.loads(response.text.replace("```json", "").replace("```", "").strip())
    
    risultato = [{"titolo": out["titolo"], "capi": [c for c in armadio_scelto if c["id"] in out["capi_ids"]]} for out in outfits_dati["outfits"]]
    return {"outfits": risultato}
