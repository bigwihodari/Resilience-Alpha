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
import threading

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

emb = OllamaEmbeddings(model=EMB_MODEL, base_url=OLLAMA)
llm = OllamaLLM(model=LLM_MODEL, base_url=OLLAMA, temperature=0.1)

PROMPT = """Tu es l'assistant opérateur de la plateforme de paiement Resilience-Alpha.
Réponds en français, de façon concise et pratique, en t'appuyant UNIQUEMENT sur le
contexte ci-dessous (procédures, architecture, sécurité). Si l'information n'y est pas,
dis-le clairement.

Contexte :
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


@app.post("/ask")
def ask(q: Q):
    if store is None:
        return {"answer": "L'index documentaire n'est pas encore prêt (réessaie dans quelques secondes).",
                "sources": [], "ready": False}
    hits = store.similarity_search(q.question, k=4)
    context = "\n\n".join(f"[{h.metadata.get('source')}]\n{h.page_content}" for h in hits)
    try:
        answer = clean(llm.invoke(PROMPT.format(context=context, question=q.question)))
    except Exception as e:  # noqa: BLE001
        return {"answer": f"Modèle local injoignable ({e}). Vérifie qu'Ollama tourne et expose son API.",
                "sources": [], "ready": True}
    sources = sorted({h.metadata.get("source") for h in hits})
    return {"answer": answer, "sources": sources, "ready": True}
