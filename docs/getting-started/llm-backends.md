# LLM 后端配置指南

## 支持的后端类型

当前**仅支持**以下四种 LLM 后端：

1. **deepseek** - DeepSeek API
2. **kimi** - Kimi（Moonshot）API
3. **ollama** - Ollama 服务（本地或远程）
4. **openai-compatible** - 符合 OpenAI API 规范的中转 API

## 配置方式

### 1. DeepSeek

**环境变量 / .env：**
```env
LLM_BACKEND=deepseek
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_MODEL=deepseek-chat
```

在 TUI 中可通过 **`/backend`** 选择后端；或通过 .env 设置默认后端。

### 2. Kimi（Moonshot）

**环境变量 / .env：**
```env
LLM_BACKEND=kimi
KIMI_API_KEY=your_api_key
KIMI_MODEL=moonshot-v1-8k
```

在 TUI 中可通过 **`/backend`** 选择后端。

### 3. 符合 OpenAI 规范的中转 API

支持任意符合 OpenAI Chat Completions 规范的中转服务（需提供 base_url 与 api_key）。

**环境变量 / .env：**
```env
LLM_BACKEND=openai-compatible
OPENAI_COMPATIBLE_API_KEY=your_api_key
OPENAI_COMPATIBLE_BASE_URL=https://api.example.com/v1
OPENAI_COMPATIBLE_MODEL=your-model-name
```

在 TUI 中可通过 **`/backend`** 选择后端。

### 4. Ollama

**环境变量 / .env：**
```env
LLM_BACKEND=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3
```

在 TUI 中可通过 **`/backend`** 选择 Ollama；远程 Ollama 可在 .env 中设置 `OLLAMA_URL`。

详细 Ollama 配置请参考 [ollama-setup.md](ollama-setup.md)。

## 后端选择建议

- **本地开发/测试**：Ollama，无需 API Key
- **中文与推理**：DeepSeek 或 Kimi
- **自建或第三方中转**：openai-compatible，填写对应 base_url 与 api_key

## 依赖说明

- 运行时统一通过开源 [LiteLLM](https://github.com/BerriAI/litellm) 调用各提供商（`deepseek/`、`moonshot/`、`ollama/`、`openai/` + `api_base`）
- 桌面设置页仍用四类运行时后端映射到 LiteLLM；不再在项目内维护各厂商 HTTP 客户端
