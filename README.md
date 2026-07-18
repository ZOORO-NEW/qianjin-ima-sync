# qianjin-ima-sync · WorkBuddy 成果自动备份到 ima

**打通 WorkBuddy 与腾讯 ima 知识库的最后一步**。

## 核心能力

| 能力 | 说明 |
|------|------|
| 📤 **单文件上传** | PDF/MD/DOCX/XLSX 等 15 种格式，一键上传到 ima 知识库 |
| 📁 **批量备份** | 整目录上传，自动跳过不支持的格式 |
| 📝 **文本转笔记** | 把任意文本直接创建为 ima 笔记 |
| 🔗 **网页收藏** | 微信文章、公开网页一键加入知识库 |
| 🎯 **智能路由** | 按文件路径/类型自动选择目标知识库，免选择 |

## 与 ima 原生 skill 的差异

| 项目 | ima 原生 skill | qianjin-ima-sync |
|------|--------------|------------------|
| 从本地路径上传文件 | 需手动给路径 | **自动接管 WorkBuddy 生成的 outputs/** |
| 批量上传整个目录 | ❌ | ✅ |
| 按文件类型自动选知识库 | ❌ | ✅ |
| 进度实时反馈 | ❌ | ✅ |
| 与 WorkBuddy 工作流集成 | ❌ | ✅ |

## 触发词

- "把刚生成的报告传到ima"
- "备份到ima" / "上传到ima"
- "把 outputs 下这个月的成果都备份到ima"
- "把刚才的总结存到ima笔记"
- "把这篇微信文章存到ima"

## 配置方式

```bash
# 方式 1：环境变量（推荐）
export IMA_OPENAPI_CLIENTID="你的ClientID"
export IMA_OPENAPI_APIKEY="你的APIKey"

# 方式 2：配置文件
mkdir -p ~/.config/ima
echo "你的ClientID" > ~/.config/ima/client_id
echo "你的APIKey" > ~/.config/ima/api_key
```

获取 API Key：https://ima.qq.com/agent-interface

## 支持的文件类型

✅ **支持**：PDF、Word、Excel、PPT、Markdown、TXT、HTML、PNG、JPG、GIF、SVG 等 15+ 种
❌ **不支持**：视频、音频、B站/YouTube 链接（需用 IMA 桌面客户端）

## 安装

```
~/.workbuddy/skills/qianjin-ima-sync/SKILL.md
```

## License

MIT
