import { useEffect, useRef, useState } from "react";
import { getUser, getRooms, createRoom, addRoomMember, getRoomMessages, postRoomMessage } from "../api.js";

// Chat flottant en bas à droite, présent sur toutes les pages.
export default function ChatWidget() {
  const me = getUser();
  const [open, setOpen] = useState(false);
  const [rooms, setRooms] = useState([]);
  const [active, setActive] = useState(null);
  const [msgs, setMsgs] = useState([]);
  const [text, setText] = useState("");
  const [creating, setCreating] = useState(false);
  const [rName, setRName] = useState("");
  const [rMembers, setRMembers] = useState("");
  const [unseen, setUnseen] = useState(0);
  const endRef = useRef(null);
  const activeRef = useRef(null); activeRef.current = active;
  const lastCountRef = useRef(0);

  async function loadRooms() {
    const r = await getRooms(); setRooms(r || []);
    if (!activeRef.current && r && r.length) setActive(r[0]);
  }
  async function loadMsgs() {
    const a = activeRef.current; if (!a) return;
    const m = await getRoomMessages(a.id) || [];
    setMsgs(m);
    if (!open && m.length > lastCountRef.current) setUnseen((u) => u + (m.length - lastCountRef.current));
    lastCountRef.current = m.length;
  }

  useEffect(() => { loadRooms(); }, []);
  useEffect(() => {
    lastCountRef.current = 0; loadMsgs();
    const poll = setInterval(loadMsgs, 2500);
    let ws, stopped = false, retry, ping;
    const connect = () => {
      try {
        const proto = location.protocol === "https:" ? "wss" : "ws";
        ws = new WebSocket(`${proto}://${location.host}/ws`);
        ws.onopen = () => { clearInterval(ping); ping = setInterval(() => { try { ws.send("ping"); } catch { /* */ } }, 25000); };
        ws.onmessage = (e) => { try { if (JSON.parse(e.data).type === "chat") loadMsgs(); } catch { /* */ } };
        ws.onclose = () => { clearInterval(ping); if (!stopped) retry = setTimeout(connect, 2000); };
        ws.onerror = () => { try { ws.close(); } catch { /* */ } };
      } catch { retry = setTimeout(connect, 2000); }
    };
    connect();
    return () => { stopped = true; clearInterval(poll); clearInterval(retry); clearInterval(ping); try { ws && ws.close(); } catch { /* */ } };
  }, [active?.id]);

  useEffect(() => { if (open) { setUnseen(0); endRef.current?.scrollIntoView({ behavior: "smooth" }); } }, [msgs, open]);

  async function send() { if (!text.trim() || !active) return; const t = text; setText(""); try { await postRoomMessage(active.id, t); await loadMsgs(); } catch { /* */ } }
  async function create() {
    if (!rName.trim()) return;
    const members = rMembers.split(",").map((s) => s.trim()).filter(Boolean);
    try { await createRoom(rName.trim(), members); setRName(""); setRMembers(""); setCreating(false); await loadRooms(); } catch { /* */ }
  }

  return (
    <>
      {!open && (
        <button onClick={() => setOpen(true)} title="Chat"
          className="fixed z-40 bottom-5 right-5 w-14 h-14 rounded-full bg-ink text-white text-2xl shadow-lg hover:bg-accent transition flex items-center justify-center">
          💬{unseen > 0 && <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[10px] font-bold w-5 h-5 rounded-full flex items-center justify-center">{unseen}</span>}
        </button>
      )}
      {open && (
        <div className="fixed z-40 bottom-5 right-5 w-[22rem] max-w-[92vw] h-[28rem] bg-white rounded-2xl shadow-2xl flex flex-col overflow-hidden border border-lav">
          <div className="bg-ink text-white px-3 py-2 flex items-center gap-2">
            <span className="font-bold text-sm">💬 Chat</span>
            <select value={active?.id || ""} onChange={(e) => setActive(rooms.find((r) => String(r.id) === e.target.value))}
              className="ml-auto bg-white/15 text-white text-xs rounded px-2 py-1 max-w-[9rem]">
              {rooms.map((r) => <option key={r.id} value={r.id} className="text-ink">{r.is_global ? "🌐 " : "🔒 "}{r.name}</option>)}
            </select>
            <button onClick={() => setCreating((v) => !v)} title="Nouveau salon" className="text-white/80 hover:text-white text-sm">＋</button>
            <button onClick={() => setOpen(false)} className="text-white/80 hover:text-white text-lg leading-none">×</button>
          </div>
          {creating && (
            <div className="p-2 bg-lavsoft space-y-1 border-b border-lav">
              <input value={rName} onChange={(e) => setRName(e.target.value)} placeholder="Nom du salon" className="w-full border border-lav rounded px-2 py-1 text-xs" />
              <input value={rMembers} onChange={(e) => setRMembers(e.target.value)} placeholder="Membres (ex: bob,alice)" className="w-full border border-lav rounded px-2 py-1 text-xs" />
              <button onClick={create} className="w-full bg-accent text-white text-xs font-semibold py-1 rounded">Créer un salon privé</button>
            </div>
          )}
          <div className="flex-1 overflow-auto p-2 space-y-1.5">
            {msgs.length === 0 && <div className="text-xs text-ink/40 text-center mt-4">Aucun message.</div>}
            {msgs.map((m) => (
              <div key={m.id} className={`flex ${m.sender === me ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[80%] rounded-2xl px-2.5 py-1.5 text-sm ${m.sender === me ? "bg-accent text-white" : "bg-lavsoft text-ink"}`}>
                  {m.sender !== me && <div className="text-[10px] font-bold opacity-70">{m.sender}</div>}{m.body}
                </div>
              </div>
            ))}
            <div ref={endRef} />
          </div>
          {active && !active.is_global && (
            <div className="px-2 py-1 border-t border-lavsoft flex gap-1 items-center">
              <input id="cw-member" placeholder="ajouter un membre…" className="flex-1 border border-lav rounded px-2 py-1 text-xs" />
              <button onClick={async () => { const el = document.getElementById("cw-member"); if (el.value.trim()) { try { await addRoomMember(active.id, el.value.trim()); el.value = ""; } catch { /* */ } } }} className="text-xs bg-lavsoft text-accent px-2 py-1 rounded">+</button>
            </div>
          )}
          <div className="p-2 border-t border-lavsoft flex gap-1">
            <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} placeholder="Message…" className="flex-1 border border-lav rounded-lg px-2.5 py-1.5 text-sm" />
            <button onClick={send} className="bg-accent text-white font-semibold px-3 rounded-lg hover:bg-ink text-sm">➤</button>
          </div>
        </div>
      )}
    </>
  );
}
