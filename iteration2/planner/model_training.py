
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import GroupShuffleSplit

from .actions import ALL_ACTIONS
from .action_masking import get_valid_actions
from .feature_extractor import extract_features
from .preprocessing import build_preprocessor, transform_features


def train_and_evaluate(examples, test_size=0.25, random_state=42):
    """
    Train models using reviewed investigation examples.

    All steps from one case stay in the same data partition.
    """

    if not examples:
        raise ValueError("No trajectory examples were provided")

    case_ids = [str(row["case_id"]) for row in examples]
    actions = [row["action"] for row in examples]

    if len(set(case_ids)) < 6:
        raise ValueError(
            "Provide at least 6 distinct reviewed cases"
        )

    if len(set(actions)) < 2:
        raise ValueError(
            "Training needs at least 2 distinct action labels"
        )

    if any(action not in ALL_ACTIONS for action in actions):
        raise ValueError("Unknown action in training examples")

    # Split by case, not individual investigation steps.
    splitter = GroupShuffleSplit(
        n_splits=1,
        test_size=test_size,
        random_state=random_state
    )

    train_idx, test_idx = next(
        splitter.split(
            np.zeros(len(examples)),
            actions,
            groups=case_ids
        )
    )

    train = [examples[i] for i in train_idx]
    test = [examples[i] for i in test_idx]

    train_cases = {row["case_id"] for row in train}
    test_cases = {row["case_id"] for row in test}

    assert train_cases.isdisjoint(test_cases), (
        "Case leakage detected"
    )

    y_train = [row["action"] for row in train]
    y_test = [row["action"] for row in test]

    if len(set(y_train)) < 2:
        raise ValueError(
            "Training split contains fewer than two action classes"
        )

    train_rows = [row["features"] for row in train]
    test_rows = [row["features"] for row in test]

    # Fit preprocessing using TRAINING DATA ONLY.
    preprocessor, training_df = build_preprocessor(
        train_rows
    )

    x_train = transform_features(
        preprocessor, train_rows
    )

    x_test = transform_features(
        preprocessor, test_rows
    )

    # Initialize the two ML models.
    models = {
        "logistic_regression": LogisticRegression(
            max_iter=2000,
            class_weight="balanced",
            random_state=random_state
        ),

        "random_forest": RandomForestClassifier(
            n_estimators=150,
            class_weight="balanced_subsample",
            random_state=random_state,
            n_jobs=-1
        )
    }

    metrics = {}

    for name, model in models.items():

        # Train the model.
        model.fit(x_train, y_train)

        # Predict next actions for held out cases.
        predictions = model.predict(x_test)

        # Get probabilities for action ranking.
        probabilities = model.predict_proba(x_test)
        class_names = list(model.classes_)

        # Calculate Top 3 accuracy.
        top_k = min(3, len(class_names))

        top_indices = np.argsort(
            probabilities, axis=1
        )[:, -top_k:]

        top3_hits = [
            y_test[i] in {
                class_names[j] for j in indices
            }
            for i, indices in enumerate(top_indices)
        ]

        metrics[name] = {
            "accuracy": float(
                accuracy_score(y_test, predictions)
            ),

            "macro_f1": float(
                f1_score(
                    y_test,
                    predictions,
                    average="macro",
                    zero_division=0
                )
            ),

            "top3_accuracy": float(
                np.mean(top3_hits)
            ),

            "trained_action_count": len(class_names)
        }

    return {
        "preprocessor": preprocessor,
        "models": models,
        "metrics": metrics,

        "train_case_ids": sorted(train_cases),
        "test_case_ids": sorted(test_cases),

        "train_example_count": len(train),
        "test_example_count": len(test),

        "feature_count": len(training_df.columns),

        "trained_actions": sorted(set(y_train)),

        "unseen_test_actions": sorted(
            set(y_test) - set(y_train)
        )
    }


def predict_next_action(
    state,
    trained,
    model_name="logistic_regression",
    available_tools=None
):
    """
    Use the trained model to recommend a valid action.
    """

    valid = set(
        get_valid_actions(state, available_tools)
    )

    if not valid:
        return {
            "recommended_action": None,
            "reason": "No valid actions"
        }

    model = trained["models"][model_name]

    # Convert current case state into ML features.
    row = extract_features(state)

    x = transform_features(
        trained["preprocessor"],
        [row]
    )

    # Predict action probabilities.
    probabilities = model.predict_proba(x)[0]

    # Keep only currently valid actions.
    eligible = [
        (action, float(score))
        for action, score in zip(
            model.classes_,
            probabilities
        )
        if action in valid
    ]

    if not eligible:

        # Safety fallback, not an ML prediction.
        fallback = (
            "RECOMMEND_HUMAN_REVIEW"
            if "RECOMMEND_HUMAN_REVIEW" in valid
            else None
        )

        return {
            "recommended_action": fallback,
            "selection_type": "fallback",
            "reason": "No trained class is currently valid"
        }

    # Select the highest scoring valid action.
    action, score = max(
        eligible,
        key=lambda pair: pair[1]
    )

    return {
        "recommended_action": action,
        "model_score": score,
        "selection_type": "model",
        "model_name": model_name
    }


def save_models(trained, output_path):
    """Save the trained models and preprocessor."""

    path = Path(output_path)
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    joblib.dump(trained, path)

    return path


def load_models(path):
    """Load only trusted model files from this project."""
    return joblib.load(path)
