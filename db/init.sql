-- Schéma du SI de paiement fictif (données entièrement fictives).
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(64) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(16) NOT NULL DEFAULT 'client',  -- client | banker
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS accounts (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    balance    NUMERIC(14,2) NOT NULL DEFAULT 0,
    savings    NUMERIC(14,2) NOT NULL DEFAULT 0,   -- livret d'epargne
    currency   VARCHAR(3) NOT NULL DEFAULT 'EUR',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Livrets d'epargne SUPPLEMENTAIRES (le principal reste accounts.savings).
-- Chaque livret produit des interets a son propre taux (jeu idle).
CREATE TABLE IF NOT EXISTS livrets (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       VARCHAR(40) NOT NULL DEFAULT 'Livret',
    balance    NUMERIC(14,2) NOT NULL DEFAULT 0,
    rate       NUMERIC(6,4) NOT NULL DEFAULT 0,
    level      INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ameliorations achetees au shop (coSts exponentiels), par utilisateur/cle.
CREATE TABLE IF NOT EXISTS upgrades (
    id      SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ukey    VARCHAR(32) NOT NULL,
    level   INTEGER NOT NULL DEFAULT 0,
    UNIQUE (user_id, ukey)
);

-- Destinataires favoris (paiement en un clic, sans recherche).
CREATE TABLE IF NOT EXISTS favorites (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fav_username VARCHAR(64) NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, fav_username)
);

-- P2 — boite mail in-app (annonces banque, lots, enchAres).
CREATE TABLE IF NOT EXISTS mail (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject    VARCHAR(140) NOT NULL,
    body       VARCHAR(2000) NOT NULL DEFAULT '',
    kind       VARCHAR(16) NOT NULL DEFAULT 'info',   -- info|auction|quiz|prize|phishing
    is_read    INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- P2 — encheres officielles (banque). A la cloture : plus offrant debite de sa
-- mise et credite de la VALEUR de l'objet (gain net = valeur - mise).
CREATE TABLE IF NOT EXISTS auctions (
    id          SERIAL PRIMARY KEY,
    title       VARCHAR(140) NOT NULL,
    item_value  NUMERIC(14,2) NOT NULL,
    min_bid     NUMERIC(14,2) NOT NULL DEFAULT 0,
    status      VARCHAR(12) NOT NULL DEFAULT 'open',   -- open|closed
    created_by  VARCHAR(64) NOT NULL,
    winner      VARCHAR(64),
    winning_bid NUMERIC(14,2),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bids (
    id         SERIAL PRIMARY KEY,
    auction_id INTEGER NOT NULL REFERENCES auctions(id) ON DELETE CASCADE,
    username   VARCHAR(64) NOT NULL,
    amount     NUMERIC(14,2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- P2 — quiz du banquier : 1re bonne reponse gagne le lot (credite, banquier-funded).
CREATE TABLE IF NOT EXISTS quizzes (
    id         SERIAL PRIMARY KEY,
    question   VARCHAR(500) NOT NULL,
    answer     VARCHAR(140) NOT NULL,
    prize      NUMERIC(14,2) NOT NULL,
    status     VARCHAR(12) NOT NULL DEFAULT 'open',   -- open|closed
    winner     VARCHAR(64),
    created_by VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS transactions (
    id         SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    amount     NUMERIC(14,2) NOT NULL,
    type       VARCHAR(16) NOT NULL DEFAULT 'debit',
    recipient  VARCHAR(128),
    status     VARCHAR(16) NOT NULL DEFAULT 'completed',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tx_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_tx_created ON transactions(created_at);
