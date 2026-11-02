"""
Command-line training script.

Examples:
    python train.py                                  # train both models
    python train.py --algorithm decision_tree --max-depth 5
    python train.py --algorithm logistic_regression --C 0.5 --activate

Inside the running container:
    podman exec -it loan-app python train.py --algorithm logistic_regression --activate
"""
import argparse
import json
import logging
import os

from app.ml import ALGORITHMS, ModelManager

BASE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser(description="Train the loan approval models")
    ap.add_argument("--algorithm", choices=list(ALGORITHMS) + ["all"], default="all")
    ap.add_argument("--max-depth", type=int, default=4)
    ap.add_argument("--min-samples-leaf", type=int, default=10)
    ap.add_argument("--C", type=float, default=1.0)
    ap.add_argument("--test-size", type=float, default=0.2)
    ap.add_argument("--activate", action="store_true", help="make this the model used for predictions")
    ap.add_argument("--model-dir", default=os.environ.get("MODEL_DIR", os.path.join(BASE, "models")))
    ap.add_argument("--data", default=os.path.join(os.environ.get("DATA_DIR", os.path.join(BASE, "data")), "loan_data.csv"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    mgr = ModelManager(args.model_dir, args.data)
    algos = list(ALGORITHMS) if args.algorithm == "all" else [args.algorithm]
    for algo in algos:
        params = ({"max_depth": args.max_depth, "min_samples_leaf": args.min_samples_leaf}
                  if algo == "decision_tree" else {"C": args.C})
        meta = mgr.train(algo, params, args.test_size)
        print(f"\n=== {meta['algorithm_label']} (v{meta['version']}) ===")
        print(json.dumps(meta["metrics"], indent=2))
        print("Confusion matrix [actual Approved/Rejected x predicted]:", meta["confusion_matrix"]["matrix"])
    if args.activate and len(algos) == 1:
        mgr.set_active(algos[0])
        print(f"\nActive model -> {algos[0]}")
    elif not os.path.exists(os.path.join(args.model_dir, "active.json")):
        mgr.set_active("decision_tree")


if __name__ == "__main__":
    main()
