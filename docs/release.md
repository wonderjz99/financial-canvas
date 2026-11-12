# Financial Canvas 实验版发行说明

Financial Canvas（财务画布）是按文件清单生成的独立源码发行，不复制原研发 Git 历史。包含自有 Python/SVG 组件、Skill、使用说明、锁定开发依赖清单及合成测试，以及 COST、AAPL、ADBE 三个官方来源报告和实际页面截图；不包含原始披露、缓存、Futu 响应、V1 HTML、原型、内部交接或私有配置。

根目录 PUBLIC_RELEASE.json 标识 `financial-visualizer-v2-public`。代码许可为 [MIT](../LICENSE)，第三方范围见 [说明](../THIRD_PARTY_NOTICES.md)。发布文件的哈希审阅清单保留于发行准备流程中，不作为用户本地取数输入。

产品名称不含版本号。内部协议、目录和 `--scope v2` 继续使用既有标识以保持兼容。源码仓库为 [wonderjz99/financial-canvas](https://github.com/wonderjz99/financial-canvas)。

三个 [离线示例](../examples/README.md) 固定于 2026-11-12，分别覆盖 COST FY2022–2026、AAPL FY2022–2026、ADBE FY2021–2025，币种均为 USD。报告保留 partial 状态及实际缺口，来源和哈希见 [provenance.json](../examples/provenance.json)。README 链接到既有 [PDD 在线历史报告](https://value.wonderjz.workers.dev/reports/financial-visualizer?symbol=PDD)，未改变 WonderValue 入口、数据或部署。

默认 `scripts/verify.py` 和 Playwright 仅采用独立单公司模式，CI 不依赖未公开资料。Git 索引与完整已获取历史还检查被排除的路径和已审阅示例的来源，避免仅在当前目录删掉数据却保留在旧提交中。

实验版支持 US GAAP 美股非金融公司的年度历史可视化。真实公司接入取决于官方结构化事实、原文和实际研究；季度、IFRS、估值、交易不在范围。未知、冲突、受限现金、NCI 和分类变化应按 [契约](report-v2.md) 处理，不以合成自动测试证明全市场适配。

后续修改应在同一提交执行测试和内容边界检查，保留正确的许可证说明；不重新引入研发仓库历史或被排除的数据。
