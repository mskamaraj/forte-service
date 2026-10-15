import * as cdk from 'aws-cdk-lib/core';
import { Template } from 'aws-cdk-lib/assertions';
import { DatabaseStack } from '../lib/stacks/database-stack';

test('DatabaseStack creates the forte-users table with an email GSI', () => {
  const app = new cdk.App();
  const stack = new DatabaseStack(app, 'TestDatabaseStack', { environment: 'test' });
  const template = Template.fromStack(stack);

  template.hasResourceProperties('AWS::DynamoDB::Table', {
    TableName: 'forte-users-test',
    GlobalSecondaryIndexes: [
      {
        IndexName: 'email-index',
      },
    ],
  });
});
