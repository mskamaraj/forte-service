import * as cdk from 'aws-cdk-lib/core';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';

export interface CompletionTableProps {
  /** Logical environment name — appended to physical resource names */
  environment: string;
  /**
   * Point-in-time recovery.
   * Defaults to true for prod, false otherwise.
   */
  pointInTimeRecovery?: boolean;
}

/**
 * Reusable construct that provisions the forte-completion DynamoDB table.
 *
 * Table design
 * ────────────
 * PK  : completion_pk  (string)   — composite of user_id + program_id
 * SK  : exercise_id    (string)   — one item per completed exercise
 *
 * A query on completion_pk returns a user's completion set for one program.
 *
 * Non-key attributes stored per item:
 *   completed, updated_at
 */
export class CompletionTable extends Construct {
  public readonly table: dynamodb.Table;

  constructor(scope: Construct, id: string, props: CompletionTableProps) {
    super(scope, id);

    const isProd = props.environment === 'prod';

    this.table = new dynamodb.Table(this, 'Table', {
      tableName: `forte-completion-${props.environment}`,

      // Primary key
      partitionKey: {
        name: 'completion_pk',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'exercise_id',
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

    // ── Outputs ───────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'TableName', {
      value: this.table.tableName,
      description: 'forte-completion DynamoDB table name',
      exportName: `ForteCompletionTableName-${props.environment}`,
    });

    new cdk.CfnOutput(this, 'TableArn', {
      value: this.table.tableArn,
      description: 'forte-completion DynamoDB table ARN',
      exportName: `ForteCompletionTableArn-${props.environment}`,
    });
  }
}
