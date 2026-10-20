// Génère le deck de présentation PPTX — PROJECT RESILIENCE-ALPHA.
const pptxgen = require("pptxgenjs");
const p = new pptxgen();
p.layout = "LAYOUT_WIDE"; // 13.3 x 7.5
p.author = "Consortium Workshop2026-M2";
p.title = "PROJECT RESILIENCE-ALPHA";

const NAVY = "261E48", PURPLE = "4B3FA6", LAV = "A1A6D4", LIGHT = "E4E6F3",
      SOFT = "EEF0F8", WHITE = "FFFFFF", GREEN = "1E8E6A", RED = "C2413C", AMBER = "B8840F", MUT = "6A6594";
const HEAD = "Calibri", BODY = "Calibri";
const W = 13.333;

function tb(slide, text, opts) { slide.addText(text, Object.assign({ isTextBox: true, fontFace: BODY }, opts)); }
function titleBar(slide, t, kicker) {
  if (kicker) tb(slide, kicker.toUpperCase(), { x: 0.6, y: 0.45, w: 12, h: 0.3, fontSize: 12, bold: true, color: PURPLE, charSpacing: 2, margin: 0 });
  tb(slide, t, { x: 0.6, y: 0.72, w: 12.1, h: 0.7, fontSize: 30, bold: true, color: NAVY, fontFace: HEAD, margin: 0 });
}
function card(slide, x, y, w, h, fill) {
  slide.addShape(p.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line: { type: "none" }, shadow: { type: "outer", color: "888888", opacity: 0.25, blur: 6, offset: 2, angle: 90 } });
}

/* 1 — Couverture */
let s = p.addSlide(); s.background = { color: NAVY };
s.addShape(p.ShapeType.roundRect, { x: 0.8, y: 1.0, w: 2.6, h: 0.42, rectRadius: 0.2, fill: { color: PURPLE }, line: { type: "none" } });
tb(s, "WORKSHOP EPSI BAC+5", { x: 0.8, y: 1.02, w: 2.6, h: 0.38, fontSize: 11, bold: true, color: WHITE, align: "center", margin: 0 });
tb(s, "PROJECT RESILIENCE-ALPHA", { x: 0.8, y: 2.0, w: 11.7, h: 1.2, fontSize: 48, bold: true, color: WHITE, fontFace: HEAD, margin: 0 });
tb(s, "Cyber-résilience et reprise autonome d'une plateforme de paiement", { x: 0.8, y: 3.3, w: 11.5, h: 0.6, fontSize: 20, color: LAV, margin: 0 });
tb(s, "« Tout système finit par tomber. La vraie question : le vôtre saura-t-il se relever seul ? »", { x: 0.8, y: 4.3, w: 11, h: 0.6, fontSize: 14, italic: true, color: LIGHT, margin: 0 });
tb(s, "Équipe : Téo Debay · Timéo Quehen · Hodari Bigwi · Théo Vambre · Adrien Planquelle", { x: 0.8, y: 5.2, w: 11.7, h: 0.4, fontSize: 13, color: WHITE, margin: 0 });
tb(s, "Consortium Workshop2026-M2-G<n>  ·  Octobre 2026  ·  github.com/bigwihodari/Resilience-Alpha", { x: 0.8, y: 6.7, w: 11.7, h: 0.4, fontSize: 11, color: LAV, margin: 0 });

