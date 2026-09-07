"""Le cerveau de JARVIS : la boucle agentique autour de l'API Claude.

Boucle manuelle plutot que le tool runner du SDK, pour trois raisons :
 - il faut gerer `pause_turn` explicitement (la recherche web s'interrompt
   au bout de plusieurs iterations serveur) ;
 - on veut afficher/vocaliser le texte au fil de l'eau ;
 - on veut intercepter chaque appel d'outil pour l'afficher et le confirmer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Callable, Iterable

import anthropic

from .config import Config
from .memory import Memoire
from .tools import Registre

# Outil serveur d'Anthropic : la recherche web s'execute cote Anthropic,
# aucun code ni cle tierce de notre cote.
OUTIL_RECHERCHE_WEB = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 6,
}

IDENTITE = """Tu es {nom}, l'assistant personnel de {utilisateur}.

Ton caractere : posé, efficace, un brin d'humour sec. Tu es serviable sans
être obséquieux. Tu ne dis jamais "En tant qu'assistant IA". Tu tutoies
{utilisateur}.

Règles de fonctionnement :
- Réponds en français, sauf si on te parle dans une autre langue.
- Va droit au but. Une réponse utile de deux phrases vaut mieux qu'un paragraphe.
- Tu as des outils : sers-t'en au lieu de dire que tu ne peux pas. Pour agir
  sur le PC, chercher sur le web, gérer l'agenda ou les tâches, appelle
  l'outil directement plutôt que de demander la permission d'abord.
- Enchaîne plusieurs outils sans repasser par l'utilisateur quand la tâche
  le demande. Ne t'arrête que quand c'est fait.
- Dès que tu apprends un fait durable sur {utilisateur} (préférence, projet,
  proche, habitude, matériel), appelle `retenir`. N'annonce pas que tu
  mémorises, fais-le simplement.
- Si tu ignores quelque chose de factuel ou d'actuel, cherche sur le web
  plutôt que de deviner.
- Quand une action échoue, dis-le franchement et propose une alternative.
  N'invente jamais un résultat d'outil."""

CONSIGNE_VOCALE = """
Mode vocal : ta réponse va être lue à voix haute.
- Pas de markdown, pas de listes à puces, pas d'astérisques, pas de titres.
- Des phrases courtes, à l'oral. Écris les nombres comme on les prononce.
- Vise trois phrases. Si le contenu est long, donne l'essentiel et propose
  d'en dire plus.
- Pas d'URL lues en entier : dis "je te l'ai ouvert dans le navigateur"."""

CONSIGNE_TEXTE = """
Mode texte : tu écris dans un terminal.
- Le markdown léger est le bienvenu (listes, `code`), mais reste sobre.
- Pas de titres pompeux ni de rappel de la question."""


