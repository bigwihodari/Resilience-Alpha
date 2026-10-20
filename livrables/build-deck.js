// Génère le deck de présentation PPTX — RESILIENCE GUARD (module plug-and-protect).
const pptxgen = require("pptxgenjs");
const p = new pptxgen();
p.layout = "LAYOUT_WIDE"; // 13.3 x 7.5
p.author = "Consortium Workshop2026-M2";
p.title = "RESILIENCE GUARD";

const NAVY = "261E48", PURPLE = "4B3FA6", LAV = "A1A6D4", LIGHT = "E4E6F3",
      SOFT = "EEF0F8", WHITE = "FFFFFF", GREEN = "1E8E6A", RED = "C2413C", AMBER = "B8840F", MUT = "6A6594";
const HEAD = "Calibri", BODY = "Calibri";

function tb(slide, text, opts) { slide.addText(text, Object.assign({ isTextBox: true, fontFace: BODY }, opts)); }
function titleBar(slide, t, kicker) {
  if (kicker) tb(slide, kicker.toUpperCase(), { x: 0.6, y: 0.45, w: 12, h: 0.3, fontSize: 12, bold: true, color: PURPLE, charSpacing: 2, margin: 0 });
  tb(slide, t, { x: 0.6, y: 0.72, w: 12.1, h: 0.7, fontSize: 30, bold: true, color: NAVY, fontFace: HEAD, margin: 0 });
}
function card(slide, x, y, w, h, fill) {
  slide.addShape(p.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line: { type: "none" }, shadow: { type: "outer", color: "888888", opacity: 0.25, blur: 6, offset: 2, angle: 90 } });
}
function bullets(slide, items, opts) {
  tb(slide, items.map((t) => ({ text: t, options: { bullet: { code: "2022" }, color: NAVY } })),
     Object.assign({ fontSize: 15, lineSpacingMultiple: 1.15, color: NAVY }, opts));
}

/* 1 — Couverture */
let s = p.addSlide(); s.background = { color: NAVY };
s.addShape(p.ShapeType.roundRect, { x: 0.8, y: 1.0, w: 2.9, h: 0.42, rectRadius: 0.2, fill: { color: PURPLE }, line: { type: "none" } });
tb(s, "WORKSHOP EPSI BAC+5", { x: 0.8, y: 1.02, w: 2.9, h: 0.38, fontSize: 11, bold: true, color: WHITE, align: "center", margin: 0 });
tb(s, "RESILIENCE GUARD", { x: 0.8, y: 2.0, w: 11.7, h: 1.1, fontSize: 48, bold: true, color: WHITE, fontFace: HEAD, margin: 0 });
tb(s, "Module de sécurité & de résilience « plug-and-protect » pour toute application", { x: 0.8, y: 3.2, w: 11.6, h: 0.6, fontSize: 19, color: LAV, margin: 0 });
tb(s, "« On ne réécrit pas chaque app pour la protéger. On pose un module devant — et il s'en charge. »", { x: 0.8, y: 4.2, w: 11.4, h: 0.6, fontSize: 14, italic: true, color: LIGHT, margin: 0 });
tb(s, "Équipe : Téo Debay · Timéo Quehen · Hodari Bigwi · Théo Vambre · Adrien Planquelle", { x: 0.8, y: 5.3, w: 11.7, h: 0.4, fontSize: 13, color: WHITE, margin: 0 });
tb(s, "Consortium Workshop2026-M2-G<n>  ·  Octobre 2026  ·  github.com/bigwihodari/Resilience-Alpha", { x: 0.8, y: 6.7, w: 11.7, h: 0.4, fontSize: 11, color: LAV, margin: 0 });

