from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
    PartialCredentialsError,
    ProfileNotFound,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Connection, ConnectionAccount

BILLING_MODE_PAYABLE_HYBRID = "payable_hybrid"
TRUTH_MODE_EXACT = "exact"
TRUTH_MODE_APPROXIMATE = "approximate"


class AwsAccessError(RuntimeError):
    pass


def utc_today():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).date()


def describe_aws_error(error: Exception, action: str | None = None) -> str:
    if isinstance(error, AwsAccessError):
        return str(error)

    action_suffix = f" while trying to {action}" if action else ""

    if isinstance(error, NoCredentialsError):
        return (
            "AWS credentials are not available to the API runtime. Mount a read-only AWS config directory "
            "or provide environment-based credentials before syncing real connections."
        )

    if isinstance(error, PartialCredentialsError):
        return (
            "AWS credentials are only partially configured in the API runtime. Complete the credential set "
            "or mounted profile before syncing real connections."
        )

    if isinstance(error, ProfileNotFound):
        return (
            "The configured AWS profile could not be found inside the API runtime. Verify AWS_PROFILE and "
            "the mounted AWS config directory."
        )

    if isinstance(error, EndpointConnectionError):
        return f"The API runtime could not reach AWS{action_suffix}. Check network access from the container."

    if isinstance(error, ClientError):
        error_code = error.response.get("Error", {}).get("Code", "Unknown")
        operation = getattr(error, "operation_name", "")

        if error_code in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}:
            if operation == "AssumeRole":
                return (
                    "AWS credentials are present, but the API runtime could not assume the configured role. "
                    "Check the role ARN, trust policy, and external ID."
                )
            if operation in {"GetCostAndUsage", "GetCostForecast"}:
                return (
                    "AWS credentials are present, but the active identity does not have Cost Explorer read access "
                    "in us-east-1."
                )
            if operation == "GetCallerIdentity":
                return "AWS credentials are present, but STS identity verification was denied."

        if error_code in {"UnrecognizedClientException", "InvalidClientTokenId", "SignatureDoesNotMatch"}:
            return "The API runtime is using invalid AWS credentials. Refresh the source credentials and retry."

        if error_code in {"ExpiredToken", "RequestExpired"}:
            return "The AWS session available to the API runtime is expired. Refresh the source credentials and retry."

        return f"AWS returned {error_code}{action_suffix}. Check the connection role, permissions, and billing access."

    if isinstance(error, BotoCoreError):
        return (
            f"The AWS SDK failed{action_suffix}. Check credentials, profile configuration, and network access "
            "from the API runtime."
        )

    return str(error)


def get_boto3_session():
    profile = (os.getenv("AWS_PROFILE") or "").strip()
    try:
        if profile:
            return boto3.session.Session(profile_name=profile)

        os.environ.pop("AWS_PROFILE", None)
        return boto3.session.Session()
    except ProfileNotFound as error:
        raise AwsAccessError(describe_aws_error(error)) from error


def get_caller_identity(session: Any) -> dict[str, str]:
    response = session.client("sts").get_caller_identity()
    return {
        "account_id": response["Account"],
        "arn": response["Arn"],
        "user_id": response["UserId"],
    }


def assume_role_session(role_arn: str, external_id: str | None):
    session = get_boto3_session()
    sts = session.client("sts")
    params: dict[str, Any] = {
        "RoleArn": role_arn,
        "RoleSessionName": "aws-dashboard-sync",
    }
    if external_id:
        params["ExternalId"] = external_id
    credentials = sts.assume_role(**params)["Credentials"]
    return session.__class__(
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
    )


def build_aws_session_for_connection(connection: Connection):
    if connection.kind == "org_management":
        return assume_role_session(connection.role_arn, connection.external_id) if connection.role_arn else get_boto3_session()
    if connection.kind == "account_role":
        if not connection.role_arn:
            raise AwsAccessError("Standalone account-role connections require role_arn.")
        return assume_role_session(connection.role_arn, connection.external_id)
    raise AwsAccessError(f"Unsupported collector kind '{connection.kind}'")


def build_cost_explorer_client(connection: Connection):
    session = build_aws_session_for_connection(connection)
    return session.client("ce", region_name="us-east-1")