class Cerveau:
    def __init__(
        self,
        config: Config,
        registre: Registre,
        memoire: Memoire,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self.config = config
        self.registre = registre
        self.memoire = memoire
        self.client = client or anthropic.Anthropic()
        self.session = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
        self.messages: list[dict[str, Any]] = []
        # Passe a False si l'API refuse le parametre de repli serveur.
        self._replis_disponibles = True
        self._systeme = self._construire_systeme()

    # ------------------------------------------------------- prompt systeme

    def _construire_systeme(self) -> list[dict[str, Any]]:
        """Deux blocs : une identite figée (mise en cache) puis le contexte
        du jour. L'ordre de rendu est tools -> system -> messages, donc tout
        ce qui est stable doit venir en premier pour que le cache tienne."""
        identite = IDENTITE.format(
            nom=self.config.nom_assistant,
            utilisateur=self.config.nom_utilisateur,
        )

        contexte = [f"Date et heure : {datetime.now():%A %d %B %Y, %H:%M}."]

        faits = self.memoire.tous_les_faits(limite=40)
        if faits:
            lignes = "\n".join(
                f"- [{f['categorie']}] {f['contenu']}" for f in faits
            )
            contexte.append(
                f"Ce que tu sais deja de {self.config.nom_utilisateur} :\n{lignes}"
            )
        else:
            contexte.append(
                f"Tu ne connais pas encore {self.config.nom_utilisateur}. "
                "Retiens ce que tu apprends avec l'outil `retenir`."
            )

        fil = self.memoire.resume_derniere_session(self.session)
        if fil:
            contexte.append(f"Fin de votre derniere conversation :\n{fil}")

        return [
            {"type": "text", "text": identite},
            {
                "type": "text",
                "text": "\n\n".join(contexte),
                # Le cache couvre tout le prefixe : outils + identite + contexte.
                # Le prompt systeme est fige pour la session, donc il tient.
                "cache_control": {"type": "ephemeral"},
            },
        ]

    def _outils(self) -> list[dict[str, Any]]:
        return self.registre.definitions(serveur=[OUTIL_RECHERCHE_WEB])

    # ------------------------------------------------------- appel au modele

    def _appeler(self, systeme: list[dict[str, Any]], mode_vocal: bool,
                 sur_texte: Callable[[str], None] | None):
        """Un aller-retour avec l'API, en streaming.

        Le streaming evite les délais d'attente HTTP sur les longues réponses
        et permet d'afficher le texte au fil de l'eau.
        """
        consigne = CONSIGNE_VOCALE if mode_vocal else CONSIGNE_TEXTE
        systeme_complet = [
            systeme[0],
            {**systeme[1], "text": systeme[1]["text"] + "\n" + consigne},
        ]

        parametres: dict[str, Any] = {
            "model": self.config.modele,
            "max_tokens": self.config.max_tokens,
            "system": systeme_complet,
            "messages": self.messages,
            "tools": self._outils(),
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.config.effort},
        }

        if self._replis_disponibles:
            try:
                return self._flux(
                    self.client.beta.messages.stream,
                    {**parametres,
                     "betas": ["server-side-fallback-2026-07-01"],
                     "fallbacks": "default"},
                    sur_texte,
                )
            except (TypeError, anthropic.BadRequestError) as err:
                # SDK ou compte sans le repli serveur : on continue sans.
                self._replis_disponibles = False
                if isinstance(err, anthropic.BadRequestError) and "fallback" not in str(err).lower():
                    raise

        return self._flux(self.client.messages.stream, parametres, sur_texte)

    @staticmethod
    def _flux(ouvrir_flux, parametres: dict[str, Any],
              sur_texte: Callable[[str], None] | None):
        with ouvrir_flux(**parametres) as flux:
            if sur_texte is not None:
                for evenement in flux:
                    if (evenement.type == "content_block_delta"
                            and getattr(evenement.delta, "type", "") == "text_delta"):
                        sur_texte(evenement.delta.text)
            return flux.get_final_message()

    # --------------------------------------------------------------- boucle

    def demander(
        self,
        entree: str,
        mode_vocal: bool = False,
        sur_texte: Callable[[str], None] | None = None,
        sur_outil: Callable[[str, dict[str, Any]], None] | None = None,
        sur_resultat: Callable[[str, str, bool], None] | None = None,
    ) -> str:
        """Traite une demande de bout en bout et renvoie la réponse finale.

        `sur_texte` reçoit le texte au fil du streaming, `sur_outil` est
        appelé avant chaque exécution d'outil, `sur_resultat` après.
        """
        self.messages.append({"role": "user", "content": entree})
        self.memoire.ajouter_message(self.session, "user", entree)

        reponses_texte: list[str] = []

        for _ in range(self.config.max_tours_outils):
            message = self._appeler(self._systeme, mode_vocal, sur_texte)

            # Un refus renvoie un HTTP 200 : il faut le tester avant de lire
            # le contenu, qui peut être vide.
            if message.stop_reason == "refusal":
                detail = getattr(message, "stop_details", None)
                motif = getattr(detail, "category", None) or "non precise"
                texte = (
                    "Je ne peux pas traiter cette demande "
                    f"(motif : {motif}). Reformule ou demande-moi autre chose."
                )
                self.messages.append({"role": "assistant", "content": texte})
                self.memoire.ajouter_message(self.session, "assistant", texte)
                return texte

            self.messages.append({"role": "assistant", "content": message.content})

            texte_du_tour = "".join(
                bloc.text for bloc in message.content if bloc.type == "text"
            ).strip()
            if texte_du_tour:
                reponses_texte.append(texte_du_tour)

            # La recherche web a atteint sa limite d'itérations côté serveur :
            # on relance tel quel, l'historique porte déjà le tour en pause.
            if message.stop_reason == "pause_turn":
                continue

            appels = [bloc for bloc in message.content if bloc.type == "tool_use"]
            if not appels:
                break

            resultats: list[dict[str, Any]] = []
            for appel in appels:
                entree_outil = dict(appel.input) if appel.input else {}
                if sur_outil is not None:
                    sur_outil(appel.name, entree_outil)

                sortie, est_erreur = self.registre.executer(appel.name, entree_outil)
                if sur_resultat is not None:
                    sur_resultat(appel.name, sortie, est_erreur)

                resultats.append({
                    "type": "tool_result",
                    "tool_use_id": appel.id,
                    "content": sortie[:20000],
                    "is_error": est_erreur,
                })

            # Tous les résultats dans un seul message utilisateur : les
            # séparer apprendrait au modèle à ne plus paralléliser.
            self.messages.append({"role": "user", "content": resultats})
        else:
            reponses_texte.append(
                "J'ai atteint ma limite d'étapes sur cette tâche. "
                "Dis-moi si je continue."
            )

        finale = (reponses_texte[-1] if reponses_texte else "").strip()
        if not finale:
            finale = "C'est fait."
        self.memoire.ajouter_message(self.session, "assistant", finale)
        return finale

    def reinitialiser(self) -> None:
        """Vide le fil de discussion, garde la mémoire long terme."""
        self.messages.clear()
        self._systeme = self._construire_systeme()


def construire_registre(config: Config, memoire: Memoire) -> Registre:
    """Assemble tous les outils disponibles."""
    from .tools import google as outils_google
    from .tools import personal as outils_personnels
    from .tools import system as outils_systeme

    registre = Registre()
    registre.confirmations_actives = config.confirmer_actions_sensibles

    outils_systeme.enregistrer(registre)
    outils_personnels.enregistrer(registre, memoire)
    outils_google.enregistrer(registre)
    return registre


def outils_absents(registre: Registre) -> Iterable[str]:
    """Capacités non branchées, pour l'afficher au démarrage."""
    from .tools import google as outils_google

    if not outils_google.integration_possible():
        yield "Google (agenda + mail) : depose credentials.json a la racine"
