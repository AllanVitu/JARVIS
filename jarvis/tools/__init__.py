"""Registre des outils de JARVIS.

Chaque module d'outils declare ses fonctions via `Registre.enregistrer`.
Le registre produit les definitions au format attendu par l'API Claude et
route les appels vers la bonne fonction Python.

Les outils marques `sensible=True` (commande shell, extinction, envoi de mail,
suppression) passent par une confirmation explicite avant de s'executer.
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Iterable

Gestionnaire = Callable[..., Any]
DemandeConfirmation = Callable[[str, str, dict[str, Any]], bool]


@dataclass
class Outil:
    nom: str
    description: str
    parametres: dict[str, Any]
    fonction: Gestionnaire
    sensible: bool = False
    # Resume lisible de l'action, montre a l'utilisateur avant confirmation.
    resume: Callable[[dict[str, Any]], str] | None = None

    def definition(self) -> dict[str, Any]:
        """Format attendu par l'API Claude.

        On n'active pas `strict` : le mode strict impose que toutes les
        proprietes figurent dans `required`, or la plupart de nos outils ont
        des arguments optionnels (limite, categorie, echeance...).
        """
        schema = dict(self.parametres)
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        schema.setdefault("required", [])
        return {
            "name": self.nom,
            "description": self.description,
            "input_schema": schema,
        }


class Registre:
    def __init__(self) -> None:
        self._outils: dict[str, Outil] = {}
        self.demander_confirmation: DemandeConfirmation | None = None
        self.confirmations_actives: bool = True

    # -------------------------------------------------------- enregistrement

    def enregistrer(
        self,
        nom: str,
        description: str,
        parametres: dict[str, Any],
        fonction: Gestionnaire,
        sensible: bool = False,
        resume: Callable[[dict[str, Any]], str] | None = None,
    ) -> None:
        if nom in self._outils:
            raise ValueError(f"Outil deja enregistre : {nom}")
        self._outils[nom] = Outil(
            nom=nom,
            description=description,
            parametres=parametres,
            fonction=fonction,
            sensible=sensible,
            resume=resume,
        )

    def noms(self) -> list[str]:
        return sorted(self._outils)

    def existe(self, nom: str) -> bool:
        return nom in self._outils

    def definitions(self, serveur: Iterable[dict[str, Any]] = ()) -> list[dict[str, Any]]:
        """Definitions des outils locaux, plus les outils serveur d'Anthropic
        (recherche web...) passes tels quels.

        L'ordre est deterministe : le prefixe de la requete reste stable d'un
        appel a l'autre, ce qui preserve le cache de prompt.
        """
        locales = [self._outils[nom].definition() for nom in sorted(self._outils)]
        return [*locales, *serveur]

    # ------------------------------------------------------------- execution

    def executer(self, nom: str, entree: dict[str, Any]) -> tuple[str, bool]:
        """Execute un outil. Renvoie (resultat_texte, est_une_erreur).

        Aucune exception ne remonte : une erreur d'outil doit revenir au
        modele sous forme de tool_result pour qu'il puisse se corriger.
        """
        outil = self._outils.get(nom)
        if outil is None:
            return (f"Outil inconnu : {nom}", True)

        if outil.sensible and self.confirmations_actives and self.demander_confirmation:
            libelle = outil.resume(entree) if outil.resume else nom
            if not self.demander_confirmation(nom, libelle, entree):
                return ("Action annulee : l'utilisateur a refuse la confirmation.", False)

        try:
            resultat = outil.fonction(**entree)
        except TypeError as err:
            return (f"Arguments invalides pour {nom} : {err}", True)
        except Exception as err:  # noqa: BLE001 - on rapporte tout au modele
            detail = traceback.format_exc(limit=3)
            return (f"Echec de {nom} : {err}\n{detail}", True)

        return (_en_texte(resultat), False)


def _en_texte(valeur: Any) -> str:
    if valeur is None:
        return "OK (aucun resultat)."
    if isinstance(valeur, str):
        return valeur
    try:
        return json.dumps(valeur, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return str(valeur)
