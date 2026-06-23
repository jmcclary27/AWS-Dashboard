from pydantic import BaseModel, Field


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


class SyncResponse(BaseModel):
    status: str
    accounts_synced: int
    records_written: int
    window_days: int

