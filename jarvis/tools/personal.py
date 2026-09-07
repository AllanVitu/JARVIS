"""Outils personnels : memoire long terme et liste de taches.

La memoire est ce qui differencie JARVIS d'un chatbot sans etat : il retient
tes preferences, ton contexte et tes habitudes d'une session a l'autre.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..memory import Memoire
from . import Registre


def enregistrer(registre: Registre, memoire: Memoire) -> None:
    # ------------------------------------------------------------- memoire

    def retenir(fait: str, categorie: str = "general") -> str:
        identifiant = memoire.retenir(fait, categorie)
        return f"Retenu (#{identifiant}, categorie '{categorie}') : {fait}"

    def rappeler(requete: str = "", limite: int = 10) -> dict[str, Any]:
        resultats = memoire.rappeler(requete, limite)
        return {
            "requete": requete or "(faits les plus recents)",
            "nombre": len(resultats),
            "faits": [
                {
                    "id": f["id"],
                    "contenu": f["contenu"],
                    "categorie": f["categorie"],
                    "depuis": f["cree_le"][:10],
                }
                for f in resultats
            ],
        }

    def oublier(fait_id: int) -> str:
        if memoire.oublier(fait_id):
            return f"Fait #{fait_id} supprime de la memoire."
        return f"Aucun fait #{fait_id} en memoire."

    registre.enregistrer(
        "retenir",
        "Memorise durablement une information sur l'utilisateur : preference, "
        "habitude, contexte personnel, projet en cours, date importante. "
        "Utilise-le des que tu apprends quelque chose qui resservira plus tard.",
        {"properties": {
            "fait": {
                "type": "string",
                "description": "Le fait a retenir, formule de facon autonome "
                               "et comprehensible hors contexte.",
            },
            "categorie": {
                "type": "string",
                "description": "Ex : preferences, travail, famille, sante, "
                               "technique, projets.",
            },
        }, "required": ["fait"]},
        retenir,
    )

    registre.enregistrer(
        "rappeler",
        "Cherche dans la memoire long terme. Laisse la requete vide pour voir "
        "les faits les plus recents.",
        {"properties": {
            "requete": {"type": "string", "description": "Mots-cles de recherche"},
            "limite": {"type": "integer"},
        }, "required": []},
        rappeler,
    )

    registre.enregistrer(
        "oublier",
        "Supprime un fait de la memoire a partir de son identifiant.",
        {"properties": {"fait_id": {"type": "integer"}}, "required": ["fait_id"]},
        oublier,
        sensible=True,
        resume=lambda e: f"Effacer definitivement le fait #{e.get('fait_id')} de la memoire",
    )

    # -------------------------------------------------------------- taches

    def ajouter_tache(
        titre: str,
        detail: str = "",
        echeance: str = "",
        priorite: str = "normale",
    ) -> str:
        identifiant = memoire.ajouter_tache(
            titre, detail or None, echeance or None, priorite
        )
        suffixe = f" (echeance {echeance})" if echeance else ""
        return f"Tache #{identifiant} ajoutee : {titre}{suffixe}"

    def lister_taches(inclure_terminees: bool = False) -> dict[str, Any]:
        taches = memoire.lister_taches(inclure_terminees)
        return {
            "nombre": len(taches),
            "aujourdhui": datetime.now().strftime("%Y-%m-%d"),
            "taches": [
                {
                    "id": t["id"],
                    "titre": t["titre"],
                    "detail": t["detail"],
                    "echeance": t["echeance"],
                    "priorite": t["priorite"],
                    "terminee": bool(t["terminee"]),
                }
                for t in taches
            ],
        }

    def terminer_tache(tache_id: int) -> str:
        if memoire.terminer_tache(tache_id):
            return f"Tache #{tache_id} marquee comme terminee."
        return f"Aucune tache #{tache_id} en cours."

    def supprimer_tache(tache_id: int) -> str:
        if memoire.supprimer_tache(tache_id):
            return f"Tache #{tache_id} supprimee."
        return f"Aucune tache #{tache_id}."

    registre.enregistrer(
        "ajouter_tache",
        "Ajoute une tache a la liste de choses a faire.",
        {"properties": {
            "titre": {"type": "string"},
            "detail": {"type": "string"},
            "echeance": {
                "type": "string",
                "description": "Date au format AAAA-MM-JJ, ou AAAA-MM-JJ HH:MM.",
            },
            "priorite": {"type": "string", "enum": ["basse", "normale", "haute"]},
        }, "required": ["titre"]},
        ajouter_tache,
    )

    registre.enregistrer(
        "lister_taches",
        "Liste les taches en cours (ou toutes, terminees comprises).",
        {"properties": {"inclure_terminees": {"type": "boolean"}}, "required": []},
        lister_taches,
    )

    registre.enregistrer(
        "terminer_tache",
        "Marque une tache comme terminee.",
        {"properties": {"tache_id": {"type": "integer"}}, "required": ["tache_id"]},
        terminer_tache,
    )

    registre.enregistrer(
        "supprimer_tache",
        "Supprime definitivement une tache de la liste.",
        {"properties": {"tache_id": {"type": "integer"}}, "required": ["tache_id"]},
        supprimer_tache,
        sensible=True,
        resume=lambda e: f"Supprimer definitivement la tache #{e.get('tache_id')}",
    )
