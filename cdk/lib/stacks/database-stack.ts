import * as cdk from 'aws-cdk-lib/core';
import { Construct } from 'constructs';
import { UsersTable } from '../constructs/users-table';

export interface DatabaseStackProps extends cdk.StackProps {
  environment: string;
}

/**
 * DatabaseStack owns all DynamoDB tables for Forte.
 *
 * Keeping the database stack separate from the application stack means
 * tables can be deployed and updated independently without touching
 * compute resources — and RETAIN removal policies on prod are never
 * accidentally overridden by an app-stack rollback.
 */
export class DatabaseStack extends cdk.Stack {
  /** Expose the users table so other stacks can grant permissions to it */
  public readonly usersTable: UsersTable;

  constructor(scope: Construct, id: string, props: DatabaseStackProps) {
    super(scope, id, props);

    this.usersTable = new UsersTable(this, 'UsersTable', {
      environment: props.environment,
    });
  }
}
