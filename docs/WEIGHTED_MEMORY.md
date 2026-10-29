# 权重检索

分区、权重、审核、原始来源和版本审计共用现有 SQLite，不另建文件记忆库。包 ID `vanilla-memory`、面板 ID `weighted-memory`、配置键 `weightedMemory.*` 和数据库路径保持兼容。

`memory_search({query,view?,from?,to?,offset?})` 是统一检索入口。memories 保留中文 FTS 排序并补充字面子串命中；sources 按完整字面条件查来源片段。from/to 是带时区 ISO 记录时间，不是事情发生时间；来源片段按片段记录时间筛选，原话的逐条接收时间仍由证据页显示。每页最多20条，返回本次授权范围、可检索记录数、匹配数、分页、正文或引用截断说明。统计只覆盖已生效的保留资料，不声称覆盖全部历史；`queryComplete` 表示本次数据库条件查询完成，`historyCompleteness` 始终 unknown。

来源结果带 `sourceMessageIds`、`memoryIds` 和 `linkedMemoryCount`，只关联同会话已通过且已生效的长期记忆。按来源片段或摘要的完整 ID 调 `memory_sources({id,offset?})` 可分页核对原始发言、说话人和时间。纠正、审核和停用立即影响下一次搜索和反向关联；被停用或待审版本不会作为已通过关联返回。旧 `memory_recall` 和 `memory_sources({query})` 保留，后者使用同一字面条件及生效限制。

“权重检索”页面同时提供这套查询与原有管理功能，可从来源跳到关联记忆，再审核、纠正或停用。页面和模型工具共用查询实现与内容审核缓存；整段 JSON 计入检索字符预算，超限结果保留续页，正文被截断时须按 ID 查证据。模型不能在参数中指定其他会话。控制台检索会话由已认证操作员填写。

无关交流继续在语义整理时略过，不生成长期记忆；原始事件保留作追溯，没有批量清理存量原文。未归档、未采集、略过和未通过的资料不在本次检索覆盖保证内。未命中只能表述为本次范围与词面条件下未找到，不能断言事情未发生。文件导出沿用原页面的一键 Markdown/JSON/SQLite 导出。

`prompt-reminder.ts` 将当前宪法中的自然表达边界和操作员维护的 `references/B表达参考.md` 拼入每轮临时 user 参考，不写入会话历史。参考文件每轮重新读取；缺失或读取失败时保留宪法提醒。示范只供表达借鉴，不能成为事实、操作许可或记忆来源；聊天文件工具不能修改该文件。身份、事实与权限仍由系统提示决定。

`MemoryStore.search()` 保留中文分词 FTS 排序，在结果不足时补充同作用域原文子串命中；LIKE 中的百分号、下划线和反斜杠按字面转义。两路查询都只召回已生效的长期记忆，排除原始资料、旧档案、未到生效时间和其他会话。补充结果不挤掉已有 FTS 命中，最多返回30条；此兜底不需要新索引或数据库迁移。

`memory_sources({id,offset?})` 按 `memory_recall` 的完整记忆 ID 核对证据，每页最多10条，包含说话人和来源记录时间。当前会话无权读取的原始来源不可通过共享核心摘要获取。控制台与工具复用 `MemoryStore.evidence()`；原始消息缺失时回退到同会话来源片段并标记 `fragments`，部分消息缺失返回 `missing`。工具输出受检索字符预算限制，`nextOffset` 可续查，单条正文超过1200字符时明确标记 `textTruncated`。原有 `memory_sources({query})` 调用保持兼容。

`memory_audit({})` 按需检查最多2000条当前可见的已生效记忆，报告同会话完全重复、仅忽略标点/空白/大小写的近似重复，以及缺失或跨会话的消息/记录来源引用。短于8个 UTF-16 码元的归一正文不做重复判断；每类最多展示50组，输出继续受检索字符预算约束，范围或输出被截断时返回 `truncated`。不外发正文、不调用模型、不自动删除或改写资料，也不新增定时事件。没有来源引用的手工记忆不会被认定为来源丢失。

`attribution.mjs` 提供在线整理、离线整理、工作区读写工具和记忆上下文共用的人物归属说明。说话人 ID、会话、行动主体和承诺双方分别保留，第三方的第一人称不能转成自己的经历，旧总结不能作为独立证据。自动检索条目显示原会话，跨会话资料不能仅按昵称或代词合并。

