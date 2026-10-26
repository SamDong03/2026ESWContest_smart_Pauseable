

import argparse
import logging
from typing import Optional, Set

import onnx

_LOGGER = logging.getLogger(__name__)


def add_alignment_output(
    model: onnx.ModelProto, tensor_name: Optional[str] = None
) -> str:
    pass


    if tensor_name:
        ceil_tensor_name = tensor_name
    else:
        ceil_tensor_names: Set[str] = set()
        for node in model.graph.node:
            if node.op_type != "Ceil":
                continue

            ceil_tensor_names.update(node.output)

        if not ceil_tensor_names:
            raise ValueError("No ceil tensors detected. Provide tensor_name manually.")

        if len(ceil_tensor_names) > 1:
            raise ValueError(
                f"Multiple ceil tensors detected, provide tensor_name manually: "
                f"{ceil_tensor_names}"
            )

        ceil_tensor_name = next(iter(ceil_tensor_names))
        _LOGGER.debug("Detected tensor name: %s", ceil_tensor_name)

    if any(output.name == ceil_tensor_name for output in model.graph.output):
        raise ValueError(f"Tensor is already marked as output: {ceil_tensor_name}")

    ceil_value_info = onnx.helper.ValueInfoProto()
    ceil_value_info.name = ceil_tensor_name
    model.graph.output.append(ceil_value_info)

    return ceil_tensor_name


def main() -> int:
    pass
    parser = argparse.ArgumentParser()
    parser.add_argument("model", help="Path to ONNX voice model")
    parser.add_argument(
        "--output", help="Path to write output model (default: overwrite)"
    )
    parser.add_argument(
        "--tensor-name", help="Name of tensor to mark as output (default: autodetect)"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    if not args.output:

        args.output = args.model

    model = onnx.load(args.model)

    try:
        ceil_tensor_name = add_alignment_output(model, args.tensor_name)
    except ValueError as error:
        _LOGGER.fatal("%s", error)
        return 1

    _LOGGER.info("Marked tensor as output: %s", ceil_tensor_name)

    onnx.save(model, args.output)
    _LOGGER.info("Successfully wrote %s", args.output)

    return 0


if __name__ == "__main__":
    main()
