#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { DatabaseStack } from '../lib/stacks/database-stack';
import { AppStack } from '../lib/stacks/app-stack';

const app = new cdk.App();

/**
 * Usage:
 *   cdk deploy --all -c environment=dev
 *   cdk deploy --all -c environment=prod
 */
const environment = app.node.tryGetContext('environment') ?? 'dev';
const validEnvironments = ['dev', 'staging', 'prod'];

if (!validEnvironments.includes(environment)) {
  throw new Error(
    `Invalid environment "${environment}". Must be one of: ${validEnvironments.join(', ')}`
  );
}

// Account and region come from the active AWS profile (aws configure).
const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION,
};

const tags = {
  Project: 'Forte',
  Environment: environment,
  ManagedBy: 'CDK',
};

// Stack 1 — DynamoDB tables
const databaseStack = new DatabaseStack(app, `Forte-Database-${environment}`, {
  env,
  environment,
  description: `Forte DynamoDB tables — ${environment}`,
  tags,
});

// Stack 2 — Lambda + API Gateway (depends on DatabaseStack for the table ref)
new AppStack(app, `Forte-App-${environment}`, {
  env,
  environment,
  databaseStack,
  description: `Forte application (Lambda + API Gateway) — ${environment}`,
  tags,
});
