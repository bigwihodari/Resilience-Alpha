import { Link } from "react-router-dom";

export default function Hub() {
  const host = typeof window !== "undefined" ? window.location.hostname : "localhost";
  const ext = (port, path = "") => `http://${host}:${port}${path}`;

  const internal = [
    { icon: "💳", title: "Paiement", desc: "Faire une transaction, voir le solde et l'historique.", to: "/pay" },
    { icon: "🛡️", title: "Cockpit de résilience", desc: "Graphes live, état des services, timeline de remédiation.", to: "/cockpit" },
  ];
  const external = [
    { icon: "📊", title: "Grafana", desc: "Tableaux de bord (métriques & logs).", href: ext(3000) },
    { icon: "📈", title: "Prometheus", desc: "Métriques brutes et cibles (/targets).", href: ext(9090, "/targets") },
    { icon: "📜", title: "Logs (Loki)", desc: "Explorer les journaux centralisés.", href: ext(3000, "/explore") },
    { icon: "🔌", title: "API — documentation", desc: "Swagger de l'API de paiement.", href: ext(8000, "/docs") },
  ];

  const Card = ({ icon, title, desc }) => (
    <div className="bg-white rounded-2xl shadow p-5 h-full hover:shadow-lg transition border border-transparent hover:border-lav">
      <div className="text-3xl">{icon}</div>
      <div className="font-bold mt-2">{title}</div>
      <div className="text-sm text-ink/60 mt-1">{desc}</div>
    </div>
  );

  return (
    <div className="max-w-4xl mx-auto p-5">
      <div className="mb-6">
        <h1 className="text-2xl font-extrabold">Poste Hôte — centre de contrôle</h1>
        <p className="text-ink/60">Tout est accessible d'ici, sans chercher les adresses.</p>
      </div>

      <h2 className="text-sm font-bold uppercase tracking-wide text-accent mb-2">Dans l'application</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-7">
        {internal.map((c) => (
          <Link key={c.to} to={c.to}><Card {...c} /></Link>
        ))}
      </div>

      <h2 className="text-sm font-bold uppercase tracking-wide text-accent mb-2">Supervision & outils</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {external.map((c) => (
          <a key={c.title} href={c.href} target="_blank" rel="noreferrer"><Card {...c} /></a>
        ))}
      </div>

      <p className="text-xs text-ink/40 mt-6">
        Les liens de supervision utilisent l'adresse de ce poste ({host}) avec les ports par défaut.
        Si tu as changé un port dans <code>.env</code>, adapte l'URL en conséquence.
      </p>
    </div>
  );
}
