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
    effort: str = os.getenv("JARVIS_EFFORT", "medium")
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
    silence_fin_phrase: float = float(os.getenv("JARVIS_SILENCE", "0.9"))
    # Seuil d'energie du micro : monte-le si la piece est bruyante.
    seuil_micro: float = float(os.getenv("JARVIS_MIC_THRESHOLD", "0.015"))
    # Apres une reponse, JARVIS ecoute la suite sans mot de reveil pendant N s.
    fenetre_conversation: float = float(os.getenv("JARVIS_FOLLOWUP_WINDOW", "12"))

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
