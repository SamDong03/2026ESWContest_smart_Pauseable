

import logging
from typing import Optional

import torch

_LOGGER = logging.getLogger(__name__)


_UTMOS_REPO = "tarepan/SpeechMOS:v1.2.0"
_UTMOS_MODEL = "utmos22_strong"


class MosPredictor:
    pass

    def __init__(self, name: str = "utmos") -> None:
        self.name = name
        self._model = None
        self._disabled = False

    def _ensure_model(self) -> None:
        if (self._model is not None) or self._disabled:
            return

        try:
            if self.name == "utmos":
                model = torch.hub.load(_UTMOS_REPO, _UTMOS_MODEL, trust_repo=True)
                model.eval()
                self._model = model
            else:
                raise ValueError(f"Unknown MOS predictor: {self.name!r}")
        except Exception as exc:  # noqa: BLE001 - never let this break training
            _LOGGER.warning(
                "Could not load MOS predictor %r (%s); val_mos logging disabled",
                self.name,
                exc,
            )
            self._disabled = True

    @torch.inference_mode()
    def score(self, audio: torch.Tensor, sample_rate: int) -> Optional[float]:
        pass


        self._ensure_model()
        if self._model is None:
            return None


        device = next(self._model.parameters()).device
        wave = audio.detach().float().flatten().unsqueeze(0).to(device)

        try:
            score = self._model(wave, sample_rate)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            _LOGGER.warning("MOS scoring failed (%s); val_mos logging disabled", exc)
            self._disabled = True
            return None

        return float(torch.as_tensor(score).mean().item())