def inspect_aws_runtime() -> dict:
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    profile = (os.getenv("AWS_PROFILE") or "").strip() or None

    try:
        session = get_boto3_session()
    except Exception as error:
        return {
            "status": "error",
            "configured": False,
            "identity_verified": False,
            "credential_source": None,
            "profile": profile,
            "region": region,
            "caller": None,
            "message": describe_aws_error(error, "load the ambient AWS session"),
        }

    credentials = session.get_credentials()
    credential_source = getattr(credentials, "method", None) if credentials else None
    if not credentials:
        return {
            "status": "error",
            "configured": False,
            "identity_verified": False,
            "credential_source": None,
            "profile": profile,
            "region": region,
            "caller": None,
            "message": (
                "No ambient AWS credentials are available to the API runtime. Real org-management and standalone "
                "account-role syncs will fail until the API can read a valid profile or environment-based credentials."
            ),
        }

    try:
        caller = get_caller_identity(session)
    except Exception as error:
        return {
            "status": "error",
            "configured": True,
            "identity_verified": False,
            "credential_source": credential_source,
            "profile": profile,
            "region": region,
            "caller": None,
            "message": describe_aws_error(error, "verify the ambient AWS identity"),
        }

    return {
        "status": "ready",
        "configured": True,
        "identity_verified": True,
        "credential_source": credential_source,
        "profile": profile,
        "region": region,
        "caller": caller,
        "message": "Ambient AWS credentials are available to the API runtime.",
    }


def verify_cost_explorer_access(session: Any, connection: Connection) -> None:
    today = utc_today()
    start_day = today - timedelta(days=2)
    end_day_exclusive = today - timedelta(days=1)
    if end_day_exclusive <= start_day:
        end_day_exclusive = today

    request: dict[str, Any] = {
        "TimePeriod": {"Start": start_day.isoformat(), "End": end_day_exclusive.isoformat()},
        "Granularity": "DAILY",
        "Metrics": ["UnblendedCost"],
    }
    if connection.billing_view_arn:
        request["BillingViewArn"] = connection.billing_view_arn

    session.client("ce", region_name="us-east-1").get_cost_and_usage(**request)


def billing_export_configured(connection: Connection) -> bool:
    return bool(connection.billing_export_bucket and connection.billing_export_prefix and connection.billing_export_region)


def list_export_objects(session: Any, connection: Connection) -> tuple[list[dict[str, Any]], datetime | None]:
    s3 = session.client("s3", region_name=connection.billing_export_region)
    paginator = s3.get_paginator("list_objects_v2")
    objects: list[dict[str, Any]] = []
    latest_modified: datetime | None = None

    for page in paginator.paginate(Bucket=connection.billing_export_bucket, Prefix=connection.billing_export_prefix):
        for item in page.get("Contents", []):
            key = item.get("Key", "")
            if not key.endswith(".parquet"):
                continue
            objects.append(item)
            modified = item.get("LastModified")
            if modified and (latest_modified is None or modified > latest_modified):
                latest_modified = modified
    return objects, latest_modified


def export_is_fresh(latest_modified: datetime | None) -> bool:
    if latest_modified is None:
        return False
    return (datetime.now(timezone.utc) - latest_modified.astimezone(timezone.utc)) <= timedelta(hours=72)


