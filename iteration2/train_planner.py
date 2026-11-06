
import argparse

from planner.trajectory_loader import load_trajectory_file
from planner.model_training import (
    train_and_evaluate,
    save_models
)
from planner.reporting import save_evaluation_reports


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "trajectory_json",
        help="Path to reviewed investigation trajectories"
    )

    args = parser.parse_args()

    # Load approved investigation examples.
    examples = load_trajectory_file(
        args.trajectory_json
    )

    # Train Logistic Regression and Random Forest.
    trained = train_and_evaluate(examples)

    # Save both models and the preprocessor.
    model_path = save_models(
        trained,
        "planner/models/cyfinx_planner.joblib"
    )

    # Generate full evaluation reports.
    report = save_evaluation_reports(
        examples,
        trained,
        output_dir="planner/reports"
    )

    print("\nCYFINX ML PLANNER EVALUATION")
    print("=" * 45)

    print(
        "Training cases:",
        report["training_cases"]
    )

    print(
        "Testing cases:",
        report["testing_cases"]
    )

    print(
        "Training examples:",
        report["training_examples"]
    )

    print(
        "Testing examples:",
        report["testing_examples"]
    )

    for model_name, scores in report["models"].items():

        print("\nMODEL:", model_name.upper())
        print("=" * 45)

        print(f"Accuracy:          {scores['accuracy']:.4f}")
        print(f"Macro Precision:   {scores['precision_macro']:.4f}")
        print(f"Macro Recall:      {scores['recall_macro']:.4f}")
        print(f"Macro F1:          {scores['f1_macro']:.4f}")
        print(f"Weighted F1:       {scores['f1_weighted']:.4f}")
        print(f"Top 3 Accuracy:    {scores['top3_accuracy']:.4f}")

        print(
            "Trained action classes:",
            scores["trained_action_count"]
        )

        print(
            "Missing training actions:",
            scores["missing_training_actions"]
        )

        print(
            "Unseen test actions:",
            scores["unseen_test_actions"]
        )

    print("\nModel saved to:", model_path)
    print("Reports saved to: planner/reports/")


if __name__ == "__main__":
    main()
