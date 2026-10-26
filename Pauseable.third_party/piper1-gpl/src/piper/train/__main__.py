import logging

import torch
from lightning.pytorch.callbacks import ModelCheckpoint
from lightning.pytorch.cli import LightningCLI

from .vits.dataset import VitsDataModule
from .vits.lightning import VitsModel

_LOGGER = logging.getLogger(__package__)


_MONITOR = "val_mel"

_DEFAULT_CALLBACKS = [
    ModelCheckpoint(
        monitor=_MONITOR,
        mode="min",
        save_top_k=5,
        save_last=True,
        filename="epoch={epoch}-val_mel={val_mel:.4f}",
        auto_insert_metric_name=False,
    ),
]


class VitsLightningCLI(LightningCLI):
    def add_arguments_to_parser(self, parser):
        parser.link_arguments("data.batch_size", "model.batch_size")
        parser.link_arguments("data.num_symbols", "model.num_symbols")
        parser.link_arguments("model.num_speakers", "data.num_speakers")
        parser.link_arguments("model.sample_rate", "data.sample_rate")
        parser.link_arguments("model.filter_length", "data.filter_length")
        parser.link_arguments("model.hop_length", "data.hop_length")
        parser.link_arguments("model.win_length", "data.win_length")
        parser.link_arguments("model.segment_size", "data.segment_size")


def main():
    logging.basicConfig(level=logging.INFO)
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.deterministic = False
    _cli = VitsLightningCLI(  # noqa: ignore=F841
        VitsModel,
        VitsDataModule,
        trainer_defaults={"max_epochs": -1, "callbacks": _DEFAULT_CALLBACKS},
    )


if __name__ == "__main__":
    main()