/* 2 — Le défi */
s = p.addSlide(); s.background = { color: WHITE };
titleBar(s, "Le défi en un coup d'œil", "Contexte & mission");
const defis = [
  ["💳", "Une plateforme de paiement fictive", "front, API, authentification, base de données — conteneurisée"],
  ["⚔️", "Une attaque réelle", "lancée depuis un poste distinct (déni de service, injection SQL)"],
  ["🧠", "Une détection par machine learning", "et non de simples seuils fixes"],
  ["🔁", "Une remédiation automatique", "preuve : une transaction réussit après l'incident"],
];
defis.forEach((d, i) => {
  const y = 1.7 + i * 1.25;
  card(s, 0.6, y, 12.1, 1.05, SOFT);
  tb(s, d[0], { x: 0.8, y: y + 0.1, w: 0.9, h: 0.85, fontSize: 30, align: "center", margin: 0 });
  tb(s, d[1], { x: 1.8, y: y + 0.14, w: 10.6, h: 0.45, fontSize: 16, bold: true, color: NAVY, margin: 0 });
  tb(s, d[2], { x: 1.8, y: y + 0.58, w: 10.6, h: 0.4, fontSize: 12.5, color: MUT, margin: 0 });
});
tb(s, "⚠ Toute intervention humaine pendant la démo = 0/5 sur l'axe remédiation.", { x: 0.6, y: 6.9, w: 12, h: 0.4, fontSize: 12, bold: true, color: RED, margin: 0 });

/* 3 — Architecture */
s = p.addSlide(); s.background = { color: WHITE };
titleBar(s, "Architecture : deux postes, une chaîne", "Infrastructure");
card(s, 0.6, 1.7, 6.0, 2.0, SOFT);
tb(s, "🖥️ PC HÔTE", { x: 0.8, y: 1.85, w: 5.6, h: 0.4, fontSize: 15, bold: true, color: NAVY, margin: 0 });
tb(s, "Plateforme + cockpit (une seule app)\nfrontend · api · auth · db · detector ML · orchestrateur · observabilité (Prometheus/Grafana/Loki)", { x: 0.8, y: 2.3, w: 5.6, h: 1.3, fontSize: 12.5, color: NAVY, margin: 0, lineSpacingMultiple: 1.1 });
card(s, 6.8, 1.7, 5.9, 2.0, "FBE8E6");
tb(s, "⚔️ PC ATTAQUANT", { x: 7.0, y: 1.85, w: 5.5, h: 0.4, fontSize: 15, bold: true, color: RED, margin: 0 });
tb(s, "Application unique dédiée\nConsole d'attaque (DoS, injection SQL) + indicateurs temps réel + liens vers la cible", { x: 7.0, y: 2.3, w: 5.5, h: 1.3, fontSize: 12.5, color: NAVY, margin: 0, lineSpacingMultiple: 1.1 });
tb(s, "Réseau Wi-Fi du groupe  ·  RESILIENCE-G<n>  ·  192.168.137.x", { x: 0.6, y: 3.95, w: 12, h: 0.4, fontSize: 12, bold: true, color: PURPLE, align: "center", margin: 0 });
card(s, 0.6, 4.6, 12.1, 2.2, NAVY);
tb(s, "Flux de résilience", { x: 0.9, y: 4.75, w: 11, h: 0.4, fontSize: 14, bold: true, color: WHITE, margin: 0 });
tb(s, "trafic + attaque  →  métriques & logs  →  détecteur ML (score)  →  orchestrateur (décision + action)  →  vérification canari  →  cockpit", { x: 0.9, y: 5.3, w: 11.5, h: 1.2, fontSize: 15, color: LIGHT, margin: 0, lineSpacingMultiple: 1.2 });

/* 3b — Interface banquier */
s = p.addSlide(); s.background = { color: WHITE };
titleBar(s, "Interface banquier : les comptes en temps réel", "App hôte · rôle banquier");
card(s, 0.6, 1.8, 6.0, 4.6, SOFT);
tb(s, "🏦 Ce que voit le banquier", { x: 0.85, y: 2.0, w: 5.5, h: 0.5, fontSize: 15, bold: true, color: NAVY, margin: 0 });
tb(s, "• Tous les comptes clients + leurs soldes\n• Masse monétaire totale\n• Créditer / débiter n'importe quel compte\n• Historique des mouvements par client\n• Mise à jour EN TEMPS RÉEL (WebSocket)\n  — aucun rafraîchissement manuel", { x: 0.85, y: 2.6, w: 5.5, h: 3.6, fontSize: 13.5, color: NAVY, margin: 0, lineSpacingMultiple: 1.3 });
card(s, 6.8, 1.8, 5.9, 4.6, "E3F3EC");
tb(s, "🔐 Accès strictement réservé", { x: 7.05, y: 2.0, w: 5.4, h: 0.5, fontSize: 15, bold: true, color: GREEN, margin: 0 });
tb(s, "• Rôle « banker » porté par le JWT\n• Endpoints /bank/* protégés\n• Un client normal reçoit 403 (vérifié)\n• Le banquier est exclu de l'annuaire\n  des clients", { x: 7.05, y: 2.6, w: 5.45, h: 3.0, fontSize: 13.5, color: NAVY, margin: 0, lineSpacingMultiple: 1.3 });
tb(s, "Compte de démo : banquier / password123", { x: 7.05, y: 5.7, w: 5.4, h: 0.5, fontSize: 14, bold: true, color: PURPLE, margin: 0 });

