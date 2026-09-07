"""Verifie la forme des requetes et la mecanique de la boucle d'outils.

Un faux client remplace l'API : on controle ce que "le modele" repond et on
inspecte les parametres envoyes. Aucune cle API n'est necessaire.

Lancement :  .venv\\Scripts\\python.exe tests\\test_brain.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.brain import Cerveau, construire_registre  # noqa: E402
from jarvis.config import config  # noqa: E402
from jarvis.memory import Memoire  # noqa: E402


# ------------------------------------------------------------- faux client


class FauxFlux:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __iter__(self):
        """Simule le streaming : un delta de texte par bloc texte."""
        for bloc in self._message.content:
            if bloc.type == "text":
                yield SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(type="text_delta", text=bloc.text),
                )

    def get_final_message(self):
        return self._message


class FauxClient:
    """Rejoue une liste de reponses et enregistre chaque appel."""

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.appels = []
        moi = self

        def stream(**kwargs):
            # `messages` est mute d'un tour a l'autre : on en fige une copie,
            # sinon on inspecterait l'etat final et non ce qui a ete envoye.
            moi.appels.append({**kwargs, "messages": list(kwargs["messages"])})
            return FauxFlux(moi.reponses.pop(0))

        self.messages = SimpleNamespace(stream=stream)
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=stream))


def bloc_texte(texte):
    return SimpleNamespace(type="text", text=texte)


def bloc_outil(nom, entree, identifiant="tu_1"):
    return SimpleNamespace(type="tool_use", name=nom, input=entree, id=identifiant)


def message(contenu, stop_reason="end_turn"):
    return SimpleNamespace(content=contenu, stop_reason=stop_reason,
                           stop_details=None)


# ------------------------------------------------------------------- tests


def preparer():
    base = Path(tempfile.mkdtemp()) / "t.db"
    memoire = Memoire(base)
    registre = construire_registre(config, memoire)
    return memoire, registre


def test_forme_de_la_requete():
    memoire, registre = preparer()
    client = FauxClient([message([bloc_texte("Bonjour.")])])
    cerveau = Cerveau(config, registre, memoire, client=client)

    cerveau.demander("salut", mode_vocal=False)
    envoi = client.appels[0]

    assert envoi["model"] == config.modele, envoi["model"]
    assert envoi["thinking"] == {"type": "adaptive"}
    assert envoi["output_config"] == {"effort": config.effort}
    assert envoi["betas"] == ["server-side-fallback-2026-07-01"]
    assert envoi["fallbacks"] == "default"

    # Systeme : identite figee puis contexte, point de cache sur le dernier bloc.
    systeme = envoi["system"]
    assert len(systeme) == 2
    assert "cache_control" not in systeme[0]
    assert systeme[1]["cache_control"] == {"type": "ephemeral"}
    assert "Mode texte" in systeme[1]["text"]

    # Outils : les locaux tries, puis la recherche web serveur.
    noms = [o["name"] for o in envoi["tools"]]
    assert noms[:-1] == sorted(noms[:-1]), "l'ordre doit etre stable pour le cache"
    assert noms[-1] == "web_search"
    assert envoi["tools"][-1]["type"] == "web_search_20260209"
    print("  OK  forme de la requete (thinking, effort, cache, outils)")


def test_consigne_vocale():
    memoire, registre = preparer()
    client = FauxClient([message([bloc_texte("Salut.")])])
    cerveau = Cerveau(config, registre, memoire, client=client)

    cerveau.demander("salut", mode_vocal=True)
    systeme = client.appels[0]["system"]
    assert "Mode vocal" in systeme[1]["text"]
    assert "markdown" in systeme[1]["text"].lower()
    # L'identite ne bouge pas entre les deux modes : le cache tient.
    assert "cache_control" not in systeme[0]
    print("  OK  consigne vocale distincte de la consigne texte")


def test_boucle_outils():
    memoire, registre = preparer()
    client = FauxClient([
        message([bloc_outil("retenir", {"fait": "Allan aime le the", "categorie": "gouts"})],
                stop_reason="tool_use"),
        message([bloc_texte("C'est note.")]),
    ])
    cerveau = Cerveau(config, registre, memoire, client=client)

    reponse = cerveau.demander("retiens que j'aime le the")
    assert reponse == "C'est note.", reponse

    # L'outil a reellement ecrit en memoire.
    faits = [f["contenu"] for f in memoire.tous_les_faits()]
    assert "Allan aime le the" in faits, faits

    # Le second appel doit porter l'historique complet : user, assistant, resultat.
    historique = client.appels[1]["messages"]
    assert [m["role"] for m in historique] == ["user", "assistant", "user"]
    resultat = historique[2]["content"][0]
    assert resultat["type"] == "tool_result"
    assert resultat["tool_use_id"] == "tu_1"
    assert resultat["is_error"] is False
    print("  OK  boucle d'outils (execution, historique, tool_result)")


def test_outils_paralleles():
    memoire, registre = preparer()
    client = FauxClient([
        message([bloc_outil("etat_systeme", {}, "a"),
                 bloc_outil("lister_taches", {}, "b")], stop_reason="tool_use"),
        message([bloc_texte("Voila.")]),
    ])
    cerveau = Cerveau(config, registre, memoire, client=client)
    cerveau.demander("etat du pc et mes taches")

    resultats = client.appels[1]["messages"][2]["content"]
    assert len(resultats) == 2, "les resultats paralleles doivent tenir dans UN message"
    assert {r["tool_use_id"] for r in resultats} == {"a", "b"}
    print("  OK  appels paralleles regroupes dans un seul message")


def test_erreur_outil_remonte_au_modele():
    memoire, registre = preparer()
    client = FauxClient([
        message([bloc_outil("outil_inexistant", {}, "x")], stop_reason="tool_use"),
        message([bloc_texte("Desole.")]),
    ])
    cerveau = Cerveau(config, registre, memoire, client=client)
    cerveau.demander("fais un truc impossible")

    resultat = client.appels[1]["messages"][2]["content"][0]
    assert resultat["is_error"] is True
    assert "inconnu" in resultat["content"].lower()
    print("  OK  erreur d'outil renvoyee au modele, pas levee")


def test_confirmation_refusee():
    memoire, registre = preparer()
    registre.demander_confirmation = lambda nom, resume, entree: False
    client = FauxClient([
        message([bloc_outil("executer_commande", {"commande": "Remove-Item C:\\ -Recurse"}, "c")],
                stop_reason="tool_use"),
        message([bloc_texte("Annule.")]),
    ])
    cerveau = Cerveau(config, registre, memoire, client=client)
    cerveau.demander("supprime tout")

    resultat = client.appels[1]["messages"][2]["content"][0]
    assert "annulee" in resultat["content"].lower(), resultat["content"]
    assert resultat["is_error"] is False
    print("  OK  action sensible bloquee par la confirmation")


def test_pause_turn():
    memoire, registre = preparer()
    client = FauxClient([
        message([bloc_texte("Je cherche...")], stop_reason="pause_turn"),
        message([bloc_texte("Voici le resultat.")]),
    ])
    cerveau = Cerveau(config, registre, memoire, client=client)
    reponse = cerveau.demander("cherche la meteo")

    assert reponse == "Voici le resultat.", reponse
    assert len(client.appels) == 2, "le tour en pause doit etre relance"
    print("  OK  pause_turn relance la requete au lieu de tronquer")


def test_refus():
    memoire, registre = preparer()
    client = FauxClient([
        SimpleNamespace(content=[], stop_reason="refusal",
                        stop_details=SimpleNamespace(category="cyber")),
    ])
    cerveau = Cerveau(config, registre, memoire, client=client)
    reponse = cerveau.demander("quelque chose de refuse")

    assert "cyber" in reponse
    assert len(client.appels) == 1, "un refus ne doit pas relancer de boucle"
    print("  OK  refus detecte avant lecture du contenu vide")


def test_repli_sans_fallbacks():
    """Si le compte ne connait pas le repli serveur, on doit reessayer sans."""
    import anthropic

    memoire, registre = preparer()
    reponse_finale = message([bloc_texte("Ca marche quand meme.")])
    appels = []

    def stream_beta(**kwargs):
        appels.append(("beta", kwargs))
        raise TypeError("unexpected keyword argument 'fallbacks'")

    def stream_normal(**kwargs):
        appels.append(("normal", kwargs))
        return FauxFlux(reponse_finale)

    client = SimpleNamespace(
        messages=SimpleNamespace(stream=stream_normal),
        beta=SimpleNamespace(messages=SimpleNamespace(stream=stream_beta)),
    )
    cerveau = Cerveau(config, registre, memoire, client=client)
    resultat = cerveau.demander("salut")

    assert resultat == "Ca marche quand meme.", resultat
    assert [voie for voie, _ in appels] == ["beta", "normal"]
    assert "fallbacks" not in appels[1][1]
    assert cerveau._replis_disponibles is False
    print("  OK  repli automatique si le parametre fallbacks est refuse")


# --------------------------------------------------- gestion des erreurs


def _erreur_http(classe, code):
    import httpx2

    requete = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return classe("boum", response=httpx2.Response(code, request=requete), body=None)


def test_traduction_des_erreurs():
    import anthropic

    from jarvis.brain import traduire_erreur

    cas = [
        (_erreur_http(anthropic.AuthenticationError, 401), "ANTHROPIC_API_KEY"),
        (_erreur_http(anthropic.NotFoundError, 404), "JARVIS_MODEL"),
        (_erreur_http(anthropic.RateLimitError, 429), "credit"),
        (_erreur_http(anthropic.OverloadedError, 529), "surchargee"),
    ]
    for erreur, attendu in cas:
        message = traduire_erreur(erreur)
        assert attendu in message, f"{type(erreur).__name__} -> {message}"

    import httpx2
    requete = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    hors_ligne = traduire_erreur(anthropic.APIConnectionError(request=requete))
    assert "connexion internet" in hors_ligne, hors_ligne

    # Chaque famille doit donner un message distinct, sinon la traduction
    # ne sert a rien.
    messages = {traduire_erreur(e) for e, _ in cas}
    assert len(messages) == len(cas), "des erreurs differentes donnent le meme texte"
    print("  OK  erreurs API traduites en messages distincts et actionnables")


def test_historique_propre_apres_erreur():
    """Une erreur d'API ne doit pas laisser un message `user` orphelin :
    l'appel suivant partirait avec deux `user` de suite et serait rejete."""
    import anthropic

    from jarvis.brain import ErreurJarvis

    memoire, registre = preparer()
    etat = {"echouer": True}
    envois = []

    def stream(**kwargs):
        envois.append(list(kwargs["messages"]))
        if etat["echouer"]:
            raise _erreur_http(anthropic.RateLimitError, 429)
        return FauxFlux(message([bloc_texte("Me revoila.")]))

    client = SimpleNamespace(
        messages=SimpleNamespace(stream=stream),
        beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)),
    )
    cerveau = Cerveau(config, registre, memoire, client=client)

    try:
        cerveau.demander("premiere question")
        raise AssertionError("une erreur d'API aurait du remonter")
    except ErreurJarvis as err:
        assert "credit" in str(err) or "debit" in str(err), str(err)

    assert cerveau.messages == [], f"historique pollue : {cerveau.messages}"

    # La conversation doit repartir normalement.
    etat["echouer"] = False
    reponse = cerveau.demander("deuxieme question")
    assert reponse == "Me revoila.", reponse

    roles = [m["role"] for m in envois[-1]]
    assert roles == ["user"], f"roles envoyes apres reprise : {roles}"
    assert envois[-1][0]["content"] == "deuxieme question"
    print("  OK  historique restaure apres une erreur d'API")