`context.ts` 在一次上下文内只注入新增或改变的条目正文；同一作用域只列加入、移出的条目 ID，切换作用域时列出当前全部检索条目的引用，复用已经注入的同版本正文。视图引用使用唯一前12位，前缀碰撞时保留完整 ID；完整来源 ID 仍由 `memory_recall` 和 `memory_sources` 返回，数据库与导出不缩写。作用域按集合比较，顺序变化不触发重新注入。来源规则不变时不重复注入，交接后重新完整恢复。检索条目使用绝对发生时间，不因“几小时前”等相对时间变化而重复注入；来源、人物和不确定时间仍保留。

`MEMORY_SELECTION_GUIDE` 要求默认略过无关第三方交流，保留理由说明与主体的具体关联。在线和离线摘要同时接收来源消息 ID、发言者 ID、接收时间和运行标识。群聊来源优先以事件的用户 ID 标识发言者；摘要保存从实际选中消息推导的 `sourceSpeakers`，发言者不等于行动主体。多消息来源须显式指定 `sourceMessageIds`，不会默认把整个片段算作本条记忆的证据。

`weightedMemory.autoContentReview` 默认开启，控制普通记忆的写入、读取和页面内容过滤；关闭后不调用自动内容过滤。对话学习候选及训练审批、导出仍使用独立过滤路径。审核开启时缓存去重、两路并发，失败或未完成隐藏正文。来源显示的旧数据不回填推测的发言者。

`weightedMemory.autoApprove` 默认关闭。开启后，已有和新生成的普通待审摘要自动通过，保留来源、权重、审计和回滚；低于单句门槛、核心身份、10–12档、对话学习、导入、捏造及已回滚记录仍需人工审核。自动通过不会授予训练许可。关闭后新摘要恢复待审，已通过条目保持原状态。

主会话在系统前缀统一携带人物归属说明，各工具定义只保留各自用途和参数；文件审核、路径限制和宪法写入保护照常执行。

`hosting.ts` 给主持话题保存更新时间；只有部署时区当天的话题进入当前进度，未标日期或跨日的话题保留在状态文件而不自动续接。quiet、safety 和 preference 持续要求不随话题到期解除。交接时重新校时，已发送内容不因交接变成待回复请求。

`hosting_topic` 的可选 `goal` 保存一个小目标、依据、已确认进度、下一步、所属场景和恢复条件。省略时保留，`null` 清除；目标跨日和重启保留，恢复前由模型核对当前场景、意愿和权限，不产生定时唤醒。部署中的 `references/对话语感参考.md` 供现有文件工具按需读取，聊天写入工具不能修改；素材是语感参考，不是事实记忆。

`draft-cognition.ts` 为 QQ 空间提供无工具、单轮的只读草稿会话，使用当前 CONSTITUTION 和经过审核的记忆资料。身份资料缺失、超预算、暂停或生成失败时不发布，也不降级绕过身份规则。

原始输入写入 `raw_messages`，保留消息 ID、正文、作用域、发言者和接收时间。内容审核在后台运行，经过审核的来源按同一会话、运行和15分钟窗口组织为缓冲片段，每片段最多3000字符。窗口只限制来源大小，语义事件由模型按活动、话题、参与者、结束信号与时间判断。同一片段可以产生多个事件，同一批次多个片段可以合为一个事件。

在线整理每批最多4个来源、6000字符；旧版较长来源单独整理，超过16000字符的来源保留待人工拆分。关闭本次任务的思考并限制输出4096 token，不改变主会话的思考配置。最多生成8个简洁事件；不完整响应或无效 JSON 不入库，原始来源保留待重试。

队列优先处理近期非迁移来源，再从旧到新处理迁移来源。每批成功后按 `weightedMemory.summaryIntervalMinutes` 等待下一批，有积压时同样遵守该间隔，完成日志记录下次整理时间。失败按1、2、4、8、15分钟退避，之后最多每15分钟重试，不沿用成功后的整理间隔。暂停仍停止自动摘要。`timeConfidence:null` 表示未知，保存为0，不因合法的空值拒绝整批；文字、百分数字符串和超出0–1的数值仍拒绝。

记忆主体可以略过与自己无关的交流；旁观或同处群聊不代表内容与自己有关。在线整理、记忆提交工具和历史摘要均按内容与主体的实际关联判断，不按参与者姓名筛选。整批无相关内容时可返回空数组，不生成候选；原始消息和来源片段保留供追溯。

`memory_candidates` 和 `long_term_memories` 是现有 `records` 表上的视图。自动摘要先进入 `pending`，开启自动通过时符合条件的普通候选随后变为 `active`；否则等待人工审核。默认检索和上下文注入只读取已通过的摘要，原始记录和旧档案只供显式 `memory_sources`、控制台和导出追溯。状态还包括 `rejected`、`superseded`、`archived`、`rolled_back`。版本改写保留旧记录，新版本重新进入审核。

