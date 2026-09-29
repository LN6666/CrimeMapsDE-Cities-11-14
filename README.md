# CrimeMapsDE-Cities-11-14

德国城市犯罪地图工程的第三组仓库，城市及编号固定为：

| 编号 | 城市 | slug | 当前状态 |
| --- | --- | --- | --- |
| 11 | Essen（埃森） | `essen` | 警方原生公告采集器；未发布地图 |
| 12 | Dresden（德累斯顿） | `dresden` | 官方 Medienservice 公开档案有界采集；未发布地图 |
| 13 | Hannover（汉诺威） | `hannover` | 警方链接的新闻室有界采集；未发布地图 |
| 14 | Nuremberg（纽伦堡） | `nuremberg` | 选定警方署名新闻室有界采集；未发布地图 |

柏林仍是第一组 `CrimeMapsBerlin` 的默认入口。本仓库没有城市地图、坐标或可发布数据。仓库名称中的 11–14 是城市组编号，不表示覆盖或完成进度。

## 当前本地来源状态

来源采集检查点如下；前三城的审核快照为 2026-09-29，纽伦堡审核更新于 2026-09-30。数量表示已发现公告／已保存正文，不表示市域案件数或地图完成度：

| 城市 | 当前检查点 | 仍待处理 |
| --- | ---: | --- |
| Essen | 402 / 402 | 警方原生档案 2026 通道遍历完成；可见首段摘要与后续正文已一并重抓，402 条来源哈希全部更新，0 缺失正文、0 来源错误；本地 8 篇已有当前哈希绑定的逐篇语义决定，394 篇待复核 |
| Dresden | 479 / 479 | 官方 Medienservice 2026 通道 80 页遍历完成、0 缺失正文、0 来源错误；本地 8 篇已有当前哈希绑定的逐篇语义决定，471 篇待复核 |
| Hannover | 470 / 470 | 警方链接新闻室的 2026 列表遍历已跨入 2025，正文哈希全部复核一致；本地 8 篇已有当前哈希绑定的逐篇语义决定，462 篇待复核 |
| Nuremberg | 849 / 849 | 选定的警方署名 Presseportal 新闻室 2026 来源收集完成；补回预格式文本后已重核全部 849 篇，31 篇正文修订、818 篇不变、0 来源错误。350 篇已有当前哈希绑定的逐篇 LLM 决定（343 supported、7 uncertain、0 stale），499 篇待审；全量几何、地图及所有者批准未完成 |

纽伦堡的 169 条基线输入和 680 条差量输入 source ID 零重叠，合并覆盖 849 条。这里的完成仅指所有者选定的警方署名分发通道；不能据此声称纽伦堡市域审查或地图完成。所有检查点、原文和生成数据均保持 Git 忽略。

纽伦堡首 350 篇完整原文已由 LLM 逐篇分析并通过来源 URL、正文 SHA-256、逐字证据和幂等重导校验，保留 625 个来源场景与 1,528 个正式地点（市内 676、市外 567、市域不明 285），全部 625 个场景保留时间决定与详情，另有 25 个明确 POI 上下文和 4 个公共交通线路／走廊决定（U3 车内事件、8 线服务影响、U2 逃离背景和市外 Hersbruck–Neuhaus 轨道替代公交走廊），尚无填入案件坐标。场景包含行动、非犯罪背景、聚合系列和旧案重述，数量不是犯罪宗数。只读 GIS 清单仅接收 343 篇 supported 决定，保留 615 个场景、1,502 个地点和 666 个市内几何请求；其余七篇 uncertain 不进入该清单。来源审查、受检几何、所有者批准和地图构建的门禁仍未完成。

主工程已从受检 Mittelfranken PBF 建立本地纽伦堡 OSM 几何索引，按市界关系 `62780` 裁切并读回核验：106,073 个对象，其中 82,287 个地址对象、14,092 个道路对象。索引 SHA-256 为 `1d47f74c6ed5c4eef1cee84e5593a5b330c21b648be5212555cc2eb453c41957`，保存于本仓库忽略的 `.runtime/safety/cities/nuremberg/osm-geometry-index.json`。它仅准备几何来源，尚未把任何案件文本自动匹配到 OSM；逐地点的 LLM 选择和几何门禁仍待完成。

