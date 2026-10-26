

import re
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import List, Optional, Set, Tuple, Union

_DIR = Path(__file__).parent
ESPEAK_DATA_DIR = _DIR / "espeak-ng-data"


class EspeakPhonemizer:
    pass

    def __init__(self, espeak_data_dir: Union[str, Path] = ESPEAK_DATA_DIR) -> None:
        pass
        from . import espeakbridge

        espeakbridge.initialize(str(espeak_data_dir))

    def phonemize(
        self,
        voice: str,
        text: str,
        vowel_clusters: Optional[Set[Tuple[str, ...]]] = None,
    ) -> list[list[str]]:
        pass
        from . import espeakbridge

        espeakbridge.set_voice(voice)

        all_phonemes: list[list[str]] = []
        sentence_phonemes: list[str] = []

        clause_phonemes = espeakbridge.get_phonemes(text)
        for phonemes_str, terminator_str, end_of_sentence in clause_phonemes:


            phonemes_str = re.sub(r"\([^)]+\)", "", phonemes_str)


            phonemes_str += terminator_str
            if terminator_str in (",", ":", ";"):

                phonemes_str += " "


            sentence_phonemes.extend(list(unicodedata.normalize("NFD", phonemes_str)))

            if end_of_sentence:
                if vowel_clusters:
                    sentence_phonemes = _merge_known_vowel_clusters(
                        sentence_phonemes, vowel_clusters
                    )

                all_phonemes.append(sentence_phonemes)
                sentence_phonemes = []

        if sentence_phonemes:

            if vowel_clusters:
                sentence_phonemes = _merge_known_vowel_clusters(
                    sentence_phonemes, vowel_clusters
                )

            all_phonemes.append(sentence_phonemes)

        return all_phonemes


def _merge_known_vowel_clusters(
    phones: Sequence[str], clusters: Set[Tuple[str, ...]]
) -> List[str]:
    pass
    max_len = max(len(k) for k in clusters)
    out: list[str] = []
    i = 0

    while i < len(phones):
        match: Tuple[str, ...] | None = None

        for n in range(min(max_len, len(phones) - i), 1, -1):
            candidate = tuple(phones[i : i + n])
            if candidate in clusters:
                match = candidate
                break

        if match is not None:
            out.append("".join(match))
            i += len(match)
        else:
            out.append(phones[i])
            i += 1

    return out