def validate_connection_access(db: Session, connection: Connection) -> dict:
    if connection.kind == "demo":
        return {
            "connection_id": connection.id,
            "kind": connection.kind,
            "ready": True,
            "status": "ready",
            "truth_mode": TRUTH_MODE_EXACT,
            "credential_source": None,
            "identity": None,
            "checks": [
                {
                    "code": "demo",
                    "status": "success",
                    "message": "Demo connections use synthetic seeded data and do not require AWS credentials.",
                }
            ],
            "message": "Demo connection is ready.",
        }

    checks: list[dict[str, str]] = []
    truth_mode = TRUTH_MODE_APPROXIMATE
    runtime = inspect_aws_runtime()
    if runtime["configured"] and runtime["identity_verified"]:
        checks.append(
            {
                "code": "ambient_credentials",
                "status": "success",
                "message": f"Ambient AWS credentials are available via {runtime['credential_source'] or 'an unknown source'}.",
            }
        )
    else:
        checks.append(
            {
                "code": "ambient_credentials",
                "status": "error",
                "message": runtime["message"],
            }
        )
        return {
            "connection_id": connection.id,
            "kind": connection.kind,
            "ready": False,
            "status": "error",
            "truth_mode": truth_mode,
            "credential_source": runtime["credential_source"],
            "identity": runtime["caller"],
            "checks": checks,
            "message": runtime["message"],
        }

    if connection.kind == "account_role":
        primary_membership = db.execute(
            select(ConnectionAccount).where(
                ConnectionAccount.connection_id == connection.id,
                ConnectionAccount.is_primary.is_(True),
                ConnectionAccount.enabled.is_(True),
            )
        ).scalar_one_or_none()
        if not primary_membership:
            checks.append(
                {
                    "code": "primary_membership",
                    "status": "error",
                    "message": "Standalone account-role connections require one enabled primary account membership.",
                }
            )
            return {
                "connection_id": connection.id,
                "kind": connection.kind,
                "ready": False,
                "status": "error",
                "truth_mode": truth_mode,
                "credential_source": runtime["credential_source"],
                "identity": runtime["caller"],
                "checks": checks,
                "message": "Connection is not ready for AWS sync.",
            }

        checks.append(
            {
                "code": "primary_membership",
                "status": "success",
                "message": "A primary account membership is configured for this standalone connection.",
            }
        )

    try:
        aws_session = build_aws_session_for_connection(connection)
        identity = get_caller_identity(aws_session)
    except Exception as error:
        message = describe_aws_error(error, "assume the configured AWS role")
        checks.append({"code": "role_access", "status": "error", "message": message})
        return {
            "connection_id": connection.id,
            "kind": connection.kind,
            "ready": False,
            "status": "error",
            "truth_mode": truth_mode,
            "credential_source": runtime["credential_source"],
            "identity": runtime["caller"],
            "checks": checks,
            "message": message,
        }

    checks.append(
        {
            "code": "role_access",
            "status": "success",
            "message": "The API runtime can reach the connection identity that will be used for AWS sync.",
        }
    )

    try:
        verify_cost_explorer_access(aws_session, connection)
    except Exception as error:
        message = describe_aws_error(error, "read Cost Explorer data")
        checks.append({"code": "cost_explorer", "status": "error", "message": message})
        return {
            "connection_id": connection.id,
            "kind": connection.kind,
            "ready": False,
            "status": "error",
            "truth_mode": truth_mode,
            "credential_source": getattr(aws_session.get_credentials(), "method", runtime["credential_source"]),
            "identity": identity,
            "checks": checks,
            "message": message,
        }

    checks.append(
        {
            "code": "cost_explorer",
            "status": "success",
            "message": "Verified Cost Explorer read access in us-east-1.",
        }
    )

    if connection.billing_mode != BILLING_MODE_PAYABLE_HYBRID:
        checks.append(
            {
                "code": "billing_exports",
                "status": "warning",
                "message": "This connection is configured for usage-only payable estimates, so bill truth will stay approximate.",
            }
        )
    elif not billing_export_configured(connection):
        checks.append(
            {
                "code": "billing_exports",
                "status": "warning",
                "message": "No AWS Data Exports bucket, prefix, and region are configured, so payable billing will fall back to approximate Cost Explorer net values.",
            }
        )
    else:
        try:
            objects, latest_modified = list_export_objects(aws_session, connection)
            if not objects:
                checks.append(
                    {
                        "code": "billing_exports",
                        "status": "warning",
                        "message": "The configured AWS Data Exports prefix is reachable, but no parquet files were found. Payable billing will be approximate.",
                    }
                )
            elif not export_is_fresh(latest_modified):
                checks.append(
                    {
                        "code": "billing_exports",
                        "status": "warning",
                        "message": "AWS Data Exports are reachable, but the latest parquet file is stale. Payable billing will be approximate until the export refreshes.",
                    }
                )
            else:
                truth_mode = TRUTH_MODE_EXACT
                checks.append(
                    {
                        "code": "billing_exports",
                        "status": "success",
                        "message": "Verified recent AWS Data Exports parquet files for payable billing truth.",
                    }
                )
        except Exception as error:
            checks.append(
                {
                    "code": "billing_exports",
                    "status": "warning",
                    "message": (
                        "AWS sync can proceed, but payable billing will be approximate because Data Exports could not be inspected: "
                        f"{describe_aws_error(error, 'inspect AWS Data Exports')}"
                    ),
                }
            )

    return {
        "connection_id": connection.id,
        "kind": connection.kind,
        "ready": True,
        "status": "ready",
        "truth_mode": truth_mode,
        "credential_source": getattr(aws_session.get_credentials(), "method", runtime["credential_source"]),
        "identity": identity,
        "checks": checks,
        "message": (
            "Connection is ready for AWS sync with exact payable billing."
            if truth_mode == TRUTH_MODE_EXACT
            else "Connection is ready for AWS sync, but payable billing will be approximate until AWS Data Exports are available."
        ),
    }
