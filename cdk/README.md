# cdk

AWS CDK (TypeScript) infrastructure for the Forte service.

## Stacks

| Stack                   | Resources                                            |
|-------------------------|------------------------------------------------------|
| `Forte-Database-{env}`  | DynamoDB `forte-users-{env}` table + `email-index`   |
| `Forte-App-{env}`       | Lambda `forte-service-{env}` + API Gateway HTTP API  |

The App stack bundles and deploys the Python code from `../service`
automatically — no manual build step.

## Structure

```
cdk/
├── bin/forte-service-cdk.ts         # Entry point; reads -c environment=...
└── lib/
    ├── constructs/users-table.ts    # DynamoDB table construct
    └── stacks/
        ├── database-stack.ts        # DynamoDB
        └── app-stack.ts             # Lambda + API Gateway + IAM
```

## Deploy

See the full setup, build, and deploy guide in
[`../service/README.md`](../service/README.md).

Quick reference:

```bash
npm install
cdk bootstrap -c environment=dev        # one-time per account/region
cdk deploy --all -c environment=dev     # deploy both stacks
```

Region and account come from your active AWS profile (`aws configure`) —
nothing is hardcoded.

## Useful commands

```bash
cdk diff   -c environment=dev   # preview changes
cdk synth  -c environment=dev   # print the CloudFormation template
cdk destroy --all -c environment=dev
```