/* 3c — Attaquant multi-vecteurs */
s = p.addSlide(); s.background = { color: WHITE };
titleBar(s, "Attaquant : attaques multiples simultanées", "PC attaquant · 7 vecteurs");
tb(s, "7 vecteurs lançables un par un, à plusieurs, ou TOUS d'un coup (« tout lancer ») pour saturer et faire tomber le serveur principal — ce qui déclenche justement la bascule vers le secours.", { x: 0.6, y: 1.65, w: 12.1, h: 0.8, fontSize: 14, color: NAVY, margin: 0, lineSpacingMultiple: 1.15 });
const vecs = [
  ["🔑", "dos_auth", "flood de /auth/login (bcrypt coûteux)"],
  ["💉", "sqli", "injection SQL → WAF"],
  ["🌊", "api_flood", "charge l'API + la base"],
  ["📝", "xss", "injection → WAF"],
  ["🔓", "cred_stuffing", "bourrage d'identifiants"],
  ["🚫", "notfound_flood", "bruit de 404"],
  ["🐌", "slowloris", "connexions lentes maintenues ouvertes"],
];
vecs.forEach((v, i) => {
  const x = 0.6 + (i % 4) * 3.05, y = 2.55 + Math.floor(i / 4) * 1.78;
  card(s, x, y, 2.9, 1.6, SOFT);
  tb(s, v[0], { x: x + 0.15, y: y + 0.12, w: 1, h: 0.5, fontSize: 22, margin: 0 });
  tb(s, v[1], { x: x + 0.15, y: y + 0.66, w: 2.6, h: 0.35, fontSize: 13, bold: true, color: NAVY, margin: 0 });
  tb(s, v[2], { x: x + 0.15, y: y + 1.0, w: 2.6, h: 0.55, fontSize: 10.5, color: MUT, margin: 0, lineSpacingMultiple: 1.0 });
});
tb(s, "Statistiques par vecteur + agrégées · métriques Prometheus par vecteur.", { x: 0.6, y: 6.5, w: 12, h: 0.4, fontSize: 12.5, bold: true, color: PURPLE, margin: 0 });

/* 4 — Boucle autonome */
s = p.addSlide(); s.background = { color: WHITE };
titleBar(s, "La boucle autonome (zéro intervention)", "Le cœur du sujet");
const steps = [["1", "Attaque", "depuis le PC attaquant"], ["2", "Détection", "machine learning"], ["3", "Décision", "le bon playbook"], ["4", "Action", "bouclier / WAF"], ["5", "Vérification", "transaction canari"]];
steps.forEach((st, i) => {
  const x = 0.6 + i * 2.5;
  card(s, x, 2.3, 2.2, 2.2, i === 4 ? "E3F3EC" : SOFT);
  s.addShape(p.ShapeType.ellipse, { x: x + 0.8, y: 2.5, w: 0.6, h: 0.6, fill: { color: PURPLE }, line: { type: "none" } });
  tb(s, st[0], { x: x + 0.8, y: 2.52, w: 0.6, h: 0.56, fontSize: 20, bold: true, color: WHITE, align: "center", margin: 0 });
  tb(s, st[1], { x: x + 0.1, y: 3.25, w: 2.0, h: 0.4, fontSize: 15, bold: true, color: NAVY, align: "center", margin: 0 });
  tb(s, st[2], { x: x + 0.1, y: 3.7, w: 2.0, h: 0.6, fontSize: 11.5, color: MUT, align: "center", margin: 0 });
});
tb(s, "RTO mesuré : ~15 s entre la détection et le service rétabli.", { x: 0.6, y: 5.2, w: 12, h: 0.5, fontSize: 16, bold: true, color: GREEN, align: "center", margin: 0 });

