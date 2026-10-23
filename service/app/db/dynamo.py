"""DynamoDB table accessor."""

import boto3
from app.core.config import settings


def get_users_table():
    """Return the forte-users DynamoDB Table resource.
    
    On Lambda, boto3 automatically uses the function's IAM execution role.
    """
    return boto3.resource("dynamodb").Table(settings.dynamodb_users_table)


def get_programs_table():
    """Return the forte-programs DynamoDB Table resource.

    On Lambda, boto3 automatically uses the function's IAM execution role.
    """
    return boto3.resource("dynamodb").Table(settings.dynamodb_programs_table)


def get_content_table():
    """Return the forte-content DynamoDB Table resource.

    On Lambda, boto3 automatically uses the function's IAM execution role.
    """
    return boto3.resource("dynamodb").Table(settings.dynamodb_content_table)


def get_enrollments_table():
    """Return the forte-enrollments DynamoDB Table resource.

    On Lambda, boto3 automatically uses the function's IAM execution role.
    """
    return boto3.resource("dynamodb").Table(settings.dynamodb_enrollments_table)


def get_completion_table():
    """Return the forte-completion DynamoDB Table resource.

    On Lambda, boto3 automatically uses the function's IAM execution role.
    """
    return boto3.resource("dynamodb").Table(settings.dynamodb_completion_table)
