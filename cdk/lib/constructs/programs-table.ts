import * as cdk from 'aws-cdk-lib/core';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';

export interface ProgramsTableProps {
  /** Logical environment name — appended to physical resource names */
  environment: string;
  /**
   * Point-in-time recovery.
   * Defaults to true for prod, false otherwise.
   */
  pointInTimeRecovery?: boolean;
}

/**
 * Reusable construct that provisions the forte-programs DynamoDB table.
 *
 * Table design
 * ────────────
 * PK  : program_id  (UUID string)                       — direct lookup by ID
 * GSI : owner-index  on owner_coach_id (string)         — list a coach's programs
 * GSI : state-index  on program_state (string, PK)
 *                    + created_at (string, SK)          — browse active programs
 *
 * Non-key attributes stored per item:
 *   title, description, price, created_at, updated_at
 */
export class ProgramsTable extends Construct {
  public readonly table: dynamodb.Table;

  constructor(scope: Construct, id: string, props: ProgramsTableProps) {
    super(scope, id);

    const isProd = props.environment === 'prod';

    this.table = new dynamodb.Table(this, 'Table', {
      tableName: `forte-programs-${props.environment}`,

      // Primary key
      partitionKey: {
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

    // GSI: list all programs owned by a coach
    this.table.addGlobalSecondaryIndex({
      indexName: 'owner-index',
      partitionKey: {
        name: 'owner_coach_id',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI: browse programs by lifecycle state, ordered by creation time
    this.table.addGlobalSecondaryIndex({
      indexName: 'state-index',
      partitionKey: {
        name: 'program_state',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'created_at',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // ── Outputs ───────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'TableName', {
      value: this.table.tableName,
      description: 'forte-programs DynamoDB table name',
      exportName: `ForteProgramsTableName-${props.environment}`,
    });

    new cdk.CfnOutput(this, 'TableArn', {
      value: this.table.tableArn,
      description: 'forte-programs DynamoDB table ARN',
      exportName: `ForteProgramsTableArn-${props.environment}`,
    });
  }
}
