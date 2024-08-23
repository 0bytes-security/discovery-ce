from enum import Enum

from tortoise import fields
from tortoise.fields import DatetimeField
from tortoise.models import Model


class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class Run(Model):
    id = fields.CharField(max_length=36, pk=True)
    name = fields.TextField()
    parent: fields.ForeignKeyNullableRelation["Run"] = fields.ForeignKeyField(
        "models.Run",
        to_field="id",
        related_name="children",
        null=True,
    )
    children: "Run"
    owner_id = fields.CharField(max_length=255, null=True)
    parameters = fields.JSONField(default={})
    status = fields.CharEnumField(RunStatus, default=RunStatus.PENDING)
    result = fields.JSONField(default={})
    files = fields.JSONField(default=[])
    errors = fields.JSONField(default=[])
    started_at = fields.DatetimeField(null=True)
    failed_at = fields.DatetimeField(null=True)
    completed_at = fields.DatetimeField(null=True)
    created_at = DatetimeField(auto_now_add=True)
    updated_at = DatetimeField(auto_now=True)


class SchemaType(str, Enum):
    TASK = "TASK"
    WORKFLOW = "WORKFLOW"


class Registry(Model):
    id = fields.CharField(max_length=256, pk=True)
    name = fields.TextField(null=True)
    description = fields.TextField(null=True)
    schema = fields.JSONField()
    type = fields.CharEnumField(SchemaType)
    created_at = DatetimeField(auto_now_add=True)
    updated_at = DatetimeField(auto_now=True)
