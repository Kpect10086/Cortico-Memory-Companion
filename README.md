# 我会牢牢记住你 · Cortico 非官方移植版

**原插件作者是 [menglimi](https://github.com/menglimi)，原作是 [astrbot_plugin_memory_companion](https://github.com/menglimi/astrbot_plugin_memory_companion)。Kpect10086 负责移植适配与融合维护，不是原插件作者。本仓库不是原作者或 Cortico 官方发行。**

保留原版 MemoryCompanion 页面、配置、工具和数据格式，与 Cortico 权重记忆、审核、原文证据、回滚和作用域隔离整合。兼容宿主运行在独立 Python 进程中。

移植版本 `0.4.0-cortico.1`；上游版本 `2.3.1`，提交 `e40a83005b0a2e0817e5680c7d14398c9ab49790`。没有“全部功能已真机验证”、官方认证或安全证书的声明。

## 同一套移植插件

| Cortico 移植仓库 | 原作者仓库 | 移植基准 |
|---|---|---|
| [我会牢牢记住你](https://github.com/Kpect10086/Cortico-Memory-Companion) | [menglimi/astrbot_plugin_memory_companion](https://github.com/menglimi/astrbot_plugin_memory_companion) | 2.3.1 |
| [我会永远陪着你](https://github.com/Kpect10086/Cortico-Private-Companion) | [menglimi/astrbot_plugin_private_companion](https://github.com/menglimi/astrbot_plugin_private_companion) | 6.7.0 |
| [我会替你留住故事](https://github.com/Kpect10086/Cortico-Content-Companion) | [menglimi/astrbot_plugin_content_companion](https://github.com/menglimi/astrbot_plugin_content_companion) | 0.2.2 |
| [梗百科](https://github.com/Kpect10086/Cortico-MemeWiki) | [in1t1a1/astrbot_plugin_memewiki](https://github.com/in1t1a1/astrbot_plugin_memewiki) | 1.6.0 |

## 安装与兼容边界

本次发布是 GitHub 源码与预览包，未发布到 npm，也未申请 Cortico 市场认证。Node >=22.16.0，Python >=3.12；审查基准为 Cortico 0.2.8 加本套移植所需兼容补丁，并非未修改的官方 0.2.8 安装即用。实际使用建议 Node 24 / Python 3.12。

请按 [INSTALL.md](docs/INSTALL.md) 安装整套兼容宿主，再启用所需 World。默认不启用模块，不导入任何真实聊天、人格、监听名单或 API Key。四个包使用按部署路径隔离的共享宿主注册表；依赖解析出多份同版本模块时也能共用同一宿主。不同版本仍不应混装。

QQ 的原生平台操作依赖提供 `qq_companion_transport` 的 QQ World；普通 OneBot 支持不等于已具备该内部适配接口。生活说说还需要 `qq_qzone_post` 和暂停/静默/额度授权，TTS 需要对应传输能力。缺少接口时会明确失败，不声称已发送。原版 ImageCompanion 等可选扩展未随本套 6.x 移植安装，封面与主动配图不承诺可用。

AstrBot 7.x 已改变体系，本仓库仍固定 6.7.0，不自动升级或把 7.x 页面冒充为 6.x 页面。首次安装请用测试部署检查，备份自己的配置与数据库；本仓库不会改写现有生产部署。

## 来源、许可与核验

- [来源与许可记录](UPSTREAM_PERMISSIONS.md)：不把私人邮件回复伪称为开源许可证或证书。
- [第三方声明](THIRD_PARTY_NOTICES.md) 与 [组件许可](LICENSE)。
- [固定源码清单](upstream-provenance.json)：原版源码随包保存，保留作者署名与文件哈希。
- [发布审查](docs/RELEASE_AUDIT.md)：列出实际检查和未验证的外部能力。

梗百科原 GitHub 地址当前返回 404；使用已保存的固定提交，不将镜像或移植维护者冒充原作者。权限邮件原图、私人邮箱、生产配置、密钥、聊天数据库、声线模型和本机 Python 虚拟环境不在发布包内。
