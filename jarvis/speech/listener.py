"""Capture micro avec detection d'activite vocale.

On evite volontairement une dependance de detection de mot de reveil
(Porcupine demande une cle, openWakeWord tire onnxruntime + un modele) :
le micro decoupe les phrases par l'energie du signal, Whisper les transcrit,
et c'est le texte transcrit qui est compare au mot de reveil. Ca marche
hors-ligne, sans compte tiers, et le mot de reveil se change dans le .env.
"""

from __future__ import annotations

import queue
import threading
import time

import numpy as np

FREQUENCE = 16_000
TAILLE_BLOC = 1024          # ~64 ms par bloc
DUREE_BLOC = TAILLE_BLOC / FREQUENCE


class Micro:
    """Decoupe le flux du micro en phrases.

    Une phrase commence des que l'energie depasse le seuil et se termine
    apres `silence_fin` secondes sous le seuil.
    """

    def __init__(
        self,
        seuil: float = 0.015,
        silence_fin: float = 0.9,
        duree_max: float = 20.0,
        marge_avant: float = 0.35,
    ) -> None:
        self.seuil = seuil
        self.silence_fin = silence_fin
        self.duree_max = duree_max
        # On garde un peu de son *avant* le declenchement : sans ca, la
        # premiere syllabe est systematiquement coupee.
        self.blocs_marge = max(1, int(marge_avant / DUREE_BLOC))
        self._file: queue.Queue[np.ndarray] = queue.Queue()
        self._flux = None
        self._en_pause = threading.Event()

    # ------------------------------------------------------------ cycle de vie

    def demarrer(self) -> None:
        import sounddevice as sd

        if self._flux is not None:
            return

        def rappel(donnees, _trames, _horloge, statut):  # noqa: ANN001
            if statut:
                pass  # depassements ponctuels : sans consequence ici
            if not self._en_pause.is_set():
                self._file.put(donnees[:, 0].copy())

        self._flux = sd.InputStream(
            samplerate=FREQUENCE,
            channels=1,
            dtype="float32",
            blocksize=TAILLE_BLOC,
            callback=rappel,
        )
        self._flux.start()

    def arreter(self) -> None:
        if self._flux is not None:
            self._flux.stop()
            self._flux.close()
            self._flux = None

    def suspendre(self) -> None:
        """A appeler pendant que JARVIS parle, pour qu'il ne s'entende pas."""
        self._en_pause.set()
        self.vider()

    def reprendre(self) -> None:
        self.vider()
        self._en_pause.clear()

    def vider(self) -> None:
        while not self._file.empty():
            try:
                self._file.get_nowait()
            except queue.Empty:
                break

    # -------------------------------------------------------------- capture

    def niveau(self, bloc: np.ndarray) -> float:
        """Energie efficace (RMS) du bloc."""
        return float(np.sqrt(np.mean(np.square(bloc))))

    def capturer_phrase(self, attente_max: float | None = None) -> np.ndarray | None:
        """Bloque jusqu'a capturer une phrase complete.

        Renvoie le signal, ou None si `attente_max` s'ecoule sans que
        personne ne parle.
        """
        self.demarrer()

        precedents: list[np.ndarray] = []
        phrase: list[np.ndarray] = []
        parle = False
        silence = 0.0
        debut_attente = time.monotonic()
        debut_phrase = 0.0

        while True:
            try:
                bloc = self._file.get(timeout=0.5)
            except queue.Empty:
                if not parle and attente_max is not None:
                    if time.monotonic() - debut_attente > attente_max:
                        return None
                continue

            fort = self.niveau(bloc) > self.seuil

            if not parle:
                # Tampon glissant : on conserve la marge avant declenchement.
                precedents.append(bloc)
                if len(precedents) > self.blocs_marge:
                    precedents.pop(0)

                if fort:
                    parle = True
                    debut_phrase = time.monotonic()
                    phrase = [*precedents, bloc]
                    silence = 0.0
                elif attente_max is not None and time.monotonic() - debut_attente > attente_max:
                    return None
                continue

            phrase.append(bloc)
            silence = 0.0 if fort else silence + DUREE_BLOC

            trop_long = time.monotonic() - debut_phrase > self.duree_max
            if silence >= self.silence_fin or trop_long:
                signal = np.concatenate(phrase)
                # Moins de 0,3 s de son utile : c'est un claquement, pas une phrase.
                if signal.size < int(0.3 * FREQUENCE):
                    parle, phrase, precedents = False, [], []
                    continue
                return signal


def contient_mot_reveil(texte: str, mot: str) -> bool:
    """Tolerant aux transcriptions approximatives de Whisper : « Jarvis »
    ressort souvent en « Jarvice », « Jervis » ou « Charvis »."""
    normalise = "".join(c for c in texte.lower() if c.isalnum() or c.isspace())
    if mot in normalise:
        return True
    if mot == "jarvis":
        return any(
            variante in normalise
            for variante in ("jarvice", "jervis", "charvis", "jarvi", "javis", "darvis")
        )
    return False


def retirer_mot_reveil(texte: str, mot: str) -> str:
    """Enleve le mot de reveil en tete pour ne garder que la demande."""
    mots = texte.split()
    if mots and contient_mot_reveil(mots[0], mot):
        mots = mots[1:]
    reste = " ".join(mots).lstrip(" ,.!?:;")
    return reste or texte
