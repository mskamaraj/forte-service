import * as cdk from 'aws-cdk-lib/core';
import { Construct } from 'constructs';
import { UsersTable } from '../constructs/users-table';
import { ProgramsTable } from '../constructs/programs-table';
import { ContentTable } from '../constructs/content-table';
import { EnrollmentsTable } from '../constructs/enrollments-table';
import { CompletionTable } from '../constructs/completion-table';

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

  /** Expose the programs table so other stacks can grant permissions to it */
  public readonly programsTable: ProgramsTable;

  /** Expose the content table so other stacks can grant permissions to it */
  public readonly contentTable: ContentTable;

  /** Expose the enrollments table so other stacks can grant permissions to it */
  public readonly enrollmentsTable: EnrollmentsTable;

  /** Expose the completion table so other stacks can grant permissions to it */
  public readonly completionTable: CompletionTable;

  constructor(scope: Construct, id: string, props: DatabaseStackProps) {
    super(scope, id, props);

    this.usersTable = new UsersTable(this, 'UsersTable', {
      environment: props.environment,
    });

    this.programsTable = new ProgramsTable(this, 'ProgramsTable', {
      environment: props.environment,
    });

    this.contentTable = new ContentTable(this, 'ContentTable', {
      environment: props.environment,
    });

    this.enrollmentsTable = new EnrollmentsTable(this, 'EnrollmentsTable', {
      environment: props.environment,
    });

    this.completionTable = new CompletionTable(this, 'CompletionTable', {
      environment: props.environment,
    });
  }
}