`metadata` 保存发生时间 `occurredAt`、时区、时间置信度、原相对时间、来源片段和消息 ID、事件分类、关键事实、人物、地点、结果、情绪、未完成标记、标签和来源类型。无证据的字段为空或 null。`createdAt` 是来源记录时间，不能代替事情发生时间。

相对日期依据各来源消息时间换算；含“上周”等不精确表达时保留“时间不确定”。跨午夜计算使用部署的 UTC+8 时区。其他时区的相对日换算保守返回未知。上下文按当前日期重新渲染，不会把历史“昨天”原样注入。置信度低于0.7时上下文显示时间不确定。迁移资料只有原始正文包含绝对日期时才接受该发生日期，片段头部和文件时间不算发生日期证据。

单消息候选标记为 `single`，`weightedMemory.singleThreshold` 默认8，可设为1–12。低于门槛的候选保留供追溯，后端拒绝实装。现有1–12档位保持兼容，1–9常规档、10–12重大影响档的评分说明保留。权重和可信度是不同字段。

## 一键导出

在“记忆概览 → 快速添加与导出”选择格式和范围，然后点击“一键导出”。每次只生成一个带时间戳的文件，可选“全部资料”或“仅已通过记忆”。

- JSON：有效 JSON 文档，包含格式版本、导出时间、范围和 data 数组；保留记忆记录、元数据与审计，全部资料还包含原始消息、来源索引和迁移索引。
- Markdown（.md）：便于阅读的记忆正文、权重、状态、时间、元数据和审计；全部资料包含原始消息正文。
- SQLite（.sqlite）：可直接用 SQLite 工具打开的独立数据库。全部资料通过在线备份生成一致快照，包含 WAL 中的已提交数据；仅已通过范围只保留已生效长期记忆、其元数据和审计，不带原始消息或待审内容。

导出不修改原数据库，不需要暂停写入。SQLite 在线备份需要 Node.js 22.16 或更新版本。大数据库导出会占用相应内存和临时磁盘空间。
## 控制台接口

现有记忆概览面板使用框架认证和通用面板调用接口，无独立未认证路由。写操作只有控制台操作员可调用，Persona 只声明来源查询和候选提交工具。当前框架为共享控制台密码，审计身份记为 `console-operator`，不区分不同登录者。

- `snapshot(filter, offset, retry, query, kind, sort)`：每页30条；time 为记录时间新到旧，time-asc 为旧到新；weight 为重要性高到低，weight-asc 为低到高。相同重要性按同方向记录时间、行号排序，翻页次序稳定。还支持 confidence/category。记录时间不是事情发生时间。
- `detail(id)`：完整摘要、元数据、来源引用、操作记录、完全相同摘要的重复提示。重复提示不替代语义冲突判断。
- `evidence(id, offset, retry)`：每页最多10条被选中的来源消息，含发言者、会话、接收时间。原文通过内容审核后才显示，未完成返回占位，失败可显式重试。原消息全部缺失时展示已有来源片段并标明未定位原消息，不补造发言者；部分缺失时返回缺失数和来源片段 ID。
- `manual(input)`：手工或自然语言内容作为摘要添加为待审。input 包含 text、scope、kind、importance、reason、occurredAt、effectiveAt、tags、sourceType。sourceType 只能为 manual/fabricated。留空时间为未知。不会改写真实来源。
- `correct(id, revision, text, importance, reason, changes)`：编辑后产生待审新版本，原版本变为 superseded。changes 包含 occurredAt 和 tags。
- `review(id, revision, state, reason)`：单条审核，state 为 active/rejected。
- `batchReview(items, state, reason)`：1–50条不同记忆，全部校验版本并在同一事务中通过、拒绝或归档。一条冲突或低权重单句导致整批回滚。
- `restructure(items, parts, reason)`：多条合并或一条拆分，part 为新摘要表单，sourceIds 和 sourceMessageIds 继承原证据，捏造标记继承，结果均待审。被替代的记录保留。时间未知时必须明确留空。
- `rollback(id, revision, reason)`：撤销最近可回滚操作；有后续版本变化时拒绝覆盖。审批和正文修改分别回滚。
- `exportFile(format, approvedOnly)`：下载选定格式；format 为 json / md / sqlite。默认全部资料，范围由界面选择。通过已认证面板的二进制响应下载。
- `exportAll(approvedOnly)`：返回 md/jsonl。默认全部状态，并包含原始消息、来源索引、迁移追溯和审计。
- `importAll(jsonl)`：全量导入，已有同 ID 不覆盖，文本或作用域冲突使整批失败。导入的已生效长期摘要重新待审，已拒绝和旧版本状态保留，原审计保留为导入证据，不能借导入自动生效。大文件使用 CLI，避免控制台请求体上限。