/* 2 — Problème / solution */
s = p.addSlide(); s.background = { color: WHITE }; titleBar(s, "Le problème, et notre réponse", "Pourquoi");
card(s, 0.6, 1.7, 5.9, 4.6, SOFT);
tb(s, "Le problème", { x: 0.9, y: 1.9, w: 5.3, h: 0.4, fontSize: 16, bold: true, color: RED, margin: 0 });
bullets(s, ["Protéger + superviser une app = ~10 outils à intégrer", "Au cas par cas, dans chaque projet", "Long, coûteux, hétérogène", "La reprise après incident dépend d'humains"], { x: 1.0, y: 2.4, w: 5.2, h: 3.5 });
card(s, 6.8, 1.7, 5.9, 4.6, NAVY);
tb(s, "Resilience Guard", { x: 7.1, y: 1.9, w: 5.3, h: 0.4, fontSize: 16, bold: true, color: WHITE, margin: 0 });
bullets(s, ["Un module unique, réutilisable, autonome", "Installé en 1 commande DEVANT l'app", "Sans toucher au code de l'app", "WAF + KPI + IA + remédiation + HA + assistant", "Un cockpit unique prêt à l'emploi"], { x: 7.2, y: 2.4, w: 5.2, h: 3.5, color: LIGHT });

/* 3 — Plug-and-protect */
s = p.addSlide(); s.background = { color: WHITE }; titleBar(s, "« Plug-and-protect » — en une commande", "Installation");
card(s, 0.6, 1.8, 12.1, 1.2, SOFT);
tb(s, "PROTECTED_UPSTREAM=http://mon-app:8000  docker compose -f docker-compose.module.yml up -d", { x: 0.9, y: 2.1, w: 11.5, h: 0.6, fontSize: 15, fontFace: "Consolas", color: NAVY, margin: 0 });
bullets(s, ["L'app tourne derrière la passerelle du module (reverse-proxy)", "Une seule variable : l'URL amont de l'app (dockerisée ou non)", "App servie + protégée + supervisée — cockpit prêt à l'emploi", "Démontré sur une app de paiement ET une app vierge (site statique)"], { x: 0.8, y: 3.3, w: 12, h: 3 });

/* 4 — Architecture */
s = p.addSlide(); s.background = { color: WHITE }; titleBar(s, "Architecture du module", "Composants");
const comps = [
  ["Passerelle WAF + proxy", "Filtre (OWASP), proxifie, expose les métriques", CYBERC()],
  ["Prometheus / Grafana / Loki", "KPI, dashboards, logs centralisés", "INFRA"],
  ["Détecteur (Isolation Forest)", "Score d'anomalie sur le trafic", "IA / DATA"],
  ["Orchestrateur", "Remédiation autonome (bouclier, vérif, intégrité)", "CYBER / IA"],
  ["Assistant RAG (Ollama)", "Répond ; lit les logs/erreurs en direct", "IA / DATA"],
  ["Cockpit + overlay HA", "Vue unique + bascule/retour automatiques", "DEV / INFRA"],
];
function CYBERC() { return "CYBER / DEV"; }
let yy = 1.8;
comps.forEach((c) => {
  card(s, 0.6, yy, 12.1, 0.72, SOFT);
  tb(s, c[0], { x: 0.8, y: yy + 0.06, w: 4.2, h: 0.6, fontSize: 14, bold: true, color: NAVY, margin: 0, valign: "middle" });
  tb(s, c[1], { x: 5.0, y: yy + 0.06, w: 5.6, h: 0.6, fontSize: 12.5, color: NAVY, margin: 0, valign: "middle" });
  tb(s, c[2], { x: 10.7, y: yy + 0.06, w: 1.9, h: 0.6, fontSize: 11, bold: true, color: PURPLE, align: "right", margin: 0, valign: "middle" });
  yy += 0.82;
});

/* 5 — DEV & INFRA */
s = p.addSlide(); s.background = { color: WHITE }; titleBar(s, "DEV & INFRA", "Pilier");
bullets(s, [
  "Tout conteneurisé (Docker Compose) ; le module est un OVERLAY superposé à l'app",
  "Aucune modification du code applicatif — découplage total, réversible",
  "Passerelle FastAPI + httpx : WAF, délestage, proxy, métriques, /health",
  "Observabilité : Prometheus (débit, latence p95, 4xx/5xx, CPU/mém, WAF), Grafana, Loki",
  "Images de base pré-tirées → builds reproductibles en labo isolé",
], { x: 0.8, y: 1.9, w: 12, h: 4.2 });

