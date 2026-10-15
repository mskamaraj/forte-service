"""DynamoDB table accessor."""

import boto3
from app.core.config import settings


def get_users_table():
    """Return the forte-users DynamoDB Table resource.
    
    On Lambda, boto3 automatically uses the function's IAM execution role.
    """
    return boto3.resource("dynamodb").Table(settings.dynamodb_users_table)
