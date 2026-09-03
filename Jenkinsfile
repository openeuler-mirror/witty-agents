pipeline {
    agent {
        docker {
            image 'shennong-oe2403sp4-acceptance:runtime-v2'
            label 'built-in'
            args '--user 0:0 --cap-add SYS_ADMIN --cap-add NET_ADMIN --security-opt seccomp=unconfined -v /home/shennong-jenkins/cache/npm:/root/.npm -v /home/shennong-jenkins/cache/pip:/root/.cache/pip -v /home/shennong-jenkins/ocr-model-cache:/home/shennong-jenkins/ocr-model-cache:ro'
        }
    }

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20', artifactNumToKeepStr: '10'))
        timeout(time: 240, unit: 'MINUTES')
    }

    triggers {
        pollSCM('H/5 * * * *')
    }

    parameters {
        string(
            name: 'AGENT',
            defaultValue: 'auto',
            description: 'Use auto/all or an Agent id registered in ci/agents.json, for example shennong-crash.'
        )
        choice(
            name: 'VARIANT',
            choices: ['default', 'online', 'offline', 'all'],
            description: 'Package content variant. Unsupported choices fail during plan resolution.'
        )
        choice(
            name: 'PACKAGE_STYLE',
            choices: ['organization', 'plain'],
            description: 'organization publishes @openeuler/*; plain publishes an unscoped package.'
        )
        choice(
            name: 'TARGET_ARCH',
            choices: ['native', 'x86_64', 'aarch64'],
            description: 'Offline packages require a native node matching this architecture.'
        )
        string(
            name: 'PYTHON_BIN',
            defaultValue: 'python3.11',
            description: 'Python 3.11/3.12 executable used to build and verify package-local environments.'
        )
        string(
            name: 'PYPI_INDEX_URL',
            defaultValue: 'https://mirrors.huaweicloud.com/repository/pypi/simple',
            description: 'Python index used while constructing online environments and offline wheels.'
        )
        string(
            name: 'OCR_MODEL_CACHE_DIR',
            defaultValue: '/home/shennong-jenkins/ocr-model-cache',
            description: 'Trusted OCR model cache used when the Git LFS service is unavailable.'
        )
        booleanParam(
            name: 'RUN_REAL_INSTALL_VALIDATION',
            defaultValue: true,
            description: 'Run install -> setup twice -> configure twice -> remove -> stop -> uninstall.'
        )
        booleanParam(
            name: 'STRICT_OFFLINE_NETWORK_CHECK',
            defaultValue: true,
            description: 'Require a Linux network namespace for offline real-install validation.'
        )
        booleanParam(
            name: 'PUBLISH',
            defaultValue: false,
            description: 'Publish selected packages. Requires official master and all variants.'
        )
        string(
            name: 'NPM_CREDENTIAL_ID',
            defaultValue: 'npm-token',
            description: 'Jenkins Secret Text credential containing the npm token.'
        )
        string(
            name: 'NPM_REGISTRY',
            defaultValue: 'https://registry.npmjs.org/',
            description: 'npm registry used only by the publish stage.'
        )
        string(
            name: 'NPM_DIST_TAG',
            defaultValue: 'latest',
            description: 'npm dist-tag used by the publish stage.'
        )
    }

    environment {
        GIT_LFS_SKIP_SMUDGE = '1'
        NPM_CONFIG_AUDIT = 'false'
        NPM_CONFIG_FUND = 'false'
        NPM_CONFIG_CACHE = '/root/.npm'
    }

    stages {
        stage('Initialize Parameters') {
            steps {
                script {
                    env.AGENT = params.AGENT ?: 'auto'
                    env.VARIANT = params.VARIANT ?: 'default'
                    env.PACKAGE_STYLE = params.PACKAGE_STYLE ?: 'organization'
                    env.TARGET_ARCH = params.TARGET_ARCH ?: 'native'
                    env.PYTHON_BIN = params.PYTHON_BIN?.trim() ?: 'python3.11'
                    env.PYPI_INDEX_URL = params.PYPI_INDEX_URL?.trim() ?: 'https://mirrors.huaweicloud.com/repository/pypi/simple'
                    env.PIP_INDEX_URL = env.PYPI_INDEX_URL
                    env.OCR_MODEL_CACHE_DIR = params.OCR_MODEL_CACHE_DIR?.trim() ?: '/home/shennong-jenkins/ocr-model-cache'
                    env.RUN_REAL_INSTALL_VALIDATION = String.valueOf(params.RUN_REAL_INSTALL_VALIDATION == null ? true : params.RUN_REAL_INSTALL_VALIDATION)
                    env.STRICT_OFFLINE_NETWORK_CHECK = String.valueOf(params.STRICT_OFFLINE_NETWORK_CHECK == null ? true : params.STRICT_OFFLINE_NETWORK_CHECK)
                    env.PUBLISH = String.valueOf(params.PUBLISH == null ? false : params.PUBLISH)
                    env.NPM_CREDENTIAL_ID = params.NPM_CREDENTIAL_ID?.trim() ?: 'npm-token'
                    env.NPM_REGISTRY = params.NPM_REGISTRY?.trim() ?: 'https://registry.npmjs.org/'
                    env.NPM_DIST_TAG = params.NPM_DIST_TAG?.trim() ?: 'latest'
                }
                sh '''
                    set -eu
                    rm -rf ci-artifacts
                    mkdir -p ci-artifacts
                    git config --global --add safe.directory "$WORKSPACE"
                    git rev-parse --show-toplevel >/dev/null
                    node -e 'const major=Number(process.versions.node.split(".")[0]); if (major < 20) throw new Error(`Node.js 20+ required, got ${process.version}`)'
                '''
            }
        }

        stage('Resolve Build Plan') {
            steps {
                sh '''
                    node ci/scripts/resolve-plan.mjs \
                      --agent="$AGENT" \
                      --variant="$VARIANT" \
                      --package-style="$PACKAGE_STYLE" \
                      --target-arch="$TARGET_ARCH" \
                      --publish="$PUBLISH" \
                      --output=ci-artifacts/build-plan.json
                '''
            }
        }

        stage('Prepare Agents') {
            steps { sh 'node ci/scripts/run-agent-phase.mjs --phase=prepare' }
        }
        stage('Prepare Assets') {
            steps { sh 'node ci/scripts/run-agent-phase.mjs --phase=prepare-assets' }
        }
        stage('Install Build Dependencies') {
            steps { sh 'node ci/scripts/run-agent-phase.mjs --phase=install-dependencies' }
        }
        stage('Validate Agents') {
            steps { sh 'node ci/scripts/run-agent-phase.mjs --phase=validate' }
        }
        stage('Build Packages') {
            steps { sh 'node ci/scripts/run-agent-phase.mjs --phase=build' }
        }
        stage('Artifact Gates') {
            steps { sh 'node ci/scripts/run-agent-phase.mjs --phase=artifact-gates' }
        }
        stage('Install Contract Checks') {
            steps { sh 'node ci/scripts/run-agent-phase.mjs --phase=install-contract' }
        }
        stage('Real Install Flow') {
            when { expression { env.RUN_REAL_INSTALL_VALIDATION == 'true' } }
            steps { sh 'node ci/scripts/run-agent-phase.mjs --phase=real-install' }
        }

        stage('Publish to npm') {
            when { expression { env.PUBLISH == 'true' } }
            steps {
                sh '''
                    set -eu
                    origin_url="$(git remote get-url origin)"
                    case "$origin_url" in
                      https://gitcode.com/openeuler/witty-agents|https://gitcode.com/openeuler/witty-agents.git|\
                      https://atomgit.com/openeuler/witty-agents|https://atomgit.com/openeuler/witty-agents.git|\
                      git@gitcode.com:openeuler/witty-agents.git|git@atomgit.com:openeuler/witty-agents.git)
                        ;;
                      *)
                        echo "Publishing is allowed only from the official repository, got: $origin_url" >&2
                        exit 1
                        ;;
                    esac
                    git fetch --no-tags origin master
                    git merge-base --is-ancestor HEAD refs/remotes/origin/master || {
                      echo 'Publishing is allowed only for a commit contained in origin/master.' >&2
                      exit 1
                    }
                '''
                script {
                    withCredentials([string(credentialsId: env.NPM_CREDENTIAL_ID, variable: 'NPM_TOKEN')]) {
                        sh '''
                            set +x
                            node ci/scripts/publish-packages.mjs --plan=ci-artifacts/build-plan.json
                        '''
                    }
                }
            }
        }
    }

    post {
        always {
            archiveArtifacts(
                artifacts: 'ci-artifacts/**,**/artifacts/**,**/ci-reports/*.json',
                allowEmptyArchive: true,
                fingerprint: true
            )
            sh 'chown -R 1000:1000 "$WORKSPACE" 2>/dev/null || true'
        }
    }
}
