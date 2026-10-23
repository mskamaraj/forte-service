import * as cdk from 'aws-cdk-lib/core';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';

export interface ContentTableProps {
  /** Logical environment name — appended to physical resource names */
  environment: string;
  /**
   * Point-in-time recovery.
   * Defaults to true for prod, false otherwise.
   */
  pointInTimeRecovery?: boolean;
}

/**
 * Reusable construct that provisions the forte-content DynamoDB table.
 *
 * Table design
 * ────────────
 * PK  : program_id  (string)   — all content nodes for one program
 * SK  : node_sk     (string)   — hierarchical module/chapter/exercise key
 *
 * A single query on program_id returns the whole content hierarchy.
 *
 * Non-key attributes stored per item:
 *   node_type, title, prompt, position, created_at, updated_at
 */
export class ContentTable extends Construct {
  public readonly table: dynamodb.Table;

  constructor(scope: Construct, id: string, props: ContentTableProps) {
    super(scope, id);

    const isProd = props.environment === 'prod';

    this.table = new dynamodb.Table(this, 'Table', {
      tableName: `forte-content-${props.environment}`,

      // Primary key
      partitionKey: {
        name: 'program_id',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'node_sk',
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
      description: 'forte-content DynamoDB table name',
      exportName: `ForteContentTableName-${props.environment}`,
    });

    new cdk.CfnOutput(this, 'TableArn', {
      value: this.table.tableArn,
      description: 'forte-content DynamoDB table ARN',
      exportName: `ForteContentTableArn-${props.environment}`,
    });
  }
}
