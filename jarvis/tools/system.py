"""Outils de controle du PC (Windows) : applications, fichiers, volume,
captures d'ecran, etat systeme et alimentation.

Les lectures de fichiers sont confinees aux dossiers listes dans
`JARVIS_ALLOWED_DIRS`. Les actions irreversibles sont marquees `sensible`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from ..config import config
from . import Registre

# Raccourcis vers les applications Windows courantes : evite au modele de
# deviner un chemin d'executable.
ALIAS_APPS = {
    "navigateur": "https://www.google.com",
    "chrome": "chrome",
    "edge": "msedge",
    "firefox": "firefox",
    "explorateur": "explorer",
    "explorateur de fichiers": "explorer",
    "bloc-notes": "notepad",
    "notepad": "notepad",
    "calculatrice": "calc",
    "calc": "calc",
    "terminal": "wt",
    "powershell": "powershell",
    "invite de commandes": "cmd",
    "parametres": "ms-settings:",
    "reglages": "ms-settings:",
    "spotify": "spotify",
    "discord": "discord",
    "vscode": "code",
    "visual studio code": "code",
    "code": "code",
    "gestionnaire des taches": "taskmgr",
}


def _dossiers_autorises() -> list[Path]:
    chemins = []
    for brut in config.dossiers_autorises:
        try:
            chemins.append(Path(brut).expanduser().resolve())
        except OSError:
            continue
    return chemins


def _chemin_autorise(cible: Path) -> bool:
    try:
        resolu = cible.expanduser().resolve()
    except OSError:
        return False
    for racine in _dossiers_autorises():
        try:
            resolu.relative_to(racine)
            return True
        except ValueError:
            continue
    return False


# --------------------------------------------------------------- application


def ouvrir_application(nom: str) -> str:
    cible = ALIAS_APPS.get(nom.strip().lower(), nom.strip())

    if cible.startswith(("http://", "https://", "ms-settings:")):
        webbrowser.open(cible)
        return f"Ouvert : {cible}"

    # `start` passe par le shell Windows : il resout le PATH, le registre des
    # applications installees et les raccourcis du menu Demarrer.
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", cible],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as err:
        return f"Impossible de lancer '{nom}' : {err}"
    return f"Lancement de '{nom}' demande."


def ouvrir_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Ouvert dans le navigateur : {url}"


# ------------------------------------------------------------------ fichiers


def chercher_fichiers(motif: str, dossier: str = "", limite: int = 25) -> dict[str, Any]:
    if dossier:
        racines = [Path(dossier).expanduser()]
        if not _chemin_autorise(racines[0]):
            return {
                "erreur": f"Dossier hors perimetre autorise : {dossier}",
                "dossiers_autorises": [str(d) for d in _dossiers_autorises()],
            }
    else:
        racines = _dossiers_autorises()

    motif_glob = motif if any(c in motif for c in "*?[") else f"*{motif}*"
    trouves: list[dict[str, Any]] = []
    ignores = {".git", "node_modules", "__pycache__", ".venv", "AppData", "$Recycle.Bin"}

    for racine in racines:
        if len(trouves) >= limite:
            break
        for dossier_courant, sous_dossiers, fichiers in os.walk(racine, onerror=lambda e: None):
            sous_dossiers[:] = [d for d in sous_dossiers if d not in ignores and not d.startswith(".")]
            for nom_fichier in fichiers:
                if fnmatch(nom_fichier.lower(), motif_glob.lower()):
                    chemin = Path(dossier_courant) / nom_fichier
                    try:
                        stat = chemin.stat()
                    except OSError:
                        continue
                    trouves.append({
                        "chemin": str(chemin),
                        "taille_ko": round(stat.st_size / 1024, 1),
                        "modifie_le": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    })
                    if len(trouves) >= limite:
                        break
            if len(trouves) >= limite:
                break

    return {"motif": motif_glob, "nombre": len(trouves), "resultats": trouves}


def lire_fichier(chemin: str, max_lignes: int = 200) -> str:
    cible = Path(chemin).expanduser()
    if not _chemin_autorise(cible):
        return (
            f"Lecture refusee : {chemin} est hors des dossiers autorises. "
            f"Autorises : {', '.join(str(d) for d in _dossiers_autorises())}"
        )
    if not cible.is_file():
        return f"Fichier introuvable : {chemin}"

    try:
        with cible.open("r", encoding="utf-8", errors="replace") as flux:
            lignes = []
            for index, ligne in enumerate(flux):
                if index >= max_lignes:
                    lignes.append(f"... (tronque a {max_lignes} lignes)")
                    break
                lignes.append(ligne.rstrip("\n"))
    except OSError as err:
        return f"Erreur de lecture : {err}"
    return "\n".join(lignes) or "(fichier vide)"


def executer_commande(commande: str, timeout: int = 30) -> dict[str, Any]:
    """Execute une commande PowerShell. Outil sensible : confirme en amont."""
    try:
        resultat = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", commande],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"erreur": f"Commande interrompue apres {timeout}s."}
    except OSError as err:
        return {"erreur": str(err)}

    return {
        "code_retour": resultat.returncode,
        "sortie": (resultat.stdout or "").strip()[:4000],
        "erreurs": (resultat.stderr or "").strip()[:2000],
    }


# -------------------------------------------------------------------- audio


def _interface_volume():
    """Recupere l'interface volume Windows. Import tardif : pycaw est
    optionnel et specifique a Windows."""
    from ctypes import POINTER, cast

    import comtypes
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    comtypes.CoInitialize()
    haut_parleurs = AudioUtilities.GetSpeakers()
    interface = haut_parleurs.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def regler_volume(niveau: int) -> str:
    niveau = max(0, min(100, int(niveau)))
    try:
        _interface_volume().SetMasterVolumeLevelScalar(niveau / 100.0, None)
    except Exception as err:  # noqa: BLE001 - pycaw absent ou COM indisponible
        return f"Reglage du volume impossible ({err}). Verifie que pycaw est installe."
    return f"Volume regle a {niveau} %."


def couper_son(muet: bool = True) -> str:
    try:
        _interface_volume().SetMute(1 if muet else 0, None)
    except Exception as err:  # noqa: BLE001
        return f"Action impossible ({err})."
    return "Son coupe." if muet else "Son retabli."


# ------------------------------------------------------------------ systeme


def capture_ecran() -> str:
    try:
        import mss
    except ImportError:
        return "Le module 'mss' n'est pas installe."

    dossier = config.dossier_donnees / "captures"
    dossier.mkdir(parents=True, exist_ok=True)
    fichier = dossier / f"capture_{datetime.now():%Y%m%d_%H%M%S}.png"

    with mss.mss() as capteur:
        capteur.shot(mon=-1, output=str(fichier))
    return f"Capture enregistree : {fichier}"


def etat_systeme() -> dict[str, Any]:
    try:
        import psutil
    except ImportError:
        return {"erreur": "psutil n'est pas installe."}

    disque = shutil.disk_usage(Path.home().anchor)
    memoire = psutil.virtual_memory()

    infos: dict[str, Any] = {
        "processeur_pourcent": psutil.cpu_percent(interval=0.4),
        "coeurs": psutil.cpu_count(logical=True),
        "memoire": {
            "utilisee_go": round(memoire.used / 1e9, 1),
            "totale_go": round(memoire.total / 1e9, 1),
            "pourcent": memoire.percent,
        },
        "disque": {
            "libre_go": round(disque.free / 1e9, 1),
            "total_go": round(disque.total / 1e9, 1),
        },
        "heure_locale": datetime.now().strftime("%A %d %B %Y, %H:%M"),
    }

    batterie = getattr(psutil, "sensors_battery", lambda: None)()
    if batterie is not None:
        infos["batterie"] = {
            "pourcent": round(batterie.percent),
            "sur_secteur": batterie.power_plugged,
        }
    return infos


def controle_alimentation(action: str) -> str:
    """Outil sensible : verrouillage, veille, redemarrage ou extinction."""
    commandes = {
        "verrouiller": ["rundll32.exe", "user32.dll,LockWorkStation"],
        "veille": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
        "redemarrer": ["shutdown", "/r", "/t", "10"],
        "eteindre": ["shutdown", "/s", "/t", "10"],
        "annuler": ["shutdown", "/a"],
    }
    cle = action.strip().lower()
    if cle not in commandes:
        return f"Action inconnue. Choix possibles : {', '.join(commandes)}."

    try:
        subprocess.run(commandes[cle], check=False, capture_output=True)
    except OSError as err:
        return f"Echec : {err}"

    if cle in {"redemarrer", "eteindre"}:
        return f"{cle.capitalize()} programme dans 10 secondes. Dis 'annuler' pour arreter."
    return f"Action '{cle}' executee."


# ---------------------------------------------------------- enregistrement


def enregistrer(registre: Registre) -> None:
    registre.enregistrer(
        "ouvrir_application",
        "Lance une application ou un site sur le PC (Chrome, Spotify, VS Code, "
        "explorateur, calculatrice...). Accepte un nom courant en francais.",
        {"properties": {"nom": {"type": "string", "description": "Nom de l'application"}},
         "required": ["nom"]},
        ouvrir_application,
    )

    registre.enregistrer(
        "ouvrir_url",
        "Ouvre une adresse web dans le navigateur par defaut.",
        {"properties": {"url": {"type": "string"}}, "required": ["url"]},
        ouvrir_url,
    )

    registre.enregistrer(
        "chercher_fichiers",
        "Cherche des fichiers par nom dans les dossiers autorises. "
        "Le motif accepte les jokers (*.pdf, rapport*).",
        {"properties": {
            "motif": {"type": "string", "description": "Nom ou motif de fichier"},
            "dossier": {"type": "string", "description": "Dossier de depart (optionnel)"},
            "limite": {"type": "integer", "description": "Nombre max de resultats"},
        }, "required": ["motif"]},
        chercher_fichiers,
    )

    registre.enregistrer(
        "lire_fichier",
        "Lit le contenu texte d'un fichier situe dans un dossier autorise.",
        {"properties": {
            "chemin": {"type": "string"},
            "max_lignes": {"type": "integer"},
        }, "required": ["chemin"]},
        lire_fichier,
    )

    registre.enregistrer(
        "executer_commande",
        "Execute une commande PowerShell sur le PC. A n'utiliser que si aucun "
        "autre outil ne convient : l'utilisateur devra confirmer.",
        {"properties": {
            "commande": {"type": "string"},
            "timeout": {"type": "integer"},
        }, "required": ["commande"]},
        executer_commande,
        sensible=True,
        resume=lambda e: f"Executer la commande PowerShell : {e.get('commande', '')}",
    )

    registre.enregistrer(
        "regler_volume",
        "Regle le volume general du PC entre 0 et 100.",
        {"properties": {"niveau": {"type": "integer"}}, "required": ["niveau"]},
        regler_volume,
    )

    registre.enregistrer(
        "couper_son",
        "Coupe ou retablit le son du PC.",
        {"properties": {"muet": {"type": "boolean"}}, "required": []},
        couper_son,
    )

    registre.enregistrer(
        "capture_ecran",
        "Prend une capture de tous les ecrans et l'enregistre dans data/captures.",
        {"properties": {}, "required": []},
        capture_ecran,
    )

    registre.enregistrer(
        "etat_systeme",
        "Donne l'etat du PC : processeur, memoire, disque, batterie, heure locale.",
        {"properties": {}, "required": []},
        etat_systeme,
    )

    registre.enregistrer(
        "controle_alimentation",
        "Verrouille, met en veille, redemarre ou eteint le PC. "
        "'annuler' stoppe un arret programme.",
        {"properties": {"action": {
            "type": "string",
            "enum": ["verrouiller", "veille", "redemarrer", "eteindre", "annuler"],
        }}, "required": ["action"]},
        controle_alimentation,
        sensible=True,
        resume=lambda e: f"Alimentation du PC : {e.get('action', '')}",
    )
