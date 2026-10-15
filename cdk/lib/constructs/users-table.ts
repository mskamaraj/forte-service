import * as cdk from 'aws-cdk-lib/core';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';

export interface UsersTableProps {
  /** Logical environment name — appended to physical resource names */
  environment: string;
  /**
   * Point-in-time recovery.
   * Defaults to true for prod, false otherwise.
   */
  pointInTimeRecovery?: boolean;
}

/**
 * Reusable construct that provisions the forte-users DynamoDB table.
 *
 * Table design
 * ────────────
 * PK  : user_id  (UUID string)           — direct lookup by ID
 * GSI : email-index  on email (string)   — login + uniqueness check
 *
 * Non-key attributes stored per item:
 *   password_hash, first_name, last_name,
 *   is_active, is_verified, created_at, updated_at
 */
export class UsersTable extends Construct {
  public readonly table: dynamodb.Table;

  constructor(scope: Construct, id: string, props: UsersTableProps) {
    super(scope, id);

    const isProd = props.environment === 'prod';

    this.table = new dynamodb.Table(this, 'Table', {
      tableName: `forte-users-${props.environment}`,

      // Primary key
      partitionKey: {
        name: 'user_id',
        type: dynamodb.AttributeType.STRING,
      },

      // Billing — on-demand scales automatically; switch to PROVISIONED if needed
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,

      // Protect prod data from accidental deletion
      removalPolicy: isProd
        ? cdk.RemovalPolicy.RETAIN
        : cdk.RemovalPolicy.DESTROY,

      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: props.pointInTimeRecovery ?? isProd,
      },

      // Encrypt at rest with AWS-managed key
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    });

    // GSI: look up a user by email
    this.table.addGlobalSecondaryIndex({
      indexName: 'email-index',
      partitionKey: {
        name: 'email',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // ── Outputs ───────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'TableName', {
      value: this.table.tableName,
      description: 'forte-users DynamoDB table name',
      exportName: `ForteUsersTableName-${props.environment}`,
    });

    new cdk.CfnOutput(this, 'TableArn', {
      value: this.table.tableArn,
      description: 'forte-users DynamoDB table ARN',
      exportName: `ForteUsersTableArn-${props.environment}`,
    });
  }
}
