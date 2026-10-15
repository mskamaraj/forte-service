# forte-service

A Python / FastAPI service for user registration and authentication.
It runs on AWS Lambda behind an API Gateway HTTP API, with DynamoDB for storage.
All infrastructure is defined and deployed with AWS CDK (see `../cdk`).

## API Endpoints

| Method | Path                     | Description                       |
|--------|--------------------------|-----------------------------------|
| GET    | `/api/v1/health`         | Health check                      |
| POST   | `/api/v1/auth/register`  | Register a new user               |
| GET    | `/api/v1/users`          | List users (paginated)            |
| GET    | `/api/v1/users/{id}`     | Get a single user by ID           |

Interactive docs are available at `/docs` on the deployed API URL.

## Project Structure

```
forte-service/
├── app/
│   ├── main.py                 # FastAPI app + Lambda handler (Mangum)
│   ├── api/v1/
│   │   ├── router.py           # Aggregates all v1 routes
│   │   └── routes/
│   │       ├── health.py       # GET /health
│   │       ├── auth.py         # POST /auth/register
│   │       └── users.py        # GET /users, GET /users/{id}
│   ├── core/config.py          # Settings (table name injected by CDK)
│   ├── db/dynamo.py            # DynamoDB table accessor
│   ├── models/user.py          # Pydantic request/response models
│   ├── repositories/           # DynamoDB data access
│   └── services/               # Business logic (hashing, registration)
└── requirements.txt
```

The CDK stacks live in the sibling `../cdk` project.

---

## Prerequisites

Install these once:

- **Python 3.12** — `brew install python@3.12`
- **Node.js 20+** — `brew install node`
- **AWS CDK CLI** — `npm install -g aws-cdk`
- **AWS CLI v2** — `brew install awscli`

---

## 1. Configure AWS

Set up credentials for an IAM user that can deploy CloudFormation, Lambda,
API Gateway, DynamoDB, IAM, S3, and SSM.

```bash
aws configure
```

You will be prompted for:

```
AWS Access Key ID     : <your access key>
AWS Secret Access Key : <your secret key>
Default region name   : ap-southeast-2
Default output format  : json
```

Verify it works:

```bash
aws sts get-caller-identity
```

You should see your account ID and user ARN. The region you set here is the
region CDK deploys to — nothing is hardcoded.

---

## 2. Install dependencies

```bash
# CDK (TypeScript) dependencies
cd cdk
npm install
```

The Python/Lambda dependencies are installed automatically by CDK during
deploy — you do **not** need to pip install anything manually.

---

## 3. Deploy

From the `cdk` directory:

```bash
# One-time per account/region — sets up the CDK toolkit stack
cdk bootstrap -c environment=dev

# Deploy both stacks (DynamoDB table + Lambda + API Gateway)
cdk deploy --all -c environment=dev
```

On deploy, CDK automatically:

1. Installs the Lambda's Python dependencies (Linux x86_64 wheels).
2. Bundles the `app/` source.
3. Uploads and deploys the function.

When it finishes, CDK prints the API URL:

```
Forte-App-dev.ApiUrl = https://xxxxxxxx.execute-api.<region>.amazonaws.com
```

### Environments

Pass a different `environment` to deploy an isolated copy (separate table,
Lambda, and API):

```bash
cdk deploy --all -c environment=prod
```

Valid values: `dev`, `staging`, `prod`.

---

## 4. Deploy changes

After editing anything under `forte-service/app/` or `requirements.txt`,
just redeploy — CDK rebuilds the bundle automatically:

```bash
cd cdk
cdk deploy Forte-App-dev -c environment=dev
```

To update only the database stack:

```bash
cdk deploy Forte-Database-dev -c environment=dev
```

---

## 5. Test the deployed API

Replace the URL with the `ApiUrl` from your deploy output.

```bash
API=https://xxxxxxxx.execute-api.ap-southeast-2.amazonaws.com

# Health check
curl $API/api/v1/health

# Register a user
curl -X POST $API/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"jane@example.com","password":"Secret@123","first_name":"Jane","last_name":"Doe"}'

# List users
curl "$API/api/v1/users?limit=10"

# Get a single user
curl $API/api/v1/users/<user_id>
```

---

## Useful commands

```bash
# View infrastructure changes before deploying
cdk diff -c environment=dev

# Tail Lambda logs
aws logs tail /aws/lambda/forte-service-dev --follow

# Tear down an environment
cdk destroy --all -c environment=dev
```
