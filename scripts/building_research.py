"""Train/adapt or compare building models against a frozen study definition."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("train", "compare"))
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--initial-model", default="whu-unetplusplus-efficientnet-b4")
    parser.add_argument("--mode", choices=("head", "decoder"), default="head")
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--learning-rate", type=float, default=.001)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--install-as")
    parser.add_argument("--enhanced-training", action="store_true")
    parser.add_argument("--max-samples", type=int, default=256)
    parser.add_argument("--cache-mb", type=int, default=2048)
    parser.add_argument("--early-stop-patience", type=int, default=5)
    parser.add_argument("--validation-only", action="store_true")
    parser.add_argument("--augmentation", choices=("none", "flips"), default="none", help="Comparison inference mode")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if args.offline:
        from scripts.building_benchmark import deny_network
        deny_network()
    if args.operation == "train":
        from vision.building_training import train_model
        result = train_model(args.dataset, {"initial_model_id": args.initial_model, "mode": args.mode,
            "epochs": args.epochs, "learning_rate": args.learning_rate, "batch_size": args.batch_size,
            "device": args.device, "enhanced_training": args.enhanced_training,
            "max_samples": args.max_samples, "cache_mb": args.cache_mb,
            "early_stop_patience": args.early_stop_patience}, args.output,
            progress=lambda value: print("training_progress", round(value, 3), flush=True) if value > .3 else None)
        if args.install_as:
            from vision.building_research_store import install_training_model
            result["installed"] = install_training_model(args.output, args.install_as)
        print(json.dumps(result, indent=2))
    else:
        from vision.building_study import compare_models
        if not args.models:
            raise SystemExit("Choose two or more --models.")
        result = compare_models(args.dataset, args.models, args.output, evaluate_test=not args.validation_only,
            augmentation=args.augmentation,
            progress=lambda value: print("comparison_progress", round(value, 3), flush=True))
        print(json.dumps({"selection": result["selection"],
            "test": {key: value["aggregate"] for key, value in result["test"].items()}}, indent=2))


if __name__ == "__main__":
    main()