/* 5 — Détection ML */
s = p.addSlide(); s.background = { color: WHITE };
titleBar(s, "Détection par machine learning", "IA / Data");
tb(s, "Un Isolation Forest apprend la « vie normale » (débit, erreurs) ; une distance standardisée à la normale déclenche l'alerte. Aucun seuil codé en dur.", { x: 0.6, y: 1.65, w: 12, h: 0.7, fontSize: 14, color: NAVY, margin: 0 });
s.addChart(p.ChartType.bar, [
  { name: "Latence auth p95 (ms)", labels: ["Normal", "Sous DoS"], values: [95, 490] },
], { x: 0.6, y: 2.6, w: 6.2, h: 4.0, barDir: "col", showTitle: true, title: "Latence auth p95 (ms)", titleColor: NAVY, titleFontSize: 14,
     showValue: true, dataLabelPosition: "outEnd", dataLabelColor: NAVY, dataLabelFontSize: 12,
     chartColors: [PURPLE], showLegend: false, valAxisHidden: true, catAxisLabelColor: NAVY, valGridLine: { style: "none" }, catGridLine: { style: "none" } });
card(s, 7.1, 2.6, 5.6, 1.85, SOFT);
tb(s, "Score d'anomalie", { x: 7.3, y: 2.75, w: 5.2, h: 0.4, fontSize: 13, bold: true, color: NAVY, margin: 0 });
tb(s, [{ text: "0", options: { color: GREEN, bold: true } }, { text: "  →  ", options: { color: MUT } }, { text: "100", options: { color: RED, bold: true } }], { x: 7.3, y: 3.2, w: 5.2, h: 0.9, fontSize: 44, align: "center", margin: 0 });
tb(s, "normal → anomalie détectée", { x: 7.3, y: 4.05, w: 5.2, h: 0.3, fontSize: 12, color: MUT, align: "center", margin: 0 });
card(s, 7.1, 4.7, 5.6, 1.9, SOFT);
tb(s, "Débit auth sous attaque : ×30   ·   Latence : ×5", { x: 7.3, y: 4.9, w: 5.2, h: 0.5, fontSize: 14, bold: true, color: NAVY, margin: 0 });
tb(s, "Modèle persisté (pas de ré-apprentissage au redémarrage). Assistant RAG local (Ollama + LangChain) pour aider l'opérateur.", { x: 7.3, y: 5.4, w: 5.2, h: 1.1, fontSize: 12.5, color: NAVY, margin: 0, lineSpacingMultiple: 1.1 });

/* 6 — Remédiation */
s = p.addSlide(); s.background = { color: WHITE };
titleBar(s, "Deux incidents, deux réponses", "Remédiation autonome");
card(s, 0.6, 1.8, 6.0, 4.6, "E3F3EC");
tb(s, "🌊 Déni de service → DISPONIBILITÉ", { x: 0.85, y: 2.0, w: 5.5, h: 0.5, fontSize: 15, bold: true, color: GREEN, margin: 0 });
tb(s, "• Détection ML (débit, latence, erreurs)\n• Bouclier anti-DoS (load-shedding) sur l'auth\n• Vérification par transaction canari\n• Relâche automatique en fin d'attaque", { x: 0.85, y: 2.6, w: 5.5, h: 3.5, fontSize: 14, color: NAVY, margin: 0, lineSpacingMultiple: 1.3 });
card(s, 6.8, 1.8, 5.9, 4.6, "FBE8E6");
tb(s, "💉 Injection SQL → COMPROMISSION", { x: 7.05, y: 2.0, w: 5.4, h: 0.5, fontSize: 15, bold: true, color: RED, margin: 0 });
tb(s, "• Blocage par le WAF applicatif (403)\n• Contrôle d'intégrité des données\n• Restauration d'un état sain si altération\n• Vérification : aucune donnée altérée", { x: 7.05, y: 2.6, w: 5.4, h: 3.5, fontSize: 14, color: NAVY, margin: 0, lineSpacingMultiple: 1.3 });
tb(s, "Accès maîtrisés : l'orchestrateur agit via une API d'administration scoped (pas d'accès god-mode aux conteneurs).", { x: 0.6, y: 6.6, w: 12, h: 0.5, fontSize: 12.5, bold: true, color: PURPLE, margin: 0 });

