"""Pandera validation schemas for SharpSpring API responses.

Intentionally loose — unknown columns are allowed, only key fields validated.
"""

import pandera as pa

lead_schema = pa.DataFrameSchema(
    columns={
        "id": pa.Column(str, nullable=False),
        "updateTimestamp": pa.Column(str, nullable=True),
    },
    strict=False,  # allow any extra columns the API sends
    coerce=True,
)

campaign_schema = pa.DataFrameSchema(
    columns={
        "id": pa.Column(str, nullable=False),
    },
    strict=False,
    coerce=True,
)

owner_schema = pa.DataFrameSchema(
    columns={
        "id": pa.Column(str, nullable=False),
    },
    strict=False,
    coerce=True,
)
