"""Synthese vocale.

Voie principale : edge-tts (voix neuronales Microsoft, gratuites, tres bonnes
en francais). Le MP3 renvoye est decode avec PyAV (deja installe comme
dependance de faster-whisper) puis joue par sounddevice.

Voie de secours : pyttsx3 / SAPI, entierement hors-ligne, si le reseau ou
edge-tts fait defaut.

La lecture se fait phrase par phrase : la voix demarre plus tot et une
interruption s'applique presque immediatement.
"""

from __future__ import annotations

import asyncio
import io
import re
import threading

import numpy as np

FREQUENCE = 24_000
# Coupe apres . ! ? … ou saut de ligne, en gardant la ponctuation.
DECOUPE_PHRASES = re.compile(r"(?<=[.!?…])\s+|\n+")
# Le TTS lit les asterisques et les diese : on nettoie avant de parler.
MARKDOWN = re.compile(r"[*_`#>]+")


def nettoyer_pour_la_voix(texte: str) -> str:
    texte = MARKDOWN.sub("", texte)
    texte = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", texte)   # liens markdown
    texte = re.sub(r"https?://\S+", "le lien", texte)
    return re.sub(r"[ \t]+", " ", texte).strip()


class Voix:
    def __init__(self, voix: str = "fr-FR-HenriNeural", vitesse: str = "+8%") -> None:
        self.voix = voix
        self.vitesse = vitesse
        self._stop = threading.Event()
        self._parle = threading.Event()
        self._moteur_secours = None
        self._edge_disponible = True

    # ------------------------------------------------------------ interface

    @property
    def en_train_de_parler(self) -> bool:
        return self._parle.is_set()

    def stopper(self) -> None:
        """Interrompt la lecture en cours (appelable depuis un autre thread)."""
        self._stop.set()

    def parler(self, texte: str) -> None:
        texte = nettoyer_pour_la_voix(texte)
        if not texte:
            return

        self._stop.clear()
        self._parle.set()
        try:
            if self._edge_disponible:
                try:
                    self._parler_edge(texte)
                    return
                except Exception:  # noqa: BLE001 - reseau coupe, voix inconnue...
                    self._edge_disponible = False
            self._parler_secours(texte)
        finally:
            self._parle.clear()

    # ----------------------------------------------------------- edge-tts

    def _parler_edge(self, texte: str) -> None:
        import sounddevice as sd

        phrases = [p.strip() for p in DECOUPE_PHRASES.split(texte) if p.strip()]
        for phrase in phrases:
            if self._stop.is_set():
                break
            echantillons = asyncio.run(self._synthetiser(phrase))
            if echantillons.size == 0 or self._stop.is_set():
                continue

            sd.play(echantillons, FREQUENCE)
            # On attend la duree exacte de la phrase, mais `wait` rend la main
            # immediatement si `stopper()` est appele : coupure nette, sans
            # attente active ni dependance a l'etat interne de sounddevice.
            duree = echantillons.size / FREQUENCE
            if self._stop.wait(timeout=duree + 0.1):
                sd.stop()
                return
            sd.wait()

    async def _synthetiser(self, phrase: str) -> np.ndarray:
        import edge_tts

        communication = edge_tts.Communicate(phrase, self.voix, rate=self.vitesse)
        mp3 = bytearray()
        async for morceau in communication.stream():
            if morceau["type"] == "audio":
                mp3.extend(morceau["data"])
        return _decoder_mp3(bytes(mp3))

    # ------------------------------------------------------------- secours

    def _parler_secours(self, texte: str) -> None:
        try:
            import pyttsx3
        except ImportError:
            print(f"[voix indisponible] {texte}")
            return

        # pyttsx3 garde mal son etat entre deux runs : on recree le moteur.
        moteur = pyttsx3.init()
        moteur.setProperty("rate", 185)
        for voix in moteur.getProperty("voices"):
            if "fr" in (getattr(voix, "id", "") + getattr(voix, "name", "")).lower():
                moteur.setProperty("voice", voix.id)
                break
        moteur.say(texte)
        moteur.runAndWait()
        moteur.stop()


def _decoder_mp3(donnees: bytes) -> np.ndarray:
    """MP3 -> mono float32 a 24 kHz, pret pour sounddevice."""
    if not donnees:
        return np.zeros(0, dtype=np.float32)

    import av

    morceaux: list[np.ndarray] = []
    with av.open(io.BytesIO(donnees), format="mp3") as conteneur:
        reechantillonneur = av.audio.resampler.AudioResampler(
            format="flt", layout="mono", rate=FREQUENCE
        )
        for trame in conteneur.decode(audio=0):
            for convertie in reechantillonneur.resample(trame):
                morceaux.append(convertie.to_ndarray().reshape(-1))
        for convertie in reechantillonneur.resample(None):   # vidange finale
            morceaux.append(convertie.to_ndarray().reshape(-1))

    if not morceaux:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(morceaux).astype(np.float32)
