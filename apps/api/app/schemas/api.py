from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AccountCreate(BaseModel):
    display_name: str = Field(min_length=3, max_length=120)
    aws_account_id: str = Field(pattern=r"^\d{12}$")
    role_arn: str | None = Field(default=None, max_length=255)
    external_id: str | None = Field(default=None, max_length=120)
    team_tag_key: str = Field(default="Team", min_length=1, max_length=64)
    enabled: bool = True


class AccountPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=3, max_length=120)
    role_arn: str | None = Field(default=None, max_length=255)
    external_id: str | None = Field(default=None, max_length=120)
    team_tag_key: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool | None = None


class ConnectionAccountInput(BaseModel):
    display_name: str = Field(min_length=3, max_length=120)
    aws_account_id: str = Field(pattern=r"^\d{12}$")


class ConnectionCreate(BaseModel):
    workspace_id: int = Field(gt=0)
    name: str = Field(min_length=3, max_length=120)
    kind: Literal["org_management", "account_role"]
    enabled: bool = True
    role_arn: str | None = Field(default=None, max_length=255)
    external_id: str | None = Field(default=None, max_length=120)
    billing_view_arn: str | None = Field(default=None, max_length=2048)
    billing_mode: Literal["usage_only", "payable_hybrid"] = "payable_hybrid"
    billing_export_bucket: str | None = Field(default=None, max_length=255)
    billing_export_prefix: str | None = Field(default=None, max_length=1024)
    billing_export_region: str | None = Field(default=None, max_length=64)
    team_tag_key: str = Field(default="Team", min_length=1, max_length=64)
    account: ConnectionAccountInput | None = None

    @model_validator(mode="after")
    def validate_shape(self):
        if self.kind == "account_role":
            if not self.role_arn:
                raise ValueError("role_arn is required for account_role connections")
            if not self.account:
                raise ValueError("account is required for account_role connections")
        if self.kind == "org_management" and self.account is not None:
            raise ValueError("account is only valid for account_role connections")
        return self


class ConnectionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    enabled: bool | None = None
    role_arn: str | None = Field(default=None, max_length=255)
    external_id: str | None = Field(default=None, max_length=120)
    billing_view_arn: str | None = Field(default=None, max_length=2048)
    billing_mode: Literal["usage_only", "payable_hybrid"] | None = None
    billing_export_bucket: str | None = Field(default=None, max_length=255)
    billing_export_prefix: str | None = Field(default=None, max_length=1024)
    billing_export_region: str | None = Field(default=None, max_length=64)
    team_tag_key: str | None = Field(default=None, min_length=1, max_length=64)
    account: ConnectionAccountInput | None = None


class SyncRequest(BaseModel):
    days: int | None = Field(default=None, ge=1, le=365)


class SyncResponse(BaseModel):
    status: str
    connection_id: int
    accounts_synced: int
    records_written: int
    window_days: int
    message: str | None = None
