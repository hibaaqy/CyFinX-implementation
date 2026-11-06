
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import (
    OneHotEncoder,
    StandardScaler,
)


# These fields contain text categories rather than quantities.
CATEGORICAL_FEATURES = [
    "case_source",
    "case_priority",
    "alert_type",
    "alert_criticality_level",
    "complaint_type",
    "complaint_channel",
    "transaction_type",
    "transaction_channel",
    "transaction_status",
    "kyc_status",
    "retailer_status",
    "retailer_type",
    "customer_account_status",
    "customer_segment",
]


def prepare_feature_dataframe(feature_rows):
    """
    Convert a list of extracted feature dictionaries
    into a DataFrame with consistent columns.
    """

    if not feature_rows:
        raise ValueError("No feature rows provided")

    df = pd.DataFrame(feature_rows)

    # Every row must have the same feature columns.
    # Missing keys become NaN.
    for column in CATEGORICAL_FEATURES:
        if column not in df.columns:
            df[column] = None

    categorical_columns = [
        col for col in CATEGORICAL_FEATURES
        if col in df.columns
    ]

    numeric_columns = [
        col for col in df.columns
        if col not in categorical_columns
    ]

    # Convert numerical features to numeric dtype.
    for column in numeric_columns:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    # Ensure categorical values have consistent types.
    for column in categorical_columns:
        df[column] = df[column].astype("string").astype(object)
        df[column] = df[column].where(
            df[column].notna(),
            None
        )

    return df


def build_preprocessor(feature_rows):
    """
    Build and fit preprocessing on training examples only.

    Returns:
        fitted_preprocessor
        training_dataframe
    """

    df = prepare_feature_dataframe(feature_rows)

    categorical_columns = [
        col for col in CATEGORICAL_FEATURES
        if col in df.columns
    ]

    numeric_columns = [
        col for col in df.columns
        if col not in categorical_columns
    ]

    numeric_pipeline = Pipeline([
        (
            "imputer",
            SimpleImputer(
                strategy="constant",
                fill_value=0,
                add_indicator=True,
                keep_empty_features=True,
            )
        ),
        ("scaler", StandardScaler()),
    ])

    categorical_pipeline = Pipeline([
        (
            "imputer",
            SimpleImputer(
                strategy="constant",
                fill_value="UNKNOWN",
                keep_empty_features=True,
            )
        ),
        (
            "encoder",
            OneHotEncoder(
                handle_unknown="ignore",
                sparse_output=False,
            )
        ),
    ])

    preprocessor = ColumnTransformer([
        ("numeric", numeric_pipeline, numeric_columns),
        ("categorical", categorical_pipeline, categorical_columns),
    ])

    preprocessor.fit(df)

    return preprocessor, df


def transform_features(preprocessor, feature_rows):
    """
    Apply an already fitted preprocessor to new states.

    Never refit preprocessing on validation,
    test, or live investigation states.
    """

    df = prepare_feature_dataframe(feature_rows)

    return preprocessor.transform(df)
