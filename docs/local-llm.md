# 本地部署开源大模型（免费、离线）

本文档说明如何用 **Ollama** 在本地跑开源千问（Qwen），让「Agent 对话」部分
真正具备自然语言理解与工具调用能力，全程免费、无需联网、数据不出本机。

---

## 一、原理

```
你的 app.py (CareerAgent)
        │  调用 OpenAI 兼容接口
        ▼
Ollama 服务 (http://127.0.0.1:11434/v1)
        │  加载本地模型权重
        ▼
开源 Qwen 模型 (Qwen2.5 3B / 7B，CPU 推理)
```

项目 `core/model_adapter.py` 已内置 `local` 模式，走标准
`/v1/chat/completions` 协议，**无需改任何代码**，只改 `config.json` 即可切换。

---

## 二、硬件要求（重要）

本地推理对硬件有硬性要求，请对照你的机器：

| 模型 | 显存/内存占用 | 无独显·16GB 内存 | 速度（CPU） | 结论 |
|---|---|---|---|---|
| qwen2.5:3b | ~2.5 GB | ✅ 可跑 | 10~20 token/秒 | **推荐** |
| qwen3:4b | ~3.5 GB | ✅ 勉强 | 8~15 token/秒 | 可选 |
| qwen2.5:7b | ~5.5 GB | ⚠️ 吃紧 | 5~10 token/秒 | 内存紧张时慎用 |

> 无独立显卡（NVIDIA）时只能 CPU 推理，速度天然较慢，属物理限制。
> 有 NVIDIA 独显则自动走 GPU，速度可提升 5~20 倍。

---

## 三、安装步骤

### 1. 安装 Ollama

任选其一：

**方式 A（推荐，Windows 有 winget）**
```bat
winget install Ollama.Ollama
```

**方式 B（手动下载）**
打开 https://ollama.com/download ，下载 Windows 安装包双击安装。

装完后，桌面/开始菜单会出现 Ollama，首次运行会常驻后台（托盘图标）。

### 2. 验证 Ollama 已启动

```bat
ollama --version
```
能打印版本号即成功。若提示找不到命令，先手动启动 Ollama 应用。

### 3. 拉取 Qwen 模型

```bat
ollama pull qwen2.5:3b
```

首次下载约 2GB，耐心等待。完成后可验证：

```bat
ollama run qwen2.5:3b
```

输入一句话回车，能收到回复即说明模型可用。输入 `/bye` 退出。

> 模型仓库若偶发 503（限流），稍等重试即可；也可改用国内镜像：
> `ollama pull registry.ollama.ai/library/qwen2.5:3b`

---

## 四、接入本项目

### 1. 创建配置

复制 `config.example.json` 为 `config.json`，改为：

```json
{
  "mode": "local",
  "model": "qwen2.5:3b",
  "base_url": "http://127.0.0.1:11434/v1",
  "api_key": "",
  "timeout_seconds": 120,
  "fallback_to_mock": false
}
```

> `timeout_seconds` 建议设 120：CPU 推理较慢，太短会超时。
> `fallback_to_mock` 为 true 时，模型调用失败会自动降级到模拟模式，不会中断使用。

### 2. 启动

```bat
python app.py
```

浏览器访问 http://127.0.0.1:8000 ，右上角徽章应显示「本地模型：qwen2.5:3b」。
此时「Agent 对话」页即可用自然语言与 Agent 交互，Agent 会自主调用工具。

---

## 五、故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 提示「无法连接模型服务」 | Ollama 没启动 | 手动打开 Ollama 应用，或命令行 `ollama serve` |
| 提示「HTTP 404」 | 模型名写错 / 未拉取 | 确认 `ollama list` 里有对应模型 |
| 超时 | CPU 推理慢 | 调大 `timeout_seconds`，或换更小模型 |
| 回复质量差 | 3B 模型能力有限 | 内存允许时换 `qwen2.5:7b` |
| 想恢复纯本地无模型 | — | `config.json` 里 `mode` 改回 `mock` |

---

## 六、三种模式对照

| 模式 | 成本 | 需联网 | 智能程度 | 适用场景 |
|---|---|---|---|---|
| `mock` 模拟 | 免费 | 否 | 规则路由，确定性 | 演示、验收、无网络环境 |
| `local` 本地 | 免费 | 否 | 取决于本地模型大小 | **日常使用、数据不出本机** |
| `cloud` 云端 | 按量付费 | 是 | 最高（qwen-max 等） | 需要最强效果、有预算 |

三者共用同一套工具调用与归一逻辑，切换只改 `config.json` 的 `mode`，业务结果始终可复现。
