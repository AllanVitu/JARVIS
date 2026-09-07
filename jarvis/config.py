"""Configuration centrale de JARVIS.

Tout se regle via le fichier `.env` a la racine du projet (voir `.env.example`).
Les valeurs ci-dessous sont les defauts utilises si la variable n'est pas definie.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parent.parent
load_dotenv(RACINE / ".env")


def _bool(nom: str, defaut: bool) -> bool:
    brut = os.getenv(nom)
    if brut is None:
        return defaut
    return brut.strip().lower() in {"1", "true", "yes", "oui", "on"}


def _int(nom: str, defaut: int) -> int:
    try:
        return int(os.getenv(nom, "").strip())
    except (ValueError, AttributeError):
        return defaut


def _float(nom: str, defaut: float, mini: float = 0.0, maxi: float = 1e9) -> float:
    """Une valeur illisible ou aberrante dans le .env ne doit pas empecher
    JARVIS de demarrer : on retombe sur le defaut en le signalant."""
    brut = (os.getenv(nom) or "").strip()
    if not brut:
        return defaut
    try:
        valeur = float(brut.replace(",", "."))
    except ValueError:
        print(f"[config] {nom}='{brut}' n'est pas un nombre, defaut {defaut} utilise.")
        return defaut
    if not mini <= valeur <= maxi:
        print(f"[config] {nom}={valeur} hors bornes [{mini}, {maxi}], "
              f"defaut {defaut} utilise.")
        return defaut
    return valeur


EFFORTS_VALIDES = {"low", "medium", "high", "xhigh", "max"}


def _effort(defaut: str = "medium") -> str:
    """Un effort invalide part en erreur 400 cote API, avec un message
    peu parlant : on le rattrape ici."""
    valeur = (os.getenv("JARVIS_EFFORT") or defaut).strip().lower()
    if valeur not in EFFORTS_VALIDES:
        print(f"[config] JARVIS_EFFORT='{valeur}' inconnu "
              f"({', '.join(sorted(EFFORTS_VALIDES))}), defaut {defaut} utilise.")
        return defaut
    return valeur


@dataclass
class Config:
    # --- Identite ---
    nom_assistant: str = os.getenv("JARVIS_NAME", "Jarvis")
    nom_utilisateur: str = os.getenv("USER_NAME", "Monsieur")

    # --- Modele Claude ---
    modele: str = os.getenv("JARVIS_MODEL", "claude-opus-5")
    # `effort` arbitre profondeur de raisonnement contre latence.
    # Pour un assistant vocal, "medium" donne des reponses vives ;
    # passe a "high" pour les taches complexes.
    effort: str = _effort("medium")
    max_tokens: int = _int("JARVIS_MAX_TOKENS", 8000)
    # Nombre max d'allers-retours d'outils avant de rendre la main.
    max_tours_outils: int = _int("JARVIS_MAX_TOOL_TURNS", 25)

    # --- Voix ---
    voix_activee: bool = _bool("JARVIS_VOICE", True)
    mot_reveil: str = os.getenv("JARVIS_WAKE_WORD", "jarvis").lower()
    voix_tts: str = os.getenv("JARVIS_TTS_VOICE", "fr-FR-HenriNeural")
    vitesse_tts: str = os.getenv("JARVIS_TTS_RATE", "+8%")
    modele_whisper: str = os.getenv("JARVIS_WHISPER_MODEL", "small")
    langue: str = os.getenv("JARVIS_LANG", "fr")
    # Duree de silence (secondes) qui marque la fin d'une phrase.
    silence_fin_phrase: float = _float("JARVIS_SILENCE", 0.9, 0.2, 5.0)
    # Seuil d'energie du micro : monte-le si la piece est bruyante.
    seuil_micro: float = _float("JARVIS_MIC_THRESHOLD", 0.015, 0.001, 0.5)
    # Apres une reponse, JARVIS ecoute la suite sans mot de reveil pendant N s.
    fenetre_conversation: float = _float("JARVIS_FOLLOWUP_WINDOW", 12.0, 0.0, 300.0)

    # --- Securite ---
    # Les outils sensibles demandent une confirmation explicite.
    confirmer_actions_sensibles: bool = _bool("JARVIS_CONFIRM", True)
    # Repertoires ou JARVIS peut lire/chercher des fichiers.
    dossiers_autorises: list[str] = field(
        default_factory=lambda: [
            d.strip()
            for d in os.getenv("JARVIS_ALLOWED_DIRS", str(Path.home())).split(";")
            if d.strip()
        ]
    )

    # --- Chemins ---
    racine: Path = RACINE
    dossier_donnees: Path = RACINE / "data"

    @property
    def base_memoire(self) -> Path:
        return self.dossier_donnees / "jarvis.db"

    @property
    def credentials_google(self) -> Path:
        return self.racine / "credentials.json"

    @property
    def token_google(self) -> Path:
        return self.racine / "token.json"

    def cle_api_presente(self) -> bool:
        """Le SDK sait aussi lire un profil `ant auth login`, mais en pratique
        une cle dans le .env est le chemin le plus simple.

        Le gabarit livre contient `sk-ant-...` : on le traite comme absent,
        sinon l'utilisateur se prend une erreur d'authentification obscure
        au lieu du message d'installation.
        """
        cle = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
        if cle.endswith("...") or cle in {"", "sk-ant-"}:
            cle = ""
        return bool(cle or (os.getenv("ANTHROPIC_AUTH_TOKEN") or "").strip())

    def __post_init__(self) -> None:
        self.dossier_donnees.mkdir(parents=True, exist_ok=True)


config = Config()
