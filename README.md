# forte-service

User registration and authentication service for Forte.

A Python / FastAPI backend running on AWS Lambda behind an API Gateway HTTP API,
with DynamoDB for storage. All infrastructure is defined and deployed with AWS CDK.

## Repository layout

```
forte-service/
├── service/     # FastAPI application (Python)
└── cdk/         # AWS CDK infrastructure (TypeScript)
```

- **[service/](service/README.md)** — the API: endpoints, models, business logic.
- **[cdk/](cdk/README.md)** — the infrastructure: DynamoDB, Lambda, API Gateway.

## Quick start

Full setup, build, and deploy instructions are in **[service/README.md](service/README.md)**.

```bash
# 1. Configure AWS credentials
aws configure

# 2. Install CDK dependencies
cd cdk && npm install

# 3. Bootstrap (one-time per account/region) and deploy
cdk bootstrap -c environment=dev
cdk deploy --all -c environment=dev
```

## CI/CD

Pushes to `main` are deployed automatically to the `dev` environment via
GitHub Actions (`.github/workflows/deploy.yml`).
