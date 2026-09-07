"""Memoire persistante de JARVIS : faits durables, taches et historique.

Tout est stocke dans un unique fichier SQLite (`data/jarvis.db`), local a la
machine. Rien ne part sur le reseau en dehors des appels a l'API Claude.
"""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS faits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contenu     TEXT    NOT NULL,
    categorie   TEXT    NOT NULL DEFAULT 'general',
    cree_le     TEXT    NOT NULL,
    vu_le       TEXT,
    occurrences INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS taches (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    titre     TEXT    NOT NULL,
    detail    TEXT,
    echeance  TEXT,
    priorite  TEXT    NOT NULL DEFAULT 'normale',
    terminee  INTEGER NOT NULL DEFAULT 0,
    cree_le   TEXT    NOT NULL,
    fini_le   TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    session  TEXT NOT NULL,
    role     TEXT NOT NULL,
    contenu  TEXT NOT NULL,
    cree_le  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session);
CREATE INDEX IF NOT EXISTS idx_faits_categorie ON faits(categorie);
"""

MOTS_VIDES = {
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "au",
    "aux", "en", "que", "qui", "quoi", "est", "sont", "je", "tu", "il", "elle",
    "mon", "ma", "mes", "ton", "ta", "tes", "ce", "cette", "pour", "dans",
    "sur", "avec", "quel", "quelle", "quels", "quelles", "moi", "se",
}


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sans_accents(texte: str) -> str:
    """Normalise pour que "prefere" matche "prefere" ecrit avec accents."""
    decompose = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


class Memoire:
    def __init__(self, chemin: Path) -> None:
        self.chemin = Path(chemin)
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self.cx = sqlite3.connect(self.chemin, check_same_thread=False)
        self.cx.row_factory = sqlite3.Row
        self.cx.executescript(SCHEMA)
        self.cx.commit()

    # ------------------------------------------------------------------ faits

    def retenir(self, contenu: str, categorie: str = "general") -> int:
        """Enregistre un fait. Si un fait identique existe deja, on incremente
        son compteur plutot que de creer un doublon."""
        contenu = contenu.strip()
        if not contenu:
            raise ValueError("Un fait ne peut pas etre vide.")

        existant = self.cx.execute(
            "SELECT id FROM faits WHERE lower(contenu) = lower(?)", (contenu,)
        ).fetchone()
        if existant:
            self.cx.execute(
                "UPDATE faits SET occurrences = occurrences + 1, vu_le = ? WHERE id = ?",
                (_maintenant(), existant["id"]),
            )
            self.cx.commit()
            return int(existant["id"])

        cur = self.cx.execute(
            "INSERT INTO faits (contenu, categorie, cree_le, vu_le) VALUES (?, ?, ?, ?)",
            (contenu, categorie.strip() or "general", _maintenant(), _maintenant()),
        )
        self.cx.commit()
        return int(cur.lastrowid)

    def rappeler(self, requete: str = "", limite: int = 12) -> list[dict[str, Any]]:
        """Recherche par mots-cles. Sans requete, renvoie les faits les plus
        recents. Le score privilegie le nombre de mots-cles trouves."""
        lignes = self.cx.execute("SELECT * FROM faits").fetchall()
        if not requete.strip():
            recents = sorted(lignes, key=lambda r: r["cree_le"], reverse=True)
            return [dict(r) for r in recents[:limite]]

        mots = [
            m for m in _sans_accents(requete).split()
            if len(m) > 2 and m not in MOTS_VIDES
        ]
        if not mots:
            mots = _sans_accents(requete).split()

        scores: list[tuple[int, sqlite3.Row]] = []
        for ligne in lignes:
            corpus = _sans_accents(f"{ligne['contenu']} {ligne['categorie']}")
            score = sum(1 for m in mots if m in corpus)
            if score:
                scores.append((score, ligne))

        scores.sort(key=lambda paire: (paire[0], paire[1]["cree_le"]), reverse=True)
        return [dict(ligne) for _, ligne in scores[:limite]]

    def oublier(self, fait_id: int) -> bool:
        cur = self.cx.execute("DELETE FROM faits WHERE id = ?", (fait_id,))
        self.cx.commit()
        return cur.rowcount > 0

    def tous_les_faits(self, limite: int = 60) -> list[dict[str, Any]]:
        lignes = self.cx.execute(
            "SELECT * FROM faits ORDER BY occurrences DESC, cree_le DESC LIMIT ?",
            (limite,),
        ).fetchall()
        return [dict(r) for r in lignes]

    # ----------------------------------------------------------------- taches

    def ajouter_tache(
        self,
        titre: str,
        detail: str | None = None,
        echeance: str | None = None,
        priorite: str = "normale",
    ) -> int:
        cur = self.cx.execute(
            "INSERT INTO taches (titre, detail, echeance, priorite, cree_le)"
            " VALUES (?, ?, ?, ?, ?)",
            (titre.strip(), detail, echeance, priorite, _maintenant()),
        )
        self.cx.commit()
        return int(cur.lastrowid)

    def lister_taches(self, inclure_terminees: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM taches"
        if not inclure_terminees:
            sql += " WHERE terminee = 0"
        sql += " ORDER BY terminee, COALESCE(echeance, '9999'), cree_le"
        return [dict(r) for r in self.cx.execute(sql).fetchall()]

    def terminer_tache(self, tache_id: int) -> bool:
        cur = self.cx.execute(
            "UPDATE taches SET terminee = 1, fini_le = ? WHERE id = ? AND terminee = 0",
            (_maintenant(), tache_id),
        )
        self.cx.commit()
        return cur.rowcount > 0

    def supprimer_tache(self, tache_id: int) -> bool:
        cur = self.cx.execute("DELETE FROM taches WHERE id = ?", (tache_id,))
        self.cx.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------- historique

    def ajouter_message(self, session: str, role: str, contenu: Any) -> None:
        self.cx.execute(
            "INSERT INTO messages (session, role, contenu, cree_le) VALUES (?, ?, ?, ?)",
            (session, role, json.dumps(contenu, ensure_ascii=False), _maintenant()),
        )
        self.cx.commit()

    def dernieres_sessions(self, limite: int = 4) -> list[str]:
        lignes = self.cx.execute(
            "SELECT session, MAX(cree_le) AS dernier FROM messages"
            " GROUP BY session ORDER BY dernier DESC LIMIT ?",
            (limite,),
        ).fetchall()
        return [r["session"] for r in lignes]

    def resume_derniere_session(self, session_actuelle: str, limite: int = 6) -> str:
        """Quelques echanges de la session precedente, en texte brut, pour
        redonner a JARVIS le fil de la derniere conversation."""
        precedentes = [s for s in self.dernieres_sessions(4) if s != session_actuelle]
        if not precedentes:
            return ""

        lignes = self.cx.execute(
            "SELECT role, contenu FROM messages WHERE session = ?"
            " ORDER BY id DESC LIMIT ?",
            (precedentes[0], limite),
        ).fetchall()

        morceaux: list[str] = []
        for ligne in reversed(lignes):
            try:
                brut = json.loads(ligne["contenu"])
            except json.JSONDecodeError:
                continue
            texte = brut if isinstance(brut, str) else ""
            if texte:
                qui = "Toi" if ligne["role"] == "user" else "Moi"
                morceaux.append(f"{qui}: {texte[:200]}")
        return "\n".join(morceaux)

    def fermer(self) -> None:
        self.cx.close()
