
import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np

from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    precision_recall_fscore_support,
    confusion_matrix,
)

from .actions import ALL_ACTIONS
from .preprocessing import transform_features


def save_evaluation_reports(
    examples,
    trained,
    output_dir="planner/reports"
):
    """
    Generate evaluation reports using held out cases.

    The same test cases selected during model training
    are reused here. No model is refitted.
    """

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    test_case_ids = set(
        map(str, trained["test_case_ids"])
    )

    test_examples = [
        example for example in examples
        if str(example["case_id"]) in test_case_ids
    ]

    if not test_examples:
        raise ValueError("No held out examples found")

    if len(test_examples) != trained["test_example_count"]:
        raise ValueError("Test example count mismatch")

    y_true = [
        example["action"]
        for example in test_examples
    ]

    feature_rows = [
        example["features"]
        for example in test_examples
    ]

    x_test = transform_features(
        trained["preprocessor"],
        feature_rows
    )

    summary = {
        "evaluation_type": "held_out_cases",
        "training_cases": len(trained["train_case_ids"]),
        "testing_cases": len(test_case_ids),
        "training_examples": trained["train_example_count"],
        "testing_examples": len(test_examples),
        "test_action_distribution": dict(Counter(y_true)),
        "models": {}
    }

    for name, model in trained["models"].items():

        y_pred = model.predict(x_test)
        probabilities = model.predict_proba(x_test)

        # Overall classification metrics
        scores = {
            "accuracy": float(
                accuracy_score(y_true, y_pred)
            ),

            "precision_macro": float(
                precision_score(
                    y_true, y_pred,
                    average="macro",
                    zero_division=0
                )
            ),

            "recall_macro": float(
                recall_score(
                    y_true, y_pred,
                    average="macro",
                    zero_division=0
                )
            ),

            "f1_macro": float(
                f1_score(
                    y_true, y_pred,
                    average="macro",
                    zero_division=0
                )
            ),

            "f1_weighted": float(
                f1_score(
                    y_true, y_pred,
                    average="weighted",
                    zero_division=0
                )
            )
        }

        # Top 3 action accuracy
        classes = list(model.classes_)
        k = min(3, len(classes))

        top_indices = np.argsort(
            probabilities,
            axis=1
        )[:, -k:]

        top3_hits = [
            y_true[i] in {
                classes[j] for j in indices
            }
            for i, indices in enumerate(top_indices)
        ]

        scores["top3_accuracy"] = float(
            np.mean(top3_hits)
        )

        scores["trained_action_count"] = len(classes)
        scores["missing_training_actions"] = sorted(
            set(ALL_ACTIONS) - set(classes)
        )
        scores["unseen_test_actions"] = sorted(
            set(y_true) - set(classes)
        )

        # Per action precision, recall, F1 and support
        precision, recall, f1, support = (
            precision_recall_fscore_support(
                y_true,
                y_pred,
                labels=ALL_ACTIONS,
                zero_division=0
            )
        )

        per_action_path = (
            output / f"{name}_per_action.csv"
        )

        with per_action_path.open(
            "w", newline="", encoding="utf-8"
        ) as file:

            writer = csv.writer(file)

            writer.writerow([
                "Action",
                "Precision",
                "Recall",
                "F1_Score",
                "Support"
            ])

            for i, action in enumerate(ALL_ACTIONS):
                writer.writerow([
                    action,
                    round(float(precision[i]), 4),
                    round(float(recall[i]), 4),
                    round(float(f1[i]), 4),
                    int(support[i])
                ])

        # Confusion matrix for all 14 actions
        matrix = confusion_matrix(
            y_true,
            y_pred,
            labels=ALL_ACTIONS
        )

        matrix_path = (
            output / f"{name}_confusion_matrix.csv"
        )

        with matrix_path.open(
            "w", newline="", encoding="utf-8"
        ) as file:

            writer = csv.writer(file)
            writer.writerow(["Actual / Predicted"] + ALL_ACTIONS)

            for action, row in zip(ALL_ACTIONS, matrix):
                writer.writerow(
                    [action] + row.tolist()
                )

        summary["models"][name] = scores

    summary_path = output / "evaluation_summary.json"

    with summary_path.open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(
            summary,
            file,
            indent=4
        )

    return summary
