import * as cdk from 'aws-cdk-lib/core';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { DatabaseStack } from '../lib/stacks/database-stack';
import { AppStack } from '../lib/stacks/app-stack';

/**
 * Verifies the four coaching DynamoDB tables (programs, content, enrollments,
 * completion) have the correct key schema and GSIs, and that the forte-service
 * Lambda execution role is granted read/write on every one of them.
 *
 * Requirements: 4.1, 9.1, 10.1, 12.2
 */

function databaseTemplate(): Template {
  const app = new cdk.App();
  const stack = new DatabaseStack(app, 'TestDatabaseStack', { environment: 'test' });
  return Template.fromStack(stack);
}

describe('coaching tables — key schema and GSIs', () => {
  test('programs table has program_id PK and owner-index / state-index GSIs', () => {
    const template = databaseTemplate();

    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TableName: 'forte-programs-test',
      KeySchema: [{ AttributeName: 'program_id', KeyType: 'HASH' }],
      GlobalSecondaryIndexes: Match.arrayWith([
        {
          IndexName: 'owner-index',
          KeySchema: [{ AttributeName: 'owner_coach_id', KeyType: 'HASH' }],
          Projection: { ProjectionType: 'ALL' },
        },
        {
          IndexName: 'state-index',
          KeySchema: [
            { AttributeName: 'program_state', KeyType: 'HASH' },
            { AttributeName: 'created_at', KeyType: 'RANGE' },
          ],
          Projection: { ProjectionType: 'ALL' },
        },
      ]),
    });
  });

  test('content table has program_id PK and node_sk SK', () => {
    const template = databaseTemplate();

    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TableName: 'forte-content-test',
      KeySchema: [
        { AttributeName: 'program_id', KeyType: 'HASH' },
        { AttributeName: 'node_sk', KeyType: 'RANGE' },
      ],
    });
  });

  test('enrollments table has user_id PK and program_id SK', () => {
    const template = databaseTemplate();

    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TableName: 'forte-enrollments-test',
      KeySchema: [
        { AttributeName: 'user_id', KeyType: 'HASH' },
        { AttributeName: 'program_id', KeyType: 'RANGE' },
      ],
    });
  });

  test('completion table has completion_pk PK and exercise_id SK', () => {
    const template = databaseTemplate();

    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TableName: 'forte-completion-test',
      KeySchema: [
        { AttributeName: 'completion_pk', KeyType: 'HASH' },
        { AttributeName: 'exercise_id', KeyType: 'RANGE' },
      ],
    });
  });
});

describe('coaching tables — Lambda read/write grants', () => {
  // Expected DynamoDB actions produced by Table.grantReadWriteData on a
  // table without a stream (read actions + write actions).
  const readWriteActions = [
    'dynamodb:BatchGetItem',
    'dynamodb:Query',
    'dynamodb:GetItem',
    'dynamodb:Scan',
    'dynamodb:ConditionCheckItem',
    'dynamodb:BatchWriteItem',
    'dynamodb:PutItem',
    'dynamodb:UpdateItem',
    'dynamodb:DeleteItem',
    'dynamodb:DescribeTable',
  ];

  function appTemplate(): Template {
    // Skip Lambda asset bundling — unit tests only need the CloudFormation shape.
    const app = new cdk.App({ context: { 'aws:cdk:bundling-stacks': [] } });
    const databaseStack = new DatabaseStack(app, 'TestDatabaseStack', { environment: 'test' });
    const appStack = new AppStack(app, 'TestAppStack', {
      environment: 'test',
      databaseStack,
    });
    return Template.fromStack(appStack);
  }

  test.each([
    ['programs', 'ProgramsTable'],
    ['content', 'ContentTable'],
    ['enrollments', 'EnrollmentsTable'],
    ['completion', 'CompletionTable'],
  ])('Lambda role is granted read/write on the %s table', (_name, constructId) => {
    const template = appTemplate();

    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Effect: 'Allow',
            Action: Match.arrayWith(readWriteActions),
            Resource: Match.arrayWith([
              Match.objectLike({
                'Fn::ImportValue': Match.stringLikeRegexp(constructId),
              }),
            ]),
          }),
        ]),
      },
    });
  });
});