逐篇阅读时发现采集器遗漏 `<pre>` 中的证物清单和目击者问题，已修正并添加合成回归测试。全部 849 篇正文随后重新检查，31 篇修订；已审的变更正文重新阅读并绑定当前哈希，旧哈希输入不得继续导入。已生成完整替换包 `CrimeMapsDE-nuremberg-source-review-input-20260929T194531Z.zip`，SHA-256 为 `60feb0b11ff2d285778b26bd87cbd5d305f75984dc49233aac509e0eb1888aef`，位于本地 `.runtime/review-packs/nuremberg-preformatted-corrected/`。ZIP 内部校验值、849 个唯一 ID 和正文哈希均已核验；原文与包均不进入 Git。

当前决定摘要为 `1452edc8fe0ee2ba9d52bc909f37aa1551ea084f6cd5cbca134969cd0e96eb83`，下一原文批次为 `source-batch-0036.ndjson`。`.runtime/review/nuremberg/` 的三个 `*.current` 决定文件含全部当前修正，350 篇重导为 0 变化；早期 `part` 文件不能覆盖它们。`6194820` 和同一事故的 `6208434` 仍有 A6 市域与拍摄位置疑点；`6198622` 的星期与日期矛盾，不擅自改日期。`6206271` 续报 `6205302` 时法院改变了嫌疑罪名，并明确第三人已自由，必须保留司法进展和同案关联。`6204326` 的赃物发现后院不是原自行车盗窃地；`6202472` 的伤者发现地址不是已确认袭击地。`6221410` 原文开始日期为异常五位年份 `18.02.20026`，保留未归一化开始日期并标 uncertain，不能悄悄改成 2026。`6232189` 标题/公布为 3 月 9 日，正文却写星期一、3 月 11 日（实际周三），保留未知归一化日期并标 uncertain。所有者检查与批准仍未完成。 `6245599` 的周六／3 月 29 日车火与发布时序矛盾、`6252709` 的 4 月 1 日／周四失踪开始日期矛盾，也保留原文并标 uncertain。

本次续审还保留 Krugstraße 旧报/续报的同案关系（`6209100` / `6209762`），避免重复计数；`6211690` 的 Worzeldorf 事件发生在 2024 年，工作组“Kirchsteig”不是案发路名。`6211377` 的学校报警最终发现的是玩具枪，不能变成枪击；`6212919` 的两批代理考试没有考场城市，Nürnberg/Hamm 搜查城市不替代考试地点。A6 Röthenbach 停车区经受检 OSM 确认市界外，与市内同名地铁站分开；Gleiwitzer Straße 的 A6 入口相关路段已确认市界内，但红灯停止线的具体匝道仍未知。

后续 40 篇续审保留 `6214923` / `6196168`（Lauf 抢劫）和 `6215558` / `6199274`（理发店入侵）的同案关系。`6214706` 是车库内停放电车受损，不能当移动列车案；`6218452` 的 U3 车内威胁与 Maxfeld 站取包/抓捕分别保留。`6217023` 的多次碰撞没有全部道路名，不能将每次碰撞压到最终 Gärtnerstraße 停车处。七家 Nürnberg/Fürth 药店的系列案 `6219434` 保留七个未知地点，不猜市域分配或商户。政治涂鸦的右翼初步描述也不自动支持仇恨标签。

本轮再续审 60 篇后，`6223106` 的 Hufelandstraße 盗车与 Klingenhofstraße 寻车、`6226191` 的原车盗与次日店盗/寻车分角色保留。`6227616` / `6226256` 和 `6228910` / `6226902` 为失踪搜索撤销关系，最终展示须更新状态。`6227703` 抢劫发生在 2025 年；`6233079` 的原集会暴力也在 2025 年，2026 搜查地点未给。`6232212` 明确医院治疗室内袭警/警开枪，医院在这里是真实事件场所。`6232513` 的 350 多宗全球诈骗不定位成 350 个纽伦堡点。`6232062` 校巴 12 名轻伤学生属一次紧急制动事件，线路号未给；`6231047` 的 8 线仅保留服务影响，实际碰撞以 Sulzbacher Straße 路段表达。

第 231–290 篇现已完成全文复核。`6233826` 补明同旧案的 24 处跨城搜查，建筑与城市数量分配仍未知；`6235024` 保留 Dinkelsbühl 15 辆、Feuchtwangen 11 辆被针对汽车，不能合为一个案点或把未遂全改既遂。`6239056` 续报 `6210317` 时车主承认自烧车、自写威胁信和自涂政治涂鸦，最终展示须采用后续解释。`6237103` 更新 Katzwang 失踪者已发现死亡，但发现时地未公开且无他人责任线索。`6242885` 是同一儿童倒球门事故后续；`6243389` 的无人机阻碍是旧火灾中的新增行动情节。9 条明确同案／状态更新关系已逐一核验当前来源哈希与场景 ID，保存于本地忽略的 `source-relations.current.ndjson`，尚未编入最终地图计数；该批次 supported GIS 清单摘要为 `25ca1fd7ae705dc2505364c9e76f6d30706a27b531305707bb47d6dacbf5f908`。

