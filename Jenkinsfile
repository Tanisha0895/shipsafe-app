pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }

    triggers {
        
        pollSCM('H/2 * * * *')
    }

    stages {
        stage('Prepare') {
            steps {
                script {
                    env.IMAGE_TAG = sh(script: 'git rev-parse --short HEAD', returnStdout: true).trim()
                }
                echo "Building commit ${env.IMAGE_TAG}"
            }
        }

        stage('Unit tests') {
            parallel {
                stage('auth') {
                    steps {
                        dir('services/auth') {
                            sh '''
                                python3 -m venv .venv
                                . .venv/bin/activate
                                pip install -q -r requirements.txt -r requirements-dev.txt
                                python -m pytest -q --junitxml=test-results.xml
                            '''
                        }
                    }
                }
                stage('product') {
                    steps {
                        dir('services/product') {
                            sh '''
                                python3 -m venv .venv
                                . .venv/bin/activate
                                pip install -q -r requirements.txt -r requirements-dev.txt
                                python -m pytest -q --junitxml=test-results.xml
                            '''
                        }
                    }
                }
            }
        }

        stage('Build images') {
            steps {
                sh '''
                    for svc in auth product order payment frontend; do
                        echo "=== Building shipsafe-$svc:$IMAGE_TAG ==="
                        docker build -t shipsafe-$svc:$IMAGE_TAG services/$svc
                    done
                '''
            }
        }
    }

    post {
        always {
            junit allowEmptyResults: true, testResults: 'services/*/test-results.xml'
        }
        success {
            echo "Pipeline passed: images tagged ${env.IMAGE_TAG}"
        }
        failure {
            echo 'Pipeline failed: nothing will be deployed'
        }
    }
}
