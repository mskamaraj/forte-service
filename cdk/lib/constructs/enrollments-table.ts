import * as cdk from 'aws-cdk-lib/core';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';

export interface EnrollmentsTableProps {
  /** Logical environment name — appended to physical resource names */
  environment: string;
  /**
   * Point-in-time recovery.
   * Defaults to true for prod, false otherwise.
   */
  pointInTimeRecovery?: boolean;
}

/**
 * Reusable construct that provisions the forte-enrollments DynamoDB table.
 *
 * Table design
 * ────────────
 * PK  : user_id     (string)   — all enrollments for one user
 * SK  : program_id  (string)   — one item per (user, program) pair
 *
 * The composite key enforces a single enrollment per user and program; a
 * query on user_id lists everything a user is enrolled in.
 *
 * Non-key attributes stored per item:
 *   enrollment_id, enrolled_at
 */
export class EnrollmentsTable extends Construct {
  public readonly table: dynamodb.Table;

  constructor(scope: Construct, id: string, props: EnrollmentsTableProps) {
    super(scope, id);

    const isProd = props.environment === 'prod';

    this.table = new dynamodb.Table(this, 'Table', {
      tableName: `forte-enrollments-${props.environment}`,

      // Primary key
      partitionKey: {
        name: 'user_id',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'program_id',
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
      description: 'forte-enrollments DynamoDB table name',
      exportName: `ForteEnrollmentsTableName-${props.environment}`,
    });

    new cdk.CfnOutput(this, 'TableArn', {
      value: this.table.tableArn,
      description: 'forte-enrollments DynamoDB table ARN',
      exportName: `ForteEnrollmentsTableArn-${props.environment}`,
    });
  }
}