批量合并/拆分输入示例：

```json
[{"text":"游戏输了后停止游戏","kind":"event","importance":5,"occurredAt":null},
 {"text":"用户喜欢红茶","kind":"preference","importance":8,"occurredAt":null}]
```

手工设置 effectiveAt 时，审批后仍要等生效时间才进入检索；捏造记忆在上下文中保留 fabricated 来源标记。自动审批仅限上述普通候选；没有抽样审批或多用户角色系统。

## 迁移和导出

数据库结构在 `MemoryStore` 首次连接时升级，新增 metadata 列及 `migrations/002-event-memory.sql` 中的表、视图和索引。升级是增量操作，不删除旧数据。先使用 SQLite 在线备份或停止所有写入后复制一致数据库，不能仅复制正在使用的 WAL 数据库主文件。

以下命令在仓库根目录运行，需要 Node.js 22.16 或更新版本。首先对一致备份演练；写生产数据库前停止旧进程。不要用演练库覆盖仍在接收消息的生产库。

```powershell
node event-migrate.mjs status path/to/memory.db
node event-migrate.mjs export path/to/memory.db ./exports/vanilla-memory-before
node event-migrate.mjs stage path/to/memory.db events-v2 500
```

stage 每次最多500条，重复运行直到 staged=0；允许单批上限5000。全部旧活动或待审条目保留为 archived 并记录原状态，不再参与召回。来源按作用域和原记录时间组织，超过2500字符的旧文本分块保留。每条新来源记录携带 migrationBatch、legacyIds 和原记录引用。重复 stage 不重复归档已登记条目。

```powershell
node --import tsx event-summarize.ts path/to/memory.db deployments/mybot 10
node event-migrate.mjs export path/to/memory.db ./exports/vanilla-memory-review
node event-migrate.mjs rollback path/to/memory.db events-v2
node event-migrate.mjs import path/to/new.db ./exports/vanilla-memory-review/all.jsonl
```

离线摘要脚本只使用部署当前模型连接，不启动 bot 或 World。每批同一作用域、最多4个片段和6000字符，串行模型调用；可重复执行继续未完成的来源。请求显式使用 reasoning.effort=none，默认1批，第三个参数控制本次最大批数。输出超限、解析失败、内容审核失败或来源不符时不提交候选、不完成来源。成功批次以 SQLite 事务提交，调用计量保存到 DB.summary.jsonl。已经有外部生成的候选 JSONL 时可使用 `event-migrate.mjs apply DB candidates.jsonl 8`。

全部候选仍需人工审核。迁移回滚恢复原记录状态及处理标记，并把本批新来源和候选停用；已有操作改动了原版本时拒绝回滚。运行时整理器每批最多12个片段、16000字符，最多30个语义事件。积压按配置的整理间隔继续下一批，人工暂停期间停止整理，失败来源重试；超过预算的单条来源保留待人工拆分。原样迁移的大量重复技术档案仍需要模型判断是否有长期价值；不同批次的同一事件可能需要控制台合并。

旧 `migrate.mjs` 只用于首次导入旧 JSON 和工作区，笔记导入后也须审核；存量事件重整使用 event-migrate.mjs。

## 验证

```powershell
node self-check.mjs
pnpm exec vitest run tests/web/memory-event-console.test.ts tests/integration/memory-event-workflow.test.ts tests/integration/memory-event-segments.test.ts tests/integration/memory-delivery-review.test.ts tests/integration/memory-content-review.test.ts
pnpm exec tsc -p tsconfig.json --noEmit
pnpm exec tsc -p tsconfig.web.json --noEmit
```

自检使用临时真实 SQLite，覆盖游戏和茶事件的精确消息引用、时间锚定、门槛、30条审核的原子性、版本冲突、捏造标记、合并拆分、版本回滚、完整导入导出、重复迁移和迁移回滚。集成测试使用真实 Persona 管线和脚本模型，不访问网络。

`prompt-reminder.ts` 每次生成前从当前 `CONSTITUTION.md` 提取“自然表达”规则，经 Persona.requestReminder 放入本轮临时请求末尾。系统提示仍定义完整人格与权限，历史台词只提供事实；修改表达规则后下一次生成重新读取，不增加模型调用，不把提醒写进持久会话。此机制是旧历史影响当前表达时的校准兜底，不保证模型每次都遵守所有风格规则。