/* 6 — IA / DATA */
s = p.addSlide(); s.background = { color: WHITE }; titleBar(s, "IA / DATA", "Pilier");
card(s, 0.6, 1.8, 5.9, 4.4, SOFT);
tb(s, "Détection", { x: 0.9, y: 2.0, w: 5.3, h: 0.4, fontSize: 15, bold: true, color: PURPLE, margin: 0 });
bullets(s, ["Isolation Forest sur le trafic (débit, erreurs)", "Score d'anomalie continu + seuil", "Suspicion PAR IP : monte/décroît", "Blocage PROBABILISTE et ISOLÉ (le suspect seul)"], { x: 1.0, y: 2.5, w: 5.2, h: 3.4 });
card(s, 6.8, 1.8, 5.9, 4.4, NAVY);
tb(s, "Assistant RAG auto-rempli", { x: 7.1, y: 2.0, w: 5.3, h: 0.4, fontSize: 15, bold: true, color: WHITE, margin: 0 });
bullets(s, ["Ollama local (modèle ≤ 8B) + embeddings", "Doc indexée (FAISS)", "+ logs/erreurs serveur LUS EN DIRECT (Loki)", "Sait dire ce qui se passe (WAF, 403, bascules)", "Sans privilèges : il lit, il n'agit pas"], { x: 7.2, y: 2.5, w: 5.2, h: 3.4, color: LIGHT });

/* 7 — CYBER */
s = p.addSlide(); s.background = { color: WHITE }; titleBar(s, "CYBER — défense & remédiation", "Pilier");
bullets(s, [
  "WAF applicatif : signatures OWASP (SQLi, XSS…) → requêtes bloquées en 403",
  "Remédiation autonome (zéro-touch) : détecte → décide → agit (bouclier) → vérifie → journalise",
  "Accès maîtrisés : pas de god-mode, API d'administration restreinte et tracée",
  "Détection par IP + blocage probabiliste : on ralentit/stoppe l'attaquant, pas les clients",
], { x: 0.8, y: 1.9, w: 12, h: 4.2 });

/* 8 — Haute disponibilité */
s = p.addSlide(); s.background = { color: WHITE }; titleBar(s, "Haute disponibilité", "INFRA / Résilience");
card(s, 0.6, 1.8, 5.9, 3.0, SOFT);
tb(s, "Bascule (failover)", { x: 0.9, y: 2.0, w: 5.3, h: 0.4, fontSize: 15, bold: true, color: PURPLE, margin: 0 });
bullets(s, ["Reverse-proxy de bascule devant 2 passerelles", "Principal KO → trafic routé sur le secours", "< 8 s, sans intervention"], { x: 1.0, y: 2.5, w: 5.2, h: 2 });
card(s, 6.8, 1.8, 5.9, 3.0, SOFT);
tb(s, "Retour (failback)", { x: 7.1, y: 2.0, w: 5.3, h: 0.4, fontSize: 15, bold: true, color: PURPLE, margin: 0 });
bullets(s, ["Principal rétabli → réconciliation d'état", "Il reprend la main automatiquement", "Visible en direct dans le cockpit"], { x: 7.2, y: 2.5, w: 5.2, h: 2 });
card(s, 0.6, 5.0, 12.1, 1.2, NAVY);
tb(s, "Toute la techno HA est conservée et démontrable — la continuité ne dépend pas d'un humain.", { x: 0.9, y: 5.25, w: 11.5, h: 0.7, fontSize: 15, bold: true, color: WHITE, margin: 0, valign: "middle" });

/* 9 — TRANSFO */
s = p.addSlide(); s.background = { color: WHITE }; titleBar(s, "TRANSFO — un produit réutilisable", "Pilier");
bullets(s, [
  "Standardisation : même socle sécurité/observabilité sur TOUTES les apps",
  "Time-to-protect : app non protégée → supervisée + résiliente en 1 commande",
  "Autonomie d'exploitation : remédiation sans astreinte + assistant qui explique",
  "Réversibilité : overlay découplé, ajouté/retiré sans toucher à l'app",
], { x: 0.8, y: 1.9, w: 12, h: 4.2 });

