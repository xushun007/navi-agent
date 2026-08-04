# 2 分钟运行 Navi Agent

如果已准备好兼容 OpenAI 协议的 API Key，配置并启动 Navi Agent 约需 2 分钟。
首次下载依赖的时间取决于网络状况，可能更长。

## 开始前准备

- 带有 `curl` 的 macOS 或 Linux，或已经安装 [`uv`](https://docs.astral.sh/uv/) 的 Windows
- 兼容 OpenAI 协议的模型名称、API Key 和服务地址

## 1. 安装

安装最新发布版本。安装脚本会在需要时自动配置 `uv`：

```bash
curl -fsSL https://raw.githubusercontent.com/xushun007/navi-agent/main/scripts/install.sh | sh
```

如果已经安装 `uv`，可以直接从 PyPI 安装：

```bash
uv tool install navi-agent
```

## 2. 初始化

创建 `~/.navi-agent/config.yaml`：

```bash
navi-agent init
```

## 3. 配置模型

编辑生成的配置文件，填写模型凭据：

```yaml
model:
  name: gpt-4o-mini
  api_key: your-api-key
  base_url: https://api.openai.com/v1
```

检查配置：

```bash
navi-agent doctor
```

## 4. 运行

在项目目录中启动交互会话：

```bash
cd /path/to/your/project
navi-agent
```

或执行单次请求：

```bash
navi-agent "总结这个仓库"
```

启动目录是权威工作区。如需授权其他目录：

```bash
navi-agent --add-dir ../shared
```

`--add-dir` 可以多次传入。

## 后续阅读

- 查看 [CLI](cli.md) 和 [Slash 命令](commands.md)。
- 使用 `--yolo` 前了解[权限机制](permissions.md)。
- 配置[微信网关](gateway.md)实现远程接入。
