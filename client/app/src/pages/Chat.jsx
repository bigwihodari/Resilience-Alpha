import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getUser, getRooms, createRoom, addRoomMember, getRoomMessages, postRoomMessage } from "../api.js";

export default function Chat() {
  const me = getUser();
  const nav = useNavigate();
  const [rooms, setRooms] = useState([]);
  const [active, setActive] = useState(null);
  const [msgs, setMsgs] = useState([]);
  const [text, setText] = useState("");
  const [newRoom, setNewRoom] = useState("");
  const [newMembers, setNewMembers] = useState("");
  const [member, setMember] = useState("");
  const endRef = useRef(null);
  const activeRef = useRef(null);
  activeRef.current = active;

  async function loadRooms() { const r = await getRooms(); setRooms(r || []); if (!activeRef.current && r && r.length) setActive(r[0]); }
  async function loadMsgs() { const a = activeRef.current; if (!a) return; setMsgs(await getRoomMessages(a.id) || []); }

  useEffect(() => { loadRooms(); }, []);
  useEffect(() => {
    loadMsgs();
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

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  async function send() {
    if (!text.trim() || !active) return;
    const t = text; setText("");
    try { await postRoomMessage(active.id, t); await loadMsgs(); } catch { /* */ }
  }
  async function create() {
    if (!newRoom.trim()) return;
    const members = newMembers.split(",").map((s) => s.trim()).filter(Boolean);
    try { await createRoom(newRoom.trim(), members); setNewRoom(""); setNewMembers(""); await loadRooms(); } catch { /* */ }
  }

  return (
    <div className="max-w-5xl mx-auto p-4">
      <div className="flex items-center gap-3 mb-4">
        <button onClick={() => nav("/dashboard")} className="text-sm bg-white px-3 py-1.5 rounded-lg shadow">← Retour</button>
        <h1 className="text-xl font-extrabold text-ink">💬 Chat</h1>
      </div>
      <div className="grid md:grid-cols-[260px_1fr] gap-4">
        <div className="bg-white rounded-2xl shadow p-3 h-fit">
          <div className="font-bold text-ink mb-2 text-sm">Salons</div>
          <div className="space-y-1 max-h-72 overflow-auto">
            {rooms.map((r) => (
              <button key={r.id} onClick={() => setActive(r)}
                className={`w-full text-left px-3 py-2 rounded-lg text-sm ${active?.id === r.id ? "bg-accent text-white" : "hover:bg-lavsoft"}`}>
                {r.is_global ? "🌐 " : "🔒 "}{r.name}
              </button>
            ))}
          </div>
          <div className="mt-3 border-t border-lavsoft pt-3 space-y-2">
            <input value={newRoom} onChange={(e) => setNewRoom(e.target.value)} placeholder="Nouveau salon" className="w-full border border-lav rounded-lg px-2 py-1.5 text-sm" />
            <input value={newMembers} onChange={(e) => setNewMembers(e.target.value)} placeholder="Membres (ex: bob,alice)" className="w-full border border-lav rounded-lg px-2 py-1.5 text-sm" />
            <button onClick={create} className="w-full bg-accent text-white font-semibold py-1.5 rounded-lg text-sm hover:bg-ink">Créer un salon privé</button>
          </div>
        </div>

        <div className="bg-white rounded-2xl shadow flex flex-col h-[60vh]">
          <div className="px-4 py-2.5 border-b border-lavsoft font-bold text-ink flex items-center gap-2">
            {active ? (active.is_global ? "🌐 " : "🔒 ") + active.name : "Sélectionne un salon"}
            {active && !active.is_global && (
              <div className="ml-auto flex items-center gap-1">
                <input value={member} onChange={(e) => setMember(e.target.value)} placeholder="ajouter…" className="w-24 border border-lav rounded px-2 py-1 text-xs" />
                <button onClick={async () => { if (member.trim()) { try { await addRoomMember(active.id, member.trim()); setMember(""); } catch { /* */ } } }} className="text-xs bg-lavsoft text-accent px-2 py-1 rounded">+</button>
              </div>
            )}
          </div>
          <div className="flex-1 overflow-auto p-4 space-y-2">
            {msgs.length === 0 && <div className="text-sm text-ink/40">Aucun message.</div>}
            {msgs.map((m) => (
              <div key={m.id} className={`flex ${m.sender === me ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[75%] rounded-2xl px-3 py-1.5 text-sm ${m.sender === me ? "bg-accent text-white" : "bg-lavsoft text-ink"}`}>
                  {m.sender !== me && <div className="text-[10px] font-bold opacity-70">{m.sender}</div>}
                  {m.body}
                </div>
              </div>
            ))}
            <div ref={endRef} />
          </div>
          <div className="p-3 border-t border-lavsoft flex gap-2">
            <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} placeholder="Message…" className="flex-1 border border-lav rounded-lg px-3 py-2 text-sm" />
            <button onClick={send} className="bg-accent text-white font-semibold px-4 py-2 rounded-lg hover:bg-ink text-sm">Envoyer</button>
          </div>
        </div>
      </div>
    </div>
  );
}
