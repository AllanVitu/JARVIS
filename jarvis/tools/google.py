"""Outils Google : agenda et messagerie.

Cette integration est optionnelle. Sans `credentials.json` a la racine, les
outils ne sont pas enregistres du tout : JARVIS fonctionne normalement, il
sait simplement qu'il n'a pas acces a l'agenda. Voir le README, section
"Brancher Google", pour la procedure OAuth (a faire une seule fois).
"""

from __future__ import annotations

import base64
import re
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any

from ..config import config
from . import Registre

PERIMETRES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

_services: dict[str, Any] = {}


def integration_possible() -> bool:
    """Vrai si le fichier d'identifiants OAuth est present."""
    return config.credentials_google.is_file()


def _identifiants():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if config.token_google.is_file():
        creds = Credentials.from_authorized_user_file(str(config.token_google), PERIMETRES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        # Premiere connexion : ouvre le navigateur pour l'autorisation.
        flux = InstalledAppFlow.from_client_secrets_file(
            str(config.credentials_google), PERIMETRES
        )
        creds = flux.run_local_server(port=0)

    config.token_google.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _service(nom: str, version: str):
    cle = f"{nom}:{version}"
    if cle not in _services:
        from googleapiclient.discovery import build

        _services[cle] = build(
            nom, version, credentials=_identifiants(), cache_discovery=False
        )
    return _services[cle]


def _iso_local(valeur: str) -> str:
    """Accepte 'AAAA-MM-JJ HH:MM' ou un ISO complet, renvoie un ISO avec
    fuseau local (l'API Google refuse les dates naives)."""
    texte = valeur.strip().replace(" ", "T")
    if len(texte) == 10:
        texte += "T09:00:00"
    if len(texte) == 16:
        texte += ":00"
    moment = datetime.fromisoformat(texte)
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.isoformat()


# ------------------------------------------------------------------- agenda


def agenda_evenements(jours: int = 7, agenda: str = "primary") -> dict[str, Any]:
    debut = datetime.now(timezone.utc)
    fin = debut + timedelta(days=max(1, jours))

    reponse = (
        _service("calendar", "v3")
        .events()
        .list(
            calendarId=agenda,
            timeMin=debut.isoformat(),
            timeMax=fin.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        )
        .execute()
    )

    evenements = []
    for item in reponse.get("items", []):
        depart = item.get("start", {})
        evenements.append({
            "id": item.get("id"),
            "titre": item.get("summary", "(sans titre)"),
            "debut": depart.get("dateTime") or depart.get("date"),
            "journee_entiere": "date" in depart,
            "lieu": item.get("location"),
            "participants": [
                p.get("email") for p in item.get("attendees", []) if p.get("email")
            ][:8],
        })

    return {"periode_jours": jours, "nombre": len(evenements), "evenements": evenements}


def agenda_creer_evenement(
    titre: str,
    debut: str,
    fin: str = "",
    description: str = "",
    lieu: str = "",
) -> str:
    depart = _iso_local(debut)
    arrivee = _iso_local(fin) if fin else (
        datetime.fromisoformat(depart) + timedelta(hours=1)
    ).isoformat()

    corps: dict[str, Any] = {
        "summary": titre,
        "start": {"dateTime": depart},
        "end": {"dateTime": arrivee},
    }
    if description:
        corps["description"] = description
    if lieu:
        corps["location"] = lieu

    cree = (
        _service("calendar", "v3")
        .events()
        .insert(calendarId="primary", body=corps)
        .execute()
    )
    return f"Evenement cree : {titre} le {depart[:16].replace('T', ' a ')}. Lien : {cree.get('htmlLink', 'n/a')}"


# ---------------------------------------------------------------- messagerie


def _texte_du_message(charge: dict[str, Any]) -> str:
    """Extrait le corps texte, en descendant dans les parties MIME."""
    if charge.get("mimeType", "").startswith("text/plain"):
        donnees = charge.get("body", {}).get("data")
        if donnees:
            return base64.urlsafe_b64decode(donnees).decode("utf-8", errors="replace")
    for partie in charge.get("parts", []) or []:
        trouve = _texte_du_message(partie)
        if trouve:
            return trouve
    return ""


def mails_recents(nombre: int = 8, requete: str = "") -> dict[str, Any]:
    service = _service("gmail", "v1")
    liste = (
        service.users()
        .messages()
        .list(userId="me", maxResults=max(1, min(25, nombre)), q=requete or None)
        .execute()
    )

    messages = []
    for reference in liste.get("messages", []):
        complet = (
            service.users()
            .messages()
            .get(userId="me", id=reference["id"], format="full")
            .execute()
        )
        entetes = {
            h["name"].lower(): h["value"]
            for h in complet.get("payload", {}).get("headers", [])
        }
        corps = _texte_du_message(complet.get("payload", {}))
        messages.append({
            "id": reference["id"],
            "de": entetes.get("from", ""),
            "sujet": entetes.get("subject", "(sans sujet)"),
            "date": entetes.get("date", ""),
            "non_lu": "UNREAD" in complet.get("labelIds", []),
            "extrait": re.sub(r"\s+", " ", corps).strip()[:300],
        })

    return {"requete": requete or "(boite de reception)", "nombre": len(messages), "messages": messages}


def mail_envoyer(destinataire: str, sujet: str, corps: str) -> str:
    """Outil sensible : confirme avant envoi."""
    message = EmailMessage()
    message["To"] = destinataire
    message["Subject"] = sujet
    message.set_content(corps)

    encode = base64.urlsafe_b64encode(message.as_bytes()).decode()
    envoye = (
        _service("gmail", "v1")
        .users()
        .messages()
        .send(userId="me", body={"raw": encode})
        .execute()
    )
    return f"Message envoye a {destinataire} (id {envoye.get('id')})."


# ---------------------------------------------------------- enregistrement


def enregistrer(registre: Registre) -> None:
    if not integration_possible():
        return

    registre.enregistrer(
        "agenda_evenements",
        "Liste les evenements a venir dans l'agenda Google sur les N prochains jours.",
        {"properties": {
            "jours": {"type": "integer", "description": "Horizon en jours (defaut 7)"},
            "agenda": {"type": "string", "description": "Identifiant d'agenda, defaut 'primary'"},
        }, "required": []},
        agenda_evenements,
    )

    registre.enregistrer(
        "agenda_creer_evenement",
        "Cree un evenement dans l'agenda Google. Les dates s'ecrivent "
        "'AAAA-MM-JJ HH:MM'. Si la fin est omise, l'evenement dure une heure.",
        {"properties": {
            "titre": {"type": "string"},
            "debut": {"type": "string"},
            "fin": {"type": "string"},
            "description": {"type": "string"},
            "lieu": {"type": "string"},
        }, "required": ["titre", "debut"]},
        agenda_creer_evenement,
    )

    registre.enregistrer(
        "mails_recents",
        "Lit les messages recents de Gmail. La requete accepte la syntaxe "
        "Gmail (ex : 'is:unread', 'from:banque', 'newer_than:2d').",
        {"properties": {
            "nombre": {"type": "integer"},
            "requete": {"type": "string"},
        }, "required": []},
        mails_recents,
    )

    registre.enregistrer(
        "mail_envoyer",
        "Envoie un e-mail depuis le compte Gmail de l'utilisateur.",
        {"properties": {
            "destinataire": {"type": "string"},
            "sujet": {"type": "string"},
            "corps": {"type": "string"},
        }, "required": ["destinataire", "sujet", "corps"]},
        mail_envoyer,
        sensible=True,
        resume=lambda e: (
            f"Envoyer un mail a {e.get('destinataire')} "
            f"(sujet : {e.get('sujet')})"
        ),
    )
