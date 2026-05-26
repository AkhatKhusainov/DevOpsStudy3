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
    agent { label 'windows' }

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    parameters {
        string(name: 'DOCKER_IMAGE_NAME', defaultValue: 'wine-quality-mlops', description: 'Local image name or registry/repository for Docker Hub push.')
        string(name: 'DOCKER_IMAGE_TAG', defaultValue: '', description: 'Optional Docker image tag. Leave empty to use build-BUILD_NUMBER.')
        string(name: 'DOCKERHUB_CREDENTIALS_ID', defaultValue: 'dockerhub-credentials', description: 'Jenkins Username/Password credentials ID for Docker Hub login.')
        booleanParam(name: 'PUSH_IMAGE', defaultValue: false, description: 'Push the API image to Docker Hub after successful validation.')
        booleanParam(name: 'TRIGGER_CD', defaultValue: false, description: 'Trigger the Lab4 CD pipeline after a successful CI run.')
        string(name: 'CD_JOB_NAME', defaultValue: 'DevOpsStudy-Lab4-CD', description: 'Jenkins job name for the Lab4 CD pipeline.')
    }

    environment {
        VENV_DIR = '.venv'
        LOCAL_API_IMAGE = 'wine-quality-mlops:local'
        FUNCTIONAL_REPORT = 'functional-test-report.json'
        POSTGRES_HOST_PORT = '16433'
        VAULT_HOST_PORT = '18201'
        KAFKA_HOST_PORT = '19092'
        API_HOST_PORT = '18001'
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
                    env.RESOLVED_IMAGE_NAME = params.DOCKER_IMAGE_NAME?.trim() ? params.DOCKER_IMAGE_NAME.trim() : 'wine-quality-mlops'
                    env.RESOLVED_IMAGE_TAG = params.DOCKER_IMAGE_TAG?.trim() ? params.DOCKER_IMAGE_TAG.trim() : "build-${env.BUILD_NUMBER}"
                    env.RESOLVED_IMAGE_REF = "${env.RESOLVED_IMAGE_NAME}:${env.RESOLVED_IMAGE_TAG}"
                }
            }
        }

        stage('Install Dependencies') {
            steps {
                script {
                    inRepoWorkspace {
                        powershell '''
if (-not (Test-Path .venv/Scripts/python.exe)) {
    python -m venv .venv
}
& "./.venv/Scripts/python.exe" -m pip install --upgrade pip
& "./.venv/Scripts/python.exe" -m pip install -r requirements.txt
'''
                    }
                }
            }
        }

        stage('Run DVC Pipeline') {
            steps {
                script {
                    inRepoWorkspace {
                        powershell '& "./.venv/Scripts/dvc.exe" repro'
                    }
                }
            }
        }

        stage('Run Pytest') {
            steps {
                script {
                    inRepoWorkspace {
                        powershell '''
if (Test-Path coverage.xml) {
    Remove-Item coverage.xml -Force
}
& "./.venv/Scripts/pytest.exe" --cov=src/wine_quality_mlops --cov-report=xml --cov-report=term-missing
'''
                    }
                }
            }
        }

        stage('Build Docker Images') {
            steps {
                script {
                    inRepoWorkspace {
                        powershell 'docker compose build api vault'
                    }
                }
            }
        }

        stage('Tag API Image') {
            steps {
                script {
                    inRepoWorkspace {
                        powershell '''
$ErrorActionPreference = 'Stop'
docker tag "$env:LOCAL_API_IMAGE" "$env:RESOLVED_IMAGE_NAME`:$env:RESOLVED_IMAGE_TAG"
if ($LASTEXITCODE -ne 0) {
    throw 'Retagging the API image for Jenkins output failed.'
}
'''
                    }
                }
            }
        }

        stage('Start Compose Stack') {
            steps {
                script {
                    inRepoWorkspace {
                        powershell '''
docker compose down -v --remove-orphans
docker compose up -d postgres vault kafka api kafka-consumer
'''
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

        stage('Run Functional Tests') {
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

        stage('Push Docker Image') {
            when {
                expression { params.PUSH_IMAGE }
            }
            steps {
                script {
                    withCredentials([
                        usernamePassword(credentialsId: params.DOCKERHUB_CREDENTIALS_ID, usernameVariable: 'DOCKERHUB_USERNAME', passwordVariable: 'DOCKERHUB_TOKEN')
                    ]) {
                        inRepoWorkspace {
                            powershell '''
$ErrorActionPreference = 'Stop'
if ($env:RESOLVED_IMAGE_NAME -notmatch '/') {
    throw 'For Docker Hub push set DOCKER_IMAGE_NAME as username/repository, for example yourname/wine-quality-mlops.'
}
$env:DOCKERHUB_TOKEN | docker login --username "$env:DOCKERHUB_USERNAME" --password-stdin
if ($LASTEXITCODE -ne 0) {
    throw 'Docker Hub login failed.'
}
docker push "$env:RESOLVED_IMAGE_NAME`:$env:RESOLVED_IMAGE_TAG"
if ($LASTEXITCODE -ne 0) {
    throw 'Docker push for the build tag failed.'
}
docker tag "$env:RESOLVED_IMAGE_NAME`:$env:RESOLVED_IMAGE_TAG" "$env:RESOLVED_IMAGE_NAME`:latest"
if ($LASTEXITCODE -ne 0) {
    throw 'Docker tag latest failed.'
}
docker push "$env:RESOLVED_IMAGE_NAME`:latest"
if ($LASTEXITCODE -ne 0) {
    throw 'Docker push for latest failed.'
}
'''
                        }
                    }
                }
            }
        }

        stage('Generate DevSecOps Metadata') {
            steps {
                script {
                    inRepoWorkspace {
                        powershell '''
& "./.venv/Scripts/python.exe" scripts/generate_dev_sec_ops.py --image-ref "$env:RESOLVED_IMAGE_NAME`:$env:RESOLVED_IMAGE_TAG" --coverage-xml coverage.xml --output dev_sec_ops.yml
'''
                    }
                }
            }
        }

        stage('Trigger Lab4 CD') {
            when {
                expression { params.TRIGGER_CD }
            }
            steps {
                build job: params.CD_JOB_NAME,
                    wait: false,
                    parameters: [
                        string(name: 'DOCKER_IMAGE_NAME', value: env.RESOLVED_IMAGE_NAME),
                        string(name: 'DOCKER_IMAGE_TAG', value: env.RESOLVED_IMAGE_TAG),
                    ]
            }
        }
    }

    post {
        always {
            script {
                inRepoWorkspace {
                    powershell(returnStatus: true, script: 'docker compose logs')
                    powershell(returnStatus: true, script: 'docker compose down -v --remove-orphans')

                    archiveArtifacts(
                        artifacts: 'coverage.xml,dev_sec_ops.yml,artifacts/metrics.json,functional-test-report.json',
                        allowEmptyArchive: true,
                        onlyIfSuccessful: false,
                    )
                }
            }
        }
    }
}