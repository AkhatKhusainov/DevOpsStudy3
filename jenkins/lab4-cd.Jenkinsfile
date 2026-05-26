def inRepoWorkspace(Closure body) {
    if (env.REPO_DIR?.trim()) {
        ws(env.REPO_DIR) {
            body()
        }
        return
    }

    body()
}


pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    parameters {
        string(name: 'DOCKER_IMAGE_NAME', defaultValue: 'wine-quality-mlops', description: 'Image name to deploy. For Docker Hub use username/repository.')
        string(name: 'DOCKER_IMAGE_TAG', defaultValue: 'local', description: 'Image tag to deploy. Default local tag matches the image produced by the local CI pipeline.')
        booleanParam(name: 'PULL_IMAGE_BEFORE_DEPLOY', defaultValue: false, description: 'Pull the API image from a registry before docker compose up. Leave disabled for the local Jenkins workflow.')
        booleanParam(name: 'KEEP_DEPLOYED', defaultValue: false, description: 'Keep the docker compose stack running after a successful deployment.')
    }

    environment {
        LOCAL_API_IMAGE = 'wine-quality-mlops:local'
        FUNCTIONAL_REPORT = 'functional-test-report.json'
    }

    stages {
        stage('Checkout') {
            when {
                expression { !env.REPO_DIR?.trim() }
            }
            steps {
                checkout scm
            }
        }

        stage('Resolve Parameters') {
            steps {
                script {
                    def requiredParams = ['DOCKER_IMAGE_NAME', 'DOCKER_IMAGE_TAG']
                    def missing = requiredParams.findAll { !params[it]?.trim() }
                    if (missing) {
                        error("Missing Jenkins parameters: ${missing.join(', ')}")
                    }

                    env.RESOLVED_IMAGE_NAME = params.DOCKER_IMAGE_NAME.trim()
                    env.RESOLVED_IMAGE_TAG = params.DOCKER_IMAGE_TAG.trim()
                    env.RESOLVED_IMAGE_REF = "${env.RESOLVED_IMAGE_NAME}:${env.RESOLVED_IMAGE_TAG}"
                }
            }
        }

        stage('Prepare API Image') {
            steps {
                script {
                    inRepoWorkspace {
                        powershell '''
$ErrorActionPreference = 'Stop'
if ($env:PULL_IMAGE_BEFORE_DEPLOY -eq 'true') {
    docker pull "$env:RESOLVED_IMAGE_NAME`:$env:RESOLVED_IMAGE_TAG"
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker image pull failed.'
    }
} else {
    docker image inspect "$env:RESOLVED_IMAGE_NAME`:$env:RESOLVED_IMAGE_TAG" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw 'Requested deployment image was not found locally. Run the CI pipeline first or enable PULL_IMAGE_BEFORE_DEPLOY.'
    }
}

if ("$env:RESOLVED_IMAGE_NAME`:$env:RESOLVED_IMAGE_TAG" -ne $env:LOCAL_API_IMAGE) {
    docker tag "$env:RESOLVED_IMAGE_NAME`:$env:RESOLVED_IMAGE_TAG" "$env:LOCAL_API_IMAGE"
    if ($LASTEXITCODE -ne 0) {
        throw 'Retagging the deployment image to wine-quality-mlops:local failed.'
    }
}
'''
                    }
                }
            }
        }

        stage('Build Vault Image') {
            steps {
                script {
                    inRepoWorkspace {
                        powershell 'docker compose build vault'
                    }
                }
            }
        }

        stage('Start Compose Stack') {
            steps {
                script {
                    inRepoWorkspace {
                        powershell 'docker compose up -d postgres vault kafka api kafka-consumer'
                    }
                }
            }
        }

        stage('Seed PostgreSQL') {
            steps {
                script {
                    inRepoWorkspace {
                        powershell 'docker compose --profile seed run --rm db-seed'
                    }
                }
            }
        }

        stage('Wait For API Health') {
            steps {
                script {
                    inRepoWorkspace {
                        powershell '''
$ErrorActionPreference = 'Stop'
$containerId = docker compose ps -q api
if (-not $containerId) {
    throw 'API container was not found.'
}

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    $status = docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $containerId
    if ($status -eq 'healthy') {
        return
    }

    if ($attempt -eq 19) {
        throw "API container did not become healthy. Last status: $status"
    }

    Start-Sleep -Seconds 5
}
'''
                    }
                }
            }
        }

        stage('Run Functional Scenario') {
            steps {
                script {
                    inRepoWorkspace {
                        powershell '''
$ErrorActionPreference = 'Stop'
docker compose exec -T api python tests/functional/run_scenario.py --scenario /app/scenario_lab4.json --base-url http://127.0.0.1:8000 --report /app/artifacts/functional-test-report.json
$containerId = docker compose ps -q api
if (-not $containerId) {
    throw 'API container was not found after functional test execution.'
}
docker cp "$containerId`:/app/artifacts/functional-test-report.json" functional-test-report.json
'''
                    }
                }
            }
        }
    }

    post {
        always {
            script {
                inRepoWorkspace {
                    powershell(returnStatus: true, script: 'docker compose logs')
                    if (!params.KEEP_DEPLOYED || currentBuild.currentResult != 'SUCCESS') {
                        powershell(returnStatus: true, script: 'docker compose down -v --remove-orphans')
                    }

                    archiveArtifacts(
                        artifacts: 'functional-test-report.json',
                        allowEmptyArchive: true,
                        onlyIfSuccessful: false,
                    )
                }
            }
        }
    }
}