/* 6b — Haute disponibilité */
s = p.addSlide(); s.background = { color: WHITE };
titleBar(s, "Haute disponibilité : le service ne tombe pas", "Montage 5 PC");
card(s, 0.6, 1.8, 6.0, 4.5, SOFT);
tb(s, "🖥️ Topologie", { x: 0.85, y: 1.98, w: 5.5, h: 0.45, fontSize: 15, bold: true, color: NAVY, margin: 0 });
tb(s, "• HOST-PRINCIPAL : serveur + cockpit\n• HOST-BACKUP : réplique le principal\n  (comptes + clés d'idempotence)\n• CLIENT-A / CLIENT-B : app de paiement\n  (login + recherche + transfert)\n• ATTAQUANT : vise le principal", { x: 0.85, y: 2.5, w: 5.55, h: 3.6, fontSize: 13.5, color: NAVY, margin: 0, lineSpacingMultiple: 1.25 });
card(s, 6.8, 1.8, 5.9, 4.5, "E3F3EC");
tb(s, "🔁 Bascule & reprise", { x: 7.05, y: 1.98, w: 5.4, h: 0.45, fontSize: 15, bold: true, color: GREEN, margin: 0 });
tb(s, "1. Le serveur principal tombe\n2. Le client bascule AUTOMATIQUEMENT sur le backup\n3. La transaction en cours est REPRISE\n   (clé d'idempotence) — sans double débit\n4. Service maintenu, zéro intervention", { x: 7.05, y: 2.5, w: 5.45, h: 3.0, fontSize: 13.5, color: NAVY, margin: 0, lineSpacingMultiple: 1.3 });
tb(s, "Recette failover : 13 / 13 ✓", { x: 7.05, y: 5.7, w: 5.4, h: 0.5, fontSize: 15, bold: true, color: GREEN, margin: 0 });

/* 6c — Continuité : failover → failback */
s = p.addSlide(); s.background = { color: WHITE };
titleBar(s, "Continuité prouvée : failover → failback", "Haute dispo · essai vérifié");
card(s, 0.6, 1.75, 6.0, 3.2, "FBE8E6");
tb(s, "⬇️ Bascule (failover)", { x: 0.85, y: 1.92, w: 5.5, h: 0.45, fontSize: 15, bold: true, color: RED, margin: 0 });
tb(s, "• 3 échecs de réplication consécutifs (2 s)\n• Le SECOURS est promu automatiquement\n• Les clients basculent via nginx (upstream)\n• Clés d'idempotence → reprise exactly-once\n  (pas de double débit)\n• Le cockpit hôte reste vivant (son nginx\n  bascule aussi)", { x: 0.85, y: 2.42, w: 5.55, h: 2.5, fontSize: 12.5, color: NAVY, margin: 0, lineSpacingMultiple: 1.25 });
card(s, 6.8, 1.75, 5.9, 3.2, "E3F3EC");
tb(s, "⬆️ Retour (failback)", { x: 7.05, y: 1.92, w: 5.4, h: 0.45, fontSize: 15, bold: true, color: GREEN, margin: 0 });
tb(s, "• Le principal se répare\n• Le secours lui REJOUE son état\n  (réconciliation — rien de perdu)\n• Puis repasse en mode réplication\n• Le principal reprend la main", { x: 7.05, y: 2.42, w: 5.45, h: 2.5, fontSize: 12.5, color: NAVY, margin: 0, lineSpacingMultiple: 1.25 });
card(s, 0.6, 5.15, 12.1, 1.75, NAVY);
tb(s, "Essai bout en bout — la preuve", { x: 0.9, y: 5.3, w: 11.5, h: 0.4, fontSize: 14, bold: true, color: WHITE, margin: 0 });
tb(s, [{ text: "PRINCIPAL sert → arrêt → ~6–11 s : SECOURS promu → crédit de 50 € PENDANT la panne (", options: { color: LIGHT } }, { text: "787 € → 837 €", options: { color: WHITE, bold: true } }, { text: ") → redémarrage → ~15 s : retour au PRINCIPAL, solde lu = ", options: { color: LIGHT } }, { text: "837 €", options: { color: WHITE, bold: true } }, { text: "  ·  aucune transaction perdue", options: { color: LIGHT } }], { x: 0.9, y: 5.75, w: 11.5, h: 1.0, fontSize: 14, margin: 0, lineSpacingMultiple: 1.2 });

