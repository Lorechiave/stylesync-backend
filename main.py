from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import google.generativeai as genai
import PIL.Image
import io, uuid, json, os, hashlib, requests, base64

app = FastAPI(title="StyleSync Pro")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ==========================================
genai.configure(api_key="GEMINI_KEY") 
model = genai.GenerativeModel('gemini-3.8-flash')
FIREBASE_URL = "FIREBASE_KEY" # Assicurati di non mettere la barra / alla fine!
# ==========================================

def carica_db():
    try:
        r = requests.get(f"{FIREBASE_URL}/utenti.json")
        return r.json() if r.json() else {}
    except: return {}

def salva_db():
    requests.put(f"{FIREBASE_URL}/utenti.json", json=database_utenti)

database_utenti = carica_db()
def cripta_password(password: str) -> str: return hashlib.sha256(password.encode()).hexdigest()

@app.post("/register/")
async def register(username: str = Form(...), password: str = Form(...), domanda: str = Form(...), risposta: str = Form(...)):
    user = username.strip().lower()
    if user in database_utenti: return {"error": "Username già in uso."}
    database_utenti[user] = {"password": cripta_password(password), "domanda": domanda, "risposta": risposta.strip().lower(), "armadi": {"Casa Principale": []}}
    salva_db()
    return {"message": "Registrazione completata!"}

@app.post("/login/")
async def login(username: str = Form(...), password: str = Form(...)):
    user = username.strip().lower()
    if user not in database_utenti: return {"error": "Utente non trovato."}
    if database_utenti[user]["password"] == cripta_password(password): return {"message": "Accesso consentito"}
    return {"error": "Password errata."}

@app.get("/get-armadi/")
async def get_armadi(username: str):
    user = username.strip().lower()
    return {"armadi": database_utenti.get(user, {}).get("armadi", {})}

@app.post("/add-armadio/")
async def add_armadio(username: str = Form(...), nome: str = Form(...)):
    user = username.strip().lower()
    if user in database_utenti and nome not in database_utenti[user]["armadi"]:
        database_utenti[user]["armadi"][nome] = []
        salva_db()
    return {"message": "Armadio creato!"}

@app.post("/upload-clothes/")
async def upload_clothes(file: UploadFile = File(...), username: str = Form(...), nome_armadio: str = Form("Casa Principale")):
    user = username.strip().lower()
    raw_bytes = await file.read()
    
    try:
        img_originale = PIL.Image.open(io.BytesIO(raw_bytes))
        img_originale.thumbnail((600, 600)) 
        compresso_io = io.BytesIO()
        img_originale.save(compresso_io, format="PNG")
        output_image = compresso_io.getvalue()
        img_base64 = base64.b64encode(output_image).decode('utf-8')
    except: return {"error": "Impossibile leggere l'immagine."}
    
    item_id = str(uuid.uuid4())[:8]
    img_per_gemini = PIL.Image.open(io.BytesIO(output_image))
    
    prompt = "Identify this clothing item. Reply ONLY with a raw JSON object containing two keys: 'nome' (e.g. Jeans, Camicia) and 'colore' (e.g. Rosso, Nero)."
    try:
        # Costringiamo Gemini a usare il formato JSON per evitare fallimenti
        response = model.generate_content([prompt, img_per_gemini], generation_config={"response_mime_type": "application/json"})
        dati_capo = json.loads(response.text)
    except: dati_capo = {"nome": "Capo", "colore": "Sconosciuto"}
        
    capo = {"id": item_id, "nome": dati_capo.get("nome", "Capo"), "colore": dati_capo.get("colore", ""), "stato": "disponibile", "base64": img_base64, "url_immagine": f"/immagini/{item_id}.png"}
    
    if nome_armadio not in database_utenti[user]["armadi"]: database_utenti[user]["armadi"][nome_armadio] = []
    database_utenti[user]["armadi"][nome_armadio].append(capo)
    salva_db()
    return {"message": "Aggiunto!", "capo": capo}

@app.get("/immagini/{filename}")
async def get_image(filename: str):
    item_id = filename.replace(".png", "")
    for user_data in database_utenti.values():
        for armadio in user_data.get("armadi", {}).values():
            for capo in armadio:
                if capo.get("id") == item_id and "base64" in capo:
                    return Response(content=base64.b64decode(capo["base64"]), media_type="image/png")
    return Response(status_code=404)

@app.post("/manage-item/")
async def manage_item(username: str = Form(...), item_id: str = Form(...), armadio_attuale: str = Form(...), azione: str = Form(...), nuovo_valore: str = Form(None)):
    user = username.strip().lower()
    armadi = database_utenti[user]["armadi"]
    capo_target = next((c for c in armadi[armadio_attuale] if c["id"] == item_id), None)
    
    if not capo_target: return {"error": "Capo non trovato."}
    
    if azione == "elimina":
        armadi[armadio_attuale].remove(capo_target)
    elif azione == "rinomina":
        capo_target["nome"] = nuovo_valore
    elif azione == "lavanderia":
        capo_target["stato"] = "lavare" if capo_target.get("stato") == "disponibile" else "disponibile"
    elif azione == "sposta":
        armadi[armadio_attuale].remove(capo_target)
        armadi[nuovo_valore].append(capo_target)
        
    salva_db()
    return {"message": "Azione completata!"}

@app.get("/generate-outfits/")
async def generate_outfits(username: str, aesthetic: str = "Y2K", nome_armadio: str = "Casa Principale", capo_forzato_id: str = None):
    user = username.strip().lower()
    armadio_completo = database_utenti[user]["armadi"].get(nome_armadio, [])
    
    # Escludiamo i capi a lavare, a meno che non sia il capo forzato dall'utente
    armadio_scelto = [c for c in armadio_completo if c.get("stato", "disponibile") == "disponibile" or c["id"] == capo_forzato_id]
    
    if len(armadio_scelto) < 2: return {"error": "Pochi capi disponibili per creare un outfit."}
    
    prompt = f"Crea 3 outfit stile {aesthetic} usando SOLO questi capi: {json.dumps(armadio_scelto)}. "
    if capo_forzato_id: prompt += f"DEVI assolutamente includere il capo con ID {capo_forzato_id} in tutti gli outfit. "
    prompt += "Rispondi in JSON puro con lista 'outfits' ('titolo' e 'capi_ids')."
    
    try:
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        outfits_dati = json.loads(response.text)
        risultato = [{"titolo": out["titolo"], "capi": [c for c in armadio_scelto if c["id"] in out["capi_ids"]]} for out in outfits_dati["outfits"]]
        return {"outfits": risultato}
    except: return {"error": "Errore AI."}

@app.get("/")
async def sveglia(): return {"status": "Online h24!"}
