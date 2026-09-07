"""Interface de JARVIS : mode texte et mode vocal."""

from __future__ import annotations

import argparse
import sys
import threading
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from .brain import Cerveau, construire_registre, outils_absents
from .config import config
from .memory import Memoire

console = Console()

AIDE = """[bold]Commandes[/bold]
  /aide          affiche cette aide
  /voix          bascule entre mode texte et mode vocal
  /memoire       liste ce que JARVIS sait de toi
  /taches        liste les taches en cours
  /oublie <id>   supprime un fait de la memoire
  /reset         repart d'une conversation vierge (la memoire est gardee)
  /quit          quitte

En mode vocal, dis [bold]"Jarvis"[/bold] suivi de ta demande.
Apres sa reponse, tu peux enchainer sans repeter le mot de reveil.
Ctrl+C interrompt la parole ou quitte."""


# --------------------------------------------------------------- affichage


def _afficher_appel_outil(nom: str, entree: dict[str, Any]) -> None:
    apercu = ", ".join(
        f"{cle}={str(valeur)[:60]}" for cle, valeur in list(entree.items())[:3]
    )
    # Les arguments viennent du modele : un crochet non echappe casserait
    # le balisage de rich.
    console.print(f"  [dim]-> {escape(nom)}({escape(apercu)})[/dim]")


def _afficher_resultat_outil(nom: str, sortie: str, erreur: bool) -> None:
    if erreur:
        premiere_ligne = sortie.splitlines()[0][:120] if sortie else "echec"
        console.print(f"  [red]x {escape(nom)} : {escape(premiere_ligne)}[/red]")