/* 7 — Sécurité */
s = p.addSlide(); s.background = { color: WHITE };
titleBar(s, "Défense & sécurité", "Cybersécurité");
const secu = [["🛡️", "WAF applicatif", "SQLi/XSS bloqués (403) + métrique + log"], ["📊", "Fonction SOC", "Loki + Prometheus + vue SOC du cockpit"], ["🔑", "Secrets", "chiffrés (SOPS + age), rien en clair"], ["🔒", "Durcissement", "no-new-privileges, base non exposée"], ["🧩", "Moindre privilège", "token d'admin dédié à l'orchestrateur"], ["📈", "Observabilité", "métriques & logs exploitables"]];
secu.forEach((d, i) => {
  const x = 0.6 + (i % 3) * 4.1, y = 1.9 + Math.floor(i / 3) * 2.3;
  card(s, x, y, 3.9, 2.0, SOFT);
  tb(s, d[0], { x: x + 0.2, y: y + 0.2, w: 1, h: 0.6, fontSize: 26, margin: 0 });
  tb(s, d[1], { x: x + 0.2, y: y + 0.85, w: 3.5, h: 0.4, fontSize: 15, bold: true, color: NAVY, margin: 0 });
  tb(s, d[2], { x: x + 0.2, y: y + 1.25, w: 3.5, h: 0.65, fontSize: 12, color: MUT, margin: 0 });
});

/* 8 — Résultats */
s = p.addSlide(); s.background = { color: WHITE };
titleBar(s, "Preuves de fonctionnement", "Recette & essais");
const kpis = [["15/15", "vérifications de recette"], ["~15 s", "RTO détection → reprise"], ["100 %", "reprise sans humain"], ["748", "requêtes bloquées (WAF)"]];
kpis.forEach((k, i) => {
  const x = 0.6 + i * 3.1;
  card(s, x, 1.8, 2.9, 1.9, NAVY);
  tb(s, k[0], { x, y: 2.05, w: 2.9, h: 0.9, fontSize: 36, bold: true, color: WHITE, align: "center", margin: 0 });
  tb(s, k[1], { x: x + 0.1, y: 2.95, w: 2.7, h: 0.6, fontSize: 12, color: LAV, align: "center", margin: 0 });
});
const checks = ["Services opérationnels + modèle ML entraîné", "DoS → reprise autonome + bouclier actif", "Transaction réussie PENDANT l'attaque", "Injection SQL contenue par le WAF", "Intégrité des données confirmée", "Transaction finale réussie après incidents"];
checks.forEach((c, i) => {
  const y = 4.1 + i * 0.52;
  tb(s, [{ text: "✓  ", options: { color: GREEN, bold: true } }, { text: c, options: { color: NAVY } }], { x: 0.8, y, w: 12, h: 0.45, fontSize: 14, margin: 0 });
});

