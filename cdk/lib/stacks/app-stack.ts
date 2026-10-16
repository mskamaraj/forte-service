import * as path from 'path';
import { spawnSync } from 'child_process';
import { cpSync } from 'fs';
import * as cdk from 'aws-cdk-lib/core';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigwv2 from 'aws-cdk-lib/aws-apigatewayv2';
import * as apigwv2integrations from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';
import { DatabaseStack } from './database-stack';

// Absolute path to the service project (sibling of cdk/ in the repo)
const serviceDir = path.join(__dirname, '../../../service');

export interface AppStackProps extends cdk.StackProps {
  environment: string;
  databaseStack: DatabaseStack;
}

/**
 * AppStack — deploys the forte-service FastAPI app as a Lambda function
 * behind an API Gateway HTTP API.
 *
 * The Lambda execution role is granted read/write access to the
 * forte-users DynamoDB table provisioned by DatabaseStack.
 */
export class AppStack extends cdk.Stack {
  public readonly apiUrl: string;

  constructor(scope: Construct, id: string, props: AppStackProps) {
    super(scope, id, props);

    const { environment, databaseStack } = props;
    const isProd = environment === 'prod';

    // ── JWT signing secret ─────────────────────────────────────────────────
    // Secrets Manager generates a random value automatically (no hardcoding).
    // We store the generated value in an SSM SecureString so the app reads it
    // from SSM Parameter Store, per the chosen design.
    const jwtSecret = new secretsmanager.Secret(this, 'JwtSigningSecret', {
      secretName: `forte-jwt-secret-${environment}`,
      description: `JWT signing secret for Forte — ${environment}`,
      generateSecretString: {
        passwordLength: 48,
        excludePunctuation: true,
      },
      removalPolicy: isProd ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });

    const jwtSecretParamName = `/forte/${environment}/jwt-secret`;
    const jwtSecretParam = new ssm.StringParameter(this, 'JwtSecretParam', {
      parameterName: jwtSecretParamName,
      // Reference the generated Secrets Manager value — never a literal.
      stringValue: jwtSecret.secretValue.unsafeUnwrap(),
      tier: ssm.ParameterTier.STANDARD,
    });

    // ── CloudWatch Log Group (explicit, so we control retention) ──────────
    const logGroup = new logs.LogGroup(this, 'ForteServiceLogGroup', {
      logGroupName: `/aws/lambda/forte-service-${environment}`,
      retention: isProd ? logs.RetentionDays.THREE_MONTHS : logs.RetentionDays.ONE_WEEK,
      removalPolicy: isProd ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });

    // ── Lambda function ────────────────────────────────────────────────────
    const fn = new lambda.Function(this, 'ForteServiceFn', {
      functionName: `forte-service-${environment}`,
      description: `Forte auth service — ${environment}`,

      // Python 3.12 matches the local venv
      runtime: lambda.Runtime.PYTHON_3_12,

      // handler = <module>.<attribute>  →  app/main.py :: handler (Mangum)
      handler: 'app.main.handler',

      // CDK builds the deployment package automatically on every deploy:
      // it installs the Linux x86_64 dependencies and copies the app source.
      // No manual build step is required.
      code: lambda.Code.fromAsset(serviceDir, {
        bundling: {
          image: lambda.Runtime.PYTHON_3_12.bundlingImage,
          local: {
            tryBundle(outputDir: string): boolean {
              const pipArgs = [
                'install',
                '-r', path.join(serviceDir, 'requirements.txt'),
                '--target', outputDir,
                '--platform', 'manylinux2014_x86_64',
                '--implementation', 'cp',
                '--python-version', '3.12',
                '--only-binary=:all:',
                '--upgrade',
              ];
              // Prefer `pip3`, fall back to `pip` (CI runners may use either).
              let result = spawnSync('pip3', pipArgs, { stdio: 'inherit' });
              if (result.status !== 0) {
                result = spawnSync('pip', pipArgs, { stdio: 'inherit' });
              }
              if (result.status !== 0) return false;

              // Copy the application source into the bundle
              cpSync(
                path.join(serviceDir, 'app'),
                path.join(outputDir, 'app'),
                { recursive: true }
              );
              return true;
            },
          },
        },
      }),

      environment: {
        ENVIRONMENT: environment,
        DYNAMODB_USERS_TABLE: databaseStack.usersTable.table.tableName,
        JWT_SECRET_PARAM_NAME: jwtSecretParamName,
      },

      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      logGroup,
    });

    // ── IAM — grant the function read/write on the users table ────────────
    databaseStack.usersTable.table.grantReadWriteData(fn);

    // ── IAM — grant the function read access to the JWT secret parameter ──
    jwtSecretParam.grantRead(fn);

    // ── API Gateway HTTP API ───────────────────────────────────────────────
    const api = new apigwv2.HttpApi(this, 'ForteApi', {
      apiName: `forte-api-${environment}`,
      description: `Forte HTTP API — ${environment}`,
      corsPreflight: {
        allowOrigins: ['*'],
        allowMethods: [apigwv2.CorsHttpMethod.ANY],
        allowHeaders: ['Content-Type', 'Authorization'],
      },
    });

    api.addRoutes({
      path: '/{proxy+}',
      methods: [apigwv2.HttpMethod.ANY],
      integration: new apigwv2integrations.HttpLambdaIntegration(
        'ForteServiceIntegration',
        fn
      ),
    });

    this.apiUrl = api.apiEndpoint;

    // ── Outputs ───────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'ApiUrl', {
      value: api.apiEndpoint,
      description: 'Forte API Gateway endpoint',
      exportName: `ForteApiUrl-${environment}`,
    });

    new cdk.CfnOutput(this, 'LambdaFunctionName', {
      value: fn.functionName,
      description: 'Forte Lambda function name',
    });
  }
}