第 291–350 篇新增复核已保存。`6253067` 明确将 `6247175` 的司机性骚扰地点修正为停靠电车外后部；两篇的 15:40／15:50 报告时刻按来源分别保留。`6247912` 经尸检初判 `6245679` 家庭死亡案为两人被杀后丈夫自杀，真实发生时刻仍未述。`6253560` 续报同 Pirckheimer Straße 死亡案的附近抓捕，不生成新死亡案。`6254368` 区分 Nightliner 内争执、Leipziger Platz 下车后袭击和 U2 逃离背景；`6254106` 保留轨道替代公交来源走廊而不猜线路号或案件点。失踪后续仅按原文区分安全找到、发现死亡和联系警方。当前 18 条同案／状态更新关系已校验来源哈希与场景 ID，但最终计数尚未编译；supported GIS 清单摘要为 `d0279c0b884a938c9a490a6614402fa023683df4909043e80b87a2d558ed22fc`。

上述三城语义决定是 2026-09-29 的本地恢复断点，不是抽样准确率或发布成果。三城的
首批决定均已通过 URL、正文 SHA-256、逐字证据、事件/正式地点完整声明和幂等重导校验；
对应只读清单目前分别保留 Essen 8 个事件、19 个正式地点、13 个市内几何请求，Dresden
6/11/7，Hannover 2/15/4。其余公告仍必须逐篇读取全文；全量几何、地图语义、所有者质询与
批准均未完成，所以三城仍保持 `owner_approved=false`、`publication_ready=false`。
当前受支持子集的几何请求已全部由 LLM 对照受检 OSM 索引作出决定：Essen 10 个解析、
3 个明确未解析，Dresden 5/2，Hannover 4/0；这只是随来源复核继续扩展的恢复断点，
并不表示全量几何或地图语义完成。

## 埃森来源与边界

