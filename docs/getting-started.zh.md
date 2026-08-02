# 2 分钟运行 Navi Agent

如果已准备好 Python、`uv` 和兼容 OpenAI 协议的 API Key，配置并启动 Navi Agent 约需
2 分钟。首次下载依赖的时间取决于网络状况，可能更长。

## 开始前准备

- Python 3.11 或更高版本
- [`uv`](https://docs.astral.sh/uv/)
- 兼容 OpenAI 协议的模型名称、API Key 和服务地址

## 1. 安装

从 GitHub 安装最新版本：

```bash
uv tool install git+https://github.com/xushun007/navi-agent.git
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
