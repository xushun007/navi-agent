# 快速开始

## 环境要求

- Python 3.11 或更高版本
- [`uv`](https://docs.astral.sh/uv/)
- 一个兼容 OpenAI 协议的模型服务

## 安装

从 GitHub 安装最新版本：

```bash
uv tool install git+https://github.com/xushun007/navi-agent.git
```

用于开发时，克隆仓库并同步依赖：

```bash
git clone https://github.com/xushun007/navi-agent.git
cd navi-agent
uv sync
```

## 初始化

创建默认配置文件并执行检查：

```bash
navi-agent init
navi-agent doctor
```

启动交互会话前，编辑 `~/.navi-agent/config.yaml`，填写模型名称和 API Key。

## 运行

在当前目录启动 Navi Agent：

```bash
navi-agent
```

执行单次请求：

```bash
navi-agent "总结这个仓库"
```

启动目录是权威工作区。如需授权其他目录：

```bash
navi-agent --add-dir ../shared
```

`--add-dir` 可以多次传入。

## 构建文档

在开发仓库中启动本地预览：

```bash
uv run --group docs mkdocs serve
```

提交文档改动前执行严格构建：

```bash
uv run --group docs mkdocs build --strict
```

## 后续阅读

- 查看 [CLI](cli.md) 和 [Slash 命令](commands.md)。
- 使用 `--yolo` 前了解[权限机制](permissions.md)。
- 配置[微信网关](gateway.md)实现远程接入。
