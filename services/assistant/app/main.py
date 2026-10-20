"""Assistant RAG local — Resilience-Alpha.

Aide les opérateurs à COMPRENDRE l'incident et à consulter les procédures.
Recherche documentaire (RAG) : embeddings nomic-embed-text + index FAISS, réponse
générée par un modèle local (Ollama, <= 8B). LangChain orchestre le tout.

Sans privilèges : ce service ne lit QUE la documentation (montée en lecture seule).
Il ne peut pas agir sur la plateforme ni accéder à la base ou à la remédiation.
"""
import os
import re
import glob
import json
import time
import threading
import urllib.parse
import urllib.request

from fastapi import FastAPI
from pydantic import BaseModel
from langchain_ollama import OllamaLLM, OllamaEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

OLLAMA = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:7b-instruct-q4_K_M")
EMB_MODEL = os.environ.get("EMB_MODEL", "nomic-embed-text")
KNOWLEDGE = os.environ.get("KNOWLEDGE_DIR", "/app/knowledge")
# RAG auto-rempli : l'assistant lit EN DIRECT les logs/erreurs du serveur (via Loki,
# qui agrège les logs de tous les conteneurs) pour répondre sur ce qui se passe.
LOKI_URL = os.environ.get("LOKI_URL", "http://loki:3100")
EVENTS_PATTERN = os.environ.get(
    "EVENTS_PATTERN",
    r"(?i)(error|exception|traceback|failed|refus|\[waf\]|\[game\]|\[ha\]|block|promotion|bascule|anomal|cramé|403|402|500)")
_events_cache = {"t": 0.0, "text": ""}


def recent_server_events(minutes=15, limit=40):
    """Dernières lignes de log intéressantes (erreurs/événements) depuis Loki."""
    now = time.time()
    if now - _events_cache["t"] < 15 and _events_cache["text"]:
        return _events_cache["text"]
    try:
        end = int(now * 1e9)
        start = int((now - minutes * 60) * 1e9)
        q = '{container=~".+"} |~ `' + EVENTS_PATTERN + '`'
        url = f"{LOKI_URL}/loki/api/v1/query_range?" + urllib.parse.urlencode(
            {"query": q, "start": start, "end": end, "limit": limit, "direction": "backward"})
        with urllib.request.urlopen(url, timeout=4) as r:
            data = json.loads(r.read())
        rows = []
        for stream in data.get("data", {}).get("result", []):
            cont = stream.get("stream", {}).get("container", "?")
            for ts, line in stream.get("values", []):
                rows.append((int(ts), cont, line.strip()[:300]))
        rows.sort(key=lambda x: x[0], reverse=True)
        out = "\n".join(f"{c}: {l}" for _, c, l in rows[:limit]) or "(aucune erreur/événement récent)"
        _events_cache.update({"t": now, "text": out})
        return out
    except Exception as e:  # noqa: BLE001
        return f"(logs serveur indisponibles : {e})"

emb = OllamaEmbeddings(model=EMB_MODEL, base_url=OLLAMA)
llm = OllamaLLM(model=LLM_MODEL, base_url=OLLAMA, temperature=0.1)

PROMPT = """Tu es l'assistant opérateur de la plateforme de paiement Resilience-Alpha.
Réponds en français, de façon concise et pratique. Tu disposes de deux sources :
1) la DOCUMENTATION (procédures, architecture, sécurité) ;
2) les ÉVÉNEMENTS RÉCENTS DU SERVEUR (logs live : erreurs, WAF, bascules, blocages…)
   — sers-t'en pour dire ce qui se passe/s'est produit, les erreurs, les incidents.
Appuie-toi UNIQUEMENT sur ce contexte ; si l'information n'y est pas, dis-le.

=== ÉVÉNEMENTS RÉCENTS DU SERVEUR (logs live) ===
{events}

=== DOCUMENTATION ===
{context}

Question : {question}
Réponse :"""

state = {"ready": False, "chunks": 0, "error": None}
store = None
_lock = threading.Lock()


def build_index():
    global store
    docs = []
    for path in glob.glob(f"{KNOWLEDGE}/**/*.md", recursive=True):
        try:
            with open(path, encoding="utf-8") as f:
                docs.append(Document(page_content=f.read(), metadata={"source": os.path.basename(path)}))
        except Exception:  # noqa: BLE001
            pass
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)
    chunks = splitter.split_documents(docs)
    if chunks:
        s = FAISS.from_documents(chunks, emb)
        with _lock:
            globals()["store"] = s
    return len(chunks)


def _init():
    try:
        n = build_index()
        state["chunks"] = n
        state["ready"] = store is not None
        print(f"[assistant] index prêt : {n} fragments", flush=True)
    except Exception as e:  # noqa: BLE001
        state["error"] = str(e)
        print(f"[assistant] échec indexation : {e}", flush=True)


def clean(text: str) -> str:
    # certains modèles emettent un bloc de raisonnement <think>…</think> : on le retire
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


app = FastAPI(title="Resilience-Alpha — Assistant RAG")


@app.on_event("startup")
def startup():
    threading.Thread(target=_init, daemon=True).start()


class Q(BaseModel):
    question: str


@app.get("/health")
def health():
    return {"status": "ok", "ready": state["ready"], "chunks": state["chunks"], "error": state["error"]}


@app.get("/events")
def events():
    """Événements/erreurs serveur récents (debug ; alimente aussi le RAG)."""
    return {"events": recent_server_events()}


@app.post("/ask")
def ask(q: Q):
    events_ctx = recent_server_events()
    hits = store.similarity_search(q.question, k=4) if store is not None else []
    context = "\n\n".join(f"[{h.metadata.get('source')}]\n{h.page_content}" for h in hits) or "(documentation non indexée)"
    try:
        answer = clean(llm.invoke(PROMPT.format(events=events_ctx, context=context, question=q.question)))
    except Exception as e:  # noqa: BLE001
        return {"answer": f"Modèle local injoignable ({e}). Vérifie qu'Ollama tourne et expose son API.",
                "sources": [], "ready": True}
    sources = sorted({h.metadata.get("source") for h in hits})
    if events_ctx and "indisponibles" not in events_ctx and "aucune" not in events_ctx:
        sources = sources + ["logs serveur (live)"]
    return {"answer": answer, "sources": sources, "ready": True}