/* 10 — Démo & résultats */
s = p.addSlide(); s.background = { color: WHITE }; titleBar(s, "Démonstration & résultats (local)", "Preuve");
const rows = [
  ["Trafic normal", "Cockpit : KPI live ; détecteur CLEAR"],
  ["Injection SQL ' OR 1=1--", "WAF 403 + waf_blocked_total ↑"],
  ["Montée en charge", "Anomalie ↑ → bouclier + vérif + journal"],
  ["Panne du principal", "Bascule auto < 8 s, retour auto ensuite"],
  ["Question à l'assistant", "Réponse citant les logs/erreurs réels"],
];
yy = 1.9;
rows.forEach((r) => {
  card(s, 0.6, yy, 12.1, 0.72, SOFT);
  tb(s, r[0], { x: 0.8, y: yy + 0.06, w: 5.0, h: 0.6, fontSize: 14, bold: true, color: NAVY, margin: 0, valign: "middle" });
  tb(s, r[1], { x: 5.9, y: yy + 0.06, w: 6.6, h: 0.6, fontSize: 13, color: GREEN, bold: true, margin: 0, valign: "middle" });
  yy += 0.82;
});

/* 11 — Gouvernance */
s = p.addSlide(); s.background = { color: WHITE }; titleBar(s, "Gouvernance & conformité", "EBIOS RM · NIS2 · DORA");
bullets(s, [
  "EBIOS RM : DoS → détection+bouclier+HA ; injection → WAF+intégrité ; panne → failover",
  "PCA/PRA : HA (bascule/retour auto) + remédiation zéro-touch = socle de continuité",
  "NIS2/DORA : détection & gestion d'incidents, résilience opérationnelle, journalisation, WAF",
  "Reco direction : adopter le module comme socle standard ; alertes cockpit → astreinte",
], { x: 0.8, y: 1.9, w: 12, h: 4.2 });

/* 12 — Équipe */
s = p.addSlide(); s.background = { color: WHITE }; titleBar(s, "L'équipe", "Contributions");
const team = [
  ["Téo Debay", "Architecture du module, passerelle, intégration"],
  ["Timéo Quehen", "Observabilité (Prometheus/Grafana/Loki), cockpit"],
  ["Hodari Bigwi", "Détection IA, orchestrateur de remédiation"],
  ["Théo Vambre", "Haute disponibilité, bascule/retour, infra"],
  ["Adrien Planquelle", "Sécurité (WAF), assistant RAG, démonstrateurs"],
];
yy = 1.9;
team.forEach((t) => {
  card(s, 0.6, yy, 12.1, 0.82, SOFT);
  tb(s, t[0], { x: 0.8, y: yy + 0.1, w: 3.6, h: 0.6, fontSize: 15, bold: true, color: PURPLE, margin: 0, valign: "middle" });
  tb(s, t[1], { x: 4.5, y: yy + 0.1, w: 8.0, h: 0.6, fontSize: 13, color: NAVY, margin: 0, valign: "middle" });
  yy += 0.92;
});

/* 13 — Clôture */
s = p.addSlide(); s.background = { color: NAVY };
tb(s, "Resilience Guard", { x: 0.8, y: 2.6, w: 11.7, h: 1.0, fontSize: 40, bold: true, color: WHITE, fontFace: HEAD, align: "center", margin: 0 });
tb(s, "Protéger, superviser et faire se relever n'importe quelle app — en une commande.", { x: 0.8, y: 3.7, w: 11.7, h: 0.6, fontSize: 18, color: LAV, align: "center", margin: 0 });
tb(s, "Merci — questions ?", { x: 0.8, y: 4.6, w: 11.7, h: 0.5, fontSize: 16, italic: true, color: LIGHT, align: "center", margin: 0 });
tb(s, "github.com/bigwihodari/Resilience-Alpha · module/README.md · données et attaques fictives", { x: 0.8, y: 6.7, w: 11.7, h: 0.4, fontSize: 11, color: LAV, align: "center", margin: 0 });

p.writeFile({ fileName: "Presentation-RESILIENCE-ALPHA.pptx" }).then((f) => console.log("OK:", f));