/* 9 — Gouvernance */
s = p.addSlide(); s.background = { color: WHITE };
titleBar(s, "Gouvernance & conformité", "Transformation");
const gov = [["EBIOS RM", "Risques reliés à l'architecture et aux attaques réellement testées"], ["PCA / PRA", "Services vitaux, RTO ~15 s mesuré, 2 playbooks, responsabilités"], ["NIS2 / DORA", "Exigences pertinentes vs non démontrables en 4 jours"]];
gov.forEach((g, i) => {
  const y = 1.9 + i * 1.3;
  card(s, 0.6, y, 12.1, 1.1, SOFT);
  tb(s, g[0], { x: 0.85, y: y + 0.18, w: 3, h: 0.7, fontSize: 16, bold: true, color: PURPLE, margin: 0 });
  tb(s, g[1], { x: 3.9, y: y + 0.2, w: 8.6, h: 0.75, fontSize: 13.5, color: NAVY, margin: 0, valign: "middle" });
});
tb(s, "Recommandations : industrialiser la reprise (HA + WAF réseau) · formaliser la notification d'incident · tests de résilience réguliers.", { x: 0.6, y: 6.0, w: 12, h: 0.9, fontSize: 13.5, bold: true, color: NAVY, margin: 0, lineSpacingMultiple: 1.2 });

/* 9b — Jeu de hacker : compromission -> blocage -> bascule */
s = p.addSlide(); s.background = { color: WHITE };
titleBar(s, "Jeu de hacker : voler… ou se faire bloquer", "Démonstration interactive");
tb(s, "Zone « Reconnaissance / Opération » ajoutée à la console attaquant : un jeu d'équilibre.", { x: 0.6, y: 1.5, w: 12.1, h: 0.4, fontSize: 13.5, color: MUT, margin: 0 });
const jeu = [
  ["🔍", "Reconnaissance discrète", "fuite progressive : comptes, soldes approximatifs, livret d'épargne"],
  ["💡", "Astuces débloquées", "au minuteur (compte à rebours) ET à chaque attaque réussie"],
  ["💰", "Vol plafonné", "retrait atomique, jamais négatif, plafonné par coup et en cumulé"],
  ["🧠", "Détection IA + réponse", "butin anormal ou attaque trop forte → blocage (cooldown)"],
  ["🛡️", "Bascule secours + butin annulé", "l'argent volé ne « gagne » pas si l'IA bascule à temps"],
];
jeu.forEach((d, i) => {
  const y = 2.0 + i * 0.97;
  card(s, 0.6, y, 12.1, 0.82, SOFT);
  tb(s, d[0], { x: 0.8, y: y + 0.12, w: 0.8, h: 0.6, fontSize: 24, align: "center", margin: 0 });
  tb(s, d[1], { x: 1.7, y: y + 0.11, w: 10.7, h: 0.35, fontSize: 14.5, bold: true, color: NAVY, margin: 0 });
  tb(s, d[2], { x: 1.7, y: y + 0.46, w: 10.7, h: 0.3, fontSize: 11.5, color: MUT, margin: 0 });
});
tb(s, "Doser : jouer discret rapporte un petit butin ; forcer déclenche le blocage, la bascule et la restauration.", { x: 0.6, y: 6.95, w: 12.1, h: 0.4, fontSize: 12, bold: true, color: PURPLE, margin: 0 });

/* 10 — Conclusion */
s = p.addSlide(); s.background = { color: NAVY };
tb(s, "À vous de jouer", { x: 0.8, y: 2.2, w: 11.7, h: 1.0, fontSize: 40, bold: true, color: WHITE, fontFace: HEAD, margin: 0 });
tb(s, "Attaquez le système, laissez-le se défendre, et prouvez qu'il se relève seul.", { x: 0.8, y: 3.4, w: 11.5, h: 0.6, fontSize: 18, color: LAV, margin: 0 });
tb(s, "Détection ML  ·  Remédiation zero-touch  ·  Preuve par transaction  ·  5 piliers interconnectés", { x: 0.8, y: 4.3, w: 11.5, h: 0.5, fontSize: 14, italic: true, color: LIGHT, margin: 0 });
tb(s, "github.com/bigwihodari/Resilience-Alpha", { x: 0.8, y: 6.7, w: 11.7, h: 0.4, fontSize: 12, color: LAV, margin: 0 });

p.writeFile({ fileName: "Presentation-RESILIENCE-ALPHA.pptx" }).then(f => console.log("OK:", f));