def _confirmation_terminal(nom: str, resume: str, entree: dict[str, Any]) -> bool:
    console.print()
    console.print(Panel(resume, title="[bold yellow]Confirmation requise[/bold yellow]",
                        border_style="yellow"))
    try:
        reponse = console.input("[yellow]Autoriser ? [o/N][/yellow] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return reponse in {"o", "oui", "y", "yes"}


# ------------------------------------------------------------- mode texte


def boucle_texte(cerveau: Cerveau, memoire: Memoire) -> str | None:
    """Renvoie 'vocal' si l'utilisateur demande a basculer, sinon None."""
    while True:
        try:
            entree = console.input("\n[bold cyan]toi >[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            return None

        if not entree:
            continue

        if entree.startswith("/"):
            action = _commande(entree, cerveau, memoire)
            if action == "quit":
                return None
            if action == "vocal":
                return "vocal"
            continue

        console.print(f"\n[bold green]{config.nom_assistant} >[/bold green] ", end="")
        premier = threading.Event()

        def sur_texte(fragment: str) -> None:
            premier.set()
            console.print(fragment, end="", markup=False, highlight=False)

        try:
            reponse = cerveau.demander(
                entree,
                mode_vocal=False,
                sur_texte=sur_texte,
                sur_outil=_afficher_appel_outil,
                sur_resultat=_afficher_resultat_outil,
            )
        except KeyboardInterrupt:
            console.print("\n[dim](interrompu)[/dim]")
            continue
        except Exception as err:  # noqa: BLE001
            console.print(f"\n[red]Erreur : {err}[/red]")
            continue

        if not premier.is_set():
            console.print(reponse, markup=False, highlight=False)
        console.print()


# ------------------------------------------------------------- mode vocal


def boucle_vocale(cerveau: Cerveau, memoire: Memoire) -> str | None:
    """Renvoie 'texte' pour revenir au clavier, sinon None pour quitter."""
    from .speech.listener import Micro, contient_mot_reveil, retirer_mot_reveil
    from .speech.stt import Oreille
    from .speech.tts import Voix

    oreille = Oreille(config.modele_whisper, config.langue)
    voix = Voix(config.voix_tts, config.vitesse_tts)
    micro = Micro(seuil=config.seuil_micro, silence_fin=config.silence_fin_phrase)

    with console.status("[cyan]Chargement du modele de transcription..."):
        oreille.charger()

    # En mode vocal, la confirmation se demande a l'oral pour rester
    # mains libres ; le clavier reste disponible en secours.
    def confirmation_vocale(nom: str, resume: str, entree: dict[str, Any]) -> bool:
        console.print(Panel(resume, title="[bold yellow]Confirmation[/bold yellow]",
                            border_style="yellow"))
        micro.suspendre()
        voix.parler(f"Confirme : {resume}. Je le fais ?")
        micro.reprendre()

        signal = micro.capturer_phrase(attente_max=8)
        if signal is None:
            console.print("[dim]Pas de reponse : action annulee.[/dim]")
            return False

        reponse = oreille.transcrire(signal).lower()
        console.print(f"[dim]  (entendu : {escape(reponse)})[/dim]")
        accepte = any(mot in reponse for mot in
                      ("oui", "vas-y", "vas y", "confirme", "ok", "d'accord", "fais"))
        if not accepte:
            voix.parler("D'accord, j'annule.")
        return accepte

    cerveau.registre.demander_confirmation = confirmation_vocale

    console.print(Panel(
        f"Mode vocal actif. Dis [bold]\"{config.mot_reveil.capitalize()}\"[/bold] "
        f"suivi de ta demande.\nCtrl+C pour revenir au clavier.",
        border_style="green",
    ))

    micro.demarrer()
    voix.parler(f"Bonjour {config.nom_utilisateur}, je vous ecoute.")
    micro.reprendre()

    en_conversation = False

    try:
        while True:
            attente = config.fenetre_conversation if en_conversation else None
            etiquette = "[dim]...[/dim]" if en_conversation else \
                        f"[dim]en veille (dis \"{config.mot_reveil}\")[/dim]"
            console.print(etiquette)

            signal = micro.capturer_phrase(attente_max=attente)
            if signal is None:
                # Fin de la fenetre de suivi : on repasse en veille.
                en_conversation = False
                continue

            texte = oreille.transcrire(signal)
            if not texte or len(texte) < 2:
                continue

            console.print(f"[bold cyan]toi >[/bold cyan] {escape(texte)}")

            if not en_conversation:
                if not contient_mot_reveil(texte, config.mot_reveil):
                    continue
                texte = retirer_mot_reveil(texte, config.mot_reveil)
                if not texte.strip():
                    micro.suspendre()
                    voix.parler("Oui ?")
                    micro.reprendre()
                    en_conversation = True
                    continue

            if any(mot in texte.lower() for mot in ("au revoir", "bonne nuit", "termine")):
                micro.suspendre()
                voix.parler("A bientot.")
                return None

            if "mode texte" in texte.lower() or "passe au clavier" in texte.lower():
                micro.suspendre()
                voix.parler("Je repasse au clavier.")
                return "texte"

            console.print(f"\n[bold green]{config.nom_assistant} >[/bold green] ", end="")

            def sur_texte(fragment: str) -> None:
                console.print(fragment, end="", markup=False, highlight=False)

            try:
                reponse = cerveau.demander(
                    texte,
                    mode_vocal=True,
                    sur_texte=sur_texte,
                    sur_outil=_afficher_appel_outil,
                    sur_resultat=_afficher_resultat_outil,
                )
            except Exception as err:  # noqa: BLE001
                console.print(f"\n[red]Erreur : {err}[/red]")
                reponse = "J'ai rencontre un probleme technique."

            console.print("\n")
            # Le micro est suspendu pendant la parole, sinon JARVIS
            # transcrit sa propre voix et se repond a lui-meme.
            micro.suspendre()
            voix.parler(reponse)
            micro.reprendre()
            en_conversation = True

    except KeyboardInterrupt:
        voix.stopper()
        console.print("\n[dim]Retour au mode texte.[/dim]")
        return "texte"
    finally:
        micro.arreter()


# ---------------------------------------------------------------- commandes


def _commande(ligne: str, cerveau: Cerveau, memoire: Memoire) -> str | None:
    morceaux = ligne.split(maxsplit=1)
    nom = morceaux[0].lower()
    argument = morceaux[1].strip() if len(morceaux) > 1 else ""

    if nom in {"/quit", "/exit", "/q"}:
        return "quit"

    if nom == "/voix":
        return "vocal"

    if nom == "/aide":
        console.print(Panel(AIDE, border_style="cyan"))
        return None

    if nom == "/reset":
        cerveau.reinitialiser()
        console.print("[dim]Conversation reinitialisee (memoire conservee).[/dim]")
        return None

    if nom == "/memoire":
        faits = memoire.tous_les_faits()
        if not faits:
            console.print("[dim]Aucun souvenir enregistre pour l'instant.[/dim]")
            return None
        table = Table(title="Memoire de JARVIS", border_style="cyan")
        table.add_column("#", style="dim", width=5)
        table.add_column("Categorie", style="magenta")
        table.add_column("Fait")
        for fait in faits:
            table.add_row(str(fait["id"]), fait["categorie"], fait["contenu"])
        console.print(table)
        return None

    if nom == "/taches":
        taches = memoire.lister_taches()
        if not taches:
            console.print("[dim]Aucune tache en cours.[/dim]")
            return None
        table = Table(title="Taches", border_style="cyan")
        table.add_column("#", style="dim", width=5)
        table.add_column("Titre")
        table.add_column("Echeance", style="yellow")
        table.add_column("Priorite", style="magenta")
        for tache in taches:
            table.add_row(str(tache["id"]), tache["titre"],
                          tache["echeance"] or "-", tache["priorite"])
        console.print(table)
        return None

    if nom == "/oublie":
        if not argument.isdigit():
            console.print("[yellow]Usage : /oublie <id>[/yellow]")
            return None
        ok = memoire.oublier(int(argument))
        console.print(f"[dim]{'Supprime.' if ok else 'Identifiant inconnu.'}[/dim]")
        return None

    console.print(f"[yellow]Commande inconnue : {nom}. Tape /aide.[/yellow]")
    return None


# --------------------------------------------------------------- demarrage


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(
        prog="jarvis", description="Assistant personnel JARVIS"
    )
    analyseur.add_argument("--voix", action="store_true", help="demarre en mode vocal")
    analyseur.add_argument("--texte", action="store_true", help="force le mode texte")
    analyseur.add_argument("demande", nargs="*",
                           help="demande unique : execute puis quitte")
    args = analyseur.parse_args(argv)

    if not config.cle_api_presente():
        fichier_env = config.racine / ".env"
        if fichier_env.is_file():
            etapes = (
                "1. Recupere une cle sur [cyan]console.anthropic.com/settings/keys[/cyan]\n"
                f"2. Ouvre [cyan]{fichier_env}[/cyan]\n"
                "3. Remplace [cyan]sk-ant-...[/cyan] par ta vraie cle, puis relance"
            )
        else:
            etapes = (
                "1. Recupere une cle sur [cyan]console.anthropic.com/settings/keys[/cyan]\n"
                "2. Copie [cyan].env.example[/cyan] vers [cyan].env[/cyan]\n"
                "3. Renseigne [cyan]ANTHROPIC_API_KEY=sk-ant-...[/cyan]"
            )
        console.print(Panel(
            f"Aucune cle API valide trouvee.\n\n{etapes}",
            title="[red]Configuration incomplete[/red]", border_style="red",
        ))
        return 1

    memoire = Memoire(config.base_memoire)
    registre = construire_registre(config, memoire)
    cerveau = Cerveau(config, registre, memoire)
    registre.demander_confirmation = _confirmation_terminal

    # Mode "one-shot" : jarvis "quelle heure il est"
    if args.demande:
        reponse = cerveau.demander(" ".join(args.demande),
                                   sur_outil=_afficher_appel_outil)
        console.print(reponse, markup=False)
        memoire.fermer()
        return 0

    console.print(Panel(
        f"[bold]{config.nom_assistant}[/bold] est en ligne.\n"
        f"{len(registre.noms())} outils + recherche web. Tape [cyan]/aide[/cyan].",
        border_style="green",
    ))
    for manquant in outils_absents(registre):
        console.print(f"[dim]  (optionnel) {manquant}[/dim]")

    mode = "vocal" if (args.voix and not args.texte) else "texte"
    try:
        while mode is not None:
            if mode == "vocal":
                mode = boucle_vocale(cerveau, memoire)
                registre.demander_confirmation = _confirmation_terminal
            else:
                mode = boucle_texte(cerveau, memoire)
    finally:
        memoire.fermer()

    console.print("\n[dim]A bientot.[/dim]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