def test_nettoyage_apres_interruption():
    """Ctrl+C pendant un appel d'outil laisse un tool_use sans tool_result :
    `nettoyer_tour_incomplet` doit defaire tout le tour."""
    memoire, registre = preparer()
    client = FauxClient([message([bloc_texte("ok")])])
    cerveau = Cerveau(config, registre, memoire, client=client)

    cerveau.demander("une question")
    assert len(cerveau.messages) == 2

    # Simule un second tour interrompu en plein vol.
    cerveau._point_de_reprise = len(cerveau.messages)
    cerveau.messages.append({"role": "user", "content": "deuxieme"})
    cerveau.messages.append({"role": "assistant", "content": [bloc_outil("x", {})]})

    cerveau.nettoyer_tour_incomplet()
    assert len(cerveau.messages) == 2, cerveau.messages
    assert cerveau.messages[-1]["role"] == "assistant"
    print("  OK  tour interrompu retire de l'historique")


def test_config_resiste_aux_valeurs_invalides():
    import importlib
    import os

    from jarvis import config as module_config

    anciennes = {c: os.environ.get(c) for c in
                 ("JARVIS_SILENCE", "JARVIS_EFFORT", "JARVIS_MIC_THRESHOLD")}
    os.environ.update({"JARVIS_SILENCE": "beaucoup", "JARVIS_EFFORT": "turbo",
                       "JARVIS_MIC_THRESHOLD": "99"})
    try:
        recharge = importlib.reload(module_config)
        assert recharge.config.silence_fin_phrase == 0.9
        assert recharge.config.effort == "medium"
        assert recharge.config.seuil_micro == 0.015
    finally:
        for cle, valeur in anciennes.items():
            if valeur is None:
                os.environ.pop(cle, None)
            else:
                os.environ[cle] = valeur
        importlib.reload(module_config)
    print("  OK  un .env casse ne bloque pas le demarrage")


if __name__ == "__main__":
    tests = [valeur for nom, valeur in sorted(globals().items())
             if nom.startswith("test_") and callable(valeur)]
    print(f"\n{len(tests)} tests\n")
    echecs = 0
    for test in tests:
        try:
            test()
        except AssertionError as err:
            echecs += 1
            print(f"  ECHEC  {test.__name__} : {err}")
        except Exception as err:  # noqa: BLE001
            echecs += 1
            print(f"  ERREUR {test.__name__} : {type(err).__name__} {err}")
    print(f"\n{len(tests) - echecs}/{len(tests)} reussis")
    sys.exit(1 if echecs else 0)
