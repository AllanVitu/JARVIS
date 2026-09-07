# JARVIS

Un assistant personnel qui t'écoute, agit sur ton PC, cherche sur le web,
gère ton agenda — et se souvient de toi d'une session à l'autre.

Propulsé par **Claude Opus 5**. Reconnaissance vocale **100 % locale**
(rien de ton micro ne quitte la machine, seul le texte transcrit part à l'API).

```
      toi ──parole──►  micro ──VAD──►  Whisper (local)  ──texte──┐
                                                                  │
   haut-parleur ◄──audio──  edge-tts  ◄──texte──  Claude Opus 5 ◄─┘
                                                        │
                                              ┌─────────┴──────────┐
                                          17 outils        recherche web
                                       (PC · mémoire ·     (côté Anthropic)
                                        tâches · Google)
```

---

## Installation

Tout est déjà en place dans ce dépôt. Il ne te reste que la clé API.

```powershell
# 1. Copier le modèle de configuration
copy .env.example .env

# 2. Ouvrir .env et coller ta clé (console.anthropic.com)
#    ANTHROPIC_API_KEY=sk-ant-...

# 3. Lancer
.venv\Scripts\python.exe jarvis.py
```

Si tu repars d'une machine vierge :

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> Python **3.13** et pas 3.14 : `ctranslate2` (le moteur de Whisper) n'a pas
> encore de wheels pour 3.14, il faudrait compiler.

---

## Utilisation

```powershell
.venv\Scripts\python.exe jarvis.py              # mode texte
.venv\Scripts\python.exe jarvis.py --voix       # mode vocal
.venv\Scripts\python.exe jarvis.py "eteins le son et dis-moi l'etat du PC"
```

Le **premier lancement en mode vocal** télécharge le modèle Whisper
(~460 Mo pour `small`). Ensuite, c'est instantané et hors-ligne.

### Mode vocal

Dis **« Jarvis »** suivi de ta demande. Après sa réponse, tu as 12 secondes
pour enchaîner **sans répéter le mot de réveil** — la conversation reste
ouverte, comme avec quelqu'un dans la pièce.

- *« Jarvis, ouvre Spotify et baisse le son à 30 »*
- *« Jarvis, qu'est-ce que j'ai de prévu demain ? »*
- *« Jarvis, retiens que je suis allergique aux arachides »*
- *« Jarvis, cherche les news sur la sortie de GTA 6 »*
- *« au revoir »* pour quitter, *« passe au clavier »* pour revenir en texte

Le micro se coupe pendant que JARVIS parle : il ne s'entend pas lui-même.

### Commandes du terminal

| Commande | Effet |
|---|---|
| `/voix` | bascule texte ↔ vocal |
| `/memoire` | affiche tout ce que JARVIS sait de toi |
| `/taches` | liste les tâches en cours |
| `/oublie <id>` | supprime un souvenir |
| `/reset` | nouvelle conversation (la mémoire est gardée) |
| `/aide` · `/quit` | aide · quitter |

---

## Ce qu'il sait faire

**Contrôle du PC** — ouvrir une application ou un site, chercher et lire des
fichiers, régler le volume, couper le son, captures d'écran, état système
(CPU, RAM, disque, batterie), verrouiller / mettre en veille / éteindre,
exécuter une commande PowerShell.

**Recherche web** — via l'outil serveur d'Anthropic : pas de clé tierce, pas
de scraping. Il cherche de lui-même quand il ignore quelque chose d'actuel.

**Mémoire** — il appelle `retenir` tout seul quand il apprend un fait durable
sur toi. Au démarrage, les faits connus et la fin de la dernière conversation
sont réinjectés dans son contexte. Il te reconnaît.

**Tâches** — ajouter, lister, terminer, supprimer, avec échéance et priorité.

**Agenda & mail** — Google Calendar et Gmail (lecture, création d'événement,
envoi de mail). Voir *Brancher Google* plus bas.

---

## Sécurité

Les actions irréversibles demandent une confirmation explicite avant de
s'exécuter :

- exécuter une commande PowerShell
- éteindre / redémarrer le PC
- envoyer un e-mail
- supprimer un souvenir ou une tâche

En mode vocal, la confirmation se demande **à l'oral** — tu restes mains
libres. Sans réponse en 8 secondes, l'action est annulée.

La lecture de fichiers est confinée aux dossiers de `JARVIS_ALLOWED_DIRS`
(par défaut Documents, Downloads, Desktop). Une tentative hors périmètre est
refusée, pas silencieusement ignorée.

Pour désactiver les confirmations (déconseillé) : `JARVIS_CONFIRM=false`.

---

## Réglages (`.env`)

| Variable | Défaut | Rôle |
|---|---|---|
| `JARVIS_EFFORT` | `medium` | profondeur de raisonnement — `low` = plus vif, `high`/`max` = plus fouillé |
| `JARVIS_MODEL` | `claude-opus-5` | `claude-sonnet-5` pour réduire le coût |
| `JARVIS_WAKE_WORD` | `jarvis` | mot de réveil |
| `JARVIS_TTS_VOICE` | `fr-FR-HenriNeural` | aussi `DeniseNeural`, `EloiseNeural`, `fr-CA-AntoineNeural` |
| `JARVIS_WHISPER_MODEL` | `small` | `tiny`/`base` = plus rapide, `medium` = plus précis |
| `JARVIS_MIC_THRESHOLD` | `0.015` | monte-le si la pièce est bruyante |
| `JARVIS_SILENCE` | `0.9` | silence (s) qui marque la fin d'une phrase |
| `JARVIS_FOLLOWUP_WINDOW` | `12` | durée (s) pour enchaîner sans mot de réveil |
| `JARVIS_ALLOWED_DIRS` | dossiers perso | périmètre de lecture, séparés par `;` |

---

## Brancher Google (optionnel)

Sans cette étape, JARVIS marche normalement — il sait simplement qu'il n'a
pas accès à l'agenda. À faire une seule fois :

1. [console.cloud.google.com](https://console.cloud.google.com) → nouveau projet
2. **API et services → Bibliothèque** → active *Google Calendar API* et *Gmail API*
3. **Écran de consentement OAuth** → type **Externe** → ajoute ton adresse
   Gmail dans **Utilisateurs de test**
4. **Identifiants → Créer → ID client OAuth → Application de bureau**
5. Télécharge le JSON, renomme-le **`credentials.json`**, dépose-le à la
   racine du projet

Au premier appel à l'agenda, le navigateur s'ouvre pour l'autorisation. Le
jeton est ensuite stocké dans `token.json`. Les deux fichiers sont dans le
`.gitignore` — ils ne partiront jamais sur GitHub.

---

## Architecture

```
jarvis.py                point d'entrée
jarvis/
  config.py              configuration, lue depuis .env
  brain.py               boucle agentique Claude
  memory.py              SQLite : faits, tâches, historique
  cli.py                 interfaces texte et vocale
  speech/
    listener.py          capture micro + détection d'activité vocale
    stt.py               transcription Whisper locale
    tts.py               synthèse edge-tts (+ secours SAPI hors-ligne)
  tools/
    __init__.py          registre + garde-fou de confirmation
    system.py            contrôle du PC
    personal.py          mémoire et tâches
    google.py            agenda et mail
data/jarvis.db           ta mémoire (jamais commitée)
```

Quelques partis pris, si tu veux modifier le code :

- **Boucle agentique manuelle** plutôt que le tool runner du SDK. Il fallait
  gérer `pause_turn` (la recherche web s'interrompt côté serveur au bout de
  quelques itérations), diffuser le texte au fil de l'eau vers la voix, et
  intercepter chaque appel d'outil pour l'afficher et le confirmer.
- **Pas de détection de mot de réveil dédiée.** Porcupine exige une clé,
  openWakeWord tire `onnxruntime` et un modèle. Ici le micro découpe les
  phrases par l'énergie du signal, Whisper transcrit, et on compare le texte.
  Hors-ligne, sans compte tiers, et le mot se change dans le `.env`.
  `contient_mot_reveil` tolère les transcriptions approximatives
  (« Jarvice », « Jervis », « Charvis »…).
- **Prompt mis en cache.** L'identité et le contexte forment un préfixe figé
  pour la session, avec un point de cache à la fin : les tours suivants ne
  repaient pas les mêmes tokens. Les outils sont triés par nom pour que ce
  préfixe reste identique d'un appel à l'autre.
- **Consigne vocale vs texte.** À l'oral, le prompt interdit le markdown et
  vise trois phrases — du markdown lu à voix haute est insupportable.

### Ajouter un outil

Dans `jarvis/tools/system.py` (ou un nouveau module), écris la fonction puis
déclare-la :

```python
registre.enregistrer(
    "ma_fonction",
    "Ce que ça fait, écrit pour que le modèle sache quand l'appeler.",
    {"properties": {"argument": {"type": "string"}}, "required": ["argument"]},
    ma_fonction,
    sensible=True,   # si l'action est irréversible
    resume=lambda e: f"Faire X avec {e.get('argument')}",
)
```

La description est ce que lit le modèle pour décider : sois explicite sur
*quand* l'utiliser, pas seulement sur ce qu'elle fait.

---

## En cas de souci

**« Aucune clé API trouvée »** — `.env` absent ou `ANTHROPIC_API_KEY` non
renseignée. Le fichier doit être à la racine, à côté de `jarvis.py`.

**Il ne réagit pas à ma voix** — baisse `JARVIS_MIC_THRESHOLD` (0.008), et
vérifie le micro par défaut de Windows. Pour diagnostiquer :

```powershell
.venv\Scripts\python.exe -c "import sounddevice; print(sounddevice.query_devices())"
```

**Il se déclenche tout seul** — monte `JARVIS_MIC_THRESHOLD` (0.03).

**Il coupe la parole trop tôt** — monte `JARVIS_SILENCE` (1.3).

**La voix est robotique** — edge-tts n'a pas pu joindre le réseau, il est
retombé sur SAPI. Vérifie ta connexion.

**Transcription approximative** — passe `JARVIS_WHISPER_MODEL` à `medium`.
Plus lent au chargement, nettement plus précis.

---

## Coût

Facturé à l'usage sur ta clé Anthropic. Le prompt mis en cache et `effort`
réglé sur `medium` limitent la note. En usage personnel quotidien, compte
quelques dizaines de centimes par jour. Pour réduire : `JARVIS_MODEL=claude-sonnet-5`
ou `JARVIS_EFFORT=low`.

La transcription et la synthèse vocale ne coûtent rien (locales / gratuites).

---

## Licence

GPL-3.0 — voir [LICENSE](LICENSE).
