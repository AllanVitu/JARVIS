"""Transcription locale avec faster-whisper.

Le modele tourne sur le processeur en quantification int8 : sur une machine
recente, `small` transcrit une phrase de 5 secondes en moins d'une seconde,
et rien ne sort de la machine.

Tailles utiles : `tiny` (tres rapide, approximatif), `base`, `small` (bon
compromis, defaut), `medium` (precis mais lourd).
"""

from __future__ import annotations

import numpy as np

FREQUENCE = 16_000


class Oreille:
    def __init__(self, modele: str = "small", langue: str = "fr") -> None:
        self.nom_modele = modele
        self.langue = langue
        self._modele = None

    def charger(self) -> None:
        """Charge le modele (telecharge au premier lancement, ~500 Mo pour
        `small`). Appele explicitement pour que l'attente soit visible."""
        if self._modele is not None:
            return
        from faster_whisper import WhisperModel

        self._modele = WhisperModel(
            self.nom_modele, device="cpu", compute_type="int8"
        )

    def transcrire(self, audio: np.ndarray) -> str:
        """`audio` : mono float32 a 16 kHz, valeurs dans [-1, 1]."""
        if audio is None or audio.size == 0:
            return ""
        self.charger()

        segments, _ = self._modele.transcribe(
            audio.astype(np.float32),
            language=self.langue,
            beam_size=1,              # gourmand : on privilegie la latence
            vad_filter=True,          # coupe les silences residuels
            condition_on_previous_text=False,
            temperature=0.0,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
