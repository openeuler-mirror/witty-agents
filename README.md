# witty-agents

## Jenkins

仓库级构建入口为根目录 `Jenkinsfile`。新服务器部署 Jenkins、自动创建
`witty-agent-package-ci` Job，以及 Pipeline from SCM 接入方式见
[`ci/jenkins/README.md`](ci/jenkins/README.md)。

This repository stores various agents for the witty project, providing a unified collection of agent implementations.

## vLLM Benchmark

新增 [vLLM Benchmark Agent](vllm-benchmark-agent/README.md)，遵循统一 setup/configure 安装契约，CI ID 为 `vllm-benchmark`（online）。