采集器从[Polizei Essen 原生公告档案](https://essen.polizei.nrw/presse/pressemitteilungen)读取分页索引和原文，每次运行先核验 [robots.txt](https://essen.polizei.nrw/robots.txt)，按至少一秒间隔请求；首次来源或解析错误即停止本批次，不自动重试。原生页面把公告首段放在独立的可见摘要字段，采集器将该字段与后续正文按页面顺序保存，并排除嵌套图片等媒体节点的说明文字。Drupal 节点 ID、规范 URL、发布时间、完整文字、SHA-256、修订号和待审状态保存在本地 SQLite。抓取过程不推断地点，也不制作公共地图。

警方署名公告可能涉及 Mülheim an der Ruhr、Oberhausen 和跨市高速路。`city_scope` 只提供保守的市域复核线索；发布机关、邮编或新闻室标签均不能证明案发地在 Essen。多地点、混合辖区、高速与不明确地点进入 `needs_review`。每篇公告仍须逐条对照官方原文接受 Codex 审查，再交项目所有者检查、质问和批准；缺失、过期或不确定的审查阻止发布。

2026-09-29 的本地完整原生通道检查点含 402 条正文；完整字段迁移保持全部 source ID 和规范 URL 不变，402 条正文哈希均因补入可见首段而修订，旧来源审核输入包因此失效。此前 2026-09-28 的页面核对中，原生筛选显示 401 条，[Polizei Essen 署名新闻室](https://www.presseportal.de/blaulicht/nr/11562)显示 418 条。来源会新增记录，且两处数量仍不一致；这里不宣称两个档案等价或警方公告是全量犯罪记录。

## 汉诺威来源与边界

[Polizeidirektion Hannover 的新闻办公室](https://www.pd-h.polizei-nds.de/wir_ueber_uns/presse/)明确链接其[Presseportal 新闻室](https://www.presseportal.de/blaulicht/nr/66841)。采集器先核验 Presseportal 的 [robots.txt](https://www.presseportal.de/robots.txt)，再按有界页数读取索引和正文；SQLite 保存新闻室文章 ID、URL、原文哈希、修订与待审状态。年度断点扫描会在续扫时刷新新闻室首页；`--pages` 指续扫页数，实际索引请求最多多一页首页。当前列表遍历已经跨入 2025，2026 新闻室通道发现并保存 470/470 篇正文，0 缺失、0 来源错误；这仍不等同于市域审核或地图完成。

新闻室包含 Langenhagen、Lehrte、Burgwedel 等周边地点及高速公路。`hannover_candidate` 只是市域复核线索；含其他市镇或跨市道路的记录保持待核验，不自动进入汉诺威地图。新闻室首页地点标签和 `Hannover (ots)` 发稿地不作为案发地点证据。

## 德累斯顿公开来源与边界

[Polizei Sachsen 档案](https://www.polizei.sachsen.de/de/113164.htm)明确指向[Polizeidirektion Dresden 的 Medienservice 档案](https://www.medienservice.sachsen.de/medien/?search%5Binstitution_ids%5D%5B%5D=10997)。Medienservice 的 `robots.txt` 当前明确返回 HTTP 404；RFC 9309 §2.3.1.3 将 4xx 视为规则文件不可用并允许抓取器访问。采集器每次重新检查，只在明确 404/410，或有效的 200 规则允许档案和文章路径时继续；401/403/429、其他 4xx、5xx、网络错误、HTML/空白/损坏规则和 `Disallow` 都会停止。

采集器使用网站公开的日期筛选 JSON 后端，固定机构 `10997` 与发布者 `Polizeidirektion Dresden`，每批限制页数和正文数，顺序请求间隔至少 4 秒，首个来源错误即停止并写入检查点。公开档案无须注册或登录；注册只与订阅推送等功能有关。稳定修订哈希基于规范化 ID、规范 URL、发布者、标题、时间和完整正文，动态 CSRF token 只进入单次原始 HTML 哈希。其公告可能把 Dresden、Meißen、Sächsische Schweiz-Osterzgebirge 多个事件合并成一篇；采集过程不使用关键词拆案或批准市域，全部交给后续逐场景 LLM 复核。

德累斯顿模块也保留人工原件入口：事先取得并放在本机的官方原文可用 JSONL 离线暂存，每行必须有 `source_id`、`source_url`、`publisher`、`title`、`published`、`body`。暂存过程不联网，写入 `source_verified=0` 和 `review_status=pending`；字段校验不等于核验原文。

若来自 [Medienservice Sachsen 注册投递](https://www.medienservice.sachsen.de/medien/account/new/other)、用户保存的页面/PDF/邮件或官方人工导出，JSONL 行还可带相对路径 `source_file` 和原文件字节的 `source_file_sha256`。支持 HTML、EML、PDF、完整 RSS/Atom XML；HTML、邮件、RSS 的所填正文必须在原文件文字中，摘要不算完整公告。PDF 只校验签名与哈希，转写须在逐篇复核时与原 PDF 核对。保存文件改变会记录新修订并清除旧复核状态。账号凭据和所有原件仍只在本机 Git 忽略目录。

```sh
PYTHONPATH=src uv run python -m crimemapsde_cities_11_14.dresden \
  --db .runtime/safety/cities/dresden/police.sqlite \
  --export-review .runtime/safety/cities/dresden/review-input.ndjson --max-records 100
```

此只读逐篇输入重新核对正文、修订和原文件哈希。直接在线取得且通过机构、发布者、规范 URL 和哈希门禁的记录标为 `source_verified=true`，人工 JSONL 仍为 `false`；`publication_ready` 始终为 `false`。后续批次可用 `--review-offset` 分页并写不同的本地输出文件。它供 Codex 对照整篇原文拆案和场景，不能证明历史通报完整或自动进入地图。

## 纽伦堡来源与边界

[Presseportal 上由 Polizeipräsidium Mittelfranken 署名的新闻室](https://www.presseportal.de/blaulicht/nr/6013)是所有者为 Nuremberg 选定的来源通道。2026-09-28 核验时，[Presseportal robots.txt](https://www.presseportal.de/robots.txt) 允许该新闻室及文章路径；程序每次运行重新核验规则，规则缺失、请求被禁止或发布者不符时停止接收相应内容。请求间隔至少一秒，并遵守 robots 的更慢限制；单次最多续扫 10 页、检查 30 篇正文，失败重试有上限。年度游标和原文存于本机 `.runtime/safety/cities/nuremberg/newsroom.sqlite`，保存新闻室 ID、规范 URL、正文 SHA-256、修订历史与待审状态。旧的巴伐利亚原生页面人工暂存仍单独保存在 `police.sqlite`，不与新闻室表混写，也不再作为来源完整性的前置要求。本仓库不抓取巴伐利亚警方原生站。

这个新闻室覆盖整个 Mittelfranken，包括 Fürth、Erlangen、Ansbach 等市镇及跨市高速。`nuremberg_candidate` 仅在正文有明确市域线索且没有已知混合辖区/区域道路提示时作为**复核候选**；新闻室标题、`Nürnberg (ots)` 发稿地及警局地址均不证明案发地。一次公告可能包含多地、多案或非案件内容，必须逐篇核查。

选定新闻室的 2026 年遍历已经跨入 2025，当前 849/849 正文通过来源与哈希核验，因此该选定通道的 `archive_complete` 为 `true`。这不表示 Nuremberg 市域筛选、犯罪清单或地图完成；新闻室覆盖整个 Mittelfranken，警方公告本身也不是全量犯罪记录。逐篇 Codex 市域与多场景审查、所有者质询与批准之前，`publication_ready` 仍为 `false`，不发布记录或地图。

## 四城只读来源契约

`registry.py` 固定四个城市的 slug、显示名、EPSG、来源类型、来源 URL、采集模式和市域复核标记。Essen、Hannover、Nuremberg 使用 EPSG:25832；Dresden 使用 EPSG:25833。这些坐标系只是后续 GIS 的元数据，本仓库不生成坐标。

`source_audit.py` 以 SQLite 只读模式审计本地数据库，按年度输出版本号为 `1` 的 JSON。它适配 Essen、Dresden、Hannover、Nuremberg 的在线采集表，以及 Dresden 和 Nuremberg 原生站的离线暂存记录。纽伦堡默认优先审计 `newsroom.sqlite`；若尚无在线库，则审计旧 `police.sqlite` 暂存。每城有 `archive_complete`、`source_verified`、`publication_ready`、`blocking_reasons`、`records` 和 `municipal_review_candidates`。每条记录只导出来源 ID、URL、日期、SHA-256、修订号、市域标记、复核状态及完整性布尔值；不导出标题、正文、市域证据原句、坐标或几何。审计时会在本机读取正文，重算哈希、核对修订表和市域标记，但不修改来源库。

`municipal_review_candidates` 只收录正文存在、哈希与修订一致、来源 ID/URL 合法、原文支持当前市域标记，且未被审查驳回的在线来源记录。这些记录仍是**待逐篇审查的市域线索**，不能据此推断具体案发点。离线暂存缺少可核查的原始来源核验记录，因此即使 SQLite 的可变 `source_verified` 字段被改为 `1`，审计输出仍将其判为未核验，不列入候选。在线记录的 `source_verified` 仅表示本地已保存文章的来源格式和正文完整性核对通过，不能代替对当前官网原文的再次复核。

现阶段 `publication_ready` 恒为 `false`。未完成的年度档案覆盖、未核验来源、缺少与修订绑定的 Codex 审查、缺少本批次所有者批准以及不存在获准地图构建，都会在 `blocking_reasons` 中说明。第一组工程消费此契约时仍须执行自己的逐篇审核与发布门禁。

## 来源绑定的 LLM 复核决定

`review_decisions.py` 只导入 LLM 读完官方全文后写出的决定，不用关键词判断公告是否为案件、案件数量、地点或市域。它适配 Essen/Dresden 的 `source_id`/`source_url` 表结构及 Hannover/Nuremberg 的 `id`/`url` 表结构。入口与 source-review pack 的三个输出文件一一对应：

```sh
PYTHONPATH=src uv run python -m crimemapsde_cities_11_14.review_decisions \
  --city hannover \
  --db .runtime/safety/cities/hannover/police.sqlite \
  --review-decisions .runtime/review/hannover/review-decisions.delta.ndjson \
  --scope-decisions .runtime/review/hannover/scope-decisions.delta.ndjson \
  --scene-decisions .runtime/review/hannover/scene-decisions.delta.json
```

三个文件必须覆盖完全相同的 `source_id` 集合，并在每条记录中重复 `schema_version: 1`、`city`、`source_id`、`source_url` 和 `source_sha256`。这些字段必须与本地检查点的当前全文完全一致。review 文件另含 `verdict`、逐字 `evidence_quotes`、`review_note`、`reviewer` 和带时区的 `reviewed_at`；scope 文件另含 `scope_verdict`（`in_city`、`out_of_city`、`mixed` 或 `uncertain`）及逐字引文。

scene 文件是 `{"schema_version":1,"city":"...","articles":[...]}`。每篇必须明确给出非负 `incident_count`、同样长度的 `incidents`、完整 `formal_locations`，并把 `incidents_complete` 与 `formal_locations_complete` 显式设为 `true`。每个案件及每个正式地点都要有能在当前完整正文中逐字找到的引文；一个案件可以引用多个地点，一篇也可以包含多个案件。零案件和零地点是允许的显式决定。街道、区域、区级及未知精度地点不得带代表点坐标，后续 GIS 阶段应保留道路或区域几何，无法确定的几何继续为空。

为保留来源包中的时间、详情、移动公交与 POI 语境，事件可额外提供 `event_time` 和 `details`，地点可提供 `transit_route` 和 `poi_contexts`。`event_time` 包含 `display`、可为空的 ISO 日期 `date`、`precision`（`exact/approximate/date/range/unknown`）及逐字 `evidence_quote`。`route` 精度必须提供交通方式、线路、范围和证据，不能带代表点坐标；游行道路不因此成为公交线路。POI 语境只接受带逐字证据的 `along_geometry/near_geometry/named_object` 决定；空列表是显式的无关联决定，附近场所不自动成为案发地。缺少这些可选字段的既有决定仍可读取，程序不会补写语义。

导入在全部记录验证通过后才原子写入本地 `llm_review_decisions` 和历史表。源正文哈希或 URL 改变会让旧决定成为 stale；决定内容改变会生成新的 `decision_set_digest`，因此任何绑定旧摘要的后续批准都失效。导入结果始终返回 `owner_approval_required: true`、`owner_approved: false` 和 `publication_ready: false`。原文、三个决定文件及本地决定表均属于运行时材料，必须留在 Git 忽略目录中。

## 本地运行

需要 Python 3.12 和 `uv`。

```sh
uv sync --locked
uv run ruff check .
uv run pytest -q
# 有界的原生来源试跑：最多 1 页索引、1 篇正文
PYTHONPATH=src uv run python -m crimemapsde_cities_11_14.essen --year 2026 --max-pages 1 --limit 1
# 汉诺威新闻室：单次续扫最多 1 页、下载最多 1 篇正文
PYTHONPATH=src uv run python -m crimemapsde_cities_11_14.hannover --year 2026 --pages 1 --limit 1
# 德累斯顿公开档案：日期筛选 1 页、正文最多 2 篇、请求间隔至少 4 秒
PYTHONPATH=src uv run python -m crimemapsde_cities_11_14.dresden --live --year 2026 --max-pages 1 --max-records 2 --delay 4
# 纽伦堡警方署名新闻室：单次续扫最多 1 页、下载最多 1 篇正文
PYTHONPATH=src uv run python -m crimemapsde_cities_11_14.nuremberg --year 2026 --pages 1 --limit 1
# 仅当人工已有原生站官方原文 JSONL 时，才运行离线暂存：
PYTHONPATH=src uv run python -m crimemapsde_cities_11_14.dresden --input .runtime/safety/cities/dresden/source.jsonl
PYTHONPATH=src uv run python -m crimemapsde_cities_11_14.nuremberg --input .runtime/safety/cities/nuremberg/source.jsonl
# 四城来源元数据审计；输出只有 JSON，不改变来源数据库
PYTHONPATH=src uv run python -m crimemapsde_cities_11_14.source_audit --year 2026
```

纽伦堡在线库使用 `.runtime/safety/cities/nuremberg/newsroom.sqlite`；其他默认库及纽伦堡原生站离线暂存使用 `.runtime/safety/cities/<slug>/police.sqlite`。Dresden `--live`、Essen `--full`、Hannover 和 Nuremberg 新闻室年度续扫会在多次运行间记录页码；`--max-pages`、`--pages`、`--limit` 或 `--max-records` 只限制**一次网络采集运行**的请求量，并非审核篇数或发布时间表。来源失效时保持上次已保存的原文和修订，不生成替代数据。

`.runtime/`、原始公告、SQLite、下载缓存、生成城市数据、个人凭据均不进入 Git。CI 只运行合成测试，不向警方网站发请求。任何获准的公共数据版本应先完成来源审查、质量检查和所有者批准，并遵循第一组仓库的发布流程。

代码沿用 Apache-2.0 许可，见 [LICENSE](LICENSE)。
